"""Workday bulk job search client.

Workday careers sites expose a hidden JSON search API that the frontend JS
calls.  The endpoint format is:

    POST https://{company}.{wd}.myworkdayjobs.com/wday/cxs/{company}/{site}/jobs

This client queries that API for curated companies to bulk-discover jobs.
"""

import asyncio
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
    {"label": "Visa", "company": "visa", "wd": "wd5", "site": "Visa"},
    {"label": "Adobe", "company": "adobe", "wd": "wd5", "site": "external_experienced"},
    {"label": "Broadcom", "company": "broadcom", "wd": "wd1", "site": "External_Career"},
    {"label": "Target", "company": "target", "wd": "wd5", "site": "targetcareers"},
    {"label": "Capital One", "company": "capitalone", "wd": "wd12", "site": "Capital_One"},
    {"label": "Netflix", "company": "netflix", "wd": "wd108", "site": "Netflix"},
    {"label": "Cisco", "company": "cisco", "wd": "wd5", "site": "Cisco_Careers"},
    {"label": "Walmart", "company": "walmart", "wd": "wd504", "site": "WalmartExternal"},
    {"label": "Zoom", "company": "zoom", "wd": "wd5", "site": "Zoom"},
    {"label": "Workday", "company": "workday", "wd": "wd5", "site": "Workday"},
    {"label": "Intel", "company": "intel", "wd": "wd1", "site": "External"},
    {"label": "CrowdStrike", "company": "crowdstrike", "wd": "wd5", "site": "CrowdStrikeCareers"},
    {"label": "Autodesk", "company": "autodesk", "wd": "wd1", "site": "Ext"},
    {"label": "Snap", "company": "snapchat", "wd": "wd1", "site": "snap"},
    {"label": "PayPal", "company": "paypal", "wd": "wd1", "site": "jobs"},
    {"label": "HP", "company": "hp", "wd": "wd5", "site": "ExternalCareerSite"},
    {"label": "Accenture", "company": "accenture", "wd": "wd103", "site": "AccentureCareers"},
]
# Removed 2026-06: ServiceNow, Qualcomm, Dell, Intuit, IBM, Palo Alto Networks,
# Deloitte (deloitteus). Their tenants now return total=0 / HTTP 422 to the
# anonymous bulk cxs search (jobs still render on individual pages, but the bulk
# facet is disabled), so they are unharvestable through this client. Re-run
# scripts/verify_workday_boards.py to recover them if the bulk API reopens.


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
    {"label": "Mass General Brigham", "company": "massgeneralbrigham", "wd": "wd1", "site": "MGBExternal", "vertical": "healthcare"},
    {"label": "Intermountain Health", "company": "imh", "wd": "wd108", "site": "IntermountainCareers", "vertical": "healthcare"},
    {"label": "Advocate Health", "company": "aah", "wd": "wd5", "site": "external", "vertical": "healthcare"},
    {"label": "Geisinger", "company": "geisinger", "wd": "wd5", "site": "GeisingerExternal", "vertical": "healthcare"},
    {"label": "Memorial Hermann", "company": "memorialhermann", "wd": "wd5", "site": "external", "vertical": "healthcare"},
    {"label": "UMass Memorial Health", "company": "ummh", "wd": "wd1", "site": "Careers", "vertical": "healthcare"},
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
    {"label": "Dollar Tree", "company": "dollartree", "wd": "wd5", "site": "dollartreeus", "vertical": "retail"},
    {"label": "Advance Auto Parts", "company": "advanceauto", "wd": "wd5", "site": "AdvanceExternalCareers", "vertical": "retail"},
    {"label": "Meijer", "company": "meijer", "wd": "wd5", "site": "Meijer_Stores_Hourly", "vertical": "retail"},
    {"label": "Gap Inc", "company": "gapinc", "wd": "wd1", "site": "GAPINC", "vertical": "retail"},
    {"label": "Williams-Sonoma", "company": "williams", "wd": "wd5", "site": "External", "vertical": "retail"},
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
            try:
                data = resp.json()
            except ValueError:
                # A 200 with an empty/HTML body (tenant in maintenance, anti-bot
                # challenge, or a config that no longer serves JSON). Benign for a
                # best-effort crawl — break like a non-200 instead of raising a
                # JSONDecodeError that the caller logs to Sentry as an error.
                logger.debug("Workday non-JSON body for %s/%s", company, site)
                break
            if not isinstance(data, dict):
                break
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


# ---------------------------------------------------------------------------
# Config drift verification + auto-repair
#
# Workday tenants migrate occasionally (the ``wd`` tier or, less often, the
# site name changes). A drifted config returns nothing and the feed silently
# loses that employer. These helpers make drift detectable: probe each config,
# and when the configured tier is dead, try the other known tiers with the same
# site name (which catches the common "tenant moved tiers" case). Used by the
# scheduled health-check task and by scripts/verify_workday_boards.py.
# ---------------------------------------------------------------------------

# All Workday tier subdomains seen across tenants, ordered by prevalence.
_REPAIR_WD_TIERS = (
    "wd1", "wd5", "wd3", "wd2", "wd10", "wd12",
    "wd103", "wd108", "wd501", "wd502", "wd503", "wd504", "wd505",
)


async def _probe_config(company: str, wd: str, site: str) -> int | None:
    """Return the live job total for a config, or None if dead/erroring."""
    url = f"https://{company}.{wd}.myworkdayjobs.com/wday/cxs/{company}/{site}/jobs"
    body = {"limit": 1, "offset": 0, "appliedFacets": {}}
    try:
        async with httpx.AsyncClient(timeout=12, follow_redirects=True) as client:
            resp = await client.post(url, json=body, headers=_HEADERS)
        if resp.status_code != 200:
            return None
        data = resp.json()
        if data.get("jobPostings"):
            return int(data.get("total", 0) or 0)
        return None
    except Exception:
        return None


async def verify_workday_config(entry: dict[str, str], *, repair: bool = True) -> dict:
    """Verify one Workday config against the live API, optionally auto-repairing.

    Returns a status dict:
      - ``status="ok"``        config returns jobs (``total``)
      - ``status="repaired"``  configured tier dead, an alternate tier works
                               (``wd`` = working tier, ``old_wd`` = configured)
      - ``status="dead"``      no tier returns jobs for this site
    """
    label = entry.get("label", entry.get("company", "?"))
    company, wd, site = entry["company"], entry["wd"], entry["site"]
    total = await _probe_config(company, wd, site)
    if total is not None:
        return {"label": label, "company": company, "site": site, "wd": wd,
                "vertical": entry.get("vertical"), "status": "ok", "total": total}
    if repair:
        for alt in _REPAIR_WD_TIERS:
            if alt == wd:
                continue
            alt_total = await _probe_config(company, alt, site)
            if alt_total is not None:
                return {"label": label, "company": company, "site": site,
                        "wd": alt, "old_wd": wd, "vertical": entry.get("vertical"),
                        "status": "repaired", "total": alt_total}
    return {"label": label, "company": company, "site": site, "wd": wd,
            "vertical": entry.get("vertical"), "status": "dead", "total": 0}


async def verify_all_workday(
    registry: list[dict[str, str]] | None = None,
    *,
    repair: bool = True,
    concurrency: int = 6,
) -> list[dict]:
    """Verify every config in a registry (defaults to tech + non-tech)."""
    entries = (
        registry
        if registry is not None
        else [*WORKDAY_COMPANIES, *WORKDAY_NONTECH_COMPANIES]
    )
    sem = asyncio.Semaphore(concurrency)

    async def run(entry: dict[str, str]) -> dict:
        async with sem:
            return await verify_workday_config(entry, repair=repair)

    return await asyncio.gather(*(run(e) for e in entries))
