"""Workday bulk job search client.

Workday careers sites expose a hidden JSON search API that the frontend JS
calls.  The endpoint format is:

    POST https://{company}.{wd}.myworkdayjobs.com/wday/cxs/{company}/{site}/jobs

This client queries that API for curated companies to bulk-discover jobs.
"""

import logging
import re
from datetime import datetime, timedelta, timezone

import httpx

logger = logging.getLogger(__name__)

_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
}
_DAYS_RE = re.compile(r"(\d+)\s*(?:\+\s*)?days?\s*ago", re.IGNORECASE)


def _parse_posted_on(raw: str) -> str | None:
    """Convert Workday relative date strings to approximate ISO 8601 timestamps.

    Known values: "Posted Today", "Posted Yesterday",
    "Posted 5 Days Ago", "Posted 30+ Days Ago".
    """
    if not raw:
        return None
    text = raw.lower().strip()
    now = datetime.now(timezone.utc)

    if "today" in text:
        return now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    if "yesterday" in text:
        dt = now - timedelta(days=1)
        return dt.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()

    m = _DAYS_RE.search(text)
    if m:
        days = int(m.group(1))
        dt = now - timedelta(days=days)
        return dt.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()

    return None


# Each entry defines how to reach a company's Workday careers API.
# Fields: label (display name), company, wd (subdomain tier), site (board name)
WORKDAY_COMPANIES: list[dict[str, str]] = [
    {"label": "Salesforce", "company": "salesforce", "wd": "wd12", "site": "External_Career_Site"},
    {"label": "NVIDIA", "company": "nvidia", "wd": "wd5", "site": "NVIDIAExternalCareerSite"},
    {"label": "Visa", "company": "visa", "wd": "wd5", "site": "Visa_Careers"},
    {"label": "Adobe", "company": "adobe", "wd": "wd5", "site": "external_experienced"},
    {"label": "ServiceNow", "company": "servicenow", "wd": "wd1", "site": "Careers"},
    {"label": "Qualcomm", "company": "qualcomm", "wd": "wd5", "site": "External"},
    {"label": "VMware", "company": "broadcom", "wd": "wd1", "site": "VMwareCareers"},
    {"label": "Target", "company": "target", "wd": "wd5", "site": "targetcareers"},
    {"label": "Capital One", "company": "capitalone", "wd": "wd1", "site": "Capital_One"},
    {"label": "Deloitte", "company": "deloitteus", "wd": "wd1", "site": "deloitteus"},
    {"label": "Netflix", "company": "netflix", "wd": "wd1", "site": "Netflix"},
    {"label": "Cisco", "company": "cisco", "wd": "wd5", "site": "Cisco_Careers"},
    {"label": "Walmart", "company": "walmart", "wd": "wd5", "site": "WalmartExternal"},
    {"label": "Zoom", "company": "zoom", "wd": "wd5", "site": "Zoom"},
    {"label": "Workday", "company": "workday", "wd": "wd5", "site": "Workday"},
    {"label": "Intel", "company": "intel", "wd": "wd1", "site": "External"},
    {"label": "Dell", "company": "dell", "wd": "wd1", "site": "External"},
    {"label": "CrowdStrike", "company": "crowdstrike", "wd": "wd5", "site": "CrowdStrikeCareers"},
    {"label": "Autodesk", "company": "autodesk", "wd": "wd1", "site": "Ext"},
    {"label": "Snap", "company": "snapchat", "wd": "wd1", "site": "snap"},
    {"label": "PayPal", "company": "paypal", "wd": "wd1", "site": "jobs"},
    {"label": "Intuit", "company": "intuit", "wd": "wd1", "site": "Intuit"},
    {"label": "Palo Alto Networks", "company": "paloaltonetworks", "wd": "wd1", "site": "Careers"},
    {"label": "HP", "company": "hp", "wd": "wd5", "site": "ExternalCareerSite"},
    {"label": "IBM", "company": "ibm", "wd": "wd5", "site": "External"},
    {"label": "Accenture", "company": "accenture", "wd": "wd3", "site": "AccentureCareers"},
]


# Curated NON-TECH employers, the vertical analog of the tech ATS boards. These
# are large hospitals/health systems, universities, banks/insurers, and
# retailers that run their careers site on Workday. Every config below was
# live-verified against the Workday jobs API (returns postings); a wrong
# wd-tier or site name silently returns nothing, so do not add unverified
# entries. The ``vertical`` field routes each employer to the occupations that
# actually hire there (see ``job_service.OCCUPATION_VERTICALS``).
WORKDAY_NONTECH_COMPANIES: list[dict[str, str]] = [
    # Higher education (universities hire across every non-tech function)
    {"label": "Penn State University", "company": "psu", "wd": "wd1", "site": "PSU_Staff", "vertical": "education"},
    {"label": "University of Southern California", "company": "usc", "wd": "wd5", "site": "ExternalUSCCareers", "vertical": "education"},
    {"label": "University of Pennsylvania", "company": "upenn", "wd": "wd1", "site": "careers-at-penn", "vertical": "education"},
    {"label": "Northeastern University", "company": "northeastern", "wd": "wd1", "site": "careers", "vertical": "education"},
    {"label": "Carnegie Mellon University", "company": "cmu", "wd": "wd5", "site": "CMU", "vertical": "education"},
    {"label": "Cornell University", "company": "cornell", "wd": "wd1", "site": "CornellCareerPage", "vertical": "education"},
    {"label": "Georgetown University", "company": "georgetown", "wd": "wd1", "site": "Georgetown_Admin_Careers", "vertical": "education"},
    {"label": "Brown University", "company": "brown", "wd": "wd5", "site": "staff-careers-brown", "vertical": "education"},
    # Health systems (nursing + allied health + clinical operations)
    {"label": "Sentara Health", "company": "sentara", "wd": "wd1", "site": "SCS", "vertical": "healthcare"},
    {"label": "Trinity Health", "company": "trinityhealth", "wd": "wd1", "site": "Jobs", "vertical": "healthcare"},
    {"label": "Banner Health", "company": "bannerhealth", "wd": "wd108", "site": "Careers", "vertical": "healthcare"},
    {"label": "Vanderbilt University Medical Center", "company": "vumc", "wd": "wd1", "site": "vumccareers", "vertical": "healthcare"},
    # Banks / insurers (finance, accounting, actuarial, sales, ops)
    {"label": "PNC", "company": "pnc", "wd": "wd5", "site": "External", "vertical": "finance"},
    {"label": "State Street", "company": "statestreet", "wd": "wd1", "site": "Global", "vertical": "finance"},
    {"label": "Truist", "company": "truist", "wd": "wd1", "site": "Careers", "vertical": "finance"},
    {"label": "Prudential", "company": "prudential", "wd": "wd3", "site": "prudential", "vertical": "finance"},
    {"label": "Allstate", "company": "allstate", "wd": "wd5", "site": "allstate_careers", "vertical": "finance"},
    {"label": "Travelers", "company": "travelers", "wd": "wd5", "site": "External", "vertical": "finance"},
    {"label": "Nationwide", "company": "nationwide", "wd": "wd1", "site": "Nationwide_Career", "vertical": "finance"},
    {"label": "Voya Financial", "company": "godirect", "wd": "wd5", "site": "voya_jobs", "vertical": "finance"},
    # Large retailers (store ops, supply chain, merchandising, sales, support)
    {"label": "Lowe's", "company": "lowes", "wd": "wd5", "site": "LWS_External_CS", "vertical": "retail"},
    {"label": "Nordstrom", "company": "nordstrom", "wd": "wd501", "site": "nordstrom_careers", "vertical": "retail"},
]


async def search_workday(
    company: str,
    wd: str,
    site: str,
    label: str,
    search_text: str = "",
    limit: int = 20,
) -> list[dict]:
    """Fetch jobs from a Workday careers site's hidden JSON API.

    Workday caps each request at 20 postings, so we page through with the
    ``offset`` parameter until we reach ``limit`` or run out (audit M16) —
    large employers (IBM, Salesforce, NVIDIA) have far more than 20 openings.
    """
    url = f"https://{company}.{wd}.myworkdayjobs.com/wday/cxs/{company}/{site}/jobs"
    base_url = f"https://{company}.{wd}.myworkdayjobs.com"
    page_size = 20

    postings: list[dict] = []
    total = 0
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        for offset in range(0, max(limit, 1), page_size):
            body: dict = {"limit": page_size, "offset": offset, "appliedFacets": {}}
            if search_text:
                body["searchText"] = search_text
            resp = await client.post(url, json=body, headers=_HEADERS)
            if resp.status_code != 200:
                logger.debug("Workday %d for %s/%s", resp.status_code, company, site)
                break
            data = resp.json()
            total = data.get("total", total)
            page_postings = data.get("jobPostings", [])
            if not page_postings:
                break
            postings.extend(page_postings)
            if len(postings) >= limit or len(page_postings) < page_size:
                break

    jobs: list[dict] = []
    for p in postings:
        title = p.get("title", "")
        if not title:
            continue

        external_path = p.get("externalPath", "")
        job_url = f"{base_url}/en-US{external_path}" if external_path else ""
        posted_at = _parse_posted_on(p.get("postedOn", ""))

        jobs.append({
            "external_id": f"wd_{external_path.split('/')[-1]}" if external_path else "",
            "title": title,
            "company_name": label,
            "location": p.get("locationsText", ""),
            "remote": "remote" in (p.get("locationsText", "") + title).lower(),
            "url": job_url,
            "apply_url": job_url or None,
            "description": "",
            "posted_at": posted_at,
            "source": "workday",
            "ats": "workday",
        })

        if len(jobs) >= limit:
            break

    logger.info("Workday %s: %d jobs (of %d total)", label, len(jobs), total)
    return jobs


async def discover_workday_companies(
    companies: list[dict[str, str]],
    search_text: str = "",
    limit_per_company: int = 20,
) -> list[dict]:
    """Query a list of Workday company configs and return combined results."""
    all_jobs: list[dict] = []
    for entry in companies:
        try:
            jobs = await search_workday(
                company=entry["company"],
                wd=entry["wd"],
                site=entry["site"],
                label=entry["label"],
                search_text=search_text,
                limit=limit_per_company,
            )
            all_jobs.extend(jobs)
        except Exception:
            logger.exception("Workday fetch failed for %s", entry["label"])
    return all_jobs


async def discover_all_workday(
    search_text: str = "",
    limit_per_company: int = 20,
) -> list[dict]:
    """Query all curated (tech) Workday companies and return combined results."""
    return await discover_workday_companies(
        WORKDAY_COMPANIES, search_text=search_text, limit_per_company=limit_per_company
    )


async def discover_all_nontech_workday(
    search_text: str = "",
    limit_per_company: int = 20,
    verticals: set[str] | None = None,
) -> list[dict]:
    """Query curated non-tech Workday employers, optionally filtered by vertical.

    ``verticals`` (e.g. ``{"healthcare", "finance"}``) restricts the fetch to
    employers in those sectors; ``None`` fetches every non-tech employer (used
    by the preference-matched background refresh).
    """
    companies = WORKDAY_NONTECH_COMPANIES
    if verticals:
        companies = [c for c in companies if c.get("vertical") in verticals]
    return await discover_workday_companies(
        companies, search_text=search_text, limit_per_company=limit_per_company
    )
