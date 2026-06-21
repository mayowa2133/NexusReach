"""Persist live people-search results as durable per-job research artifacts.

Used by the job command center so freshly discovered recruiters / hiring
managers / peers survive across sessions without re-running search providers.
One snapshot per (user, job) — replaced on every fresh search.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import Job
from app.models.job_research_snapshot import JobResearchSnapshot

# Stale-while-revalidate windows for serving a saved snapshot on a Find People
# click. Within FRESH_TTL we serve and do nothing. Between FRESH_TTL and
# MAX_SERVE_AGE we serve instantly but trigger a background refresh. Beyond
# MAX_SERVE_AGE the data is too old to trust (people change companies) — run a
# live search instead.
SNAPSHOT_FRESH_TTL = timedelta(hours=24)
SNAPSHOT_MAX_SERVE_AGE = timedelta(days=14)

SnapshotServeDecision = Literal["fresh", "stale", "miss"]


def snapshot_serve_decision(
    snapshot: JobResearchSnapshot | None,
    *,
    now: datetime | None = None,
) -> SnapshotServeDecision:
    """Decide how to use a snapshot for a Find People click.

    - ``"fresh"``: serve it, no refresh needed.
    - ``"stale"``: serve it instantly, but kick off a background refresh.
    - ``"miss"``: do not serve — run a live search (no snapshot, empty result,
      or too old to trust).
    """
    if snapshot is None:
        return "miss"
    # Never serve an empty snapshot — a user clicking Find People on a blank
    # result would assume it's broken. Run live to actually find people.
    if not snapshot.total_candidates:
        return "miss"
    ts = snapshot.updated_at or snapshot.created_at
    if ts is None:
        return "miss"
    now = now or datetime.now(timezone.utc)
    age = now - ts
    if age > SNAPSHOT_MAX_SERVE_AGE:
        return "miss"
    if age > SNAPSHOT_FRESH_TTL:
        return "stale"
    return "fresh"


def _person_warm_path(person: dict) -> bool:
    return bool(person.get("warm_path_type"))


def _person_verified(person: dict) -> bool:
    return bool(person.get("current_company_verified"))


def _summarize(
    *,
    recruiters: list[dict],
    hiring_managers: list[dict],
    peers: list[dict],
    your_connections: list[dict],
) -> dict[str, int]:
    total = len(recruiters) + len(hiring_managers) + len(peers)
    warm_in_buckets = sum(
        1
        for person in (*recruiters, *hiring_managers, *peers)
        if _person_warm_path(person)
    )
    verified = sum(
        1
        for person in (*recruiters, *hiring_managers, *peers)
        if _person_verified(person)
    )
    return {
        "recruiter_count": len(recruiters),
        "manager_count": len(hiring_managers),
        "peer_count": len(peers),
        "warm_path_count": warm_in_buckets + len(your_connections),
        "verified_count": verified,
        "total_candidates": total,
    }


async def save_job_research_snapshot(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    job_id: uuid.UUID,
    company_name: str | None,
    target_count_per_bucket: int | None,
    recruiters: list[dict],
    hiring_managers: list[dict],
    peers: list[dict],
    your_connections: list[dict],
    errors: list[dict] | None = None,
) -> JobResearchSnapshot | None:
    """Upsert the latest snapshot for (user_id, job_id).

    Returns None if the job does not belong to the user (defensive — callers
    should already have verified ownership via search_people_for_job).
    """
    job_result = await db.execute(
        select(Job.id).where(Job.id == job_id, Job.user_id == user_id)
    )
    if job_result.scalar_one_or_none() is None:
        return None

    counts = _summarize(
        recruiters=recruiters,
        hiring_managers=hiring_managers,
        peers=peers,
        your_connections=your_connections,
    )

    existing_result = await db.execute(
        select(JobResearchSnapshot).where(
            JobResearchSnapshot.user_id == user_id,
            JobResearchSnapshot.job_id == job_id,
        )
    )
    snapshot = existing_result.scalar_one_or_none()

    if snapshot is None:
        snapshot = JobResearchSnapshot(
            user_id=user_id,
            job_id=job_id,
        )
        db.add(snapshot)

    snapshot.company_name = company_name
    snapshot.target_count_per_bucket = target_count_per_bucket
    snapshot.recruiters = recruiters
    snapshot.hiring_managers = hiring_managers
    snapshot.peers = peers
    snapshot.your_connections = your_connections
    snapshot.errors = errors
    snapshot.recruiter_count = counts["recruiter_count"]
    snapshot.manager_count = counts["manager_count"]
    snapshot.peer_count = counts["peer_count"]
    snapshot.warm_path_count = counts["warm_path_count"]
    snapshot.verified_count = counts["verified_count"]
    snapshot.total_candidates = counts["total_candidates"]

    await db.commit()
    await db.refresh(snapshot)
    return snapshot


async def get_job_research_snapshot(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    job_id: uuid.UUID,
) -> JobResearchSnapshot | None:
    result = await db.execute(
        select(JobResearchSnapshot).where(
            JobResearchSnapshot.user_id == user_id,
            JobResearchSnapshot.job_id == job_id,
        )
    )
    return result.scalar_one_or_none()


async def delete_job_research_snapshot(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    job_id: uuid.UUID,
) -> bool:
    snapshot = await get_job_research_snapshot(db, user_id=user_id, job_id=job_id)
    if snapshot is None:
        return False
    await db.delete(snapshot)
    await db.commit()
    return True


def serialize_snapshot(snapshot: JobResearchSnapshot | None) -> dict[str, Any] | None:
    if snapshot is None:
        return None
    return {
        "id": str(snapshot.id),
        "job_id": str(snapshot.job_id),
        "company_name": snapshot.company_name,
        "target_count_per_bucket": snapshot.target_count_per_bucket,
        "recruiters": snapshot.recruiters or [],
        "hiring_managers": snapshot.hiring_managers or [],
        "peers": snapshot.peers or [],
        "your_connections": snapshot.your_connections or [],
        "recruiter_count": snapshot.recruiter_count,
        "manager_count": snapshot.manager_count,
        "peer_count": snapshot.peer_count,
        "warm_path_count": snapshot.warm_path_count,
        "verified_count": snapshot.verified_count,
        "total_candidates": snapshot.total_candidates,
        "errors": snapshot.errors,
        "created_at": snapshot.created_at.isoformat() if snapshot.created_at else None,
        "updated_at": snapshot.updated_at.isoformat() if snapshot.updated_at else None,
    }
