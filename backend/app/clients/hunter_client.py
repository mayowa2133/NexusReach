"""Hunter.io API client for email finding and verification."""

import httpx

from app.config import settings

HUNTER_BASE_URL = "https://api.hunter.io/v2"


async def find_email(
    domain: str,
    first_name: str,
    last_name: str,
) -> dict | None:
    """Find a professional email address for a person at a company.

    Args:
        domain: Company domain (e.g. "stripe.com").
        first_name: Person's first name.
        last_name: Person's last name.

    Returns:
        Dict with email, score, and verification status, or None if not found.
    """
    if not settings.hunter_api_key:
        return None

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{HUNTER_BASE_URL}/email-finder",
            params={
                "api_key": settings.hunter_api_key,
                "domain": domain,
                "first_name": first_name,
                "last_name": last_name,
            },
        )
        if resp.status_code != 200:
            return None
        data = resp.json().get("data", {})

    email = data.get("email")
    if not email:
        return None

    return {
        "email": email,
        "score": data.get("score", 0),
        "position": data.get("position", ""),
        "sources": data.get("sources", 0),
        "verified": data.get("verification", {}).get("status") == "valid",
    }


async def verify_email(email: str) -> dict | None:
    """Verify if an email address is valid and deliverable.

    Returns:
        Dict with status, result, score, or None on error.
    """
    if not settings.hunter_api_key:
        return None

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{HUNTER_BASE_URL}/email-verifier",
            params={
                "api_key": settings.hunter_api_key,
                "email": email,
            },
        )
        if resp.status_code != 200:
            return None
        data = resp.json().get("data", {})

    return {
        "email": data.get("email", email),
        "status": data.get("status", "unknown"),
        "result": data.get("result", "unknown"),
        "score": data.get("score", 0),
        "disposable": data.get("disposable", False),
        "webmail": data.get("webmail", False),
    }


async def domain_search(domain: str, limit: int = 10) -> list[dict]:
    """Search for email addresses at a domain.

    Returns:
        List of email dicts found at the domain.
    """
    if not settings.hunter_api_key:
        return []

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{HUNTER_BASE_URL}/domain-search",
            params={
                "api_key": settings.hunter_api_key,
                "domain": domain,
                "limit": min(limit, 100),
            },
        )
        if resp.status_code != 200:
            return []
        data = resp.json().get("data", {})

    return [
        {
            "email": e.get("value", ""),
            "type": e.get("type", ""),
            "first_name": e.get("first_name", ""),
            "last_name": e.get("last_name", ""),
            "position": e.get("position", ""),
            "confidence": e.get("confidence", 0),
        }
        for e in data.get("emails", [])
    ]
