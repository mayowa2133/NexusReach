"""Backfill enrichment for existing newgrad-jobs rows."""

import logging
import uuid

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients import newgrad_jobs_client
from app.models.job import Job
from app.models.profile import Profile
from app.services.job_service import (
    _experience_level_for_job,
    _fingerprint,
    _refresh_existing_job,
    _score_job,
)

logger = logging.getLogger(__name__)


def _job_snapshot(job: Job) -> tuple:
    return (
        job.external_id,
        job.location,
        job.remote,
        job.description,
        job.employment_type,
        job.salary_min,
        job.salary_max,
        job.salary_currency,
        job.experience_level,
        job.match_score,
        job.posted_at,
        job.fingerprint,
    )


async def backfill_newgrad_jobs(
    db: AsyncSession,
    *,
    user_id: uuid.UUID | None = None,
    limit: int | None = None,
) -> dict[str, int]:
    """Re-enrich existing newgrad-jobs rows in place."""
    stmt = (
        select(Job)
        .where(Job.source == "newgrad_jobs")
        .order_by(Job.created_at.asc(), Job.id.asc())
    )
    if user_id is not None:
        stmt = stmt.where(Job.user_id == user_id)
    if limit is not None:
        stmt = stmt.limit(limit)

    result = await db.execute(stmt)
    jobs = list(result.scalars().all())
    if not jobs:
        return {"checked": 0, "updated": 0, "skipped": 0}

    profile_cache: dict[uuid.UUID, Profile | None] = {}
    updated = 0
    skipped = 0

    async with httpx.AsyncClient(
        timeout=newgrad_jobs_client.DEFAULT_TIMEOUT,
        follow_redirects=True,
    ) as client:
        for job in jobs:
            if not job.url:
                skipped += 1
                continue

            detail = await newgrad_jobs_client.fetch_job_detail(job.url, client=client)
            if not detail or detail.get("closed"):
                skipped += 1
                continue

            if job.user_id not in profile_cache:
                profile_result = await db.execute(
                    select(Profile).where(Profile.user_id == job.user_id)
                )
                profile_cache[job.user_id] = profile_result.scalar_one_or_none()
            profile = profile_cache[job.user_id]

            data = {
                "external_id": job.external_id or newgrad_jobs_client.build_external_id_from_url(job.url),
                "title": job.title,
                "company_name": job.company_name,
                "company_logo": job.company_logo,
                "location": job.location,
                "remote": job.remote,
                "url": job.url,
                "description": job.description,
                "employment_type": job.employment_type,
                "salary_min": job.salary_min,
                "salary_max": job.salary_max,
                "salary_currency": job.salary_currency,
                "source": job.source,
                "ats": job.ats,
                "ats_slug": job.ats_slug,
                "posted_at": job.posted_at,
                "tags": job.tags,
                "department": job.department,
            }
            data.update(detail)

            fingerprint = _fingerprint(
                data.get("company_name", ""),
                data.get("title", ""),
                data.get("location", ""),
            )
            score, breakdown = _score_job(data, profile)
            experience_level = _experience_level_for_job(data)

            before = _job_snapshot(job)
            _refresh_existing_job(
                job,
                data,
                fingerprint=fingerprint,
                score=score,
                breakdown=breakdown,
                experience_level=experience_level,
            )
            after = _job_snapshot(job)
            if after != before:
                updated += 1
            else:
                skipped += 1

    if updated:
        await db.commit()

    logger.info(
        "Backfilled newgrad jobs: checked=%d updated=%d skipped=%d",
        len(jobs),
        updated,
        skipped,
    )
    return {"checked": len(jobs), "updated": updated, "skipped": skipped}
