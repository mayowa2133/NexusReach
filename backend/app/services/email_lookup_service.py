"""Free hiring-manager email lookup.

Accepts a LinkedIn URL OR (first/last name) plus a company name or domain.
Tries SMTP RCPT TO verification first; if that fails, returns the top 3
pattern-based suggestions with confidence scores. No paid APIs (no Hunter,
no Proxycurl) — purely free signals.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.email_pattern_client import find_email_by_pattern
from app.clients.email_suggestion_client import suggest_email
from app.models.company import Company

logger = logging.getLogger(__name__)


_LINKEDIN_SLUG_RE = re.compile(r"linkedin\.com/in/([^/?#]+)", re.IGNORECASE)
# Strip trailing identifier hash that LinkedIn appends, e.g. "john-doe-1a2b3c4d"
_TRAILING_HASH_RE = re.compile(r"-[a-z0-9]{6,}$", re.IGNORECASE)


def parse_linkedin_url(url: str) -> tuple[str | None, str | None]:
    """Best-effort extraction of (first_name, last_name) from a LinkedIn URL.

    Returns (None, None) if the slug cannot be parsed into a plausible name.
    """
    if not url:
        return None, None
    match = _LINKEDIN_SLUG_RE.search(url)
    if not match:
        return None, None
    slug = match.group(1).strip().lower()
    # Drop the trailing random identifier hash if it looks like one
    cleaned = _TRAILING_HASH_RE.sub("", slug)
    parts = [p for p in cleaned.split("-") if p and p.isalpha()]
    if len(parts) < 2:
        return None, None
    first = parts[0].capitalize()
    last = " ".join(p.capitalize() for p in parts[1:])
    return first, last


def _domain_from_url(url: str) -> str | None:
    if not url:
        return None
    if "://" not in url:
        url = "https://" + url
    try:
        host = urlparse(url).hostname or ""
    except ValueError:
        return None
    host = host.lower().lstrip(".")
    if host.startswith("www."):
        host = host[4:]
    return host or None


def _slugify_company(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


async def resolve_company_domain(
    db: AsyncSession,
    company_name: str | None,
    company_domain: str | None,
) -> str | None:
    """Resolve a company to its primary email domain.

    Priority:
      1. explicit company_domain (cleaned)
      2. Company table lookup by name (case-insensitive)
      3. naive guess: <slug>.com
    """
    if company_domain:
        cleaned = _domain_from_url(company_domain) or company_domain.lower().strip()
        return cleaned

    if not company_name:
        return None

    result = await db.execute(
        select(Company)
        .where(func.lower(Company.name) == company_name.strip().lower())
        .limit(1)
    )
    company = result.scalar_one_or_none()
    if company and company.domain:
        return company.domain.lower().strip()

    # Fall back to naive guess
    slug = _slugify_company(company_name)
    if not slug:
        return None
    return f"{slug}.com"


async def lookup_email(
    db: AsyncSession,
    *,
    linkedin_url: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
    company_name: str | None = None,
    company_domain: str | None = None,
) -> dict:
    """Find a hiring manager email using only free signals.

    Returns a dict:
        {
          "verified": bool,
          "email": str | None,            # verified email if found
          "domain": str | None,
          "first_name": str | None,
          "last_name": str | None,
          "domain_status": str,           # success | catch_all | no_mx | ...
          "suggestions": [                # top 3 (always present when domain known)
              {"email": str, "confidence": int}, ...
          ],
          "known_company": bool,
          "source": "smtp_verified" | "pattern_suggestion" | "insufficient_input",
        }
    """
    # Resolve name
    fn, ln = first_name, last_name
    if (not fn or not ln) and linkedin_url:
        parsed_first, parsed_last = parse_linkedin_url(linkedin_url)
        fn = fn or parsed_first
        ln = ln or parsed_last

    if not fn or not ln:
        return {
            "verified": False,
            "email": None,
            "domain": None,
            "first_name": fn,
            "last_name": ln,
            "domain_status": "missing_name",
            "suggestions": [],
            "known_company": False,
            "source": "insufficient_input",
        }

    domain = await resolve_company_domain(db, company_name, company_domain)
    if not domain:
        return {
            "verified": False,
            "email": None,
            "domain": None,
            "first_name": fn,
            "last_name": ln,
            "domain_status": "missing_domain",
            "suggestions": [],
            "known_company": False,
            "source": "insufficient_input",
        }

    # Step 1: try SMTP verification
    smtp_result = await find_email_by_pattern(fn, ln, domain)
    domain_status = smtp_result.get("domain_status", "unknown")

    if smtp_result.get("verified") and smtp_result.get("email"):
        # Still include alternates for context
        sugg = suggest_email(fn, ln, domain)
        suggestions = (sugg or {}).get("suggestions", [])[:3]
        return {
            "verified": True,
            "email": smtp_result["email"],
            "domain": domain,
            "first_name": fn,
            "last_name": ln,
            "domain_status": domain_status,
            "suggestions": suggestions,
            "known_company": (sugg or {}).get("known_company", False),
            "source": "smtp_verified",
        }

    # Step 2: fall back to top 3 ranked pattern suggestions
    sugg = suggest_email(fn, ln, domain)
    suggestions = (sugg or {}).get("suggestions", [])[:3]

    return {
        "verified": False,
        "email": None,
        "domain": domain,
        "first_name": fn,
        "last_name": ln,
        "domain_status": domain_status,
        "suggestions": suggestions,
        "known_company": (sugg or {}).get("known_company", False),
        "source": "pattern_suggestion",
    }
