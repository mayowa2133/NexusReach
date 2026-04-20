"""Next-action / follow-up cadence engine.

Deterministic rule-based queue of "do this next" items across jobs, messages,
outreach logs, and live job-research snapshots. No LLM scoring in v1 — every
recommendation has an explicit reason the user can audit.

Surfaces on Dashboard ("Act Now") and later Outreach. Helps the user
distinguish wait / follow-up / reply-now / deprioritize without remembering
each thread manually.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.job import Job
from app.models.job_research_snapshot import JobResearchSnapshot
from app.models.message import Message
from app.models.outreach import OutreachLog
from app.models.person import Person


# --- Tuning knobs (v1 hardcoded; later move to UserSettings) -----------------

DRAFT_UNSENT_AGE_HOURS = 24
AWAITING_REPLY_DAYS = 5
APPLIED_UNTOUCHED_DAYS = 7
THANK_YOU_WINDOW_HOURS = 48
LIVE_TARGETS_MIN_VERIFIED = 1


URGENCY_RANK = {"high": 0, "medium": 1, "low": 2}


@dataclass
class NextAction:
    kind: str
    urgency: str  # "high" | "medium" | "low"
    reason: str
    suggested_channel: str | None = None
    suggested_goal: str | None = None
    job_id: str | None = None
    job_title: str | None = None
    company_name: str | None = None
    person_id: str | None = None
    person_name: str | None = None
    message_id: str | None = None
    outreach_id: str | None = None
    age_days: float | None = None
    deep_link: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _age_days(dt: datetime | None) -> float | None:
    aware = _aware(dt)
    if aware is None:
        return None
    return round((_now() - aware).total_seconds() / 86400, 1)


# --- Rule helpers ------------------------------------------------------------


async def _load_jobs(db: AsyncSession, user_id: uuid.UUID) -> list[Job]:
    result = await db.execute(select(Job).where(Job.user_id == user_id))
    return list(result.scalars().all())


async def _load_messages(db: AsyncSession, user_id: uuid.UUID) -> list[Message]:
    result = await db.execute(
        select(Message)
        .options(selectinload(Message.person))
        .where(Message.user_id == user_id)
    )
    return list(result.scalars().all())


async def _load_outreach(db: AsyncSession, user_id: uuid.UUID) -> list[OutreachLog]:
    result = await db.execute(
        select(OutreachLog)
        .options(selectinload(OutreachLog.person))
        .where(OutreachLog.user_id == user_id)
    )
    return list(result.scalars().all())


async def _load_snapshots(
    db: AsyncSession, user_id: uuid.UUID
) -> list[JobResearchSnapshot]:
    result = await db.execute(
        select(JobResearchSnapshot).where(JobResearchSnapshot.user_id == user_id)
    )
    return list(result.scalars().all())


def _person_name(person: Person | None) -> str | None:
    if person is None:
        return None
    return person.full_name or None


def _job_link(job_id: uuid.UUID) -> str:
    return f"/jobs/{job_id}"


def _person_link(person_id: uuid.UUID) -> str:
    return f"/people?person_id={person_id}"


# --- Rules -------------------------------------------------------------------


def _rule_reply_needed(outreach_logs: list[OutreachLog]) -> list[NextAction]:
    actions: list[NextAction] = []
    for log in outreach_logs:
        if not log.response_received:
            continue
        # Heuristic: response received but status not advanced past responded
        if log.status not in {"responded"}:
            continue
        last = _aware(log.last_contacted_at) or _aware(log.updated_at)
        age = _age_days(last)
        actions.append(
            NextAction(
                kind="reply_needed",
                urgency="high",
                reason="They replied — keep the thread warm with a same-day response.",
                suggested_channel=log.channel,
                suggested_goal="follow_up",
                job_id=str(log.job_id) if log.job_id else None,
                person_id=str(log.person_id),
                person_name=_person_name(log.person),
                outreach_id=str(log.id),
                age_days=age,
                deep_link=_person_link(log.person_id),
            )
        )
    return actions


def _rule_thank_you_due(jobs: list[Job], messages: list[Message]) -> list[NextAction]:
    actions: list[NextAction] = []
    cutoff = _now() - timedelta(hours=THANK_YOU_WINDOW_HOURS)
    for job in jobs:
        if job.stage != "interviewing":
            continue
        rounds = job.interview_rounds or []
        # `interview_rounds` may be list-shaped JSONB; tolerate dict/list
        if isinstance(rounds, dict):
            rounds = list(rounds.values())
        if not isinstance(rounds, list):
            continue
        recent = None
        for r in rounds:
            if not isinstance(r, dict):
                continue
            scheduled_raw = r.get("scheduled_at") or r.get("completed_at")
            if not scheduled_raw:
                continue
            try:
                scheduled = datetime.fromisoformat(str(scheduled_raw).replace("Z", "+00:00"))
            except ValueError:
                continue
            scheduled = _aware(scheduled)
            if scheduled and scheduled >= cutoff and scheduled <= _now():
                recent = scheduled
                break
        if recent is None:
            continue
        # Skip if any thank_you message exists for this job recently
        already = any(
            m.goal == "thank_you"
            and m.context_snapshot
            and isinstance(m.context_snapshot, dict)
            and m.context_snapshot.get("job_id") == str(job.id)
            and _aware(m.created_at)
            and _aware(m.created_at) >= recent
            for m in messages
        )
        if already:
            continue
        actions.append(
            NextAction(
                kind="thank_you_due",
                urgency="high",
                reason="Recent interview — send a thank-you within 48 hours.",
                suggested_channel="email",
                suggested_goal="thank_you",
                job_id=str(job.id),
                job_title=job.title,
                company_name=job.company_name,
                age_days=_age_days(recent),
                deep_link=_job_link(job.id),
            )
        )
    return actions


def _rule_draft_unsent(
    messages: list[Message], outreach_logs: list[OutreachLog]
) -> list[NextAction]:
    cutoff = _now() - timedelta(hours=DRAFT_UNSENT_AGE_HOURS)
    actions: list[NextAction] = []
    outreach_by_message = {
        log.message_id: log for log in outreach_logs if log.message_id is not None
    }
    for msg in messages:
        if msg.status not in {"draft", "edited"}:
            continue
        created = _aware(msg.created_at)
        if created is None or created > cutoff:
            continue
        log = outreach_by_message.get(msg.id)
        if log and log.status not in {"draft"}:
            continue
        snap = msg.context_snapshot if isinstance(msg.context_snapshot, dict) else {}
        actions.append(
            NextAction(
                kind="draft_unsent",
                urgency="high",
                reason="Draft sitting more than 24h — send or edit before it goes stale.",
                suggested_channel=msg.channel,
                suggested_goal=msg.goal,
                job_id=snap.get("job_id"),
                person_id=str(msg.person_id),
                person_name=_person_name(msg.person),
                message_id=str(msg.id),
                outreach_id=str(log.id) if log else None,
                age_days=_age_days(created),
                deep_link=_person_link(msg.person_id),
            )
        )
    return actions


def _rule_awaiting_reply(outreach_logs: list[OutreachLog]) -> list[NextAction]:
    cutoff = _now() - timedelta(days=AWAITING_REPLY_DAYS)
    actions: list[NextAction] = []
    for log in outreach_logs:
        if log.status != "sent":
            continue
        if log.response_received:
            continue
        last = _aware(log.last_contacted_at) or _aware(log.sent_at) or _aware(log.updated_at)
        if last is None or last > cutoff:
            continue
        actions.append(
            NextAction(
                kind="awaiting_reply",
                urgency="medium",
                reason=f"Sent {AWAITING_REPLY_DAYS}+ days ago with no reply — consider a follow-up.",
                suggested_channel=log.channel,
                suggested_goal="follow_up",
                job_id=str(log.job_id) if log.job_id else None,
                person_id=str(log.person_id),
                person_name=_person_name(log.person),
                outreach_id=str(log.id),
                age_days=_age_days(last),
                deep_link=_person_link(log.person_id),
            )
        )
    return actions


def _rule_live_targets_unused(
    snapshots: list[JobResearchSnapshot],
    outreach_logs: list[OutreachLog],
    jobs_by_id: dict[uuid.UUID, Job],
) -> list[NextAction]:
    contacted_jobs = {log.job_id for log in outreach_logs if log.job_id is not None}
    actions: list[NextAction] = []
    for snap in snapshots:
        if snap.verified_count < LIVE_TARGETS_MIN_VERIFIED:
            continue
        if snap.job_id in contacted_jobs:
            continue
        job = jobs_by_id.get(snap.job_id)
        if job is None:
            continue
        actions.append(
            NextAction(
                kind="live_targets_unused",
                urgency="medium",
                reason=(
                    f"{snap.verified_count} verified contact"
                    f"{'s' if snap.verified_count != 1 else ''} from your last research run — none contacted yet."
                ),
                suggested_channel="email",
                suggested_goal="referral",
                job_id=str(snap.job_id),
                job_title=job.title,
                company_name=job.company_name or snap.company_name,
                age_days=_age_days(snap.updated_at),
                deep_link=_job_link(snap.job_id),
                meta={
                    "verified_count": snap.verified_count,
                    "warm_path_count": snap.warm_path_count,
                },
            )
        )
    return actions


def _rule_applied_untouched(
    jobs: list[Job], outreach_logs: list[OutreachLog]
) -> list[NextAction]:
    cutoff = _now() - timedelta(days=APPLIED_UNTOUCHED_DAYS)
    contacted_jobs = {log.job_id for log in outreach_logs if log.job_id is not None}
    actions: list[NextAction] = []
    for job in jobs:
        if job.stage != "applied":
            continue
        applied_at = _aware(job.applied_at)
        if applied_at is None or applied_at > cutoff:
            continue
        if job.id in contacted_jobs:
            continue
        actions.append(
            NextAction(
                kind="applied_untouched",
                urgency="low",
                reason=f"Applied {APPLIED_UNTOUCHED_DAYS}+ days ago — no networking outreach yet.",
                suggested_channel="email",
                suggested_goal="referral",
                job_id=str(job.id),
                job_title=job.title,
                company_name=job.company_name,
                age_days=_age_days(applied_at),
                deep_link=_job_link(job.id),
            )
        )
    return actions


# --- Public API --------------------------------------------------------------


async def compute_next_actions(
    db: AsyncSession, user_id: uuid.UUID, limit: int | None = None
) -> list[NextAction]:
    jobs = await _load_jobs(db, user_id)
    messages = await _load_messages(db, user_id)
    outreach = await _load_outreach(db, user_id)
    snapshots = await _load_snapshots(db, user_id)

    jobs_by_id = {job.id: job for job in jobs}

    actions: list[NextAction] = []
    actions.extend(_rule_reply_needed(outreach))
    actions.extend(_rule_thank_you_due(jobs, messages))
    actions.extend(_rule_draft_unsent(messages, outreach))
    actions.extend(_rule_awaiting_reply(outreach))
    actions.extend(_rule_live_targets_unused(snapshots, outreach, jobs_by_id))
    actions.extend(_rule_applied_untouched(jobs, outreach))

    actions.sort(
        key=lambda a: (
            URGENCY_RANK.get(a.urgency, 99),
            -(a.age_days or 0),
        )
    )
    if limit is not None:
        actions = actions[:limit]
    return actions


def serialize_action(action: NextAction) -> dict[str, Any]:
    return asdict(action)
