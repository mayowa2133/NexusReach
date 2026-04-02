"""Workday bulk job search client.

Workday careers sites expose a hidden JSON search API that the frontend JS
calls.  The endpoint format is:

    POST https://{company}.{wd}.myworkdayjobs.com/wday/cxs/{company}/{site}/jobs

This client queries that API for curated companies to bulk-discover jobs.
"""

import logging

import httpx

logger = logging.getLogger(__name__)

_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
}


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
]


async def search_workday(
    company: str,
    wd: str,
    site: str,
    label: str,
    search_text: str = "",
    limit: int = 20,
) -> list[dict]:
    """Fetch jobs from a Workday careers site's hidden JSON API."""
    url = f"https://{company}.{wd}.myworkdayjobs.com/wday/cxs/{company}/{site}/jobs"
    body: dict = {"limit": min(limit, 20), "offset": 0, "appliedFacets": {}}
    if search_text:
        body["searchText"] = search_text

    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        resp = await client.post(url, json=body, headers=_HEADERS)
        if resp.status_code != 200:
            logger.debug("Workday %d for %s/%s", resp.status_code, company, site)
            return []

    data = resp.json()
    postings = data.get("jobPostings", [])
    base_url = f"https://{company}.{wd}.myworkdayjobs.com"

    jobs: list[dict] = []
    for p in postings:
        title = p.get("title", "")
        if not title:
            continue

        external_path = p.get("externalPath", "")
        job_url = f"{base_url}/en-US{external_path}" if external_path else ""
        bullet_fields = p.get("bulletFields", [])
        posted_on = bullet_fields[0] if bullet_fields else ""

        # Clean up "Posted 30+ Days Ago" style strings
        posted_at = ""
        if "posted" in posted_on.lower():
            posted_at = ""  # Workday doesn't give exact dates in bulk

        jobs.append({
            "external_id": f"wd_{external_path.split('/')[-1]}" if external_path else "",
            "title": title,
            "company_name": label,
            "location": p.get("locationsText", ""),
            "remote": "remote" in (p.get("locationsText", "") + title).lower(),
            "url": job_url,
            "description": "",
            "posted_at": posted_at,
            "source": "workday",
            "ats": "workday",
        })

        if len(jobs) >= limit:
            break

    logger.info("Workday %s: %d jobs (of %d total)", label, len(jobs), data.get("total", 0))
    return jobs


async def discover_all_workday(
    search_text: str = "",
    limit_per_company: int = 20,
) -> list[dict]:
    """Query all curated Workday companies and return combined results."""
    all_jobs: list[dict] = []
    for entry in WORKDAY_COMPANIES:
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
