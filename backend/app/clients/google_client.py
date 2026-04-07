"""Google Careers job search client.

Google publishes a comprehensive XML feed of all open positions at:
    https://www.google.com/about/careers/applications/jobs/feed.xml

The feed is ~22 MB and contains rich structured data per entry including
published date, employer (Google / DeepMind / YouTube / etc.), remote
status, locations, categories, job type, and full description HTML.

This client streams the feed via iterparse to keep memory usage bounded
and supports keyword filtering on the client side.
"""

from __future__ import annotations

import logging
import re
from html import unescape
from xml.etree.ElementTree import iterparse

import httpx

logger = logging.getLogger(__name__)

_FEED_URL = "https://www.google.com/about/careers/applications/jobs/feed.xml"

_HEADERS = {
    "Accept": "application/xml, text/xml, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}

_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


def _strip_tags(html: str) -> str:
    """Remove HTML tags and collapse whitespace."""
    return _WHITESPACE_RE.sub(" ", unescape(_TAG_RE.sub(" ", html))).strip()


def _extract_job_url(raw_url: str, job_id: str) -> str:
    """Return a clean job detail URL."""
    if raw_url:
        return raw_url
    return f"https://www.google.com/about/careers/applications/jobs/results/{job_id}"


def _parse_locations(entry_xml: dict[str, str]) -> str:
    """Build a semicolon-separated location string from parsed location fields."""
    locations: list[str] = []
    # Locations come as <locations><location>...</location></locations>
    # We collect them during parsing into a list stored under "_locations"
    raw = entry_xml.get("_locations", [])
    for loc in raw:
        loc = loc.strip()
        if loc and loc not in locations:
            locations.append(loc)
    return "; ".join(locations)


def _matches_query(entry: dict, keywords: list[str]) -> bool:
    """Check if an entry matches all query keywords (case-insensitive)."""
    if not keywords:
        return True
    searchable = " ".join([
        entry.get("title", ""),
        entry.get("employer", ""),
        entry.get("description_text", ""),
        entry.get("location", ""),
        " ".join(entry.get("_categories", [])),
    ]).lower()
    return all(kw in searchable for kw in keywords)


async def search_google_jobs(
    search_text: str = "",
    limit: int = 20,
) -> list[dict]:
    """Fetch jobs from Google Careers XML feed.

    Parameters
    ----------
    search_text:
        Free-text query (e.g. ``"software engineer"``).  Matched against
        title, employer, description, location, and categories.
    limit:
        Maximum jobs to return.

    Returns
    -------
    list[dict]
        Normalized job dicts for the NexusReach pipeline.
    """
    keywords = [kw.lower() for kw in search_text.split() if kw] if search_text else []

    try:
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            async with client.stream("GET", _FEED_URL, headers=_HEADERS) as resp:
                if resp.status_code != 200:
                    logger.debug("Google Careers feed returned %d", resp.status_code)
                    return []

                # Stream to a temp buffer for iterparse
                chunks: list[bytes] = []
                async for chunk in resp.aiter_bytes(chunk_size=65536):
                    chunks.append(chunk)

    except Exception:
        logger.exception("Google Careers feed fetch failed")
        return []

    # Parse the XML feed
    import io

    xml_bytes = b"".join(chunks)
    if not xml_bytes:
        logger.debug("Google Careers: empty feed response")
        return []

    jobs: list[dict] = []

    try:
        source = io.BytesIO(xml_bytes)
        context = iterparse(source, events=("end",))

        # Track current entry fields
        current_entry: dict | None = None
        current_locations: list[str] = []
        current_categories: list[str] = []

        for event, elem in context:
            # Strip namespace prefix if present
            tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag

            if tag == "entry":
                # Finished an entry — process it
                if current_entry is not None:
                    current_entry["_locations"] = current_locations
                    current_entry["_categories"] = current_categories

                    title = current_entry.get("title", "").strip()
                    job_id = current_entry.get("jobid", "")
                    employer = current_entry.get("employer", "Google")
                    raw_url = current_entry.get("url", "")
                    remote_field = current_entry.get("remote", "").lower()
                    is_remote_field = current_entry.get("isRemote", "").lower()
                    published = current_entry.get("published", "")
                    description_html = current_entry.get("description", "")
                    location = _parse_locations(current_entry)
                    remote = (
                        remote_field in ("remote", "hybrid")
                        or is_remote_field in ("yes",)
                        or "remote" in (location + " " + title).lower()
                    )
                    description_text = _strip_tags(description_html) if description_html else ""

                    # Build a searchable version for filtering
                    entry_for_match = {
                        "title": title,
                        "employer": employer,
                        "description_text": description_text,
                        "location": location,
                        "_categories": current_categories,
                    }

                    if title and job_id and _matches_query(entry_for_match, keywords):
                        job_url = _extract_job_url(raw_url, job_id)

                        # Use employer as company_name (can be Google, DeepMind, YouTube, etc.)
                        company_name = employer if employer else "Google"

                        posted_at = published if published else None

                        jobs.append({
                            "external_id": f"goog_{job_id}",
                            "title": title,
                            "company_name": company_name,
                            "location": location,
                            "remote": remote,
                            "url": job_url,
                            "description": description_text[:2000] if description_text else "",
                            "posted_at": posted_at,
                            "source": "google_careers",
                            "ats": None,
                        })

                        if len(jobs) >= limit:
                            break

                # Reset for next entry
                current_entry = None
                current_locations = []
                current_categories = []
                elem.clear()
                continue

            # Detect entry start by tracking child elements
            # In Atom feeds, entries contain these child elements
            if tag in (
                "title", "jobid", "url", "employer", "remote",
                "isRemote", "published", "description", "jobtype",
            ):
                if current_entry is None:
                    current_entry = {}
                    current_locations = []
                    current_categories = []
                text = elem.text or ""
                current_entry[tag] = text

            elif tag == "location":
                if current_entry is None:
                    current_entry = {}
                    current_locations = []
                    current_categories = []
                if elem.text:
                    current_locations.append(elem.text.strip())

            elif tag == "category":
                if current_entry is None:
                    current_entry = {}
                    current_locations = []
                    current_categories = []
                if elem.text:
                    current_categories.append(elem.text.strip())

            elem.clear()

    except Exception:
        logger.exception("Google Careers feed parse failed")
        # Return whatever we've collected so far
        pass

    logger.info("Google Careers: %d jobs (query=%r)", len(jobs), search_text)
    return jobs
