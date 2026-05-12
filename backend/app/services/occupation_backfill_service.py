"""Backfill `occupation:<key>` tags on historical Job rows.

This is intentionally idempotent and safe to re-run:
- A job that already carries an ``occupation:`` tag is left alone (we trust
  whatever the ingestion pipeline stamped).
- A job whose title classifies cleanly gets the matching tags merged in.
- A job whose title doesn't match any alias is skipped (recorded as
  ``unclassified``); we do not invent tags.

The classifier is the same one used during live ingestion, so behavior here
matches what new jobs would receive.
"""

from __future__ import annotations

import logging
import uuid
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import Job
from app.services.occupation_taxonomy import (
    OCCUPATION_TAG_PREFIX,
    classify_title,
    occupation_tag,
)
from app.utils.startup_jobs import merge_tags

logger = logging.getLogger(__name__)

BATCH_SIZE = 200


def _existing_occupation_tags(tags: Iterable[str] | None) -> list[str]:
    return [
        tag
        for tag in (tags or [])
        if isinstance(tag, str) and tag.startswith(OCCUPATION_TAG_PREFIX)
    ]


async def backfill_occupation_tags(
    db: AsyncSession,
    *,
    user_id: uuid.UUID | None = None,
    limit: int | None = None,
    dry_run: bool = False,
) -> dict[str, int]:
    """Walk Job rows and stamp inferred ``occupation:<key>`` tags.

    Returns a counters dict for the caller to surface:
    - ``scanned``: total rows examined
    - ``already_tagged``: rows that already had at least one occupation tag
    - ``tagged``: rows newly tagged
    - ``unclassified``: rows the classifier could not match
    - ``errors``: rows that raised during processing
    """
    counters = {
        "scanned": 0,
        "already_tagged": 0,
        "tagged": 0,
        "unclassified": 0,
        "errors": 0,
    }

    stmt = select(Job).order_by(Job.created_at.asc(), Job.id.asc())
    if user_id is not None:
        stmt = stmt.where(Job.user_id == user_id)
    if limit is not None and limit > 0:
        stmt = stmt.limit(limit)

    result = await db.execute(stmt)
    jobs = list(result.scalars().all())
    pending: list[Job] = []

    for job in jobs:
        counters["scanned"] += 1
        try:
            if _existing_occupation_tags(job.tags):
                counters["already_tagged"] += 1
                continue

            keys = classify_title(job.title, job.description)
            if not keys:
                counters["unclassified"] += 1
                continue

            new_tags = [occupation_tag(key) for key in keys]
            merged = merge_tags(job.tags, new_tags)
            if merged == job.tags:
                counters["unclassified"] += 1
                continue

            counters["tagged"] += 1
            if dry_run:
                continue

            job.tags = merged
            pending.append(job)

            if len(pending) >= BATCH_SIZE:
                await db.commit()
                pending.clear()
        except Exception:
            counters["errors"] += 1
            logger.exception("Backfill failed for job %s", getattr(job, "id", None))

    if pending and not dry_run:
        await db.commit()

    logger.info(
        "Occupation tag backfill complete: user=%s scanned=%d tagged=%d already=%d unclassified=%d errors=%d dry_run=%s",
        user_id,
        counters["scanned"],
        counters["tagged"],
        counters["already_tagged"],
        counters["unclassified"],
        counters["errors"],
        dry_run,
    )
    return counters
