"""ATS job URL parsing into ParsedATSJobURL metadata."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse


from app.utils.url_safety import is_safe_public_url
from app.clients.ats.html import WORKDAY_JOB_TOKEN_RE, _clean_url, _domain_root, _workday_company_slug


@dataclass(frozen=True)
class ParsedATSJobURL:
    """Normalized ATS job URL metadata."""

    ats_type: str
    company_slug: str | None
    external_id: str | None = None
    canonical_url: str | None = None
    host: str = ""
    exact_url_only: bool = False


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


def _parse_generic_exact_url(job_url: str) -> ParsedATSJobURL | None:
    parsed = urlparse((job_url or "").strip())
    host = parsed.netloc.lower()
    if parsed.scheme not in {"http", "https"} or not host:
        return None
    # Block SSRF at the user entry point: the generic adapter accepts arbitrary
    # hosts, so reject private/loopback/link-local/metadata targets before the
    # server ever fetches them (audit pass-2 P4).
    if not is_safe_public_url(job_url):
        return None
    return ParsedATSJobURL(
        ats_type="generic_exact",
        company_slug=_domain_root(host) or None,
        canonical_url=_clean_url(job_url),
        host=host,
        exact_url_only=True,
    )
