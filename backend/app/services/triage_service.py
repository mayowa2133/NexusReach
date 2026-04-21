"""Batch triage — networking ROI scorer.

Ranks all of a user's saved jobs by how much networking effort each deserves.
No LLM. Every score is derived from observable CRM state and is explainable.

Dimensions (each 0-100):
  job_fit          30%  match_score against profile
  contactability   25%  verified contacts found via research snapshot
  warm_path        20%  LinkedIn warm-path connections present
  outreach_opp     15%  how open the outreach window is
  stage_momentum   10%  how active the pipeline stage is

Tiers:
  high   ≥ 70
  medium ≥ 45
  low    ≥ 20
  skip   < 20
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import Job
from app.models.job_research_snapshot import JobResearchSnapshot
from app.models.outreach import OutreachLog
from app.schemas.triage import (
    TriageDimensions,
    TriageJobSummary,
    TriageResponse,
    TriageResult,
)

# Stages that are effectively closed — deprioritize automatically
_CLOSED_STAGES = {"rejected", "withdrawn", "archived"}

_STAGE_MOMENTUM: dict[str, float] = {
    "discovered": 40.0,
    "saved": 60.0,
    "applied": 80.0,
    "interviewing": 95.0,
    "offer": 100.0,
    "rejected": 0.0,
    "withdrawn": 0.0,
    "archived": 0.0,
}

_WEIGHTS = {
    "job_fit": 0.30,
    "contactability": 0.25,
    "warm_path": 0.20,
    "outreach_opp": 0.15,
    "stage_momentum": 0.10,
}


# ---------------------------------------------------------------------------
# Dimension scorers
# ---------------------------------------------------------------------------


def _score_job_fit(match_score: float | None) -> float:
    """Direct match score, default 50 if not yet analysed."""
    if match_score is None:
        return 50.0
    return float(match_score)


def _score_contactability(verified_count: int, has_snapshot: bool) -> float:
    if not has_snapshot:
        return 20.0  # unknown — possible but unresearched
    if verified_count == 0:
        return 0.0
    if verified_count == 1:
        return 50.0
    if verified_count == 2:
        return 75.0
    return 100.0


def _score_warm_path(warm_path_count: int, has_snapshot: bool) -> float:
    if not has_snapshot or warm_path_count == 0:
        return 0.0
    if warm_path_count == 1:
        return 75.0
    return 100.0


def _score_outreach_opportunity(
    verified_count: int,
    has_snapshot: bool,
    outreach_sent: int,
    has_active_conversation: bool,
) -> float:
    if has_active_conversation:
        return 80.0  # conversation in progress — keep warm
    if outreach_sent > 0:
        return 60.0  # sent, awaiting reply
    if has_snapshot and verified_count > 0:
        return 100.0  # contacts found, nothing sent yet — full opportunity
    if not has_snapshot:
        return 30.0  # unresearched — could be open
    return 10.0  # researched but no contacts found


def _score_stage_momentum(stage: str) -> float:
    return _STAGE_MOMENTUM.get(stage, 40.0)


# ---------------------------------------------------------------------------
# Tier + recommended action
# ---------------------------------------------------------------------------


def _tier(roi: float) -> str:
    if roi >= 70:
        return "high"
    if roi >= 45:
        return "medium"
    if roi >= 20:
        return "low"
    return "skip"


def _recommend(
    *,
    stage: str,
    job_fit: float,
    contactability: float,
    warm_path: float,
    has_snapshot: bool,
    verified_count: int,
    outreach_sent: int,
    has_active_conversation: bool,
    warm_path_count: int,
) -> str:
    if stage in _CLOSED_STAGES:
        return "Role closed — deprioritize."
    if stage == "offer":
        return "Evaluate offer and decide."
    if stage == "interviewing":
        return "Focus on interview prep and thank-you follow-ups."
    if has_active_conversation:
        return "Reply to keep the conversation warm."
    if outreach_sent > 0:
        return "Follow up — no reply yet."
    if warm_path_count > 0 and outreach_sent == 0:
        return "Reach out via warm path — you have a connection here."
    if verified_count > 0 and outreach_sent == 0:
        return "Draft outreach to verified contacts."
    if not has_snapshot:
        return "Run people search to discover contacts at this company."
    if verified_count == 0 and has_snapshot:
        return "No verified contacts found — try people search again or check email finder."
    if job_fit < 40:
        return "Low match score — consider deprioritizing."
    return "Research contacts and start outreach."


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def compute_triage(
    db: AsyncSession,
    user_id: uuid.UUID,
    stages: list[str] | None = None,
    limit: int | None = None,
) -> TriageResponse:
    """Compute networking ROI triage for all of a user's jobs."""

    # Load jobs
    stmt = select(Job).where(Job.user_id == user_id)
    jobs = list((await db.execute(stmt)).scalars().all())

    if stages:
        jobs = [j for j in jobs if j.stage in stages]

    # Load research snapshots
    snap_stmt = select(JobResearchSnapshot).where(
        JobResearchSnapshot.user_id == user_id
    )
    snaps = {
        s.job_id: s
        for s in (await db.execute(snap_stmt)).scalars().all()
    }

    # Load outreach logs grouped by job
    outreach_stmt = select(OutreachLog).where(OutreachLog.user_id == user_id)
    all_outreach = list((await db.execute(outreach_stmt)).scalars().all())

    outreach_by_job: dict[uuid.UUID, list[OutreachLog]] = {}
    for log in all_outreach:
        if log.job_id:
            outreach_by_job.setdefault(log.job_id, []).append(log)

    results: list[TriageResult] = []

    for job in jobs:
        snap = snaps.get(job.id)
        has_snapshot = snap is not None
        verified_count = snap.verified_count if snap else 0
        warm_path_count = snap.warm_path_count if snap else 0

        job_logs = outreach_by_job.get(job.id, [])
        sent_logs = [lg for lg in job_logs if lg.status == "sent"]
        outreach_sent = len(sent_logs)
        has_active_conversation = any(lg.response_received for lg in job_logs)

        # Score each dimension
        jf = _score_job_fit(job.match_score)
        ct = _score_contactability(verified_count, has_snapshot)
        wp = _score_warm_path(warm_path_count, has_snapshot)
        oo = _score_outreach_opportunity(
            verified_count, has_snapshot, outreach_sent, has_active_conversation
        )
        sm = _score_stage_momentum(job.stage)

        roi = round(
            jf * _WEIGHTS["job_fit"]
            + ct * _WEIGHTS["contactability"]
            + wp * _WEIGHTS["warm_path"]
            + oo * _WEIGHTS["outreach_opp"]
            + sm * _WEIGHTS["stage_momentum"],
            1,
        )

        tier = _tier(roi)
        action = _recommend(
            stage=job.stage,
            job_fit=jf,
            contactability=ct,
            warm_path=warm_path_count > 0,  # type: ignore[arg-type]
            has_snapshot=has_snapshot,
            verified_count=verified_count,
            outreach_sent=outreach_sent,
            has_active_conversation=has_active_conversation,
            warm_path_count=warm_path_count,
        )

        results.append(
            TriageResult(
                job=TriageJobSummary(
                    id=str(job.id),
                    title=job.title,
                    company_name=job.company_name,
                    stage=job.stage,
                    match_score=job.match_score,
                    starred=job.starred,
                    tags=list(job.tags) if job.tags else None,
                    applied_at=job.applied_at.isoformat() if job.applied_at else None,
                    url=job.url,
                ),
                roi_score=roi,
                roi_tier=tier,
                dimensions=TriageDimensions(
                    job_fit=round(jf, 1),
                    contactability=round(ct, 1),
                    warm_path=round(wp, 1),
                    outreach_opportunity=round(oo, 1),
                    stage_momentum=round(sm, 1),
                ),
                recommended_action=action,
                verified_contacts=verified_count,
                warm_path_contacts=warm_path_count,
                outreach_sent=outreach_sent,
                has_active_conversation=has_active_conversation,
            )
        )

    results.sort(key=lambda r: r.roi_score, reverse=True)
    if limit:
        results = results[:limit]

    return TriageResponse(
        items=results,
        total=len(results),
        high_count=sum(1 for r in results if r.roi_tier == "high"),
        medium_count=sum(1 for r in results if r.roi_tier == "medium"),
        low_count=sum(1 for r in results if r.roi_tier == "low"),
        skip_count=sum(1 for r in results if r.roi_tier == "skip"),
    )
