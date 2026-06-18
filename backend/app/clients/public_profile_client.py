"""Free public-web profile enrichment.

Replacement for the defunct Proxycurl LinkedIn enrichment (sunset 2025-07).
Instead of a paid API that proxied LinkedIn, this reads the public **search
snippet** for a profile through the existing self-hosted SearXNG layer and
parses the ``"Name - Title - Company | LinkedIn"`` header LinkedIn publishes to
search engines.

This is $0, unlimited, and self-hosted; it never scrapes LinkedIn directly and
stores no credentials/cookies, so it carries none of the legal/operational risk
that killed Proxycurl. It recovers the high-value fields (name, current title,
current company, headline) — which is exactly what the enrich flow consumes —
but not the full experience/education history a paid enrichment API would.

Fails soft to ``None`` whenever SearXNG is unconfigured or no matching public
result is found.
"""

import re

from app.clients import searxng_search_client
from app.utils.linkedin import normalize_linkedin_url

# Opaque id tokens LinkedIn appends to slugs, e.g. "jane-doe-1a2b3c4d" or
# "jane-doe-12345". Once we hit one, the human-name portion of the slug is done.
_SLUG_ID_TOKEN = re.compile(r"^(?:[0-9a-f]{6,}|\d+)$", re.IGNORECASE)
_LINKEDIN_SUFFIX = re.compile(r"\s*[|\-–—]\s*LinkedIn.*$", re.IGNORECASE)


def _name_from_slug(slug: str) -> str:
    """Derive a best-effort human name from a LinkedIn slug.

    ``"jane-doe-1a2b3c4d" -> "Jane Doe"``. Used only to seed the search query;
    the authoritative name comes from the matched SERP title.
    """
    words: list[str] = []
    for token in slug.split("-"):
        if not token:
            continue
        if _SLUG_ID_TOKEN.match(token):
            break
        words.append(token)
    return " ".join(word.capitalize() for word in words)


def _parse_profile_title(title_raw: str) -> tuple[str, str, str]:
    """Parse ``"Name - Title - Company | LinkedIn"`` into (name, title, company).

    Also handles the ``"Name - Senior Recruiter at Company | LinkedIn"`` form.
    Returns empty strings for parts that aren't present.
    """
    clean = _LINKEDIN_SUFFIX.sub("", title_raw).strip()
    # Normalize en/em dashes to the canonical " - " separator before splitting.
    clean = re.sub(r"\s*[–—]\s*", " - ", clean)
    parts = [p.strip() for p in clean.split(" - ") if p.strip()]
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


async def enrich_profile(linkedin_url: str) -> dict | None:
    """Enrich a LinkedIn profile from its public search snippet.

    Returns a dict shaped for ``Person`` population (``full_name``, ``title``,
    ``company``, ``headline``, ``linkedin_url``, ``source``, ``profile_data``)
    or ``None`` if the profile can't be recovered for free.
    """
    canonical = normalize_linkedin_url(linkedin_url)
    if not canonical:
        return None

    slug = canonical.rsplit("/in/", 1)[-1]
    name_guess = _name_from_slug(slug)

    # Most-specific query first (quoted name), then a bare-slug fallback.
    queries: list[str] = []
    if name_guess:
        queries.append(f'site:linkedin.com/in "{name_guess}"')
    queries.append(f"site:linkedin.com/in {slug}")

    for query in queries:
        for item in await searxng_search_client._run_searxng_query(query, 5):
            # Only trust a result that points at this exact profile.
            if normalize_linkedin_url(item.get("url") or "") != canonical:
                continue

            title_raw = item.get("title") or ""
            name, title, company = _parse_profile_title(title_raw)
            if not (name or title):
                continue

            return {
                "full_name": name or name_guess or None,
                "title": title or None,
                "company": company or None,
                "headline": title_raw or None,
                "linkedin_url": canonical,
                "source": "public_web",
                "profile_data": {
                    "enrichment_source": "searxng_serp_snippet",
                    "serp_title": title_raw,
                    "serp_snippet": item.get("content") or "",
                },
            }

    return None
