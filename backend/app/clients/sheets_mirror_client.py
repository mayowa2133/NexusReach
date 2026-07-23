"""Server-side mirror of waitlist signups to a Google Sheet.

The referral loop made the backend the primary waitlist sink — the browser
can't read the Apps Script ``no-cors`` response needed to hydrate the referral
panel — so signups no longer reach the Google Sheet from the frontend. This
mirrors each signup to the Apps Script ``/exec`` endpoint **server-side** (where
the response is readable and there's no CORS), keeping the Sheet as a familiar
live view / backup.

Best-effort by design: an unset URL or any error is a no-op that never affects
the signup (it is dispatched as a FastAPI background task, after the response).
"""

import logging
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 10.0


def is_configured() -> bool:
    """True when a Sheet mirror URL is set."""
    return bool(settings.waitlist_sheet_mirror_url)


async def mirror_signup(row: dict[str, Any]) -> bool:
    """POST one signup row to the Apps Script endpoint.

    Returns ``True`` when the endpoint accepted it. Returns ``False`` (never
    raises) when unconfigured or on any error. Apps Script answers a successful
    ``doPost`` with a 302 redirect to its content host — the row is already
    written by then — so any non-4xx/5xx status counts as success.
    """
    if not is_configured():
        return False
    try:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT_SECONDS, follow_redirects=False
        ) as client:
            resp = await client.post(settings.waitlist_sheet_mirror_url, json=row)
        if resp.status_code >= 400:
            logger.error(
                "Waitlist Sheet mirror failed (%s): %s",
                resp.status_code,
                resp.text[:300],
            )
            return False
        return True
    except httpx.HTTPError:
        logger.warning("Waitlist Sheet mirror errored", exc_info=True)
        return False
