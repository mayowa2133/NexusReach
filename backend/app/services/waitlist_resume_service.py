"""Optional resume attachment for public waitlist signups.

Split of responsibility, deliberately:

* **Invalid input** (bad base64, wrong type, oversize, wrong magic bytes) raises
  an HTTP error so the visitor is told what to fix — the same posture as the
  existing disposable-email rejection.
* **Infrastructure failure** (Storage down/unconfigured) is fail-soft: the
  signup still succeeds and the row is marked ``failed``. We never punish a
  visitor for our outage.

Parsing is *not* done here. The web request only validates and stores; the
sandboxed parser (up to 512 MiB) runs later in the Celery worker.
"""

import base64
import binascii
import logging
from datetime import datetime, timezone

from fastapi import HTTPException, status

from app.clients import supabase_storage_client
from app.config import settings
from app.models.waitlist import WaitlistSignup
from app.schemas.waitlist import WaitlistSignupCreate
from app.utils.resume_upload import (
    ensure_resume_magic_bytes,
    normalize_resume_content_type,
)

logger = logging.getLogger(__name__)

_EXTENSION_FOR_TYPE = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
}


def decode_and_validate(
    payload: WaitlistSignupCreate,
) -> tuple[bytes, str] | None:
    """Decode + validate an attached resume.

    Returns ``(data, content_type)``, or ``None`` when nothing was attached.
    Raises ``HTTPException`` (400/413/422) on invalid input.
    """
    encoded = payload.resume_file_base64
    if not encoded:
        return None

    try:
        data = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Resume upload was corrupted. Please try attaching it again.",
        ) from None

    if not data:
        return None

    if len(data) > settings.max_waitlist_resume_bytes:
        limit_mb = settings.max_waitlist_resume_bytes // (1024 * 1024)
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Resume must be smaller than {limit_mb} MB.",
        )

    content_type = normalize_resume_content_type(
        payload.resume_content_type, payload.resume_filename
    )
    ensure_resume_magic_bytes(data, content_type)
    return data, content_type


def build_object_path(entry: WaitlistSignup, content_type: str) -> str:
    """Storage key for a signup's resume.

    The filename is *derived*, never taken from user input, so nothing
    attacker-controlled reaches the object path.
    """
    extension = _EXTENSION_FOR_TYPE.get(content_type, ".bin")
    return f"{entry.id}/resume{extension}"


async def attach_resume(
    entry: WaitlistSignup,
    data: bytes,
    content_type: str,
    original_filename: str | None,
) -> None:
    """Upload to Supabase Storage and stamp metadata on ``entry``.

    Fail-soft: on a storage failure the entry is marked ``failed`` and the
    caller still returns a successful signup. Does not commit — the caller owns
    the transaction.
    """
    path = build_object_path(entry, content_type)
    uploaded = await supabase_storage_client.upload_object(path, data, content_type)

    entry.resume_filename = original_filename
    entry.resume_content_type = content_type
    entry.resume_size_bytes = len(data)
    entry.resume_uploaded_at = datetime.now(timezone.utc)

    if uploaded:
        entry.resume_path = path
        entry.resume_parse_status = "pending"
    else:
        # Storage unavailable/unconfigured — keep the signup, flag the resume.
        entry.resume_path = None
        entry.resume_parse_status = "failed"
        logger.warning("Waitlist resume not stored for signup %s", entry.id)
