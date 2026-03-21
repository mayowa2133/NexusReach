"""ATS ingestion clients for board-backed and exact-job job URLs."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from html import unescape
from typing import Awaitable, Callable
from urllib.parse import parse_qs, urlparse

import httpx

from app.clients import public_page_client

JSON_LD_RE = re.compile(
    r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(?P<payload>.*?)</script>",
    flags=re.IGNORECASE | re.DOTALL,
)
STATIC_ROUTER_RE = re.compile(
    r"window\.__staticRouterHydrationData\s*=\s*JSON\.parse\(\"(?P<payload>.*?)\"\);",
    flags=re.DOTALL,
)
TITLE_RE = re.compile(r"<title>(?P<title>.*?)</title>", flags=re.IGNORECASE | re.DOTALL)
HEADING_RE = re.compile(r"<h1[^>]*>(?P<title>.*?)</h1>", flags=re.IGNORECASE | re.DOTALL)
TAG_RE = re.compile(r"<[^>]+>")
WHITESPACE_RE = re.compile(r"\s+")
COMMON_SUBDOMAINS = {"jobs", "careers", "apply", "app", "www"}


@dataclass(frozen=True)
class ParsedATSJobURL:
    """Normalized ATS job URL metadata."""

    ats_type: str
    company_slug: str | None
    external_id: str | None = None
    canonical_url: str | None = None
    host: str = ""
    exact_url_only: bool = False


@dataclass(frozen=True)
class ATSAdapter:
    ats_type: str
    parse_url: Callable[[str], ParsedATSJobURL | None]
    search_board: Callable[[str, int | None], Awaitable[list[dict]]] | None = None
    fetch_exact: Callable[[ParsedATSJobURL], Awaitable[list[dict]]] | None = None


class ExactJobFetchError(ValueError):
    """Raised when an exact job URL can be resolved but not extracted."""


def _clean_url(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    return parsed._replace(path=path, query="", fragment="").geturl()


def _strip_tags(value: str | None) -> str:
    return WHITESPACE_RE.sub(" ", unescape(TAG_RE.sub(" ", value or ""))).strip()


def _normalize_text(value: str | None) -> str:
    normalized = unescape(value or "").replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


def _extract_title(html: str) -> str:
    match = TITLE_RE.search(html or "")
    return _strip_tags(match.group("title")) if match else ""


def _extract_heading(html: str) -> str:
    match = HEADING_RE.search(html or "")
    return _strip_tags(match.group("title")) if match else ""


def _find_attr(tag: str, attr: str) -> str:
    match = re.search(rf'{attr}\s*=\s*["\']([^"\']+)["\']', tag, flags=re.IGNORECASE)
    return unescape(match.group(1)).strip() if match else ""


def _extract_meta_content(html: str, key: str) -> str:
    lowered_key = key.lower()
    for match in re.finditer(r"<meta\b[^>]*>", html or "", flags=re.IGNORECASE):
        tag = match.group(0)
        name = _find_attr(tag, "name") or _find_attr(tag, "property")
        if name.lower() != lowered_key:
            continue
        content = _find_attr(tag, "content")
        if content:
            return content
    return ""


def _domain_root(host: str | None) -> str:
    parts = [part for part in (host or "").lower().split(".") if part]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    if len(parts[-1]) == 2 and len(parts) >= 3:
        return parts[-3]
    return parts[-2]


def _host_ats_label(host: str) -> str:
    root = _domain_root(host)
    label = re.sub(r"[^a-z0-9]+", "_", root).strip("_")
    return f"{label}_jobs" if label else "custom_jobs"


def _job_posting_candidates(payload: object) -> list[dict]:
    candidates: list[dict] = []
    if isinstance(payload, dict):
        payload_type = payload.get("@type")
        if payload_type == "JobPosting" or (
            isinstance(payload_type, list) and "JobPosting" in payload_type
        ):
            candidates.append(payload)
        if isinstance(payload.get("@graph"), list):
            for item in payload["@graph"]:
                candidates.extend(_job_posting_candidates(item))
    elif isinstance(payload, list):
        for item in payload:
            candidates.extend(_job_posting_candidates(item))
    return candidates


def _extract_json_ld_job(html: str) -> dict | None:
    for match in JSON_LD_RE.finditer(html or ""):
        raw_payload = match.group("payload").strip()
        if not raw_payload:
            continue
        try:
            payload = json.loads(raw_payload)
        except json.JSONDecodeError:
            continue
        candidates = _job_posting_candidates(payload)
        if candidates:
            return candidates[0]
    return None


def _extract_static_router_payload(html: str) -> dict | None:
    match = STATIC_ROUTER_RE.search(html or "")
    if not match:
        return None
    try:
        decoded = json.loads(f"\"{match.group('payload')}\"")
        payload = json.loads(decoded)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _string_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _coerce_posted_at(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _json_ld_company(job_posting: dict, host: str) -> str:
    hiring = job_posting.get("hiringOrganization")
    if isinstance(hiring, dict):
        name = hiring.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    return _domain_root(host).title()


def _json_ld_location(job_posting: dict) -> str | None:
    raw_locations = job_posting.get("jobLocation")
    if not raw_locations:
        return None

    if not isinstance(raw_locations, list):
        raw_locations = [raw_locations]

    formatted: list[str] = []
    for location in raw_locations:
        if not isinstance(location, dict):
            continue
        address = location.get("address")
        if isinstance(address, dict):
            parts = [
                address.get("addressLocality"),
                address.get("addressRegion"),
                address.get("addressCountry"),
            ]
            joined = ", ".join(str(part).strip() for part in parts if str(part).strip())
            if joined:
                formatted.append(joined)
    return " | ".join(dict.fromkeys(formatted)) or None


def _normalize_json_ld_job(parsed: ParsedATSJobURL, job_posting: dict) -> dict | None:
    title = _normalize_text(job_posting.get("title"))
    company_name = _json_ld_company(job_posting, parsed.host)
    if not title or not company_name:
        return None

    description = _normalize_text(_strip_tags(str(job_posting.get("description") or "")))
    employment_type = job_posting.get("employmentType")
    if isinstance(employment_type, list):
        employment_type_value = ", ".join(str(item).strip() for item in employment_type if str(item).strip())
    else:
        employment_type_value = str(employment_type).strip() if employment_type else None

    ats_label = parsed.ats_type if parsed.ats_type != "generic_exact" else _host_ats_label(parsed.host)
    remote = str(job_posting.get("jobLocationType") or "").upper() == "TELECOMMUTE"

    return {
        "external_id": parsed.external_id
        or (
            f"{ats_label}_{job_posting.get('identifier', {}).get('value')}"
            if isinstance(job_posting.get("identifier"), dict) and job_posting["identifier"].get("value")
            else None
        ),
        "title": title,
        "company_name": company_name,
        "location": _json_ld_location(job_posting),
        "remote": remote or "remote" in f"{title} {description}".lower(),
        "url": parsed.canonical_url,
        "description": description or None,
        "employment_type": employment_type_value,
        "posted_at": _coerce_posted_at(job_posting.get("datePosted")),
        "source": ats_label,
        "ats": ats_label,
        "ats_slug": parsed.company_slug or _domain_root(parsed.host),
    }


def _cleanup_generic_title(raw_title: str, company_name: str | None = None) -> str:
    title = _normalize_text(raw_title)
    if not title:
        return ""
    cleanup_patterns = [
        r"\s*[-|]\s*jobs?\s*[-|].*$",
        r"\s*[-|]\s*careers?.*$",
    ]
    for pattern in cleanup_patterns:
        cleaned = re.sub(pattern, "", title, flags=re.IGNORECASE).strip()
        if cleaned and cleaned != title:
            title = cleaned
            break
    if company_name:
        title = re.sub(
            rf"\s*[-|]\s*{re.escape(company_name)}\s*$",
            "",
            title,
            flags=re.IGNORECASE,
        ).strip()
    return title


def _generic_company_name(page: dict, parsed: ParsedATSJobURL) -> str:
    html = page.get("html") or ""
    candidates = [
        _extract_meta_content(html, "og:site_name"),
        _extract_meta_content(html, "application-name"),
    ]
    for candidate in candidates:
        if candidate:
            return candidate.strip()
    return _domain_root(parsed.host).replace("-", " ").title()


def _normalize_generic_exact_job(page: dict, parsed: ParsedATSJobURL) -> dict | None:
    html = page.get("html") or ""
    json_ld = _extract_json_ld_job(html)
    if json_ld:
        return _normalize_json_ld_job(parsed, json_ld)

    company_name = _generic_company_name(page, parsed)
    raw_title = _extract_heading(html) or _extract_meta_content(html, "og:title") or page.get("title") or ""
    title = _cleanup_generic_title(raw_title, company_name=company_name)
    if not title or not company_name or not parsed.canonical_url:
        return None

    description = _normalize_text(
        _extract_meta_content(html, "description")
        or _extract_meta_content(html, "og:description")
        or (page.get("content") or "")[:4000]
    )
    location = _extract_meta_content(html, "job:location") or None
    ats_label = parsed.ats_type if parsed.ats_type != "generic_exact" else _host_ats_label(parsed.host)

    return {
        "external_id": parsed.external_id,
        "title": title,
        "company_name": company_name,
        "location": location,
        "remote": "remote" in f"{title} {description}".lower(),
        "url": parsed.canonical_url,
        "description": description or None,
        "employment_type": None,
        "posted_at": None,
        "source": ats_label,
        "ats": ats_label,
        "ats_slug": parsed.company_slug or _domain_root(parsed.host),
    }


def _apple_location(locations: object) -> str | None:
    if not isinstance(locations, list):
        return None
    formatted: list[str] = []
    for location in locations:
        if not isinstance(location, dict):
            continue
        parts = [
            location.get("city") or location.get("name"),
            location.get("stateProvince"),
            location.get("countryName"),
        ]
        joined = ", ".join(str(part).strip() for part in parts if str(part).strip())
        if joined:
            formatted.append(joined)
    return " | ".join(dict.fromkeys(formatted)) or None


def _apple_description(job_data: dict) -> str | None:
    sections: list[str] = []
    summary = _normalize_text(job_data.get("jobSummary"))
    description = _normalize_text(job_data.get("description"))
    responsibilities = _normalize_text(job_data.get("responsibilities"))
    minimum = _normalize_text(job_data.get("minimumQualifications"))
    preferred = _normalize_text(job_data.get("preferredQualifications"))

    if summary:
        sections.append(summary)
    if description:
        sections.append(description)
    if responsibilities:
        sections.append(f"Responsibilities\n{responsibilities}")
    if minimum:
        sections.append(f"Minimum Qualifications\n{minimum}")
    if preferred:
        sections.append(f"Preferred Qualifications\n{preferred}")

    joined = "\n\n".join(section for section in sections if section)
    return joined or None


def _normalize_apple_job(parsed: ParsedATSJobURL, page: dict) -> dict | None:
    html = page.get("html") or ""
    payload = _extract_static_router_payload(html)
    jobs_data = ((payload or {}).get("loaderData") or {}).get("jobDetails", {}).get("jobsData", {})
    if not isinstance(jobs_data, dict):
        return None

    title = _normalize_text(jobs_data.get("postingTitle"))
    if not title:
        title = _cleanup_generic_title(page.get("title") or "", company_name="Apple")
    if not title or not parsed.canonical_url:
        return None

    team_names = _string_list(jobs_data.get("teamNames"))
    return {
        "external_id": parsed.external_id or f"apple_{jobs_data.get('jobNumber')}",
        "title": title,
        "company_name": "Apple",
        "location": _apple_location(jobs_data.get("locations")),
        "remote": bool(jobs_data.get("homeOffice")) or "remote" in f"{title} {jobs_data.get('description', '')}".lower(),
        "url": parsed.canonical_url,
        "description": _apple_description(jobs_data),
        "employment_type": _normalize_text(jobs_data.get("employmentType")) or _normalize_text(jobs_data.get("jobType")) or None,
        "posted_at": _coerce_posted_at(jobs_data.get("postDateInGMT") or jobs_data.get("postingDate")),
        "source": "apple_jobs",
        "ats": "apple_jobs",
        "ats_slug": "apple",
        "department": ", ".join(team_names) or None,
    }


async def _fetch_exact_page(parsed: ParsedATSJobURL) -> dict:
    page = await public_page_client.fetch_page(parsed.canonical_url or "", timeout_seconds=20)
    if not page:
        raise ExactJobFetchError("Could not read the job posting page.")
    return page


async def _fetch_workable_exact_job(parsed: ParsedATSJobURL) -> list[dict]:
    if not parsed.company_slug or not parsed.external_id:
        raise ExactJobFetchError("Could not resolve the Workable job URL.")
    return await search_workable(
        parsed.company_slug,
        job_shortcode=parsed.external_id.removeprefix("wk_"),
    )


async def _fetch_apple_exact_job(parsed: ParsedATSJobURL) -> list[dict]:
    page = await _fetch_exact_page(parsed)
    job = _normalize_apple_job(parsed, page)
    if not job:
        raise ExactJobFetchError("We found the Apple job page, but couldn't extract enough job details from it.")
    return [job]


async def _fetch_generic_exact_job(parsed: ParsedATSJobURL) -> list[dict]:
    page = await _fetch_exact_page(parsed)
    job = _normalize_generic_exact_job(page, parsed)
    if not job:
        raise ExactJobFetchError("We found the page, but couldn't extract enough job details from it.")
    return [job]


def _parse_greenhouse_url(job_url: str) -> ParsedATSJobURL | None:
    parsed = urlparse((job_url or "").strip())
    host = parsed.netloc.lower()
    if "greenhouse.io" not in host:
        return None

    path_parts = [part for part in parsed.path.split("/") if part]
    query = parse_qs(parsed.query)
    if path_parts[:2] == ["embed", "job_app"]:
        company_slug = (query.get("for") or [None])[0]
        raw_job_id = (query.get("token") or query.get("job_id") or query.get("gh_jid") or [None])[0]
        if not company_slug:
            return None
        canonical_url = None
        external_id = None
        if raw_job_id:
            external_id = f"gh_{raw_job_id}"
            canonical_url = f"https://job-boards.greenhouse.io/{company_slug}/jobs/{raw_job_id}"
        return ParsedATSJobURL(
            ats_type="greenhouse",
            company_slug=company_slug,
            external_id=external_id,
            canonical_url=canonical_url,
            host=host,
        )

    if "jobs" in path_parts:
        jobs_index = path_parts.index("jobs")
        if jobs_index >= 1:
            company_slug = path_parts[jobs_index - 1]
            raw_job_id = path_parts[jobs_index + 1] if len(path_parts) > jobs_index + 1 else None
            return ParsedATSJobURL(
                ats_type="greenhouse",
                company_slug=company_slug,
                external_id=f"gh_{raw_job_id}" if raw_job_id else None,
                canonical_url=_clean_url(job_url),
                host=host,
            )
    return None


def _parse_lever_url(job_url: str) -> ParsedATSJobURL | None:
    parsed = urlparse((job_url or "").strip())
    host = parsed.netloc.lower()
    if "lever.co" not in host:
        return None
    path_parts = [part for part in parsed.path.split("/") if part]
    if not path_parts:
        return None
    company_slug = path_parts[0]
    raw_job_id = path_parts[1] if len(path_parts) > 1 else None
    return ParsedATSJobURL(
        ats_type="lever",
        company_slug=company_slug,
        external_id=f"lv_{raw_job_id}" if raw_job_id else None,
        canonical_url=_clean_url(job_url),
        host=host,
    )


def _parse_ashby_url(job_url: str) -> ParsedATSJobURL | None:
    parsed = urlparse((job_url or "").strip())
    host = parsed.netloc.lower()
    if "ashbyhq.com" not in host or not host.startswith("jobs."):
        return None
    path_parts = [part for part in parsed.path.split("/") if part]
    if not path_parts:
        return None
    company_slug = path_parts[0]
    raw_job_id = path_parts[1] if len(path_parts) > 1 else None
    return ParsedATSJobURL(
        ats_type="ashby",
        company_slug=company_slug,
        external_id=f"ab_{raw_job_id}" if raw_job_id else None,
        canonical_url=_clean_url(job_url),
        host=host,
    )


def _parse_workable_url(job_url: str) -> ParsedATSJobURL | None:
    parsed = urlparse((job_url or "").strip())
    host = parsed.netloc.lower()
    if "apply.workable.com" not in host:
        return None
    path_parts = [part for part in parsed.path.split("/") if part]
    if len(path_parts) < 3 or path_parts[1] != "j":
        return None
    company_slug = path_parts[0]
    raw_job_id = path_parts[2]
    return ParsedATSJobURL(
        ats_type="workable",
        company_slug=company_slug,
        external_id=f"wk_{raw_job_id}" if raw_job_id else None,
        canonical_url=_clean_url(job_url),
        host=host,
        exact_url_only=True,
    )


def _parse_apple_jobs_url(job_url: str) -> ParsedATSJobURL | None:
    parsed = urlparse((job_url or "").strip())
    host = parsed.netloc.lower()
    if host != "jobs.apple.com":
        return None
    path_parts = [part for part in parsed.path.split("/") if part]
    if len(path_parts) < 3 or path_parts[1] != "details":
        return None
    raw_job_id = path_parts[2]
    return ParsedATSJobURL(
        ats_type="apple_jobs",
        company_slug="apple",
        external_id=f"apple_{raw_job_id}" if raw_job_id else None,
        canonical_url=_clean_url(job_url),
        host=host,
        exact_url_only=True,
    )


def _parse_generic_exact_url(job_url: str) -> ParsedATSJobURL | None:
    parsed = urlparse((job_url or "").strip())
    host = parsed.netloc.lower()
    if parsed.scheme not in {"http", "https"} or not host:
        return None
    return ParsedATSJobURL(
        ats_type="generic_exact",
        company_slug=_domain_root(host) or None,
        canonical_url=_clean_url(job_url),
        host=host,
        exact_url_only=True,
    )


async def search_greenhouse(company_slug: str, limit: int | None = None) -> list[dict]:
    """Fetch open jobs from a Greenhouse company board."""
    url = f"https://boards-api.greenhouse.io/v1/boards/{company_slug}/jobs"
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url, params={"content": "true"})
        if resp.status_code != 200:
            return []
        data = resp.json()

    jobs = [
        {
            "external_id": f"gh_{j.get('id', '')}",
            "title": j.get("title", ""),
            "company_name": data.get("name", company_slug),
            "location": (j.get("location", {}) or {}).get("name", ""),
            "remote": "remote" in (j.get("title", "") + (j.get("location", {}) or {}).get("name", "")).lower(),
            "url": j.get("absolute_url", ""),
            "description": j.get("content", ""),
            "posted_at": j.get("updated_at", ""),
            "source": "greenhouse",
            "ats": "greenhouse",
            "ats_slug": company_slug,
        }
        for j in data.get("jobs", [])
    ]
    return jobs[:limit] if limit is not None else jobs


async def search_lever(company_slug: str, limit: int | None = None) -> list[dict]:
    """Fetch open jobs from a Lever company board."""
    url = f"https://api.lever.co/v0/postings/{company_slug}"
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url, params={"mode": "json"})
        if resp.status_code != 200:
            return []
        postings = resp.json()

    if not isinstance(postings, list):
        return []

    normalized = [
        {
            "external_id": f"lv_{p.get('id', '')}",
            "title": p.get("text", ""),
            "company_name": company_slug,
            "location": p.get("categories", {}).get("location", ""),
            "remote": "remote" in (p.get("text", "") + p.get("categories", {}).get("location", "")).lower(),
            "url": p.get("hostedUrl", "") or p.get("applyUrl", ""),
            "description": p.get("descriptionPlain", "") or p.get("description", ""),
            "department": p.get("categories", {}).get("department", ""),
            "posted_at": "",
            "source": "lever",
            "ats": "lever",
            "ats_slug": company_slug,
        }
        for p in postings
    ]
    return normalized[:limit] if limit is not None else normalized


async def search_ashby(company_slug: str, limit: int | None = None) -> list[dict]:
    """Fetch open jobs from an Ashby job board."""
    url = f"https://api.ashbyhq.com/posting-api/job-board/{company_slug}"
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url)
        if resp.status_code != 200:
            return []
        data = resp.json()

    jobs = [
        {
            "external_id": f"ab_{j.get('id', '')}",
            "title": j.get("title", ""),
            "company_name": data.get("organizationName", company_slug),
            "location": j.get("location", ""),
            "remote": j.get("isRemote", False) or "remote" in j.get("location", "").lower(),
            "url": j.get("jobUrl", ""),
            "description": j.get("descriptionHtml", "") or j.get("descriptionPlain", ""),
            "department": j.get("department", ""),
            "posted_at": j.get("publishedAt", ""),
            "source": "ashby",
            "ats": "ashby",
            "ats_slug": company_slug,
        }
        for j in data.get("jobs", [])
    ]
    return jobs[:limit] if limit is not None else jobs


def _workable_location(raw_job: dict) -> str:
    locations = raw_job.get("locations") or []
    primary = raw_job.get("location") or (locations[0] if locations else {}) or {}
    parts = [
        primary.get("city") or "",
        primary.get("region") or "",
        primary.get("country") or "",
    ]
    return ", ".join(part for part in parts if part)


async def search_workable(
    company_slug: str,
    *,
    job_shortcode: str,
) -> list[dict]:
    """Fetch a single public Workable job by shortcode from a direct job URL."""
    job_url = f"https://apply.workable.com/api/v2/accounts/{company_slug}/jobs/{job_shortcode}"
    account_url = f"https://apply.workable.com/api/v1/accounts/{company_slug}"

    async with httpx.AsyncClient(timeout=15) as client:
        job_resp = await client.get(job_url)
        if job_resp.status_code != 200:
            return []
        raw_job = job_resp.json()

        account_resp = await client.get(account_url, params={"full": "true"})
        account_name = company_slug
        if account_resp.status_code == 200:
            account_name = account_resp.json().get("name", company_slug)

    shortcode = raw_job.get("shortcode") or job_shortcode
    workplace = raw_job.get("workplace", "")
    remote = bool(raw_job.get("remote")) or workplace == "remote"
    department = raw_job.get("department") or []
    if isinstance(department, list):
        department_value = ", ".join(item for item in department if item)
    else:
        department_value = str(department or "")

    return [
        {
            "external_id": f"wk_{shortcode}",
            "title": raw_job.get("title", ""),
            "company_name": account_name,
            "location": _workable_location(raw_job),
            "remote": remote,
            "url": f"https://apply.workable.com/{company_slug}/j/{shortcode}",
            "description": raw_job.get("description", ""),
            "department": department_value,
            "employment_type": raw_job.get("type"),
            "posted_at": raw_job.get("published", ""),
            "source": "workable",
            "ats": "workable",
            "ats_slug": company_slug,
        }
    ]


ATS_ADAPTERS = (
    ATSAdapter("greenhouse", _parse_greenhouse_url, search_board=search_greenhouse),
    ATSAdapter("lever", _parse_lever_url, search_board=search_lever),
    ATSAdapter("ashby", _parse_ashby_url, search_board=search_ashby),
    ATSAdapter("workable", _parse_workable_url, fetch_exact=_fetch_workable_exact_job),
    ATSAdapter("apple_jobs", _parse_apple_jobs_url, fetch_exact=_fetch_apple_exact_job),
    ATSAdapter("generic_exact", _parse_generic_exact_url, fetch_exact=_fetch_generic_exact_job),
)
ATS_ADAPTERS_BY_TYPE = {adapter.ats_type: adapter for adapter in ATS_ADAPTERS}


def parse_ats_job_url(job_url: str) -> ParsedATSJobURL | None:
    """Parse a job URL into adapter-specific ATS metadata."""
    for adapter in ATS_ADAPTERS:
        parsed = adapter.parse_url(job_url)
        if parsed:
            return parsed
    return None


def get_adapter(ats_type: str | None) -> ATSAdapter | None:
    if not ats_type:
        return None
    return ATS_ADAPTERS_BY_TYPE.get(ats_type)


async def fetch_exact_job(parsed_job_url: ParsedATSJobURL) -> list[dict]:
    """Fetch a single job posting from an exact job URL adapter."""
    adapter = get_adapter(parsed_job_url.ats_type)
    if not adapter or adapter.fetch_exact is None:
        raise ExactJobFetchError("Unsupported exact job posting URL.")

    jobs = await adapter.fetch_exact(parsed_job_url)
    if not jobs:
        raise ExactJobFetchError("We found the page, but couldn't extract enough job details from it.")
    return jobs
