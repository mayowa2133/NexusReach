"""ATS ingestion clients for board-backed and exact-job job URLs."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from html import unescape
from typing import Awaitable, Callable
from urllib.parse import parse_qs, urlparse

import httpx

from app.clients import crawl4ai_client, firecrawl_client

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
CANONICAL_LINK_RE = re.compile(
    r"<link\b[^>]*rel=[\"']canonical[\"'][^>]*href=[\"'](?P<href>[^\"']+)[\"']",
    flags=re.IGNORECASE,
)
TAG_RE = re.compile(r"<[^>]+>")
WHITESPACE_RE = re.compile(r"\s+")
COMMON_SUBDOMAINS = {"jobs", "careers", "apply", "app", "www"}
WORKDAY_JOB_TOKEN_RE = re.compile(r"_(?P<token>JR[A-Za-z0-9-]+)$")
WORKDAY_COMPANY_NOISE_TOKENS = {
    "inc",
    "incorporated",
    "corp",
    "corporation",
    "company",
    "co",
    "llc",
    "ltd",
    "limited",
    "usa",
    "us",
}


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


def _extract_canonical_link(html: str) -> str | None:
    match = CANONICAL_LINK_RE.search(html or "")
    if not match:
        return None
    href = unescape(match.group("href")).strip()
    if not href:
        return None
    return _clean_url(href)


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


def _display_company_slug(company_slug: str | None, *, raw_name: str | None = None) -> str:
    if not company_slug:
        return ""

    normalized_slug = company_slug.replace("-", " ").strip()
    if raw_name:
        pattern = r"[-\s]+".join(re.escape(part) for part in normalized_slug.split() if part)
        if pattern:
            match = re.search(rf"\b{pattern}\b", raw_name, flags=re.IGNORECASE)
            if match:
                return match.group(0).replace("-", " ")

    return " ".join(part.capitalize() for part in normalized_slug.split())


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


def _epoch_ms_to_iso(value: object) -> str | None:
    """Convert a Unix epoch-millisecond timestamp to an ISO 8601 string."""
    if not isinstance(value, (int, float)) or value <= 0:
        return None
    from datetime import datetime, timezone

    try:
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat()
    except (OSError, ValueError, OverflowError):
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


def _normalize_exact_page(
    *,
    url: str,
    title: str,
    html: str,
    markdown: str,
    content: str,
    retrieval_method: str,
    fallback_used: bool,
    allow_empty_content: bool,
) -> dict | None:
    normalized_html = (html or "").strip()
    normalized_markdown = (markdown or "").strip()
    normalized_content = _normalize_text(content or "")

    if not normalized_content and normalized_markdown:
        normalized_content = _normalize_text(normalized_markdown)
    if not normalized_content and normalized_html:
        normalized_content = _normalize_text(_strip_tags(normalized_html))

    if not normalized_html and not normalized_markdown and not normalized_content:
        return None
    if not normalized_content and not allow_empty_content:
        return None

    return {
        "url": url,
        "title": title.strip(),
        "content": normalized_content,
        "html": normalized_html,
        "markdown": normalized_markdown,
        "retrieval_method": retrieval_method,
        "fallback_used": fallback_used,
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


def _workday_company_slug(host: str) -> str | None:
    host_parts = [part for part in (host or "").lower().split(".") if part]
    if len(host_parts) >= 4 and host_parts[-2:] == ["myworkdayjobs", "com"]:
        return host_parts[0]
    return _domain_root(host) or None


def _workday_page_matches(parsed: ParsedATSJobURL, page: dict) -> bool:
    page_url = str(page.get("url") or "").strip()
    page_host = urlparse(page_url).netloc.lower() if page_url else ""
    html = page.get("html") or ""
    canonical_url = _extract_canonical_link(html)
    canonical_host = urlparse(canonical_url).netloc.lower() if canonical_url else ""
    if canonical_host.endswith(".myworkdayjobs.com"):
        return True

    return page_host.endswith(".myworkdayjobs.com") and _extract_json_ld_job(html) is not None


def _workday_company_name(raw_name: str | None, parsed: ParsedATSJobURL) -> str:
    brand_name = _display_company_slug(parsed.company_slug, raw_name=raw_name)
    if raw_name and brand_name:
        cleaned_raw = raw_name.strip()
        if cleaned_raw and cleaned_raw.lower() == brand_name.lower():
            return cleaned_raw
        raw_tokens = [
            token
            for token in re.findall(r"[a-z0-9]+", cleaned_raw.lower())
            if not token.isdigit() and token not in WORKDAY_COMPANY_NOISE_TOKENS
        ]
        normalized_raw = " ".join(raw_tokens).strip()
        normalized_brand = re.sub(r"[^a-z0-9]+", " ", brand_name.lower()).strip()
        if normalized_brand:
            brand_tokens = normalized_brand.split()
            if normalized_raw == normalized_brand:
                return brand_name
            if raw_tokens[:len(brand_tokens)] == brand_tokens and len(raw_tokens) > len(brand_tokens):
                return " ".join(token.capitalize() for token in raw_tokens)
            if normalized_brand in normalized_raw:
                return brand_name

    return raw_name.strip() if raw_name else brand_name


def _workday_location_from_json_ld(job_posting: dict) -> str | None:
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
        if not isinstance(address, dict):
            continue

        locality = str(address.get("addressLocality") or "").strip()
        region = str(address.get("addressRegion") or "").strip()
        country = str(address.get("addressCountry") or "").strip()

        city = locality
        if locality:
            locality_parts = [part.strip() for part in locality.split(",") if part.strip()]
            if len(locality_parts) >= 3 and len(locality_parts[0]) <= 3:
                city = locality_parts[-1]
                if not region:
                    region = locality_parts[-2]
            elif len(locality_parts) == 2:
                city = locality_parts[-1]
                if not region:
                    region = locality_parts[0]

        if country == "United States of America":
            country = "United States"

        parts = [city, region, country]
        joined = ", ".join(part for part in parts if part)
        if joined:
            formatted.append(joined)

    return " | ".join(dict.fromkeys(formatted)) or None


def _normalize_workday_job(parsed: ParsedATSJobURL, page: dict) -> dict | None:
    if not _workday_page_matches(parsed, page):
        return None

    html = page.get("html") or ""
    canonical_url = _extract_canonical_link(html) or parsed.canonical_url
    json_ld = _extract_json_ld_job(html)

    if json_ld:
        raw_company_name = _json_ld_company(json_ld, parsed.host)
        title = _normalize_text(json_ld.get("title"))
        company_name = _workday_company_name(raw_company_name, parsed)
        description = _normalize_text(_strip_tags(str(json_ld.get("description") or "")))
        employment_type = json_ld.get("employmentType")
        if isinstance(employment_type, list):
            employment_type_value = ", ".join(
                str(item).strip() for item in employment_type if str(item).strip()
            )
        else:
            employment_type_value = str(employment_type).strip() if employment_type else None

        identifier = json_ld.get("identifier")
        identifier_value = identifier.get("value") if isinstance(identifier, dict) else None
        external_id = parsed.external_id or (f"wd_{identifier_value}" if identifier_value else None)

        if title and company_name and canonical_url:
            return {
                "external_id": external_id,
                "title": title,
                "company_name": company_name,
                "location": _workday_location_from_json_ld(json_ld),
                "remote": str(json_ld.get("jobLocationType") or "").upper() == "TELECOMMUTE"
                or "remote" in f"{title} {description}".lower(),
                "url": canonical_url,
                "description": description or None,
                "employment_type": employment_type_value,
                "posted_at": _coerce_posted_at(json_ld.get("datePosted")),
                "source": "workday",
                "ats": "workday",
                "ats_slug": parsed.company_slug or _workday_company_slug(parsed.host),
            }

    company_name = _workday_company_name(None, parsed)
    raw_title = _extract_meta_content(html, "og:title") or page.get("title") or _extract_heading(html)
    title = _cleanup_generic_title(raw_title, company_name=company_name)
    if not title or not company_name or not canonical_url:
        return None

    description = _normalize_text(
        _extract_meta_content(html, "description")
        or _extract_meta_content(html, "og:description")
        or (page.get("content") or "")[:4000]
    )

    return {
        "external_id": parsed.external_id,
        "title": title,
        "company_name": company_name,
        "location": None,
        "remote": "remote" in f"{title} {description}".lower(),
        "url": canonical_url,
        "description": description or None,
        "employment_type": None,
        "posted_at": None,
        "source": "workday",
        "ats": "workday",
        "ats_slug": parsed.company_slug or _workday_company_slug(parsed.host),
    }


async def _fetch_direct_exact_page(
    url: str,
    *,
    timeout_seconds: int = 20,
    allow_empty_content: bool = False,
) -> dict | None:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
    }

    try:
        async with httpx.AsyncClient(timeout=timeout_seconds, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
    except httpx.HTTPError:
        return None

    body = resp.text
    content_type = (resp.headers.get("content-type") or "").lower()
    html = body if "html" in content_type or "<html" in body.lower() else ""

    return _normalize_exact_page(
        url=str(resp.url),
        title=_extract_title(html) if html else "",
        html=html,
        markdown="",
        content="" if html else body.strip(),
        retrieval_method="direct",
        fallback_used=False,
        allow_empty_content=allow_empty_content,
    )


async def _fetch_exact_page_candidates(
    parsed: ParsedATSJobURL,
    *,
    allow_empty_content: bool = False,
) -> list[dict]:
    url = parsed.canonical_url or ""
    pages: list[dict] = []

    direct_page = await _fetch_direct_exact_page(
        url,
        timeout_seconds=20,
        allow_empty_content=allow_empty_content,
    )
    if direct_page:
        pages.append(direct_page)

    crawl4ai_page = await crawl4ai_client.fetch_url(url, timeout_seconds=20)
    if crawl4ai_page:
        crawl4ai_page["fallback_used"] = bool(pages)
        pages.append(crawl4ai_page)

    firecrawl_page = await firecrawl_client.scrape_url(url, timeout_seconds=20)
    if firecrawl_page:
        firecrawl_page["fallback_used"] = bool(pages)
        pages.append(firecrawl_page)

    return pages


async def _probe_workday_job_redirect(parsed: ParsedATSJobURL) -> str | None:
    url = parsed.canonical_url or ""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
    }

    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
            resp = await client.get(url, headers=headers)
    except httpx.HTTPError:
        return None

    if resp.status_code not in {301, 302, 303, 307, 308}:
        return None

    location = str(resp.headers.get("location") or "").strip().lower()
    if not location:
        return "redirected"
    if "wday/drs/outage" in location or "community.workday.com/maintenance-page" in location:
        return "outage"
    return "redirected"


async def _fetch_exact_job_with_normalizer(
    parsed: ParsedATSJobURL,
    *,
    normalizer: Callable[[ParsedATSJobURL, dict], dict | None],
    error_message: str,
    allow_empty_content: bool = False,
) -> list[dict]:
    pages = await _fetch_exact_page_candidates(parsed, allow_empty_content=allow_empty_content)
    if not pages:
        raise ExactJobFetchError("Could not read the job posting page.")

    for page in pages:
        job = normalizer(parsed, page)
        if job:
            return [job]

    raise ExactJobFetchError(error_message)


async def _fetch_workable_exact_job(parsed: ParsedATSJobURL) -> list[dict]:
    if not parsed.company_slug or not parsed.external_id:
        raise ExactJobFetchError("Could not resolve the Workable job URL.")
    return await search_workable(
        parsed.company_slug,
        job_shortcode=parsed.external_id.removeprefix("wk_"),
    )


async def _fetch_apple_exact_job(parsed: ParsedATSJobURL) -> list[dict]:
    return await _fetch_exact_job_with_normalizer(
        parsed,
        normalizer=_normalize_apple_job,
        error_message="We found the Apple job page, but couldn't extract enough job details from it.",
        allow_empty_content=True,
    )


async def _fetch_workday_exact_job(parsed: ParsedATSJobURL) -> list[dict]:
    redirect_status = await _probe_workday_job_redirect(parsed)
    pages = await _fetch_exact_page_candidates(parsed, allow_empty_content=True)
    candidate_pages = [page for page in pages if _workday_page_matches(parsed, page)]

    if not candidate_pages:
        if redirect_status == "outage":
            raise ExactJobFetchError("Workday is currently unavailable for this job posting.")
        if redirect_status == "redirected":
            raise ExactJobFetchError(
                "Workday redirected away from the job details, so we couldn't extract the posting."
            )
        raise ExactJobFetchError("Could not read the job posting page.")

    for page in candidate_pages:
        job = _normalize_workday_job(parsed, page)
        if job:
            return [job]

    raise ExactJobFetchError("We found the Workday job page, but couldn't extract enough job details from it.")


async def _fetch_generic_exact_job(parsed: ParsedATSJobURL) -> list[dict]:
    return await _fetch_exact_job_with_normalizer(
        parsed,
        normalizer=lambda parsed_job, page: _normalize_generic_exact_job(page, parsed_job),
        error_message="We found the page, but couldn't extract enough job details from it.",
        allow_empty_content=True,
    )


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
    if len(path_parts) == 1:
        return ParsedATSJobURL(
            ats_type="greenhouse",
            company_slug=path_parts[0],
            external_id=None,
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


def _parse_workday_url(job_url: str) -> ParsedATSJobURL | None:
    parsed = urlparse((job_url or "").strip())
    host = parsed.netloc.lower()
    if not host.endswith(".myworkdayjobs.com"):
        return None

    path_parts = [part for part in parsed.path.split("/") if part]
    if "job" not in path_parts or not path_parts:
        return None

    company_slug = _workday_company_slug(host)
    if not company_slug:
        return None

    job_segment = path_parts[-1]
    token_match = WORKDAY_JOB_TOKEN_RE.search(job_segment)
    token = token_match.group("token") if token_match else None

    return ParsedATSJobURL(
        ats_type="workday",
        company_slug=company_slug,
        external_id=f"wd_{token}" if token else None,
        canonical_url=_clean_url(job_url),
        host=host,
        exact_url_only=True,
    )


def _parse_icims_url(job_url: str) -> ParsedATSJobURL | None:
    """Parse iCIMS job URLs like university-uber.icims.com/jobs/158009/job."""
    parsed = urlparse((job_url or "").strip())
    host = parsed.netloc.lower()
    if ".icims.com" not in host:
        return None
    # Extract company slug from subdomain: "university-uber.icims.com" → "uber"
    subdomain = host.replace(".icims.com", "")
    # Many iCIMS subdomains have a prefix like "university-", "careers-", etc.
    # Try to extract the company name from the last segment after a hyphen
    slug_parts = subdomain.split("-")
    company_slug = slug_parts[-1] if slug_parts else subdomain

    # Extract job ID from path: /jobs/158009/... → "158009"
    path_parts = [part for part in parsed.path.split("/") if part]
    external_id: str | None = None
    if len(path_parts) >= 2 and path_parts[0] == "jobs":
        external_id = f"icims_{path_parts[1]}"

    return ParsedATSJobURL(
        ats_type="icims",
        company_slug=company_slug,
        external_id=external_id,
        canonical_url=_clean_url(job_url),
        host=host,
        exact_url_only=True,
    )


def _normalize_icims_job(parsed: ParsedATSJobURL, page: dict) -> dict | None:
    """Normalize an iCIMS job page.

    iCIMS pages include JSON-LD with JobPosting schema, but the
    ``hiringOrganization.name`` is often "UNAVAILABLE".  We fall back
    to extracting the company name from the iCIMS subdomain.
    """
    html = page.get("html") or ""
    json_ld = _extract_json_ld_job(html)

    # Try JSON-LD first for structured fields
    if json_ld:
        ld_company = (
            (json_ld.get("hiringOrganization") or {}).get("name") or ""
        ).strip()
        # iCIMS often returns "UNAVAILABLE" — fall back to subdomain
        if not ld_company or ld_company.upper() == "UNAVAILABLE":
            ld_company = _display_company_slug(parsed.company_slug)
        json_ld_copy = dict(json_ld)
        if "hiringOrganization" in json_ld_copy:
            if isinstance(json_ld_copy["hiringOrganization"], dict):
                json_ld_copy["hiringOrganization"]["name"] = ld_company
            else:
                json_ld_copy["hiringOrganization"] = {"@type": "Organization", "name": ld_company}
        else:
            json_ld_copy["hiringOrganization"] = {"@type": "Organization", "name": ld_company}

        result = _normalize_json_ld_job(parsed, json_ld_copy)
        if result:
            result["source"] = "icims"
            result["ats"] = "icims"
            return result

    # Fallback: HTML parsing (same as generic_exact but with better company name)
    company_name = _display_company_slug(parsed.company_slug) or _generic_company_name(page, parsed)
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
        "source": "icims",
        "ats": "icims",
        "ats_slug": parsed.company_slug or _domain_root(parsed.host),
    }


async def _fetch_icims_exact_job(parsed: ParsedATSJobURL) -> list[dict]:
    return await _fetch_exact_job_with_normalizer(
        parsed,
        normalizer=_normalize_icims_job,
        error_message="We found the iCIMS job page, but couldn't extract enough job details from it.",
        allow_empty_content=True,
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
            "posted_at": j.get("updated_at") or None,
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
            "posted_at": _epoch_ms_to_iso(p.get("createdAt")),
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
            "posted_at": j.get("publishedAt") or None,
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
            "posted_at": raw_job.get("published") or None,
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
    ATSAdapter("workday", _parse_workday_url, fetch_exact=_fetch_workday_exact_job),
    ATSAdapter("icims", _parse_icims_url, fetch_exact=_fetch_icims_exact_job),
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
