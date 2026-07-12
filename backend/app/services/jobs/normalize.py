"""Pure helpers: fingerprinting, URL canonicalization, source stats, metadata coercion."""

import asyncio
import logging
import httpx
from app.models.job import Job
from app.clients import ats
from app.utils.job_metadata import country_code_for_name
from datetime import date
from datetime import datetime
from datetime import timedelta
from app.utils.job_metadata import geocode_location_query
import hashlib
from app.utils.startup_jobs import merge_tags
from app.utils.job_metadata import normalize_job_metadata
import re
from sqlalchemy import func as sa_func
from datetime import timezone
from urllib.parse import urlparse
from urllib.parse import urlunparse

logger = logging.getLogger(__name__)


def is_transient_fetch_error(exc: BaseException) -> bool:
    """True for expected, transient failures fetching an external job source.

    The aggregator/board clients are best-effort and already fail soft, so a
    third-party site being slow, unreachable, or returning a transport error is
    operational noise — not a bug. Callers log these at WARNING (which stays out
    of Sentry) and reserve ``logger.exception`` for genuinely unexpected errors
    (parse bugs, programming errors) so real problems still surface.

    Covers httpx transport/timeout/status errors, asyncio timeouts, raw socket
    ``OSError``/``ConnectionError``, and thread-pool exhaustion (``RuntimeError:
    can't start new thread`` — every in-flight fetch that needs a DNS/executor
    thread raises it at once when the worker is under resource pressure, so it
    would page dozens of duplicate Sentry events per episode; the worker
    self-heals via child recycling and the real signal is the source-health
    monitor).
    """
    if isinstance(exc, (httpx.HTTPError, asyncio.TimeoutError, OSError)):
        return True
    return isinstance(exc, RuntimeError) and "can't start new thread" in str(exc)


EARTH_RADIUS_KM = 6371.0


def _fingerprint(company_name: str | None, title: str | None, location: str | None) -> str:
    """Create a fingerprint for deduplication based on company + title + location."""
    raw = (
        f"{(company_name or '').lower().strip()}|"
        f"{(title or '').lower().strip()}|"
        f"{(location or '').lower().strip()}"
    )
    return hashlib.md5(raw.encode(), usedforsecurity=False).hexdigest()


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
# A time component anywhere in an ISO-shaped string => the source gave us
# sub-day precision (e.g. "2026-05-21T14:30:00Z"), so we can show "14 hours ago".
_ISO_HAS_TIME_RE = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}")
# Trailing epoch (seconds=10 digits / millis=13 digits) some feeds emit.
_EPOCH_RE = re.compile(r"^\s*(\d{10}|\d{13})\s*$")
# "5 minutes ago", "2 hours ago", "3 days ago", "1 week ago", ...
_REL_AGO_RE = re.compile(
    r"\b(\d+)\s*(sec(?:ond)?|min(?:ute)?|hour|hr|day|week|month|year)s?\s+ago\b",
    re.IGNORECASE,
)
# "an hour ago", "a day ago", "one minute ago"
_REL_AN_RE = re.compile(
    r"\b(?:an?|one)\s+(sec(?:ond)?|min(?:ute)?|hour|hr|day|week|month|year)\s+ago\b",
    re.IGNORECASE,
)


def _relative_posting_time(
    low: str, now: datetime
) -> tuple[datetime | None, date | None] | None:
    """Resolve a relative phrase ("3 days ago", "today") to (precise_ts, day).

    ``precise_ts`` is only returned when the phrase carries sub-day precision
    (seconds/minutes/hours/"just now"); coarser phrases (days/weeks/months,
    "today", "yesterday") return ``(None, day)`` so we never invent a fake
    posting time. Returns ``None`` when the text is not a relative phrase.
    """
    if low in {"just posted", "just now", "posted just now", "moments ago", "a moment ago"}:
        return (now, now.date())
    if low in {"today", "posted today"}:
        return (None, now.date())
    if low in {"yesterday", "posted yesterday"}:
        return (None, (now - timedelta(days=1)).date())

    match = _REL_AGO_RE.search(low)
    if match:
        count, unit = int(match.group(1)), match.group(2).lower()
    else:
        match = _REL_AN_RE.search(low)
        if not match:
            return None
        count, unit = 1, match.group(1).lower()

    if unit.startswith("sec"):
        ts = now - timedelta(seconds=count)
        return (ts, ts.date())
    if unit.startswith("min"):
        ts = now - timedelta(minutes=count)
        return (ts, ts.date())
    if unit in ("hour", "hr"):
        ts = now - timedelta(hours=count)
        return (ts, ts.date())
    if unit == "day":
        return (None, (now - timedelta(days=count)).date())
    if unit == "week":
        return (None, (now - timedelta(weeks=count)).date())
    if unit == "month":
        return (None, (now - timedelta(days=30 * count)).date())
    if unit == "year":
        return (None, (now - timedelta(days=365 * count)).date())
    return None


def _parse_iso_datetime(text: str) -> datetime | None:
    """Parse an ISO-8601 datetime (with 'Z'/offset, optional trailing junk) to UTC."""
    candidate = text.strip()
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        # Recover the leading datetime if there's trailing content.
        m = re.match(
            r"^\s*(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?)"
            r"(Z|[+-]\d{2}:?\d{2})?",
            text,
        )
        if not m:
            return None
        base, offset = m.group(1), m.group(2) or ""
        if offset == "Z":
            offset = "+00:00"
        elif offset and ":" not in offset:  # "+0000" -> "+00:00"
            offset = offset[:3] + ":" + offset[3:]
        try:
            dt = datetime.fromisoformat(base + offset)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_posting_time(
    value: str | None, *, now: datetime | None = None
) -> tuple[datetime | None, date | None]:
    """Parse a source ``posted_at`` string into ``(precise_ts, posted_date)``.

    - ``precise_ts`` (tz-aware UTC) is set ONLY when the source gives genuine
      sub-day precision — an ISO datetime, an epoch, or a fine relative phrase
      ("30 minutes ago") — so "15 minutes ago" in the UI is never fabricated.
    - ``posted_date`` (calendar-validated day) is set whenever a posting day is
      resolvable, including coarse relative phrases ("3 days ago"). It feeds the
      indexed ``posted_date`` column, so date ordering never casts a bad string
      at query time (audit pass-2 P3) and invalid dates still resolve to None.

    Both are ``None`` for missing or unrecognized values.
    """
    if not isinstance(value, str):
        return (None, None)
    text = value.strip()
    if not text:
        return (None, None)
    if now is None:
        now = datetime.now(timezone.utc)

    relative = _relative_posting_time(text.lower(), now)
    if relative is not None:
        return relative

    epoch = _EPOCH_RE.match(text)
    if epoch:
        raw = int(epoch.group(1))
        seconds = raw / 1000.0 if len(epoch.group(1)) == 13 else float(raw)
        try:
            ts = datetime.fromtimestamp(seconds, tz=timezone.utc)
        except (ValueError, OverflowError, OSError):
            return (None, None)
        return (ts, ts.date())

    if _ISO_HAS_TIME_RE.search(text):
        ts = _parse_iso_datetime(text)
        if ts is not None:
            return (ts, ts.date())

    match = _POSTED_DATE_RE.match(text)
    if match:
        try:
            return (None, date(int(match.group(1)), int(match.group(2)), int(match.group(3))))
        except ValueError:
            return (None, None)

    return (None, None)


def _parse_posted_date(value: str | None) -> date | None:
    """Calendar-validated posting day parsed from a source ``posted_at`` string.

    Thin wrapper over :func:`_parse_posting_time` (the day component). Resolves
    ISO dates/datetimes, epochs, and relative phrases ("3 days ago"); returns
    None for missing or date-shaped-but-invalid values (e.g. "2026-02-30").
    """
    return _parse_posting_time(value)[1]


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
