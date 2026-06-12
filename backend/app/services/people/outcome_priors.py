"""Outcome-driven ranking priors from the user's own outreach history.

Reply detection writes ``responded`` / ``response_received`` onto outreach
logs automatically; this module turns that history into a small, bounded
ranking prior: archetypes (person_type x org level) that actually replied for
this user get a late tie-break boost. With fewer than ``MIN_SENT_PER_ARCHETYPE``
sends for an archetype the prior is neutral, so new users are unaffected.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.outreach import OutreachLog
from app.models.person import Person
from app.services.people.classify import _classify_org_level

logger = logging.getLogger(__name__)

MIN_SENT_PER_ARCHETYPE = 3
_REPLIED_STATUSES = ("responded", "met", "closed")
_SENT_STATUSES = ("sent",) + _REPLIED_STATUSES


def _archetype(person_type: str | None, org_level: str | None) -> tuple[str, str]:
    return (person_type or "unknown", org_level or "ic")


async def load_reply_priors(db: AsyncSession, user_id: uuid.UUID) -> dict[tuple[str, str], float]:
    """Reply rate per (person_type, org_level) with enough samples to trust."""
    try:
        stmt = (
            select(Person.person_type, Person.seniority_level, OutreachLog.status, OutreachLog.response_received)
            .join(Person, OutreachLog.person_id == Person.id)
            .where(
                OutreachLog.user_id == user_id,
                OutreachLog.status.in_(_SENT_STATUSES),
            )
        )
        rows = (await db.execute(stmt)).all()
    except Exception:
        logger.debug("reply prior load failed; ranking stays neutral", exc_info=True)
        return {}

    sent: dict[tuple[str, str], int] = {}
    replied: dict[tuple[str, str], int] = {}
    for person_type, seniority_level, status, response_received in rows:
        key = _archetype(person_type, seniority_level)
        sent[key] = sent.get(key, 0) + 1
        if response_received or status in _REPLIED_STATUSES:
            replied[key] = replied.get(key, 0) + 1

    priors: dict[tuple[str, str], float] = {}
    for key, count in sent.items():
        if count >= MIN_SENT_PER_ARCHETYPE:
            priors[key] = replied.get(key, 0) / count
    return priors


def stamp_outcome_priors(
    candidates: list[dict],
    priors: dict[tuple[str, str], float],
    *,
    bucket: str,
) -> None:
    """Annotate candidates with a 0/1 late-rank component from reply history.

    A candidate is favored only when its archetype has an above-average reply
    rate among archetypes observed for this bucket. No data = everyone gets
    the same neutral value and ordering is untouched.
    """
    if not priors:
        return
    person_type = {
        "recruiters": "recruiter",
        "hiring_managers": "hiring_manager",
        "peers": "peer",
    }.get(bucket, bucket)
    bucket_rates = [rate for (ptype, _), rate in priors.items() if ptype == person_type]
    if not bucket_rates:
        return
    average = sum(bucket_rates) / len(bucket_rates)
    for candidate in candidates:
        org_level = candidate.get("_org_level") or _classify_org_level(
            candidate.get("title", ""), snippet=candidate.get("snippet", "")
        )
        rate = priors.get(_archetype(person_type, org_level))
        if rate is not None and rate > average:
            candidate["_outcome_prior_rank"] = 0


def outcome_prior_rank(data: dict[str, Any]) -> int:
    return data.get("_outcome_prior_rank", 1)
