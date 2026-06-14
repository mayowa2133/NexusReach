"""Job intelligence service — aggregates, deduplicates, scores, and tracks jobs."""

import asyncio
import hashlib
import logging
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlparse, urlunparse

from sqlalchemy import Date, func as sa_func, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.clients import (
    adzuna_client,
    amazon_client,
    apple_client,
    ats,
    conviction_jobs_client,
    curated_startups_client,
    google_client,
    jsearch_client,
    lever_scrape_client,
    meta_client,
    microsoft_client,
    newgrad_jobs_client,
    public_page_client,
    remote_jobs_client,
    speedrun_jobs_client,
    tesla_client,
    ventureloop_jobs_client,
    wellfound_jobs_client,
    workday_client,
    yc_jobs_client,
)
from app.models.company import Company
from app.models.job import Job
from app.models.job_refresh_run import JobSourceRun
from app.models.message import Message
from app.models.outreach import OutreachLog
from app.models.person import Person
from app.models.profile import Profile
from app.models.resume_artifact import ResumeArtifact
from app.models.search_preference import SearchPreference
from app.models.tailored_resume import TailoredResume
from app.services.job_research_snapshot_service import (
    get_job_research_snapshot,
    serialize_snapshot,
)
from app.utils.company_identity import normalize_company_name
from app.utils.job_metadata import (
    country_code_for_name,
    geocode_location_query,
    normalize_job_metadata,
)
from app.services.occupation_taxonomy import (
    OCCUPATION_TAG_PREFIX,
    discover_queries_for_occupations,
    occupation_tag,
    occupation_tags_for_job,
)
from app.utils.startup_jobs import (
    STARTUP_TAG,
    append_startup_tags,
    extract_candidate_links,
    has_startup_tag,
    is_supported_job_link,
    job_matches_any_query,
    looks_like_careers_page,
    merge_startup_tags,
    merge_tags,
    startup_discover_queries,
    startup_source_tag,
    startup_tags,
)

logger = logging.getLogger(__name__)

EARTH_RADIUS_KM = 6371.0
DEFAULT_SEARCH_SOURCES = [
    "jsearch",
    "adzuna",
    "remotive",
    "jobicy",
    "dice",
    "simplify",
    "newgrad",
]
STARTUP_BOARD_SOURCES = ["yc_jobs", "wellfound", "ventureloop"]
STARTUP_LINK_RESOLVE_CONCURRENCY = 6
DISCOVER_LIMIT_PER_SOURCE = 50
DISCOVER_LOCATION_FANOUT = 2
STARTUP_MAX_RESOLVED_LINKS_PER_COMPANY = 3
APPLY_URL_REPAIR_MAX_JOBS = 20

# Occupations bound to non-tech industries: hospitals, schools, law firms,
# government, studios. For these, the curated tech ATS boards + tech-leaning
# boards (Dice, Simplify, newgrad) are pure noise, so discovery routes to the
# broad all-industry aggregators (JSearch / Adzuna / Remotive) instead.
INDUSTRY_BOUND_NONTECH_OCCUPATIONS = frozenset({
    "healthcare",
    "education_training",
    "legal_compliance",
    "public_sector_government",
    "arts_entertainment",
})


def _suppress_tech_sources(resolved_occupations: list[str] | None) -> bool:
    """True only when EVERY resolved occupation is industry-bound non-tech.

    Conservative: a cross-industry occupation (sales, marketing, finance, ...)
    keeps the tech sources, since those seekers may target tech companies. We
    only suppress when the whole search is for a sector where tech employers
    cannot be the answer (e.g. nursing, teaching, law).
    """
    occs = [o for o in (resolved_occupations or []) if o]
    if not occs:
        return False
    return all(o in INDUSTRY_BOUND_NONTECH_OCCUPATIONS for o in occs)


# Curated non-tech employer lists (Workday-backed health systems, universities,
# banks/insurers, retailers) are the vertical analog of the tech ATS boards.
# This maps an occupation to the verticals whose employers actually hire it, so
# a nursing search pulls health systems and a finance search pulls banks. Only
# occupations with a clear vertical home are mapped; everything else relies on
# the broad aggregators. Cross-industry occupations (sales, support) map to
# multiple verticals since those employers hire heavily for them.
OCCUPATION_VERTICALS: dict[str, frozenset[str]] = {
    "healthcare": frozenset({"healthcare"}),
    "education_training": frozenset({"education"}),
    "accounting_finance": frozenset({"finance"}),
    "sales": frozenset({"finance", "retail"}),
    "customer_service_support": frozenset({"finance", "retail"}),
    "supply_chain": frozenset({"retail"}),
}


def verticals_for_occupations(resolved_occupations: list[str] | None) -> set[str]:
    """Union of curated verticals the resolved occupations should pull from."""
    out: set[str] = set()
    for occ in resolved_occupations or []:
        out |= OCCUPATION_VERTICALS.get(occ, frozenset())
    return out


# --- Deduplication ---

def _fingerprint(company_name: str | None, title: str | None, location: str | None) -> str:
    """Create a fingerprint for deduplication based on company + title + location."""
    raw = (
        f"{(company_name or '').lower().strip()}|"
        f"{(title or '').lower().strip()}|"
        f"{(location or '').lower().strip()}"
    )
    return hashlib.md5(raw.encode()).hexdigest()


def _normalized_pref_location(location: str | None) -> str:
    """Normalize a saved-search location for dedup (audit M17).

    Uses the geocoder's canonical label when the location is recognized so
    "New York", "New York, NY" and "NYC" collapse to one key; otherwise falls
    back to a whitespace/case-folded form. Empty stays empty.
    """
    raw = (location or "").strip()
    if not raw:
        return ""
    geo = geocode_location_query(raw)
    if geo and getattr(geo, "label", None):
        return " ".join(geo.label.lower().split())
    return " ".join(raw.lower().split())


def _canonical_job_url(url: str | None) -> str | None:
    if not url:
        return None
    parsed = ats.parse_ats_job_url(url)
    if parsed and parsed.canonical_url:
        return parsed.canonical_url.rstrip("/")
    normalized = url.rstrip("/")
    if not normalized:
        return None
    parsed_url = urlparse(normalized)
    if parsed_url.scheme and parsed_url.netloc:
        return urlunparse(parsed_url._replace(query="", fragment="")).rstrip("/")
    return None


def _result_first(result) -> Job | None:
    scalars = getattr(result, "scalars", None)
    if callable(scalars):
        return scalars().first()
    return result.scalar_one_or_none()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _source_stat(source: str, *, started_at: datetime | None = None) -> dict:
    started = started_at or _utcnow()
    return {
        "source": source,
        "status": "success",
        "started_at": started,
        "finished_at": None,
        "duration_seconds": None,
        "raw_count": 0,
        "new_count": 0,
        "existing_count": 0,
        "duplicate_count": 0,
        "skipped_count": 0,
        "error": None,
        "details": None,
    }


def _finish_source_stat(stat: dict, *, status: str | None = None, error: str | None = None) -> None:
    finished_at = _utcnow()
    stat["finished_at"] = finished_at
    stat["duration_seconds"] = round(
        (finished_at - stat["started_at"]).total_seconds(), 3
    )
    if status:
        stat["status"] = status
    if error:
        stat["error"] = error[:2000]


def summarize_source_stats(source_stats: list[dict]) -> dict:
    return {
        "total_seen": sum(int(stat.get("raw_count") or 0) for stat in source_stats),
        "total_new": sum(int(stat.get("new_count") or 0) for stat in source_stats),
        "total_existing": sum(int(stat.get("existing_count") or 0) for stat in source_stats),
        "total_duplicates": sum(int(stat.get("duplicate_count") or 0) for stat in source_stats),
        "total_errors": sum(1 for stat in source_stats if stat.get("status") == "failed"),
    }


def _job_source_key(data: dict | None = None, *, source: str | None = None, ats: str | None = None) -> str | None:
    if source:
        return source
    if data is not None and data.get("source"):
        return data.get("source")
    if ats:
        return ats
    if data is not None:
        return data.get("ats")
    return None


def _job_identity_key(data: dict, *, fingerprint: str) -> str:
    source_key = _job_source_key(data)
    external_id = data.get("external_id")
    if source_key and external_id:
        return f"source:{source_key}:external:{external_id}"

    canonical_url = _canonical_job_url(data.get("url"))
    if source_key and canonical_url:
        return f"source:{source_key}:url:{canonical_url}"
    if canonical_url:
        return f"url:{canonical_url}"

    return f"fingerprint:{fingerprint}"


def _coerce_posted_at(value: str | None) -> str | None:
    """Normalize posted_at to None when empty or whitespace-only."""
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


_POSTED_DATE_RE = re.compile(r"^\s*(\d{4})-(\d{2})-(\d{2})")


def _parse_posted_date(value: str | None) -> date | None:
    """Parse a calendar-valid leading ISO date (YYYY-MM-DD) from posted_at.

    Returns None for missing, non-date-shaped, or date-shaped-but-invalid values
    (e.g. "2026-02-30", "2026-13-01"). This validated value feeds the indexed
    ``posted_date`` column so date ordering never casts a bad string at query
    time (audit pass-2 P3).
    """
    if not isinstance(value, str):
        return None
    match = _POSTED_DATE_RE.match(value)
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def _experience_level_for_job(job_data: dict) -> str:
    return normalize_job_metadata(job_data).get("experience_level") or "mid"


def _employment_type_for_job(job_data: dict, experience_level: str) -> str | None:
    employment_type = job_data.get("employment_type")
    if employment_type:
        return employment_type
    if experience_level == "intern":
        return "internship"
    return None


def _apply_if_present(job: Job, attr: str, value) -> None:
    if isinstance(value, str):
        if value.strip():
            setattr(job, attr, value)
        return
    if value is not None:
        setattr(job, attr, value)


def _distance_km_expression(latitude: float, longitude: float):
    """Return SQL expression for distance from a job to a point in kilometers."""
    lat_rad = sa_func.radians(latitude)
    lng_rad = sa_func.radians(longitude)
    job_lat_rad = sa_func.radians(Job.location_lat)
    job_lng_rad = sa_func.radians(Job.location_lng)
    cosine_distance = (
        sa_func.cos(lat_rad)
        * sa_func.cos(job_lat_rad)
        * sa_func.cos(job_lng_rad - lng_rad)
        + sa_func.sin(lat_rad)
        * sa_func.sin(job_lat_rad)
    )
    bounded = sa_func.least(1.0, sa_func.greatest(-1.0, cosine_distance))
    return EARTH_RADIUS_KM * sa_func.acos(bounded)


def _with_extra_tags(data: dict, extra_tags: list[str] | None) -> dict:
    if not extra_tags:
        return data
    return {
        **data,
        "tags": merge_tags(data.get("tags"), extra_tags),
    }


def _refresh_existing_job(
    job: Job,
    data: dict,
    *,
    fingerprint: str,
    score: float | None,
    breakdown: dict,
    experience_level: str,
) -> None:
    _apply_if_present(job, "external_id", data.get("external_id"))
    _apply_if_present(job, "title", data.get("title"))
    _apply_if_present(job, "company_name", data.get("company_name"))
    _apply_if_present(job, "company_logo", data.get("company_logo"))
    _apply_if_present(job, "location", data.get("location"))
    # Only overwrite location/geocode fields when the refresh actually provides
    # them — otherwise a source that omits location on re-fetch would wipe
    # previously enriched data (audit M1).
    for _field in (
        "locations",
        "country_codes",
        "countries",
        "location_lat",
        "location_lng",
        "location_radius_km",
        "location_geocode_label",
    ):
        _value = data.get(_field)
        if _value is not None:
            setattr(job, _field, _value)
    if data.get("remote") is not None:
        job.remote = bool(data.get("remote"))
    # Only overwrite work_mode when the refresh actually detected one — a source
    # that yields work_mode=None must not wipe a previously detected hybrid/remote
    # label (audit pass-2 P7; same class as M1).
    if data.get("work_mode") is not None:
        job.work_mode = data.get("work_mode")
    _apply_if_present(job, "url", data.get("url"))
    # Keep the indexed canonical URL in sync so dedup stays fast (audit H7).
    new_canonical = _canonical_job_url(data.get("url"))
    if new_canonical:
        job.canonical_url = new_canonical
    _apply_if_present(job, "apply_url", data.get("apply_url") or data.get("url"))
    _apply_if_present(job, "description", data.get("description"))
    _apply_if_present(job, "source", data.get("source"))
    _apply_if_present(job, "ats", data.get("ats"))
    _apply_if_present(job, "ats_slug", data.get("ats_slug"))
    _apply_if_present(job, "posted_at", data.get("posted_at"))
    # Keep the validated posted_date in sync when a new posted_at is provided.
    new_posted_date = _parse_posted_date(data.get("posted_at"))
    if new_posted_date is not None:
        job.posted_date = new_posted_date
    job.match_score = score
    job.score_breakdown = breakdown
    job.scored_at = datetime.now(timezone.utc) if score is not None else None
    job.last_seen_at = _utcnow()
    job.source_status = "active"
    job.closed_at = None
    job.not_seen_count = 0
    job.fingerprint = fingerprint
    _apply_if_present(job, "department", data.get("department"))
    _apply_if_present(job, "employment_type", _employment_type_for_job(data, experience_level))
    job.salary_min = data.get("salary_min")
    job.salary_max = data.get("salary_max")
    job.salary_currency = data.get("salary_currency")
    job.salary_period = data.get("salary_period")
    if data.get("tags") is not None:
        # Carry over startup tags from the incoming payload (existing behavior),
        # then layer in any new occupation:* tags inferred from the latest data
        # so jobs created before the taxonomy existed gain occupation tags on
        # the next refresh.
        merged = merge_startup_tags(job.tags, data.get("tags"))
        incoming_occupation_tags = [
            tag
            for tag in (data.get("tags") or [])
            if isinstance(tag, str) and tag.startswith(OCCUPATION_TAG_PREFIX)
        ]
        if incoming_occupation_tags:
            merged = merge_tags(merged, incoming_occupation_tags)
        job.tags = merged
    job.experience_level = experience_level
    job.experience_level_confidence = data.get("experience_level_confidence")
    job.metadata_provenance = data.get("metadata_provenance")


def _build_job(
    *,
    user_id: uuid.UUID,
    data: dict,
    score: float | None,
    breakdown: dict,
    fingerprint: str,
) -> Job:
    experience_level = data.get("experience_level") or _experience_level_for_job(data)
    return Job(
        user_id=user_id,
        external_id=data.get("external_id"),
        title=data.get("title", ""),
        company_name=data.get("company_name", "Unknown"),
        company_logo=data.get("company_logo"),
        location=data.get("location"),
        locations=data.get("locations"),
        country_codes=data.get("country_codes"),
        countries=data.get("countries"),
        location_lat=data.get("location_lat"),
        location_lng=data.get("location_lng"),
        location_radius_km=data.get("location_radius_km"),
        location_geocode_label=data.get("location_geocode_label"),
        remote=data.get("remote", False),
        work_mode=data.get("work_mode"),
        url=data.get("url"),
        canonical_url=_canonical_job_url(data.get("url")),
        apply_url=data.get("apply_url") or data.get("url"),
        description=data.get("description"),
        employment_type=_employment_type_for_job(data, experience_level),
        experience_level=experience_level,
        experience_level_confidence=data.get("experience_level_confidence"),
        salary_min=data.get("salary_min"),
        salary_max=data.get("salary_max"),
        salary_currency=data.get("salary_currency"),
        salary_period=data.get("salary_period"),
        source=data.get("source", "unknown"),
        ats=data.get("ats"),
        ats_slug=data.get("ats_slug"),
        posted_at=_coerce_posted_at(data.get("posted_at")),
        posted_date=_parse_posted_date(data.get("posted_at")),
        match_score=score,
        score_breakdown=breakdown,
        scored_at=datetime.now(timezone.utc) if score is not None else None,
        fingerprint=fingerprint,
        tags=data.get("tags"),
        metadata_provenance=data.get("metadata_provenance"),
        department=data.get("department"),
        source_status="active",
        last_seen_at=_utcnow(),
        not_seen_count=0,
    )


async def _find_existing_job(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    source: str | None,
    ats: str | None,
    external_id: str | None,
    url: str | None,
    fingerprint: str | None,
) -> Job | None:
    source_key = _job_source_key(source=source, ats=ats)

    if source_key and external_id:
        result = await db.execute(
            select(Job)
            .where(Job.user_id == user_id, Job.source == source_key, Job.external_id == external_id)
            .order_by(Job.created_at.asc(), Job.id.asc())
        )
        existing = _result_first(result)
        if existing:
            return existing

    normalized_url = _canonical_job_url(url)
    if normalized_url:
        # Indexed exact match on the stored canonical URL (audit H7) — replaces
        # the previous unbounded scan that loaded every job for the user+source
        # and recomputed canonical URLs in Python.
        result = await db.execute(
            select(Job)
            .where(Job.user_id == user_id, Job.canonical_url == normalized_url)
            .order_by(Job.created_at.asc(), Job.id.asc())
        )
        existing = _result_first(result)
        if existing:
            return existing

        # Fallback for legacy rows ingested before canonical_url existed: scan
        # only rows that still lack it, narrowed by host, and backfill on match.
        host = urlparse(normalized_url).netloc
        legacy_filters = [
            Job.user_id == user_id,
            Job.url.is_not(None),
            Job.canonical_url.is_(None),
        ]
        if host:
            # Escape LIKE metacharacters so a host containing % or _ can't widen
            # the scan (audit pass-2 P14).
            safe_host = host.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            legacy_filters.append(Job.url.ilike(f"%{safe_host}%", escape="\\"))
        legacy_result = await db.execute(
            select(Job).where(*legacy_filters).order_by(Job.created_at.asc(), Job.id.asc())
        )
        for existing in legacy_result.scalars().all():
            if _canonical_job_url(existing.url) == normalized_url:
                existing.canonical_url = normalized_url
                return existing

    if fingerprint:
        result = await db.execute(
            select(Job)
            .where(Job.user_id == user_id, Job.fingerprint == fingerprint)
            .order_by(Job.created_at.asc(), Job.id.asc())
        )
        existing = _result_first(result)
        if existing:
            return existing

    return None


# --- Scoring ---


def _score_job(job_data: dict, profile: Profile | None) -> tuple[float | None, dict]:
    """Score a job against the user's profile using the enhanced scorer.

    Delegates to match_scoring.score_job for multi-axis algorithmic matching
    with skill synonyms, word-boundary matching, experience relevance, etc.

    Returns:
        (score 0-100, breakdown dict)
    """
    from app.services.match_scoring import score_job  # noqa: PLC0415
    return score_job(job_data, profile)


def _adzuna_country_for_location(location: str | None) -> str:
    geocode = geocode_location_query(location)
    if geocode and geocode.country_code:
        return geocode.country_code.lower()
    country_code = country_code_for_name(location)
    if country_code:
        return country_code.lower()
    lowered = (location or "").lower()
    if any(token in lowered for token in ("canada", "ontario", "toronto", "gta", "vancouver")):
        return "ca"
    if any(token in lowered for token in ("united kingdom", "uk", "london")):
        return "gb"
    return "us"


def _job_matches_refresh_filters(data: dict, *, location: str | None, remote_only: bool) -> bool:
    if remote_only and not bool(data.get("remote")) and data.get("work_mode") != "remote":
        return False

    if not location or not location.strip():
        return True

    requested = location.strip().lower()
    geocode = geocode_location_query(location)
    requested_country = (
        geocode.country_code if geocode and geocode.country_code else country_code_for_name(location)
    )
    location_text = " ".join(
        str(part or "")
        for part in [
            data.get("location"),
            data.get("location_geocode_label"),
            " ".join(data.get("countries") or []),
            " ".join(data.get("country_codes") or []),
        ]
    ).lower()

    if requested in location_text:
        return True
    if geocode and geocode.label.lower() in location_text:
        return True

    country_codes = {str(code).upper() for code in (data.get("country_codes") or [])}
    if requested_country:
        if country_codes and requested_country.upper() not in country_codes:
            return False
        if requested_country.upper() in country_codes and not geocode:
            return True

    if geocode and data.get("location_lat") is not None and data.get("location_lng") is not None:
        try:
            from math import asin, cos, radians, sin, sqrt

            lat1 = radians(float(geocode.latitude))
            lng1 = radians(float(geocode.longitude))
            lat2 = radians(float(data["location_lat"]))
            lng2 = radians(float(data["location_lng"]))
            dlat = lat2 - lat1
            dlng = lng2 - lng1
            distance = 2 * EARTH_RADIUS_KM * asin(
                sqrt(sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlng / 2) ** 2)
            )
            return distance <= max(float(geocode.radius_km), 50.0)
        except (TypeError, ValueError, OverflowError):
            return False

    # Remote roles are location-eligible (audit H9). If a job is remote and was
    # not already excluded by a non-matching explicit country code above, treat
    # it as a match instead of requiring the literal word "remote" in its HQ
    # location string. Note: a remote role with an explicit foreign country_code
    # (e.g. US-only) is still rejected at the country-code gate above before
    # reaching here (audit pass-2 P19 — comment corrected).
    if bool(data.get("remote")) or data.get("work_mode") == "remote":
        return True

    return False


async def _fetch_jobs_for_source(
    source: str,
    *,
    query: str,
    location: str | None,
    remote_only: bool,
    limit: int,
) -> tuple[list[dict], dict]:
    stat = _source_stat(source)
    try:
        if source == "jsearch":
            jobs = await jsearch_client.search_jobs(
                query, location=location, remote_only=remote_only, limit=limit
            )
        elif source == "adzuna":
            jobs = await adzuna_client.search_jobs(
                query,
                location=location,
                country=_adzuna_country_for_location(location),
                limit=limit,
            )
        elif source == "remotive":
            jobs = await remote_jobs_client.search_remotive(query, limit=limit)
        elif source == "jobicy":
            jobs = await remote_jobs_client.search_jobicy(query, limit=limit)
        elif source == "dice":
            jobs = await remote_jobs_client.search_dice(
                query,
                location=location,
                country_code=(
                    geocode_location_query(location).country_code
                    if geocode_location_query(location)
                    else country_code_for_name(location)
                ),
                limit=limit,
            )
        elif source == "simplify":
            jobs = await remote_jobs_client.fetch_simplify_jobs(limit=limit)
        elif source == "newgrad":
            jobs = await newgrad_jobs_client.search_newgrad_jobs(query=query)
        elif source == "yc_jobs":
            jobs = await yc_jobs_client.search_yc_jobs(query=query, limit=max(limit, 50))
        elif source == "wellfound":
            jobs = await wellfound_jobs_client.search_wellfound_jobs(query=query, limit=max(limit, 50))
        elif source == "ventureloop":
            jobs = await ventureloop_jobs_client.search_ventureloop_jobs(query=query, limit=max(limit, 100))
        else:
            jobs = []
            stat["details"] = {"skipped_reason": "unknown_source"}

        for job in jobs:
            job["_fetch_source_key"] = source
        stat["raw_count"] = len(jobs)
        _finish_source_stat(stat, status="success")
        return jobs, stat
    except Exception as exc:
        logger.exception("Job source fetch failed: %s", source)
        _finish_source_stat(stat, status="failed", error=str(exc))
        return [], stat


async def _record_source_runs(
    db: AsyncSession,
    *,
    refresh_run_id: uuid.UUID | None,
    source_stats: list[dict],
) -> None:
    if not refresh_run_id:
        return
    for stat in source_stats:
        db.add(
            JobSourceRun(
                refresh_run_id=refresh_run_id,
                source=stat["source"],
                status=stat.get("status") or "success",
                raw_count=int(stat.get("raw_count") or 0),
                new_count=int(stat.get("new_count") or 0),
                existing_count=int(stat.get("existing_count") or 0),
                duplicate_count=int(stat.get("duplicate_count") or 0),
                skipped_count=int(stat.get("skipped_count") or 0),
                error=stat.get("error"),
                details=stat.get("details"),
                started_at=stat["started_at"],
                finished_at=stat.get("finished_at"),
                duration_seconds=stat.get("duration_seconds"),
            )
        )


# --- Aggregation ---

async def search_jobs(
    db: AsyncSession,
    user_id: uuid.UUID,
    query: str,
    location: str | None = None,
    remote_only: bool = False,
    sources: list[str] | None = None,
    limit: int = 20,
    refresh_run_id: uuid.UUID | None = None,
    source_stats: list[dict] | None = None,
    occupation_hint: str | None = None,
) -> list[Job]:
    """Search for jobs across all sources, deduplicate, score, and store.

    Returns every job that matched this search — both newly created rows and
    existing rows that were refreshed in place. Each returned ``Job`` carries a
    transient ``_is_new_job`` flag (True for newly created rows) so the Celery
    refresh task can keep new-only counts and notifications accurate.

    Args:
        sources: List of sources to search. None = all.
                 Options: jsearch, adzuna, remotive, jobicy, dice, simplify, newgrad,
                 yc_jobs, wellfound, ventureloop
    """
    all_sources = sources or DEFAULT_SEARCH_SOURCES

    # Load user profile for scoring
    result = await db.execute(
        select(Profile).where(Profile.user_id == user_id)
    )
    profile = result.scalar_one_or_none()

    fetch_results = await asyncio.gather(
        *(
            _fetch_jobs_for_source(
                source,
                query=query,
                location=location,
                remote_only=remote_only,
                limit=limit,
            )
            for source in all_sources
        )
    )
    raw_jobs = [job for jobs, _ in fetch_results for job in jobs]
    local_source_stats = [stat for _, stat in fetch_results]
    stats_by_source = {stat["source"]: stat for stat in local_source_stats}

    # Deduplicate and store
    stored_jobs: list[Job] = []
    seen_job_keys: set[str] = set()
    known_startup_companies = (
        await _load_known_startup_company_names(db, user_id) if raw_jobs else set()
    )

    for data in raw_jobs:
        data = dict(data)
        fetch_source_key = data.pop("_fetch_source_key", None) or _job_source_key(data) or "unknown"
        stat = stats_by_source.setdefault(fetch_source_key, _source_stat(fetch_source_key))
        if occupation_hint:
            data.setdefault("_occupation_hint", occupation_hint)
        _infer_startup_tags_for_job(data, known_startup_companies)
        _infer_occupation_tags_for_job(data)
        data = normalize_job_metadata(data)
        if not _job_matches_refresh_filters(data, location=location, remote_only=remote_only):
            stat["skipped_count"] += 1
            continue
        fp = _fingerprint(
            data.get("company_name", ""),
            data.get("title", ""),
            data.get("location", ""),
        )
        job_key = _job_identity_key(data, fingerprint=fp)

        if job_key in seen_job_keys:
            stat["duplicate_count"] += 1
            continue
        seen_job_keys.add(job_key)

        existing = await _find_existing_job(
            db,
            user_id=user_id,
            source=data.get("source"),
            ats=data.get("ats"),
            external_id=data.get("external_id"),
            url=data.get("url"),
            fingerprint=fp,
        )

        score, breakdown = _score_job(data, profile)
        experience_level = _experience_level_for_job(data)

        if existing:
            stat["existing_count"] += 1
            _refresh_existing_job(
                existing,
                data,
                fingerprint=fp,
                score=score,
                breakdown=breakdown,
                experience_level=experience_level,
            )
            # Return refreshed matches too so the search endpoint shows results
            # even when every hit dedup-matched an existing row (audit C3). The
            # transient flag lets the refresh task keep "new" counts/notifications
            # scoped to genuinely new rows.
            existing._is_new_job = False  # type: ignore[attr-defined]
            stored_jobs.append(existing)
            continue

        job = _build_job(
            user_id=user_id,
            data=data,
            score=score,
            breakdown=breakdown,
            fingerprint=fp,
        )
        job._is_new_job = True  # type: ignore[attr-defined]
        db.add(job)
        stored_jobs.append(job)
        stat["new_count"] += 1

    # Auto-save search preference for Celery auto-refresh. Match on a normalized
    # location so "New York", "New York, NY" and "new york " don't each spawn a
    # separate hourly refresh cycle (audit M17).
    pref_stmt = select(SearchPreference).where(
        SearchPreference.user_id == user_id,
        SearchPreference.query == query.strip(),
        SearchPreference.remote_only == remote_only,
        SearchPreference.mode == "default",
    )
    pref_result = await db.execute(pref_stmt)
    target_location_key = _normalized_pref_location(location)
    existing_pref = next(
        (
            pref
            for pref in pref_result.scalars().all()
            if _normalized_pref_location(pref.location) == target_location_key
        ),
        None,
    )
    if not existing_pref:
        db.add(SearchPreference(
            user_id=user_id,
            query=query.strip(),
            location=location,
            remote_only=remote_only,
            mode="default",
        ))

    if source_stats is not None:
        source_stats.extend(local_source_stats)
    await _record_source_runs(
        db, refresh_run_id=refresh_run_id, source_stats=local_source_stats
    )
    await db.commit()
    return stored_jobs


async def search_ats_jobs(
    db: AsyncSession,
    user_id: uuid.UUID,
    company_slug: str | None,
    ats_type: str | None,
    limit: int | None = None,
    job_url: str | None = None,
    *,
    extra_tags: list[str] | None = None,
    include_existing_exact_matches: bool = True,
) -> list[Job]:
    """Search a supported board-backed ATS or ingest a single exact job URL."""
    target_external_id: str | None = None
    target_url: str | None = None
    parsed_job_url: ats.ParsedATSJobURL | None = None

    if job_url:
        parsed_job_url = ats.parse_ats_job_url(job_url)
        if not parsed_job_url:
            raise ValueError("Unsupported or invalid job posting URL.")
        company_slug = parsed_job_url.company_slug
        ats_type = parsed_job_url.ats_type
        target_external_id = parsed_job_url.external_id
        target_url = parsed_job_url.canonical_url

    if not ats_type:
        raise ValueError("ATS search requires either job_url or company_slug plus ats_type.")

    adapter = ats.get_adapter(ats_type)
    if not adapter:
        raise ValueError("Unsupported or invalid job posting URL.")

    result = await db.execute(
        select(Profile).where(Profile.user_id == user_id)
    )
    profile = result.scalar_one_or_none()

    if job_url and parsed_job_url and adapter.fetch_exact is not None:
        try:
            raw_jobs = await ats.fetch_exact_job(parsed_job_url)
        except ats.ExactJobFetchError as exc:
            raise ValueError(str(exc)) from exc
    else:
        if not company_slug or adapter.search_board is None:
            raise ValueError("This job platform currently requires a direct job posting URL.")
        raw_jobs = await adapter.search_board(company_slug, limit)

    stored_jobs: list[Job] = []
    board_jobs: list[Job] = []
    seen_job_keys: set[str] = set()
    for raw_data in raw_jobs:
        data = normalize_job_metadata(_with_extra_tags(raw_data, extra_tags))
        fp = _fingerprint(data.get("company_name", ""), data["title"], data.get("location", ""))
        job_key = _job_identity_key(data, fingerprint=fp)
        if job_key in seen_job_keys:
            continue
        seen_job_keys.add(job_key)

        job_ats = data.get("ats", ats_type)
        job_ats_slug = data.get("ats_slug", company_slug)
        score, breakdown = _score_job(data, profile)
        experience_level = _experience_level_for_job(data)
        existing_job = await _find_existing_job(
            db,
            user_id=user_id,
            source=data.get("source", ats_type),
            ats=job_ats,
            external_id=data.get("external_id"),
            url=data.get("url"),
            fingerprint=fp,
        )
        if existing_job:
            _refresh_existing_job(
                existing_job,
                data,
                fingerprint=fp,
                score=score,
                breakdown=breakdown,
                experience_level=experience_level,
            )
            board_jobs.append(existing_job)
            continue

        job = _build_job(
            user_id=user_id,
            data={
                **data,
                "company_name": data.get("company_name", company_slug),
                "source": data.get("source", ats_type),
                "ats": job_ats,
                "ats_slug": job_ats_slug,
            },
            score=score,
            breakdown=breakdown,
            fingerprint=fp,
        )
        db.add(job)
        stored_jobs.append(job)
        board_jobs.append(job)

    await db.commit()

    if not job_url:
        return stored_jobs

    normalized_target = _canonical_job_url(target_url or job_url)
    exact_matches = [
        job
        for job in board_jobs
        if (target_external_id and job.external_id == target_external_id)
        or (_canonical_job_url(job.url) and _canonical_job_url(job.url) == normalized_target)
    ]
    if not exact_matches:
        return board_jobs

    if not include_existing_exact_matches:
        stored_ids = {job.id for job in stored_jobs}
        return [job for job in exact_matches if job.id in stored_ids]

    exact_ids = {job.id for job in exact_matches}
    ordered_jobs = exact_matches + [job for job in board_jobs if job.id not in exact_ids]
    return ordered_jobs


async def _repair_missing_apply_urls(db: AsyncSession, jobs: list[Job]) -> None:
    did_update = False
    for job in jobs:
        if job.source == "simplify_github" and not job.apply_url and job.url:
            job.apply_url = job.url
            did_update = True

    dice_jobs = [
        job
        for job in jobs
        if job.source == "dice" and not job.apply_url and job.url
    ][:APPLY_URL_REPAIR_MAX_JOBS]

    if dice_jobs:
        resolved_urls = await remote_jobs_client.resolve_dice_apply_urls(
            [job.url for job in dice_jobs if job.url]
        )
        for job in dice_jobs:
            apply_url = resolved_urls.get(job.url or "")
            if not apply_url:
                continue
            job.apply_url = apply_url
            did_update = True

    newgrad_jobs = [
        job
        for job in jobs
        if job.source == "newgrad_jobs" and not job.apply_url and job.url
    ][:APPLY_URL_REPAIR_MAX_JOBS]

    if newgrad_jobs:
        resolved_urls = await newgrad_jobs_client.resolve_newgrad_apply_urls(
            [job.url for job in newgrad_jobs if job.url]
        )
        for job in newgrad_jobs:
            apply_url = resolved_urls.get(job.url or "")
            if not apply_url:
                continue
            job.apply_url = apply_url
            did_update = True

    for job in jobs:
        if not job.apply_url and job.url:
            job.apply_url = job.url
            did_update = True

    if did_update:
        await db.commit()


async def toggle_job_starred(
    db: AsyncSession,
    user_id: uuid.UUID,
    job_id: uuid.UUID,
    starred: bool,
) -> Job:
    """Toggle a job's starred status."""
    result = await db.execute(
        select(Job).where(Job.id == job_id, Job.user_id == user_id)
    )
    job = result.scalar_one_or_none()
    if not job:
        raise ValueError("Job not found.")

    job.starred = starred
    await db.commit()
    await db.refresh(job)
    return job


async def get_jobs(
    db: AsyncSession,
    user_id: uuid.UUID,
    stage: str | None = None,
    sort_by: str = "score",
    starred: bool | None = None,
    *,
    employment_type: str | None = None,
    experience_level: str | None = None,
    salary_min: float | None = None,
    country: str | None = None,
    near: str | None = None,
    near_lat: float | None = None,
    near_lng: float | None = None,
    radius_km: float | None = None,
    include_remote_in_radius: bool = False,
    remote: bool | None = None,
    startup: bool | None = None,
    occupations: list[str] | None = None,
    search: str | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> tuple[list[Job], int]:
    """Get saved jobs for a user with optional filtering and pagination.

    Returns ``(jobs, total_count)``.
    """
    from app.utils.pagination import paginate

    query = select(Job).where(Job.user_id == user_id)
    distance_expr = None
    if stage:
        query = query.where(Job.stage == stage)
    if starred is not None:
        query = query.where(Job.starred == starred)
    if employment_type:
        if employment_type.strip().lower() == "internship":
            query = query.where(
                or_(
                    sa_func.lower(Job.employment_type) == "internship",
                    Job.experience_level == "intern",
                )
            )
        else:
            query = query.where(Job.employment_type == employment_type)
    if experience_level:
        query = query.where(Job.experience_level == experience_level)
    if salary_min is not None:
        query = query.where(
            or_(Job.salary_max >= salary_min, Job.salary_min >= salary_min)
        )
    if country:
        country_name = country.strip()
        country_code = country_code_for_name(country_name)
        clauses = []
        if country_code:
            clauses.append(Job.country_codes.contains([country_code]))
        if country_name:
            clauses.append(Job.countries.contains([country_name]))
            clauses.append(Job.location.ilike(f"%{country_name}%"))
        if clauses:
            query = query.where(or_(*clauses))
    if near_lat is None or near_lng is None:
        geocode = geocode_location_query(near)
        if geocode:
            near_lat = geocode.latitude
            near_lng = geocode.longitude
            if radius_km is None:
                radius_km = geocode.radius_km
    if near_lat is not None and near_lng is not None:
        effective_radius_km = radius_km if radius_km is not None else 50.0
        distance_expr = _distance_km_expression(near_lat, near_lng)
        local_clause = (
            Job.location_lat.is_not(None)
            & Job.location_lng.is_not(None)
            & (distance_expr <= effective_radius_km)
        )
        if include_remote_in_radius:
            query = query.where(or_(local_clause, Job.remote.is_(True)))
        else:
            query = query.where(local_clause)
    elif near:
        # Last-resort fallback for unrecognized manual entries. Known cities and
        # metro aliases use the coordinate path above.
        query = query.where(Job.location.ilike(f"%{near.strip()}%"))
    if remote is not None:
        query = query.where(Job.remote == remote)
    if startup is not None:
        if startup:
            query = query.where(Job.tags.contains([STARTUP_TAG]))
        else:
            query = query.where(or_(Job.tags.is_(None), not_(Job.tags.contains([STARTUP_TAG]))))
    if occupations:
        occupation_clauses = [
            Job.tags.contains([occupation_tag(key)]) for key in occupations if key
        ]
        if occupation_clauses:
            query = query.where(or_(*occupation_clauses))
    if search:
        term = f"%{search}%"
        query = query.where(
            Job.title.ilike(term) | Job.company_name.ilike(term)
        )

    if sort_by == "score":
        query = query.order_by(Job.match_score.desc().nullslast())
    elif sort_by == "distance" and distance_expr is not None:
        query = query.order_by(distance_expr.asc().nullslast())
    else:
        # Date sort (and default). Order by the pre-parsed, calendar-validated
        # `posted_date` column (populated at ingest), falling back to the ingest
        # timestamp. The previous approach cast a substring of the free-form
        # `posted_at` string to ::date at query time, which raised and aborted
        # the whole query on a date-shaped-but-invalid value like "2026-02-30"
        # (audit pass-2 P3). Using a real Date column is crash-proof and indexed.
        recency = sa_func.coalesce(Job.posted_date, sa_func.cast(Job.created_at, Date))
        query = query.order_by(recency.desc().nullslast(), Job.created_at.desc())

    jobs, total = await paginate(db, query, limit=limit, offset=offset)
    await _repair_missing_apply_urls(db, jobs)
    return jobs, total


async def update_job_stage(
    db: AsyncSession,
    user_id: uuid.UUID,
    job_id: uuid.UUID,
    stage: str,
    notes: str | None = None,
) -> Job:
    """Update a job's kanban stage."""
    from datetime import datetime as _dt
    from datetime import timezone as _tz

    result = await db.execute(
        select(Job).where(Job.id == job_id, Job.user_id == user_id)
    )
    job = result.scalar_one_or_none()
    if not job:
        raise ValueError("Job not found.")

    old_stage = job.stage
    job.stage = stage
    if notes is not None:
        job.notes = notes

    # Auto-set applied_at when moving to 'applied' for the first time
    if stage == "applied" and old_stage != "applied" and not job.applied_at:
        job.applied_at = _dt.now(_tz.utc)

    await db.commit()
    await db.refresh(job)

    # Auto-draft outreach when moving to 'applied' (if enabled)
    if stage == "applied" and old_stage != "applied":
        try:
            from app.services.settings_service import get_auto_prospect  # noqa: PLC0415

            auto_settings = await get_auto_prospect(db, user_id)
            if auto_settings.get("auto_draft_on_apply"):
                from app.tasks.auto_prospect import auto_draft_for_job  # noqa: PLC0415
                auto_draft_for_job.delay(str(user_id), str(job_id))
                logger.info(
                    "Auto-draft queued on apply: user=%s job=%s", user_id, job_id,
                )
        except Exception:
            logger.debug("Auto-draft trigger check failed", exc_info=True)

    return job


async def update_interview_rounds(
    db: AsyncSession,
    user_id: uuid.UUID,
    job_id: uuid.UUID,
    rounds: list[dict],
) -> Job:
    """Update a job's interview rounds (full replacement)."""
    result = await db.execute(
        select(Job).where(Job.id == job_id, Job.user_id == user_id)
    )
    job = result.scalar_one_or_none()
    if not job:
        raise ValueError("Job not found.")

    job.interview_rounds = rounds
    await db.commit()
    await db.refresh(job)
    return job


async def update_offer_details(
    db: AsyncSession,
    user_id: uuid.UUID,
    job_id: uuid.UUID,
    offer: dict,
) -> Job:
    """Update a job's offer details."""
    result = await db.execute(
        select(Job).where(Job.id == job_id, Job.user_id == user_id)
    )
    job = result.scalar_one_or_none()
    if not job:
        raise ValueError("Job not found.")

    job.offer_details = offer
    await db.commit()
    await db.refresh(job)
    return job


async def get_job(
    db: AsyncSession,
    user_id: uuid.UUID,
    job_id: uuid.UUID,
) -> Job | None:
    """Get a single job by ID."""
    result = await db.execute(
        select(Job).where(Job.id == job_id, Job.user_id == user_id)
    )
    job = result.scalar_one_or_none()
    if job:
        await _repair_missing_apply_urls(db, [job])
    return job


async def get_job_command_center(
    db: AsyncSession,
    user_id: uuid.UUID,
    job_id: uuid.UUID,
) -> dict | None:
    """Build a compact command-center summary for a single saved job."""
    job = await get_job(db, user_id, job_id)
    if not job:
        return None

    normalized_company = normalize_company_name(job.company_name)
    now = datetime.now(timezone.utc)

    profile_result = await db.execute(
        select(Profile).where(Profile.user_id == user_id)
    )
    profile = profile_result.scalar_one_or_none()

    contacts_result = await db.execute(
        select(Person)
        .join(Company, Person.company_id == Company.id)
        .where(
            Person.user_id == user_id,
            Company.user_id == user_id,
            Company.normalized_name == normalized_company,
        )
        .order_by(
            Person.current_company_verified.desc().nullslast(),
            Person.email_verified.desc().nullslast(),
            Person.relevance_score.desc().nullslast(),
            Person.created_at.desc(),
        )
        .options(selectinload(Person.company))
    )
    contacts = list(contacts_result.scalars().all())
    top_contacts = contacts[:4]

    tailored_result = await db.execute(
        select(TailoredResume.id)
        .where(
            TailoredResume.user_id == user_id,
            TailoredResume.job_id == job_id,
        )
        .limit(1)
    )
    has_tailored_resume = tailored_result.scalar_one_or_none() is not None

    artifact_result = await db.execute(
        select(ResumeArtifact.id)
        .where(
            ResumeArtifact.user_id == user_id,
            ResumeArtifact.job_id == job_id,
        )
        .limit(1)
    )
    has_resume_artifact = artifact_result.scalar_one_or_none() is not None

    messages_result = await db.execute(
        select(Message, Person)
        .join(Person, Message.person_id == Person.id)
        .where(
            Message.user_id == user_id,
            Message.context_snapshot["job_id"].astext == str(job_id),
        )
        .order_by(Message.created_at.desc())
        .limit(5)
    )
    recent_messages_rows = messages_result.all()

    outreach_result = await db.execute(
        select(OutreachLog)
        .where(
            OutreachLog.user_id == user_id,
            OutreachLog.job_id == job_id,
        )
        .options(selectinload(OutreachLog.person), selectinload(OutreachLog.job))
        .order_by(OutreachLog.updated_at.desc())
    )
    outreach_logs = list(outreach_result.scalars().all())
    recent_outreach = outreach_logs[:5]

    verified_contacts_count = sum(1 for person in contacts if person.current_company_verified)
    reachable_contacts_count = sum(1 for person in contacts if person.work_email or person.linkedin_url)
    active_outreach_count = sum(
        1 for log in outreach_logs if log.status in {"sent", "connected", "following_up"}
    )
    responded_outreach_count = sum(
        1 for log in outreach_logs if log.response_received or log.status in {"responded", "met", "closed"}
    )
    due_follow_ups_count = sum(
        1
        for log in outreach_logs
        if log.next_follow_up_at is not None
        and log.next_follow_up_at <= now
        and log.status != "closed"
    )

    checklist = {
        "resume_uploaded": bool(profile and profile.resume_parsed),
        "match_scored": job.match_score is not None,
        "resume_tailored": has_tailored_resume,
        "resume_artifact_generated": has_resume_artifact,
        "contacts_saved": len(contacts) > 0,
        "outreach_started": len(outreach_logs) > 0,
        "applied": job.stage in {"applied", "interviewing", "offer", "accepted", "rejected", "withdrawn"},
        "interview_rounds_logged": bool(job.interview_rounds),
    }

    stats = {
        "saved_contacts_count": len(contacts),
        "verified_contacts_count": verified_contacts_count,
        "reachable_contacts_count": reachable_contacts_count,
        "drafted_messages_count": len(recent_messages_rows),
        "outreach_count": len(outreach_logs),
        "active_outreach_count": active_outreach_count,
        "responded_outreach_count": responded_outreach_count,
        "due_follow_ups_count": due_follow_ups_count,
    }

    snapshot = await get_job_research_snapshot(db, user_id=user_id, job_id=job_id)
    research_snapshot = serialize_snapshot(snapshot)

    next_action = _determine_job_next_action(
        job=job,
        checklist=checklist,
        stats=stats,
        research_snapshot=research_snapshot,
    )

    return {
        "job_id": str(job.id),
        "research_snapshot": research_snapshot,
        "stage": job.stage,
        "checklist": checklist,
        "stats": stats,
        "next_action": next_action,
        "top_contacts": [
            {
                "id": str(person.id),
                "full_name": person.full_name,
                "title": person.title,
                "person_type": person.person_type,
                "work_email": person.work_email,
                "linkedin_url": person.linkedin_url,
                "email_verified": bool(person.email_verified),
                "current_company_verified": person.current_company_verified,
            }
            for person in top_contacts
        ],
        "recent_messages": [
            {
                "id": str(message.id),
                "person_id": str(person.id),
                "person_name": person.full_name,
                "channel": message.channel,
                "goal": message.goal,
                "status": message.status,
                "created_at": message.created_at.isoformat(),
            }
            for message, person in recent_messages_rows
        ],
        "recent_outreach": [
            {
                "id": str(log.id),
                "person_id": str(log.person_id),
                "person_name": log.person.full_name if log.person else None,
                "channel": log.channel,
                "status": log.status,
                "response_received": log.response_received,
                "last_contacted_at": log.last_contacted_at.isoformat() if log.last_contacted_at else None,
                "next_follow_up_at": log.next_follow_up_at.isoformat() if log.next_follow_up_at else None,
                "created_at": log.created_at.isoformat(),
            }
            for log in recent_outreach
        ],
    }


def _determine_job_next_action(
    *,
    job: Job,
    checklist: dict,
    stats: dict,
    research_snapshot: dict | None = None,
) -> dict:
    """Return the single highest-leverage next action for the job command center."""
    has_live_targets = bool(research_snapshot and research_snapshot.get("total_candidates", 0) > 0)
    if not checklist["resume_uploaded"]:
        return {
            "key": "upload_resume",
            "title": "Upload your resume first",
            "detail": "Resume-backed scoring and tailoring are unavailable until your profile has a parsed resume.",
            "cta_label": "Open Profile",
            "cta_section": "profile",
        }

    if not checklist["contacts_saved"] and not has_live_targets:
        return {
            "key": "find_people",
            "title": "Find people at this company",
            "detail": "You do not have saved or fresh recruiter, hiring manager, or peer matches for this role yet.",
            "cta_label": "Find People",
            "cta_section": "people",
        }

    if (
        has_live_targets
        and stats["outreach_count"] == 0
        and job.stage in {"discovered", "interested", "researching", "networking"}
    ):
        total = research_snapshot["total_candidates"] if research_snapshot else 0
        return {
            "key": "draft_live_outreach",
            "title": "Work the saved people-search results",
            "detail": (
                f"You have {total} live candidate{'s' if total != 1 else ''} stored from your latest "
                "people search. Convert that targeting into outreach."
            ),
            "cta_label": "Draft Message",
            "cta_section": "people",
        }

    if stats["due_follow_ups_count"] > 0:
        return {
            "key": "follow_up_due",
            "title": "Review overdue follow-ups",
            "detail": "At least one job-linked outreach thread is due for follow-up now.",
            "cta_label": "Review Outreach",
            "cta_section": "activity",
        }

    if not checklist["resume_tailored"] and checklist["match_scored"]:
        return {
            "key": "tailor_resume",
            "title": "Tailor your resume for this role",
            "detail": "You have a scored job but no saved tailoring suggestions for this application yet.",
            "cta_label": "Tailor Resume",
            "cta_section": "resume",
        }

    if checklist["resume_tailored"] and not checklist["resume_artifact_generated"] and job.stage in {"discovered", "interested", "researching", "networking", "applied"}:
        return {
            "key": "generate_resume_artifact",
            "title": "Generate a submission-ready resume variant",
            "detail": "Tailoring suggestions exist, but you have not saved a concrete resume artifact for this role yet.",
            "cta_label": "Generate Resume",
            "cta_section": "resume",
        }

    if job.stage in {"interviewing", "offer"} and not checklist["interview_rounds_logged"]:
        return {
            "key": "log_interviews",
            "title": "Log interview rounds",
            "detail": "Interview stage is active, but no rounds are saved on this job yet.",
            "cta_label": "Update Tracker",
            "cta_section": "stage",
        }

    if job.stage in {"discovered", "interested", "researching", "networking"} and stats["outreach_count"] == 0:
        return {
            "key": "draft_first_outreach",
            "title": "Draft your first message",
            "detail": "You already have company contacts saved for this role, but no outreach has been logged yet.",
            "cta_label": "Open Messages",
            "cta_section": "activity",
        }

    if job.stage == "applied" and stats["outreach_count"] == 0:
        return {
            "key": "post_apply_outreach",
            "title": "Start post-apply outreach",
            "detail": "This role is already in the pipeline, but no recruiter, hiring manager, or peer contact has been logged for it yet.",
            "cta_label": "Open Messages",
            "cta_section": "activity",
        }

    return {
        "key": "review_job",
        "title": "Keep this job moving",
        "detail": "The core workflow is in place. Review activity, update stage, or re-run people search if the context has changed.",
        "cta_label": "Review Activity",
        "cta_section": "activity",
    }


# --- Default Seed Feeds ---

DEFAULT_SEED_SEARCHES = [
    {"query": "Software Engineer", "location": None, "remote_only": False},
    {"query": "New Grad Software", "location": None, "remote_only": False},
]


async def seed_default_feeds(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> int:
    """Seed default job searches for a brand-new user.

    Idempotent: does nothing if the user already has any jobs or search
    preferences.  Returns the total number of new jobs stored.
    """
    job_count_r = await db.execute(
        select(sa_func.count()).select_from(Job).where(Job.user_id == user_id)
    )
    if (job_count_r.scalar() or 0) > 0:
        return 0

    pref_count_r = await db.execute(
        select(sa_func.count())
        .select_from(SearchPreference)
        .where(SearchPreference.user_id == user_id)
    )
    if (pref_count_r.scalar() or 0) > 0:
        return 0

    total_new = 0
    for seed in DEFAULT_SEED_SEARCHES:
        try:
            stored = await search_jobs(
                db,
                user_id,
                query=seed["query"],  # type: ignore[arg-type]
                location=seed["location"],  # type: ignore[arg-type]
                remote_only=seed["remote_only"],  # type: ignore[arg-type]
            )
            total_new += len(stored)
        except Exception:
            logger.exception("Failed to seed default feed: %s", seed["query"])

    logger.info("Seeded %d default jobs for user %s", total_new, user_id)
    return total_new


# Discovery queries spanning multiple roles. These are now derived from the
# occupation taxonomy at runtime via `discover_queries_for_occupations()`.
# DISCOVER_QUERIES remains as a backwards-compatible default fallback used
# when neither user occupations nor explicit queries are supplied.
DISCOVER_QUERIES: list[dict] = discover_queries_for_occupations(None)

# Curated ATS boards to pull from during discovery.
# These are popular tech companies with public Greenhouse/Ashby boards.
ATS_DISCOVER_BOARDS: list[dict[str, str]] = [
    # Greenhouse
    {"slug": "stripe", "ats": "greenhouse"},
    {"slug": "airbnb", "ats": "greenhouse"},
    {"slug": "figma", "ats": "greenhouse"},
    {"slug": "coinbase", "ats": "greenhouse"},
    {"slug": "robinhood", "ats": "greenhouse"},
    {"slug": "databricks", "ats": "greenhouse"},
    {"slug": "discord", "ats": "greenhouse"},
    {"slug": "brex", "ats": "greenhouse"},
    {"slug": "doordash", "ats": "greenhouse"},
    {"slug": "plaid", "ats": "greenhouse"},
    {"slug": "duolingo", "ats": "greenhouse"},
    {"slug": "squarespace", "ats": "greenhouse"},
    {"slug": "relativityspace", "ats": "greenhouse"},
    {"slug": "airtable", "ats": "greenhouse"},
    {"slug": "zscaler", "ats": "greenhouse"},
    {"slug": "instacart", "ats": "greenhouse"},
    {"slug": "scaleai", "ats": "greenhouse"},
    {"slug": "twitch", "ats": "greenhouse"},
    {"slug": "affirm", "ats": "greenhouse"},
    {"slug": "epicgames", "ats": "greenhouse"},
    {"slug": "roblox", "ats": "greenhouse"},
    {"slug": "postman", "ats": "greenhouse"},
    {"slug": "vercel", "ats": "greenhouse"},
    {"slug": "roku", "ats": "greenhouse"},
    {"slug": "gusto", "ats": "greenhouse"},
    {"slug": "jfrog", "ats": "greenhouse"},
    {"slug": "block", "ats": "greenhouse"},
    {"slug": "toast", "ats": "greenhouse"},
    {"slug": "spacex", "ats": "greenhouse"},
    {"slug": "marqeta", "ats": "greenhouse"},
    {"slug": "anthropic", "ats": "greenhouse"},
    {"slug": "asana", "ats": "greenhouse"},
    {"slug": "stabilityai", "ats": "greenhouse"},
    {"slug": "pinterest", "ats": "greenhouse"},
    {"slug": "togetherai", "ats": "greenhouse"},
    {"slug": "reddit", "ats": "greenhouse"},
    {"slug": "lucidmotors", "ats": "greenhouse"},
    {"slug": "dropbox", "ats": "greenhouse"},
    {"slug": "twilio", "ats": "greenhouse"},
    {"slug": "datadog", "ats": "greenhouse"},
    {"slug": "cloudflare", "ats": "greenhouse"},
    {"slug": "betterment", "ats": "greenhouse"},
    {"slug": "webflow", "ats": "greenhouse"},
    {"slug": "elastic", "ats": "greenhouse"},
    {"slug": "chime", "ats": "greenhouse"},
    {"slug": "flexport", "ats": "greenhouse"},
    {"slug": "billcom", "ats": "greenhouse"},
    {"slug": "gitlab", "ats": "greenhouse"},
    {"slug": "linkedin", "ats": "greenhouse"},
    {"slug": "mongodb", "ats": "greenhouse"},
    {"slug": "lyft", "ats": "greenhouse"},
    {"slug": "okta", "ats": "greenhouse"},
    {"slug": "waymo", "ats": "greenhouse"},
    {"slug": "andurilindustries", "ats": "greenhouse"},
    {"slug": "samsara", "ats": "greenhouse"},
    {"slug": "uberfreight", "ats": "greenhouse"},
    {"slug": "grammarly", "ats": "greenhouse"},
    {"slug": "verkada", "ats": "greenhouse"},
    {"slug": "niantic", "ats": "greenhouse"},
    {"slug": "nuro", "ats": "greenhouse"},
    {"slug": "canva", "ats": "greenhouse"},
    {"slug": "wiz", "ats": "greenhouse"},
    {"slug": "snyk", "ats": "greenhouse"},
    {"slug": "applovin", "ats": "greenhouse"},
    {"slug": "coreweave", "ats": "greenhouse"},
    # Ashby
    {"slug": "ramp", "ats": "ashby"},
    {"slug": "notion", "ats": "ashby"},
    {"slug": "openai", "ats": "ashby"},
    {"slug": "linear", "ats": "ashby"},
    {"slug": "cursor", "ats": "ashby"},
    {"slug": "snowflake", "ats": "ashby"},
    {"slug": "cohere", "ats": "ashby"},
    {"slug": "clickup", "ats": "ashby"},
    {"slug": "zapier", "ats": "ashby"},
    {"slug": "runway", "ats": "ashby"},
    {"slug": "deel", "ats": "ashby"},
    {"slug": "vanta", "ats": "ashby"},
    # Plaid runs its board on Greenhouse (see GREENHOUSE_DISCOVER_BOARDS); the
    # duplicate Ashby entry was removed to avoid double/stale imports (audit M5).
    {"slug": "elevenlabs", "ats": "ashby"},
    {"slug": "replit", "ats": "ashby"},
    {"slug": "perplexity", "ats": "ashby"},
    {"slug": "ashby", "ats": "ashby"},
    {"slug": "deepgram", "ats": "ashby"},
    {"slug": "confluent", "ats": "ashby"},
    {"slug": "benchling", "ats": "ashby"},
    {"slug": "supabase", "ats": "ashby"},
    {"slug": "sentry", "ats": "ashby"},
    {"slug": "sanity", "ats": "ashby"},
    {"slug": "modal", "ats": "ashby"},
    {"slug": "lambda", "ats": "ashby"},
    {"slug": "astronomer", "ats": "ashby"},
    {"slug": "drata", "ats": "ashby"},
    {"slug": "livekit", "ats": "ashby"},
    {"slug": "atlan", "ats": "ashby"},
    {"slug": "render", "ats": "ashby"},
    {"slug": "posthog", "ats": "ashby"},
    {"slug": "anyscale", "ats": "ashby"},
    {"slug": "neon", "ats": "ashby"},
    {"slug": "resend", "ats": "ashby"},
    {"slug": "railway", "ats": "ashby"},
    {"slug": "airbyte", "ats": "ashby"},
]

# Lever companies (scraped from HTML since the API is deprecated)
LEVER_DISCOVER_SLUGS = [
    "spotify",
    "matchgroup",
    "palantir",
    "plaid",
    "ro",
    "outreach",
    "toptal",
    "jumpcloud",
    "greenlight",
    "wealthfront",
    "matillion",
]


async def _discover_ats_boards(
    db: AsyncSession,
    user_id: uuid.UUID,
    limit_per_board: int = 50,
    refresh_run_id: uuid.UUID | None = None,
) -> int:
    """Pull jobs from curated Greenhouse, Ashby, Lever, and Workday boards."""
    source_payloads, source_stats = await fetch_curated_ats_source_payloads(
        limit_per_board=limit_per_board
    )
    return await store_curated_ats_payloads_for_user(
        db,
        user_id,
        source_payloads=source_payloads,
        source_stats=source_stats,
        preferences=None,
        refresh_run_id=refresh_run_id,
    )


async def _discover_nontech_vertical_boards(
    db: AsyncSession,
    user_id: uuid.UUID,
    verticals: set[str],
    profile,
    limit_per_company: int = 20,
) -> int:
    """Pull jobs from curated non-tech employers in the given verticals.

    The non-tech analog of ``_discover_ats_boards``: health systems,
    universities, banks/insurers, and retailers on Workday. Occupation-routed
    by ``verticals`` so only relevant employers are fetched. Fails soft.
    """
    if not verticals:
        return 0
    try:
        raw_jobs = await workday_client.discover_all_nontech_workday(
            limit_per_company=limit_per_company, verticals=verticals
        )
    except Exception:
        logger.exception("non-tech vertical board discovery failed")
        return 0
    stored = await _store_raw_jobs(db, user_id, raw_jobs, profile)
    return len(stored)


async def fetch_curated_ats_source_payloads(
    limit_per_board: int = 50,
) -> tuple[dict[str, list[dict]], list[dict]]:
    """Fetch curated ATS/proprietary sources once for fanout to users."""
    semaphore = asyncio.Semaphore(8)
    source_fetches = []

    async def run_source(source_key: str, fetcher) -> tuple[str, list[dict], dict]:
        stat = _source_stat(source_key)
        try:
            async with semaphore:
                raw_jobs = await fetcher()
            for job in raw_jobs:
                job["_source_run_key"] = source_key
            stat["raw_count"] = len(raw_jobs)
            _finish_source_stat(stat, status="success")
            return source_key, raw_jobs, stat
        except Exception as exc:
            logger.exception("Curated job source failed: %s", source_key)
            _finish_source_stat(stat, status="failed", error=str(exc))
            return source_key, [], stat

    for board in ATS_DISCOVER_BOARDS:
        source_key = f"{board['ats']}:{board['slug']}"

        async def fetch_board(board=board) -> list[dict]:
            adapter = ats.get_adapter(board["ats"])
            return (
                await adapter.search_board(board["slug"], limit_per_board)
                if adapter and adapter.search_board is not None
                else []
            )

        source_fetches.append(run_source(source_key, fetch_board))

    for slug in LEVER_DISCOVER_SLUGS:
        source_key = f"lever:{slug}"

        async def fetch_lever(slug=slug) -> list[dict]:
            return await lever_scrape_client.search_lever_html(slug, limit=limit_per_board)

        source_fetches.append(run_source(source_key, fetch_lever))

    async def fetch_workday() -> list[dict]:
        return await workday_client.discover_all_workday(limit_per_company=20)

    source_fetches.append(run_source("workday:curated", fetch_workday))

    proprietary_sources: list[tuple[str, object]] = [
        ("amazon", amazon_client.search_amazon_jobs),
        ("microsoft", microsoft_client.search_microsoft_jobs),
        ("apple", apple_client.search_apple_jobs),
        ("google", google_client.search_google_jobs),
        ("tesla", tesla_client.search_tesla_jobs),
        ("meta", meta_client.search_meta_jobs),
    ]
    for source_key, fetcher in proprietary_sources:
        async def fetch_proprietary(fetcher=fetcher) -> list[dict]:
            return await fetcher(limit=20)

        source_fetches.append(run_source(source_key, fetch_proprietary))

    source_payloads: dict[str, list[dict]] = {}
    source_stats: list[dict] = []
    for source_key, raw_jobs, stat in await asyncio.gather(*source_fetches):
        source_payloads[source_key] = raw_jobs
        source_stats.append(stat)

    return source_payloads, source_stats


def job_matches_refresh_preferences(
    raw_job: dict,
    preferences,
) -> bool:
    """Return whether a crawled board job matches at least one saved search."""
    normalized = normalize_job_metadata(dict(raw_job))
    for pref in preferences:
        if not getattr(pref, "enabled", True):
            continue
        if (getattr(pref, "mode", "default") or "default") != "default":
            continue
        query = (getattr(pref, "query", "") or "").strip()
        if query and not job_matches_any_query(normalized, [query]):
            continue
        if not _job_matches_refresh_filters(
            normalized,
            location=getattr(pref, "location", None),
            remote_only=bool(getattr(pref, "remote_only", False)),
        ):
            continue
        return True
    return False


def _source_run_key_for_stored_job(job: Job) -> str:
    if job.ats in {"greenhouse", "ashby", "lever"} and job.ats_slug:
        return f"{job.ats}:{job.ats_slug}"
    if job.source == "workday":
        return "workday:curated"
    if job.source == "google_careers":
        return "google"
    if job.source == "apple_jobs":
        return "apple"
    return job.source or job.ats or "unknown"


async def store_curated_ats_payloads_for_user(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    source_payloads: dict[str, list[dict]],
    source_stats: list[dict],
    preferences=None,
    refresh_run_id: uuid.UUID | None = None,
) -> int:
    """Store one global ATS crawl for a user after saved-search filtering."""
    result = await db.execute(select(Profile).where(Profile.user_id == user_id))
    profile = result.scalar_one_or_none()

    filtered_jobs: list[dict] = []
    matched_counts_by_source: dict[str, int] = {}
    for source_key, jobs in source_payloads.items():
        for raw_job in jobs:
            if preferences is not None and not job_matches_refresh_preferences(raw_job, preferences):
                continue
            matched = dict(raw_job)
            matched["_source_run_key"] = source_key
            filtered_jobs.append(matched)
            matched_counts_by_source[source_key] = matched_counts_by_source.get(source_key, 0) + 1

    stored = await _store_raw_jobs(db, user_id, filtered_jobs, profile)
    stored_counts_by_source: dict[str, int] = {}
    for job in stored:
        source_key = _source_run_key_for_stored_job(job)
        stored_counts_by_source[source_key] = stored_counts_by_source.get(source_key, 0) + 1

    user_source_stats: list[dict] = []
    for stat in source_stats:
        user_stat = dict(stat)
        source_key = user_stat["source"]
        if user_stat.get("status") == "success":
            user_stat["raw_count"] = matched_counts_by_source.get(source_key, 0)
        user_stat["new_count"] = stored_counts_by_source.get(source_key, 0)
        user_source_stats.append(user_stat)

    await _record_source_runs(
        db, refresh_run_id=refresh_run_id, source_stats=user_source_stats
    )
    return len(stored)


async def _load_known_startup_company_names(
    db: AsyncSession, user_id: uuid.UUID
) -> set[str]:
    """Return the lowercased company names this user already has startup jobs for.

    Used by ``_infer_startup_tags_for_job`` to tag new postings from the same
    company even when they arrive via non-startup ingestion paths (e.g. a YC
    company posting via Greenhouse).
    """
    try:
        stmt = (
            select(sa_func.lower(Job.company_name))
            .where(
                Job.user_id == user_id,
                Job.tags.contains([STARTUP_TAG]),
            )
            .distinct()
        )
        result = await db.execute(stmt)
        return {row.strip() for row in result.scalars().all() if row}
    except Exception:
        logger.debug("known-startup company lookup failed", exc_info=True)
        return set()


def _infer_startup_tags_for_job(
    data: dict, known_startup_companies: set[str]
) -> None:
    """If a job's company is a known startup, merge inferred startup tags in-place.

    Skips jobs that already carry authoritative startup tags from their
    source-based ingestion path.
    """
    tags = data.get("tags") or []
    if has_startup_tag(tags):
        return
    company = (data.get("company_name") or "").strip().lower()
    if not company or company not in known_startup_companies:
        return
    inferred = [STARTUP_TAG, startup_source_tag("inferred")]
    data["tags"] = merge_tags(tags, inferred)


def _infer_occupation_tags_for_job(data: dict) -> None:
    """Stamp `occupation:<key>` tags on a raw job dict in-place.

    Honors any explicit occupation tags already present (e.g., from the
    newgrad-jobs scraper's source-category hint). Otherwise falls back to
    title/description classification, and finally to the occupation whose
    discover query surfaced the job (``_occupation_hint``), so query-seeded
    jobs with unclassifiable titles stay visible to occupation filters.
    """
    hint = data.pop("_occupation_hint", None)
    existing = data.get("tags") or []
    explicit_keys: list[str] = []
    for tag in existing:
        if isinstance(tag, str) and tag.startswith(OCCUPATION_TAG_PREFIX):
            explicit_keys.append(tag[len(OCCUPATION_TAG_PREFIX):])

    inferred = occupation_tags_for_job(
        title=data.get("title"),
        description=data.get("description"),
        explicit_keys=explicit_keys or None,
        fallback_keys=[hint] if isinstance(hint, str) and hint else None,
    )
    if inferred:
        data["tags"] = merge_tags(existing, inferred)


async def _store_raw_jobs(
    db: AsyncSession,
    user_id: uuid.UUID,
    raw_jobs: list[dict],
    profile: Profile | None,
) -> list[Job]:
    """Deduplicate and store raw job dicts from any source."""
    stored: list[Job] = []
    seen_job_keys: set[str] = set()
    refreshed_existing = False
    known_startup_companies = (
        await _load_known_startup_company_names(db, user_id) if raw_jobs else set()
    )

    for data in raw_jobs:
        _infer_startup_tags_for_job(data, known_startup_companies)
        _infer_occupation_tags_for_job(data)
        data = normalize_job_metadata(data)
        fp = _fingerprint(data.get("company_name", ""), data.get("title", ""), data.get("location", ""))
        job_key = _job_identity_key(data, fingerprint=fp)
        if job_key in seen_job_keys:
            continue
        seen_job_keys.add(job_key)

        existing = await _find_existing_job(
            db,
            user_id=user_id,
            source=data.get("source"),
            ats=data.get("ats"),
            external_id=data.get("external_id"),
            url=data.get("url"),
            fingerprint=fp,
        )
        score, breakdown = _score_job(data, profile)
        experience_level = _experience_level_for_job(data)
        if existing:
            _refresh_existing_job(
                existing,
                data,
                fingerprint=fp,
                score=score,
                breakdown=breakdown,
                experience_level=experience_level,
            )
            refreshed_existing = True
            continue

        job = _build_job(
            user_id=user_id,
            data=data,
            score=score,
            breakdown=breakdown,
            fingerprint=fp,
        )
        db.add(job)
        stored.append(job)

    if stored or refreshed_existing:
        await db.commit()

    if stored:
        # Trigger auto-prospect for newly stored jobs (if enabled)
        try:
            await _maybe_auto_prospect(db, user_id, stored)
        except Exception:
            logger.debug("Auto-prospect trigger check failed", exc_info=True)

    return stored


async def mark_stale_jobs_for_user(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    stale_after_days: int = 14,
    closed_after_days: int = 45,
) -> dict:
    """Mark jobs that have not been seen recently as stale/closed.

    This avoids presenting old postings as confidently active while preserving
    user tracking state for jobs they may have saved or applied to.
    """
    now = _utcnow()
    stale_cutoff = now - timedelta(days=stale_after_days)
    closed_cutoff = now - timedelta(days=closed_after_days)
    result = await db.execute(
        select(Job).where(
            Job.user_id == user_id,
            Job.last_seen_at.is_not(None),
            Job.last_seen_at < stale_cutoff,
            Job.source_status != "closed",
        )
    )
    stale_count = 0
    closed_count = 0
    for job in result.scalars().all():
        if job.last_seen_at and job.last_seen_at < closed_cutoff:
            job.source_status = "closed"
            job.closed_at = job.closed_at or now
            closed_count += 1
        else:
            job.source_status = "stale"
            stale_count += 1
        job.not_seen_count = (job.not_seen_count or 0) + 1

    if stale_count or closed_count:
        await db.commit()
    return {"stale": stale_count, "closed": closed_count}


async def _maybe_auto_prospect(
    db: AsyncSession,
    user_id: uuid.UUID,
    jobs: list,
) -> None:
    """Queue auto-prospect Celery tasks for new jobs if the user has it enabled."""
    from app.services.settings_service import is_auto_prospect_enabled  # noqa: PLC0415

    for job in jobs:
        company = getattr(job, "company_name", None) or ""
        if not await is_auto_prospect_enabled(db, user_id, company):
            continue
        try:
            from app.tasks.auto_prospect import auto_prospect_job  # noqa: PLC0415
            auto_prospect_job.delay(str(user_id), str(job.id))
            logger.info(
                "Auto-prospect queued: user=%s job=%s company=%s",
                user_id, job.id, company,
            )
        except Exception:
            logger.debug("Failed to queue auto-prospect task", exc_info=True)


async def _resolve_supported_job_links(url: str, *, max_depth: int = 1) -> list[str]:
    if is_supported_job_link(url):
        return [url]

    visited_pages: set[str] = set()
    queue: list[tuple[str, int]] = [(url, 0)]
    resolved: list[str] = []
    seen_links: set[str] = set()

    while queue:
        page_url, depth = queue.pop(0)
        if page_url in visited_pages:
            continue
        visited_pages.add(page_url)

        page = await public_page_client.fetch_direct_page(page_url, timeout_seconds=15)
        if not page or not page.get("html"):
            continue

        for candidate in extract_candidate_links(str(page.get("url") or page_url), str(page.get("html") or "")):
            if candidate in seen_links:
                continue
            seen_links.add(candidate)
            if is_supported_job_link(candidate):
                resolved.append(candidate)
            elif depth < max_depth and looks_like_careers_page(candidate):
                queue.append((candidate, depth + 1))

    return resolved


async def _discover_startup_direct_sources(
    db: AsyncSession,
    user_id: uuid.UUID,
    profile: Profile | None,
    queries: list[str],
) -> int:
    raw_jobs: list[dict] = []
    fetchers = [
        ("yc_jobs", yc_jobs_client.search_yc_jobs),
        ("wellfound", wellfound_jobs_client.search_wellfound_jobs),
        ("ventureloop", ventureloop_jobs_client.search_ventureloop_jobs),
    ]

    # Forward the query so each fetcher applies its built-in filtering instead of
    # returning everything (audit H8). Only pass it when there's a single query —
    # passing one of several would drop jobs matching the other queries, so the
    # multi-query discover path stays broad and relies on the post-hoc filter.
    fetch_query = queries[0] if len(queries) == 1 else None
    results = await asyncio.gather(
        *(fetcher(query=fetch_query, limit=200) for _, fetcher in fetchers),
        return_exceptions=True,
    )
    for (source_key, _fetcher), result in zip(fetchers, results):
        if isinstance(result, BaseException):
            logger.error("Startup direct source failed: %s", source_key, exc_info=result)
        else:
            raw_jobs.extend(result)

    matching_jobs = [job for job in raw_jobs if job_matches_any_query(job, queries)]
    stored = await _store_raw_jobs(db, user_id, matching_jobs, profile)
    return len(stored)


async def _import_startup_candidate_link(
    db: AsyncSession,
    user_id: uuid.UUID,
    profile: Profile | None,
    *,
    startup_source: str,
    candidate_url: str,
    queries: list[str],
) -> int:
    parsed = ats.parse_ats_job_url(candidate_url)
    if not parsed:
        return 0

    if (
        parsed.company_slug
        and parsed.external_id is None
        and parsed.exact_url_only is False
        and parsed.ats_type in {"greenhouse", "lever", "ashby"}
    ):
        adapter = ats.get_adapter(parsed.ats_type)
        if adapter is None or adapter.search_board is None:
            return 0
        raw_jobs = await adapter.search_board(parsed.company_slug, None)
        tagged_jobs = [
            append_startup_tags(job, startup_source)
            for job in raw_jobs
            if job_matches_any_query(job, queries)
        ]
        stored = await _store_raw_jobs(db, user_id, tagged_jobs, profile)
        return len(stored)

    exact_jobs = await search_ats_jobs(
        db,
        user_id,
        company_slug=None,
        ats_type=None,
        job_url=candidate_url,
        extra_tags=startup_tags(startup_source),
        include_existing_exact_matches=False,
    )
    return len(exact_jobs)


async def _discover_startup_ecosystem_entries(
    db: AsyncSession,
    user_id: uuid.UUID,
    profile: Profile | None,
    *,
    entries: list[dict],
    url_key: str,
    startup_source: str,
    queries: list[str],
) -> int:
    semaphore = asyncio.Semaphore(STARTUP_LINK_RESOLVE_CONCURRENCY)

    async def _process_entry(entry: dict) -> int:
        raw_url = str(entry.get(url_key) or "").strip()
        if not raw_url:
            return 0

        # Entries with roles (e.g. Conviction) are pre-filtered here.
        # Entries without roles (e.g. Speedrun companies) intentionally skip
        # this filter — role queries can't match bare company names, and the
        # real query filtering happens downstream in _import_startup_candidate_link.
        roles = entry.get("roles") or []
        if roles:
            matches_role = any(
                job_matches_any_query(
                    {
                        "title": role.get("title"),
                        "location": role.get("location"),
                        "company_name": entry.get("company_name"),
                    },
                    queries,
                )
                for role in roles
                if isinstance(role, dict)
            )
            if not matches_role:
                return 0

        async with semaphore:
            links = await _resolve_supported_job_links(raw_url)

        total_new = 0
        for candidate in links[:STARTUP_MAX_RESOLVED_LINKS_PER_COMPANY]:
            try:
                total_new += await _import_startup_candidate_link(
                    db,
                    user_id,
                    profile,
                    startup_source=startup_source,
                    candidate_url=candidate,
                    queries=queries,
                )
            except Exception:
                logger.exception(
                    "Failed importing startup candidate link from %s: %s",
                    startup_source,
                    candidate,
                )
        return total_new

    if not entries:
        return 0

    counts = await asyncio.gather(*(_process_entry(entry) for entry in entries))
    return sum(counts)


async def _discover_startup_ecosystems(
    db: AsyncSession,
    user_id: uuid.UUID,
    profile: Profile | None,
    queries: list[str],
) -> int:
    total_new = 0

    try:
        conviction_entries = await conviction_jobs_client.fetch_conviction_startups()
        total_new += await _discover_startup_ecosystem_entries(
            db,
            user_id,
            profile,
            entries=conviction_entries,
            url_key="career_url",
            startup_source="conviction",
            queries=queries,
        )
    except Exception:
        logger.exception("Conviction startup discover failed")

    try:
        speedrun_companies = await speedrun_jobs_client.fetch_speedrun_companies(limit=100)
        total_new += await _discover_startup_ecosystem_entries(
            db,
            user_id,
            profile,
            entries=speedrun_companies,
            url_key="website_url",
            startup_source="a16z_speedrun",
            queries=queries,
        )
    except Exception:
        logger.exception("a16z Speedrun startup discover failed")

    try:
        curated_entries = curated_startups_client.get_curated_startups()
        total_new += await _discover_startup_ecosystem_entries(
            db,
            user_id,
            profile,
            entries=curated_entries,
            url_key="career_url",
            startup_source="curated_list",
            queries=queries,
        )
    except Exception:
        logger.exception("Curated startups list discover failed")

    return total_new


async def run_startup_refresh_for_query(
    db: AsyncSession,
    user_id: uuid.UUID,
    query: str,
) -> list[Job]:
    """Re-run the startup discover flow for a single saved-search query.

    Returns the list of Job rows that were newly created by this run so the
    caller (Celery refresh task) can fire notifications. Matches the
    snapshotting approach used by ``search_jobs`` but scoped to the startup
    sources + ecosystems rather than standard job boards.
    """
    trimmed = (query or "").strip()
    if not trimmed:
        return []

    result = await db.execute(select(Profile).where(Profile.user_id == user_id))
    profile = result.scalar_one_or_none()

    snapshot_time = datetime.now(timezone.utc)
    queries = [trimmed]

    try:
        await _discover_startup_direct_sources(db, user_id, profile, queries)
    except Exception:
        logger.exception("Startup refresh: direct sources failed for query '%s'", trimmed)
    try:
        await _discover_startup_ecosystems(db, user_id, profile, queries)
    except Exception:
        logger.exception("Startup refresh: ecosystems failed for query '%s'", trimmed)

    await db.commit()

    new_rows = await db.execute(
        select(Job)
        .where(
            Job.user_id == user_id,
            Job.created_at >= snapshot_time,
        )
        .order_by(Job.created_at.desc())
    )
    return list(new_rows.scalars().all())


async def _ensure_startup_search_preferences(
    db: AsyncSession,
    user_id: uuid.UUID,
    queries: list[str],
) -> None:
    """Persist a SearchPreference(mode="startup") per query if not already stored."""
    for raw_query in queries:
        query = (raw_query or "").strip()
        if not query:
            continue
        stmt = select(SearchPreference).where(
            SearchPreference.user_id == user_id,
            SearchPreference.query == query,
            SearchPreference.mode == "startup",
        )
        result = await db.execute(stmt)
        if result.scalar_one_or_none() is None:
            db.add(
                SearchPreference(
                    user_id=user_id,
                    query=query,
                    location=None,
                    remote_only=False,
                    mode="startup",
                )
            )


async def discover_jobs(
    db: AsyncSession,
    user_id: uuid.UUID,
    queries: list[str] | None = None,
    mode: str = "default",
    occupations: list[str] | None = None,
) -> int:
    """Run a batch of job searches across free sources and ATS boards.

    Unlike seed_default_feeds this always runs — it is the manual
    "Discover Jobs" action.  Deduplication is handled by search_jobs
    and search_ats_jobs, so repeat runs are safe.

    Args:
        queries: Optional custom list of free-text search terms. Wins over
                 occupations when both are supplied.
        occupations: Optional list of occupation taxonomy keys. When set,
                     each occupation's default queries are flattened in.
                     Falls back to ``profile.target_occupations`` and finally
                     to ``DISCOVER_QUERIES``.
    """
    result = await db.execute(select(Profile).where(Profile.user_id == user_id))
    profile = result.scalar_one_or_none()

    resolved_occupations = (
        list(occupations)
        if occupations
        else (profile.target_occupations if profile is not None else None)
    )

    if mode == "startup":
        if queries:
            startup_queries = list(queries)
        else:
            target_roles = profile.target_roles if profile is not None else None
            startup_queries = startup_discover_queries(
                target_roles, occupation_keys=resolved_occupations
            )
        total_new = await _discover_startup_direct_sources(db, user_id, profile, startup_queries)
        total_new += await _discover_startup_ecosystems(db, user_id, profile, startup_queries)
        # Persist search preferences with mode="startup" so the hourly Celery
        # refresh can re-run the startup discover flow instead of falling back
        # to the default job-board search.
        await _ensure_startup_search_preferences(db, user_id, startup_queries)
        await db.commit()
        return total_new

    if queries:
        search_list = [
            {"query": q, "location": None, "remote_only": False} for q in queries
        ]
    elif resolved_occupations:
        search_list = discover_queries_for_occupations(resolved_occupations)
    else:
        search_list = DISCOVER_QUERIES

    total_new = 0

    # 1. Standard job search (JSearch, Dice, Remotive — newgrad excluded here)
    #    newgrad is scraped once unfiltered below instead of 7× with keyword filters
    #    that would discard most results.
    target_locations = [
        loc for loc in ((profile.target_locations if profile else None) or []) if loc
    ][:DISCOVER_LOCATION_FANOUT]
    expanded_seeds: list[dict] = []
    for seed in search_list:
        expanded_seeds.append(seed)
        if seed.get("location") is None and not seed.get("remote_only"):
            for loc in target_locations:
                expanded_seeds.append({**seed, "location": loc})

    suppress_tech = _suppress_tech_sources(resolved_occupations)
    if suppress_tech:
        # All-industry aggregators only - the curated tech employers and
        # tech-leaning boards are noise for nursing / teaching / law / etc.
        discover_sources = ["jsearch", "adzuna", "remotive"]
        logger.info(
            "Discover: routing to broad aggregators only (non-tech occupations: %s)",
            resolved_occupations,
        )
    else:
        discover_sources = ["jsearch", "adzuna", "remotive", "jobicy", "dice", "simplify"]

    for seed in expanded_seeds:
        try:
            stored = await search_jobs(
                db,
                user_id,
                query=seed["query"],  # type: ignore[arg-type]
                location=seed["location"],  # type: ignore[arg-type]
                remote_only=seed["remote_only"],  # type: ignore[arg-type]
                sources=discover_sources,
                limit=DISCOVER_LIMIT_PER_SOURCE,
                occupation_hint=seed.get("occupation"),
            )
            total_new += len(stored)
        except Exception:
            logger.exception("Discover failed for query: %s", seed["query"])

    # 2. newgrad-jobs.com — tech/new-grad-leaning; skip for non-tech occupations.
    if not suppress_tech:
        try:
            raw_newgrad = await newgrad_jobs_client.search_newgrad_jobs()
            ng_stored = await _store_raw_jobs(db, user_id, raw_newgrad, profile)
            if ng_stored:
                logger.info("newgrad-jobs discover: %d new jobs", len(ng_stored))
            total_new += len(ng_stored)
        except Exception:
            logger.exception("newgrad-jobs discover failed")

    # 3. Curated ATS boards are all tech companies — skip for non-tech occupations.
    if not suppress_tech:
        try:
            ats_new = await _discover_ats_boards(db, user_id)
            total_new += ats_new
        except Exception:
            logger.exception("ATS board discovery failed")

    # 4. Curated non-tech vertical boards (health systems, universities,
    #    banks/insurers, retailers). Occupation-routed and additive: fires
    #    whenever the resolved occupations have a vertical home, independent of
    #    the tech-source suppression decision (a finance seeker isn't suppressed
    #    but still wants banks; a nurse is suppressed and still wants hospitals).
    target_verticals = verticals_for_occupations(resolved_occupations)
    if target_verticals:
        try:
            nt_new = await _discover_nontech_vertical_boards(
                db, user_id, target_verticals, profile
            )
            total_new += nt_new
            logger.info(
                "Discover: non-tech vertical boards (%s) -> %d new jobs",
                sorted(target_verticals),
                nt_new,
            )
        except Exception:
            logger.exception("non-tech vertical board discovery failed")

    logger.info("Discovered %d new jobs for user %s", total_new, user_id)
    return total_new
