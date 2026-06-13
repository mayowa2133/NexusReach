"""Ingest the LinkedIn "Meet the hiring team" panel captured by the companion.

LinkedIn shows, on a job posting, the actual people who posted the req - the
literal hiring contact(s). The companion captures that panel from the page the
user is already viewing in their own browser (same posture as the existing
profile capture) and posts it here. These are the strongest possible contacts:
LinkedIn itself attached them to this exact req, so they are stored verified
and rank at the very top of their bucket.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.people.classify import _classify_person_with_confidence
from app.services.people.persistence import _store_person, get_or_create_company
from app.utils.linkedin import normalize_linkedin_url

logger = logging.getLogger(__name__)

CAPTURE_SOURCE = "linkedin_hiring_team"
MAX_MEMBERS = 6


def _classify_member(headline: str, role_label: str) -> str:
    """Bucket a captured member from its headline / panel role label.

    The panel's own label ("Job poster", "Recruiter", "Hiring manager") is the
    first signal; the LinkedIn headline is the fallback. Anything not clearly a
    recruiter or manager defaults to recruiter, because the hiring-team panel
    is a hiring contact by definition - never a random peer.
    """
    label = (role_label or "").lower()
    if "recruit" in label or "talent" in label or "sourcer" in label:
        return "recruiter"
    if "hiring manager" in label or "manager" in label or "lead" in label or "director" in label:
        return "hiring_manager"
    bucket, _ = _classify_person_with_confidence(headline or "")
    # The panel is a hiring contact; if the classifier says "peer" we still
    # treat them as a recruiter (the default hiring contact on a posting).
    return "hiring_manager" if bucket == "hiring_manager" else "recruiter"


def _member_to_candidate(member: dict, company_name: str, job_title: str | None) -> dict | None:
    name = (member.get("name") or "").strip()
    if not name or " " not in name:
        return None
    headline = (member.get("headline") or "").strip()
    role_label = (member.get("role_label") or "").strip()
    linkedin_url = normalize_linkedin_url(member.get("profile_url"))
    bucket = _classify_member(headline, role_label)
    job_ref = f" for {job_title}" if job_title else ""
    return {
        "bucket": bucket,
        "data": {
            "full_name": name,
            "title": headline or role_label or "Recruiter",
            "source": CAPTURE_SOURCE,
            "snippet": (
                f"Named on {company_name}'s LinkedIn hiring team{job_ref}"
                + (f" ({role_label})" if role_label else "")
            ),
            "linkedin_url": linkedin_url,
            "_hiring_team_capture": True,
            "_employment_status": "current",
            "profile_data": {
                "company_match_confidence": "verified",
                "current_company_verified": True,
                "hiring_team_capture": True,
                "hiring_team_role_label": role_label or None,
                "captured_at": datetime.now(timezone.utc).isoformat(),
            },
        },
    }


async def ingest_hiring_team_capture(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    company_name: str,
    members: list[dict],
    job_id: uuid.UUID | None = None,
    job_title: str | None = None,
) -> dict:
    """Persist captured hiring-team members as verified contacts.

    Each member is classified, stored as a Person row in the right bucket
    (deduped by ``_store_person``), and written to the global known-people
    cache so future searches for this company surface them. Returns per-bucket
    stored counts and the stored people.
    """
    company_name = (company_name or "").strip()
    if not company_name or not members:
        return {"stored": 0, "recruiters": 0, "hiring_managers": 0}

    company = await get_or_create_company(db, user_id, company_name)

    candidates = []
    for member in members[:MAX_MEMBERS]:
        candidate = _member_to_candidate(member, company_name, job_title)
        if candidate is not None:
            candidates.append(candidate)

    stored = {"stored": 0, "recruiters": 0, "hiring_managers": 0, "people": []}
    for candidate in candidates:
        bucket = candidate["bucket"]
        data = candidate["data"]
        if job_id is not None:
            data["job_id"] = str(job_id)
        try:
            person = await _store_person(db, user_id, company, data, bucket)
        except Exception:
            logger.warning("hiring-team member store failed for %s", data.get("full_name"), exc_info=True)
            continue
        stored["stored"] += 1
        stored["recruiters" if bucket == "recruiter" else "hiring_managers"] += 1
        stored["people"].append(person)

    if stored["stored"]:
        await db.commit()

    # Best-effort write to the global known-people cache so future searches
    # for this company surface these contacts without re-capture.
    try:
        from app.services.known_people_service import write_candidates_to_cache

        await write_candidates_to_cache(
            db,
            [c["data"] for c in candidates],
            company_name=company_name,
            company_domain=company.domain if company else None,
        )
    except Exception:
        logger.debug("hiring-team cache write failed", exc_info=True)

    return stored
