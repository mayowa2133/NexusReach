"""Raw ATS page payload to normalized job dict converters."""

from __future__ import annotations

import re
from urllib.parse import urlparse


from app.utils.job_metadata import parse_json_ld_base_salary
from app.clients.ats.html import _coerce_posted_at, _display_company_slug, _domain_root, _extract_canonical_link, _extract_heading, _extract_json_ld_job, _extract_meta_content, _extract_static_router_payload, _host_ats_label, _json_ld_company, _json_ld_location, _normalize_text, _string_list, _strip_tags, _workday_company_slug
from app.clients.ats.urls import ParsedATSJobURL




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
    salary = parse_json_ld_base_salary(job_posting.get("baseSalary"))

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
        "work_mode": "remote" if remote else None,
        "url": parsed.canonical_url,
        "apply_url": parsed.canonical_url,
        "description": description or None,
        "employment_type": employment_type_value,
        "posted_at": _coerce_posted_at(job_posting.get("datePosted")),
        "salary_min": salary.minimum if salary else None,
        "salary_max": salary.maximum if salary else None,
        "salary_currency": salary.currency if salary else None,
        "salary_period": salary.period if salary else None,
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


def _company_name_from_keywords(html: str) -> str:
    """Extract company name from keywords meta tag.

    Many career sites include the company name as the first keyword,
    e.g. ``<meta name="keywords" content="ByteDance, Job, Careers...">``.
    Only returns a candidate when the first keyword looks like a proper
    company name (title-cased or all-caps, 2+ chars, no generic words).
    """
    raw = _extract_meta_content(html, "keywords")
    if not raw:
        return ""
    first = raw.split(",")[0].strip()
    if not first or len(first) < 2 or len(first) > 40:
        return ""
    # Reject generic leading keywords that aren't company names
    generic = {
        "jobs", "job", "careers", "career", "hiring", "employment",
        "work", "apply", "openings", "opportunities", "vacancy",
        "remote", "software", "engineering", "developer",
    }
    if first.lower() in generic:
        return ""
    # Require at least one uppercase letter (proper name signal)
    if first == first.lower():
        return ""
    return first


def _generic_company_name(page: dict, parsed: ParsedATSJobURL) -> str:
    html = page.get("html") or ""
    candidates = [
        _extract_meta_content(html, "og:site_name"),
        _extract_meta_content(html, "application-name"),
        _company_name_from_keywords(html),
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
        "apply_url": parsed.canonical_url,
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
        "apply_url": parsed.canonical_url,
        "description": _apple_description(jobs_data),
        "employment_type": _normalize_text(jobs_data.get("employmentType")) or _normalize_text(jobs_data.get("jobType")) or None,
        "posted_at": _coerce_posted_at(jobs_data.get("postDateInGMT") or jobs_data.get("postingDate")),
        "source": "apple_jobs",
        "ats": "apple_jobs",
        "ats_slug": "apple",
        "department": ", ".join(team_names) or None,
    }




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
        remote = str(json_ld.get("jobLocationType") or "").upper() == "TELECOMMUTE"
        salary = parse_json_ld_base_salary(json_ld.get("baseSalary"))

        if title and company_name and canonical_url:
            return {
                "external_id": external_id,
                "title": title,
                "company_name": company_name,
                "location": _workday_location_from_json_ld(json_ld),
                "remote": remote or "remote" in f"{title} {description}".lower(),
                "work_mode": "remote" if remote else None,
                "url": canonical_url,
                "apply_url": canonical_url,
                "description": description or None,
                "employment_type": employment_type_value,
                "posted_at": _coerce_posted_at(json_ld.get("datePosted")),
                "salary_min": salary.minimum if salary else None,
                "salary_max": salary.maximum if salary else None,
                "salary_currency": salary.currency if salary else None,
                "salary_period": salary.period if salary else None,
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
        "apply_url": canonical_url,
        "description": description or None,
        "employment_type": None,
        "posted_at": None,
        "source": "workday",
        "ats": "workday",
        "ats_slug": parsed.company_slug or _workday_company_slug(parsed.host),
    }


def _job_richness_score(job: dict) -> int:
    """Score how much useful content a normalized job dict contains.

    Higher = richer.  Used to pick the best result when multiple page
    candidates (direct, Crawl4AI, Firecrawl) all produce a valid job.
    """
    score = 0
    desc = job.get("description") or ""
    score += min(len(desc), 4000)  # description length up to cap
    if job.get("location"):
        score += 200
    if job.get("company_name") and job["company_name"] != _domain_root("").title():
        score += 100
    return score


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
        "apply_url": parsed.canonical_url,
        "description": description or None,
        "employment_type": None,
        "posted_at": None,
        "source": "icims",
        "ats": "icims",
        "ats_slug": parsed.company_slug or _domain_root(parsed.host),
    }
