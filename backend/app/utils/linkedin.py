"""LinkedIn URL normalization utilities for deduplication."""

from urllib.parse import urlparse


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
