"""Celery task: parse a waitlist signup's uploaded resume.

Runs out-of-band on purpose. ``POST /api/waitlist`` is public and unauthenticated,
and the resume parser executes in a sandboxed subprocess allowed up to
``parser_sandbox_memory_bytes`` (512 MiB). Doing that inline would make the web
service an OOM/DoS target; here it lands on the Celery worker instead, and the
signup response stays fast.

Reuses the existing hardened parser (``resume_parser.parse_resume_document`` via
``run_in_sandbox_async``), which already enforces zip-bomb, page-count, extracted
-text and no-network limits.
"""

import logging
import uuid

from sqlalchemy import select

from app.clients import supabase_storage_client
from app.config import settings
from app.database import async_session
from app.models.waitlist import WaitlistSignup
from app.tasks import celery_app, run_async
from app.utils.sandboxed_process import run_in_sandbox_async

logger = logging.getLogger(__name__)


async def _run(signup_id: str) -> dict:
    async with async_session() as db:
        result = await db.execute(
            select(WaitlistSignup).where(WaitlistSignup.id == uuid.UUID(signup_id))
        )
        signup = result.scalar_one_or_none()
        if signup is None:
            return {"parsed": False, "reason": "signup_not_found"}
        if not signup.resume_path:
            return {"parsed": False, "reason": "no_resume"}

        data = await supabase_storage_client.download_object(signup.resume_path)
        if not data:
            signup.resume_parse_status = "failed"
            await db.commit()
            return {"parsed": False, "reason": "download_failed"}

        try:
            parsed = await run_in_sandbox_async(
                "app.services.resume_parser",
                "parse_resume_document",
                data,
                signup.resume_content_type or "application/pdf",
                timeout_seconds=settings.parser_sandbox_timeout_seconds,
                memory_bytes=settings.parser_sandbox_memory_bytes,
                cpu_seconds=settings.parser_sandbox_cpu_seconds,
                output_bytes=settings.parser_sandbox_output_bytes,
            )
        except Exception:
            logger.warning(
                "Waitlist resume parse failed for signup %s", signup_id, exc_info=True
            )
            signup.resume_parse_status = "failed"
            await db.commit()
            return {"parsed": False, "reason": "parse_failed"}

        signup.resume_text = parsed.get("raw_text")
        signup.resume_parsed = parsed.get("parsed")
        signup.resume_parse_status = "ready"
        await db.commit()
        return {"parsed": True}


@celery_app.task(
    name="app.tasks.waitlist_resume.parse_waitlist_resume",
    autoretry_for=(Exception,),
    retry_backoff=60,
    retry_backoff_max=600,
    max_retries=2,
)
def parse_waitlist_resume(signup_id: str) -> dict:
    """Download, sandbox-parse, and store a waitlist resume's text/structure."""
    result = run_async(_run(signup_id))
    logger.info("Waitlist resume parse complete: %s", result)
    return result
