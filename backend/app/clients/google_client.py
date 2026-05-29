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
from xml.etree.ElementTree import XMLPullParser

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

    async def _iter_feed_events():
        """Yield (event, elem) incrementally so the full ~22MB feed is never
        buffered in memory (audit H10). Chunks are fed to a streaming pull
        parser; the caller clears each element as it is handled."""
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            async with client.stream("GET", _FEED_URL, headers=_HEADERS) as resp:
                if resp.status_code != 200:
                    logger.debug("Google Careers feed returned %d", resp.status_code)
                    return
                parser = XMLPullParser(events=("end",))
                async for chunk in resp.aiter_bytes(chunk_size=65536):
                    parser.feed(chunk)
                    for event, elem in parser.read_events():
                        yield event, elem
                parser.close()
                for event, elem in parser.read_events():
                    yield event, elem

    jobs: list[dict] = []

    # Track current entry fields
    current_entry: dict | None = None
    current_locations: list[str] = []
    current_categories: list[str] = []
    current_location_parts: list[str] = []

    try:
        async for event, elem in _iter_feed_events():
            # Strip namespace prefix if present
            tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag

            if tag in {"entry", "job"}:
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
                    is_hybrid_field = current_entry.get("isHybrid", "").lower()
                    published = current_entry.get("published", "")
                    description_html = current_entry.get("description", "")
                    location = _parse_locations(current_entry)
                    remote = (
                        remote_field in ("remote", "hybrid")
                        or is_remote_field in ("yes",)
                        or is_hybrid_field in ("yes", "true")
                        or "remote" in (location + " " + title).lower()
                    )
                    work_mode = (
                        "hybrid" if remote_field == "hybrid" or is_hybrid_field in ("yes", "true")
                        else "remote" if remote_field == "remote" or is_remote_field == "yes"
                        else None
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
                            "work_mode": work_mode,
                            "url": job_url,
                            "apply_url": job_url,
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
                current_location_parts = []
                elem.clear()
                continue

            # Detect entry start by tracking child elements
            # In Atom feeds, entries contain these child elements
            if tag in (
                "title", "jobid", "url", "employer", "remote",
                "isRemote", "isHybrid", "published", "description", "jobtype",
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
                    current_location_parts = []
                if elem.text and elem.text.strip():
                    current_locations.append(elem.text.strip())
                elif current_location_parts:
                    current_locations.append(", ".join(current_location_parts))
                current_location_parts = []

            elif tag in {"city", "state", "country"}:
                if current_entry is not None and elem.text and elem.text.strip():
                    current_location_parts.append(elem.text.strip())

            elif tag == "category":
                if current_entry is None:
                    current_entry = {}
                    current_locations = []
                    current_categories = []
                    current_location_parts = []
                if elem.text:
                    current_categories.append(elem.text.strip())

            elem.clear()

    except Exception:
        logger.exception("Google Careers feed fetch/parse failed")
        # Return whatever we've collected so far.

    logger.info("Google Careers: %d jobs (query=%r)", len(jobs), search_text)
    return jobs
