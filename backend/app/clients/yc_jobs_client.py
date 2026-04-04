"""Client for Y Combinator Jobs."""

from __future__ import annotations

import html
import json
import logging
import re
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from app.utils.startup_jobs import startup_tags, text_matches_query

logger = logging.getLogger(__name__)

BASE_URL = "https://www.ycombinator.com/jobs"
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}
_CURRENCY_RE = re.compile(r"\b(USD|EUR|GBP|CAD)\b", re.IGNORECASE)
_AMOUNT_RE = re.compile(r"(\d[\d,]{3,})")


def _extract_payload(html_content: str) -> dict:
    soup = BeautifulSoup(html_content or "", "html.parser")
    node = soup.select_one("[data-page]")
    raw_payload = node.get("data-page") if node else None
    if not raw_payload:
        return {}
    try:
        return json.loads(html.unescape(raw_payload))
    except json.JSONDecodeError:
        logger.warning("Failed to decode YC jobs payload")
        return {}


def _parse_salary_range(raw_value: str | None) -> tuple[float | None, float | None, str | None]:
    if not raw_value:
        return None, None, None
    amounts = [float(match.group(1).replace(",", "")) for match in _AMOUNT_RE.finditer(raw_value)]
    if not amounts:
        return None, None, None
    currency_match = _CURRENCY_RE.search(raw_value)
    currency = currency_match.group(1).upper() if currency_match else ("USD" if "$" in raw_value else None)
    minimum = amounts[0]
    maximum = amounts[1] if len(amounts) > 1 else None
    return minimum, maximum, currency


def _normalize_employment_type(raw_value: str | None) -> str | None:
    normalized = str(raw_value or "").strip().lower()
    if not normalized:
        return None
    return normalized.replace(" ", "-")


def _description(job: dict) -> str | None:
    parts: list[str] = []
    one_liner = str(job.get("companyOneLiner") or "").strip()
    if one_liner:
        parts.append(one_liner)

    pretty_role = str(job.get("prettyRole") or "").strip()
    if pretty_role:
        parts.append(f"Role: {pretty_role}")

    skills = [str(skill).strip() for skill in (job.get("skills") or []) if str(skill).strip()]
    if skills:
        parts.append(f"Skills: {', '.join(skills)}")

    min_experience = job.get("minExperience")
    if min_experience not in {None, ""}:
        parts.append(f"Experience: {min_experience}+ years")

    return "\n\n".join(parts) or None


def parse_jobs_page_html(html_content: str, *, query: str | None = None, limit: int = 100) -> list[dict]:
    payload = _extract_payload(html_content)
    postings = ((payload.get("props") or {}).get("jobPostings") or []) if isinstance(payload, dict) else []
    jobs: list[dict] = []

    for job in postings:
        if not isinstance(job, dict):
            continue

        title = str(job.get("title") or "").strip()
        company_name = str(job.get("companyName") or "").strip()
        location = str(job.get("location") or "").strip()
        searchable_text = " ".join(
            part
            for part in [
                title,
                company_name,
                location,
                str(job.get("prettyRole") or ""),
                str(job.get("companyOneLiner") or ""),
                " ".join(str(skill) for skill in (job.get("skills") or [])),
            ]
            if part
        )
        if query and not text_matches_query(text=searchable_text, query=query):
            continue

        salary_min, salary_max, salary_currency = _parse_salary_range(str(job.get("salaryRange") or ""))
        job_url = urljoin(BASE_URL, str(job.get("url") or "").strip())
        jobs.append({
            "external_id": f"yc_{job.get('id')}",
            "title": title,
            "company_name": company_name,
            "company_logo": job.get("companyLogoUrl"),
            "location": location or None,
            "remote": "remote" in location.lower(),
            "url": job_url or None,
            "description": _description(job),
            "employment_type": _normalize_employment_type(job.get("type")),
            "salary_min": salary_min,
            "salary_max": salary_max,
            "salary_currency": salary_currency,
            "posted_at": job.get("lastActive") or job.get("createdAt"),
            "source": "yc_jobs",
            "department": str(job.get("prettyRole") or "").strip() or None,
            "tags": startup_tags("yc_jobs"),
        })
        if len(jobs) >= limit:
            break

    return jobs


async def search_yc_jobs(query: str | None = None, limit: int = 100) -> list[dict]:
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        response = await client.get(BASE_URL, headers=REQUEST_HEADERS)
        response.raise_for_status()
    return parse_jobs_page_html(response.text, query=query, limit=limit)
