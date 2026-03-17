"""Gravatar client — check if an email has a Gravatar account (existence signal)."""

import hashlib

import httpx

GRAVATAR_BASE_URL = "https://gravatar.com/avatar"


async def check_gravatar(email: str) -> bool:
    """Check if an email has an associated Gravatar account.

    This is a lightweight existence signal — if someone registered a Gravatar
    with this email, it's likely a real address.

    Args:
        email: Email address to check.

    Returns:
        True if Gravatar exists for this email, False otherwise.
    """
    if not email or "@" not in email:
        return False

    email_hash = hashlib.md5(email.strip().lower().encode()).hexdigest()
    url = f"{GRAVATAR_BASE_URL}/{email_hash}"

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(url, params={"d": "404", "s": "1"})
            return resp.status_code == 200
    except (httpx.HTTPError, ValueError):
        return False
