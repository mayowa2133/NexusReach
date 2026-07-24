"""Supabase Storage object upload/download.

The backend has no other object storage: uploaded resumes were historically
parsed to text and the bytes discarded. The pre-launch waitlist now keeps the
original file, so this client stores it in a **private** Supabase Storage bucket
(``settings.supabase_storage_bucket``, created manually — see the runbook).

Implemented with raw ``httpx`` against the Storage REST API using the
service-role key, mirroring ``services/account_service.delete_supabase_auth_user``
(the ``supabase`` SDK is a dependency but is deliberately never imported).

Everything here is **fail-soft**: a storage outage must never fail a waitlist
signup, which is designed to always succeed for the visitor. Callers treat a
``None``/``False`` result as "no file stored" and carry on.
"""

import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 30.0


def is_configured() -> bool:
    """True when a Supabase URL, service-role key, and bucket are all set."""
    return bool(
        settings.supabase_url
        and settings.supabase_service_role_key
        and settings.supabase_storage_bucket
    )


def _object_url(path: str) -> str:
    base = settings.supabase_url.rstrip("/")
    bucket = settings.supabase_storage_bucket
    return f"{base}/storage/v1/object/{bucket}/{path.lstrip('/')}"


def _headers() -> dict[str, str]:
    key = settings.supabase_service_role_key
    return {"apikey": key, "Authorization": f"Bearer {key}"}


async def upload_object(path: str, data: bytes, content_type: str) -> bool:
    """Upload bytes to ``path`` in the configured bucket. Never raises.

    Returns ``True`` only when Storage accepted the object. ``x-upsert`` makes a
    re-submission overwrite rather than 409.
    """
    if not is_configured():
        logger.info("Supabase Storage not configured; skipping upload of %s", path)
        return False

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                _object_url(path),
                content=data,
                headers={
                    **_headers(),
                    "Content-Type": content_type,
                    "x-upsert": "true",
                },
            )
        if resp.status_code >= 400:
            logger.error(
                "Supabase Storage upload failed (%s) for %s: %s",
                resp.status_code,
                path,
                resp.text[:300],
            )
            return False
        return True
    except httpx.HTTPError:
        logger.error("Supabase Storage upload errored for %s", path, exc_info=True)
        return False


async def download_object(path: str) -> bytes | None:
    """Fetch an object's bytes, or ``None`` when missing/unconfigured/failed."""
    if not is_configured():
        return None

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            resp = await client.get(_object_url(path), headers=_headers())
        if resp.status_code >= 400:
            logger.error(
                "Supabase Storage download failed (%s) for %s",
                resp.status_code,
                path,
            )
            return None
        return resp.content
    except httpx.HTTPError:
        logger.error("Supabase Storage download errored for %s", path, exc_info=True)
        return None
