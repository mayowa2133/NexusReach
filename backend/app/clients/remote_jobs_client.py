"""Clients for remote/niche job boards — Dice, Remotive, Jobicy, SimplifyJobs."""

import re

import httpx

from app.config import settings


async def search_dice(query: str, location: str | None = None, limit: int = 10) -> list[dict]:
    """Search Dice for tech jobs."""
    params: dict = {
        "q": query,
        "countryCode2": "US",
        "radius": "30",
        "radiusUnit": "mi",
        "page": "1",
        "pageSize": str(min(limit, 20)),
        "fields": "id|jobId|guid|summary|title|postedDate|modifiedDate|jobLocation.displayName|detailsPageUrl|salary|clientBrandId|companyPageUrl|isRemote|employerType",
    }
    if location:
        params["location"] = location

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            "https://job-search-api.svc.dhigroupinc.com/v1/dice/jobs/search",
            params=params,
            headers={"x-api-key": "1YAt0R9wBg4WfsF9VB2778F5CHLAPMVW3WAZcKd8"},
        )
        if resp.status_code != 200:
            return []
        data = resp.json()

    jobs = data.get("data", [])[:limit]
    return [
        {
            "external_id": f"dice_{j.get('id', '')}",
            "title": j.get("title", ""),
            "company_name": j.get("companyName", ""),
            "location": j.get("jobLocation", {}).get("displayName", ""),
            "remote": j.get("isRemote", False),
            "url": j.get("detailsPageUrl", ""),
            "description": j.get("summary", ""),
            "posted_at": j.get("postedDate", ""),
            "source": "dice",
        }
        for j in jobs
    ]


async def search_remotive(query: str, limit: int = 10) -> list[dict]:
    """Search Remotive for remote jobs."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            "https://remotive.com/api/remote-jobs",
            params={"search": query, "limit": min(limit, 50)},
        )
        if resp.status_code != 200:
            return []
        data = resp.json()

    jobs = data.get("jobs", [])[:limit]
    return [
        {
            "external_id": f"remotive_{j.get('id', '')}",
            "title": j.get("title", ""),
            "company_name": j.get("company_name", ""),
            "location": j.get("candidate_required_location", "Worldwide"),
            "remote": True,
            "url": j.get("url", ""),
            "description": j.get("description", ""),
            "employment_type": j.get("job_type", ""),
            "posted_at": j.get("publication_date", ""),
            "salary": j.get("salary", ""),
            "tags": j.get("tags", []),
            "source": "remotive",
        }
        for j in jobs
    ]


async def search_jobicy(query: str, limit: int = 10) -> list[dict]:
    """Search Jobicy for remote jobs."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            "https://jobicy.com/api/v2/remote-jobs",
            params={"count": str(min(limit, 50)), "tag": query},
        )
        if resp.status_code != 200:
            return []
        data = resp.json()

    jobs = data.get("jobs", [])[:limit]
    return [
        {
            "external_id": f"jobicy_{j.get('id', '')}",
            "title": j.get("jobTitle", ""),
            "company_name": j.get("companyName", ""),
            "location": j.get("jobGeo", "Remote"),
            "remote": True,
            "url": j.get("url", ""),
            "description": j.get("jobDescription", ""),
            "employment_type": j.get("jobType", ""),
            "posted_at": j.get("pubDate", ""),
            "salary_min": j.get("annualSalaryMin"),
            "salary_max": j.get("annualSalaryMax"),
            "salary_currency": j.get("salaryCurrency", "USD"),
            "source": "jobicy",
        }
        for j in jobs
    ]


async def fetch_simplify_jobs(repo: str = "SimplifyJobs/New-Grad-Positions", limit: int = 50) -> list[dict]:
    """Parse job listings from SimplifyJobs GitHub markdown tables.

    Args:
        repo: GitHub repo path (SimplifyJobs/New-Grad-Positions or Summer2025-Internships).
        limit: Max results.
    """
    # Fetch raw README
    url = f"https://raw.githubusercontent.com/{repo}/dev/README.md"
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(url)
        if resp.status_code != 200:
            # Try main branch
            url = f"https://raw.githubusercontent.com/{repo}/main/README.md"
            resp = await client.get(url)
            if resp.status_code != 200:
                return []
        content = resp.text

    # Parse markdown table rows: | Company | Role | Location | Link | Date |
    # Pattern: lines starting with | that have multiple | separators
    rows = re.findall(r'^\|(.+)\|$', content, re.MULTILINE)
    if len(rows) < 2:
        return []

    # Skip header and separator rows
    jobs: list[dict] = []
    for row in rows[2:]:  # skip header + separator
        cols = [c.strip() for c in row.split("|")]
        if len(cols) < 4:
            continue

        company = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', cols[0]).strip()
        title = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', cols[1]).strip()
        location = cols[2].strip() if len(cols) > 2 else ""

        # Extract URL from markdown link
        link_match = re.search(r'\[([^\]]*)\]\(([^)]+)\)', cols[3] if len(cols) > 3 else "")
        url = link_match.group(2) if link_match else ""

        date_posted = cols[4].strip() if len(cols) > 4 else ""

        if not company or not title or company.startswith("---"):
            continue

        # Skip closed positions
        if "🔒" in row or "closed" in row.lower():
            continue

        jobs.append({
            "external_id": f"simplify_{hash(f'{company}_{title}')}",
            "title": title,
            "company_name": company,
            "location": location,
            "remote": "remote" in location.lower(),
            "url": url,
            "description": f"{title} at {company} — {location}",
            "posted_at": date_posted,
            "source": "simplify_github",
        })

        if len(jobs) >= limit:
            break

    return jobs
