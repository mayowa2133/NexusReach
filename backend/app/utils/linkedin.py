"""LinkedIn URL normalization utilities for deduplication."""

import re
from urllib.parse import urlparse

# Trailing "| LinkedIn" / "- LinkedIn" (and anything after it) on a SERP title.
_LINKEDIN_TITLE_SUFFIX = re.compile(r"\s*[|\-–—]\s*LinkedIn.*$", re.IGNORECASE)


def parse_linkedin_serp_title(title_raw: str) -> tuple[str, str, str]:
    """Parse a LinkedIn search-result title into ``(name, title, company)``.

    Canonical search-engine titles look like
    ``"Name - Title - Company | LinkedIn"`` (also the
    ``"Name - Senior Recruiter at Company | LinkedIn"`` variant). This is the
    single source of truth for that parse, shared by the search-provider result
    parsers (Brave/Google/SearXNG) and the public-web profile enricher. Handles
    en/em-dash separators and trailing junk after ``LinkedIn``; any part that
    isn't present comes back as an empty string.
    """
    if not title_raw:
        return "", "", ""

    clean = _LINKEDIN_TITLE_SUFFIX.sub("", title_raw).strip()
    # Normalize en/em dashes to the canonical " - " separator before splitting.
    clean = re.sub(r"\s*[–—]\s*", " - ", clean)
    parts = [part.strip() for part in clean.split(" - ") if part.strip()]
    if not parts:
        return "", "", ""

    name = parts[0]
    title = parts[1] if len(parts) > 1 else ""
    company = parts[2] if len(parts) > 2 else ""

    # "<Title> at <Company>" — pull the company out of the title segment.
    at_match = re.search(r"\s+at\s+(.+)$", title, flags=re.IGNORECASE)
    if at_match and not company:
        company = at_match.group(1).strip()
        title = re.sub(r"\s+at\s+.+$", "", title, flags=re.IGNORECASE).strip()

    return name, title, company


def normalize_linkedin_url(url: str | None) -> str | None:
    """Normalize a LinkedIn profile URL for consistent matching.

    Returns a canonical ``https://www.linkedin.com/in/{slug}`` form,
    or ``None`` if the input is not a valid LinkedIn profile URL.
    """
    if not url or not isinstance(url, str):
        return None

    url = url.strip()
    if not url:
        return None

    # Ensure scheme is present for urlparse
    if url.startswith("linkedin.com") or url.startswith("www.linkedin.com"):
        url = "https://" + url

    try:
        parsed = urlparse(url)
    except ValueError:
        return None

    host = (parsed.hostname or "").lower()
    if host not in ("linkedin.com", "www.linkedin.com"):
        return None

    path = parsed.path.rstrip("/")

    # Extract /in/{slug} pattern
    parts = [p for p in path.split("/") if p]
    if len(parts) < 2 or parts[0] != "in":
        return None

    slug = parts[1].lower()
    if not slug:
        return None

    return f"https://www.linkedin.com/in/{slug}"
