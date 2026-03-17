"""SMTP domain tracking service — records probe outcomes and manages blocklist."""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.smtp_domain_result import SmtpDomainResult

logger = logging.getLogger(__name__)

# After this many blocked/timeout results, auto-block the domain
SMTP_BLOCK_THRESHOLD = 3

# How long a blocked domain stays blocked before we retry
SMTP_BLOCK_TTL_DAYS = 30

# Catch-all domains get a shorter block (they might change config)
SMTP_CATCH_ALL_TTL_DAYS = 14

# Domains behind known SEGs (Proofpoint/Mimecast/Barracuda) are blocked for 6
# months — corporate email infrastructure changes rarely
SMTP_INFRASTRUCTURE_BLOCK_TTL_DAYS = 180


async def is_domain_blocked(db: AsyncSession, domain: str) -> bool:
    """Check if a domain is currently blocked for SMTP probing.

    Returns True if blocked_until is in the future.
    """
    domain = domain.lower().strip()
    now = datetime.now(timezone.utc)

    result = await db.execute(
        select(SmtpDomainResult).where(
            SmtpDomainResult.domain == domain,
            SmtpDomainResult.blocked_until > now,
        )
    )
    return result.scalar_one_or_none() is not None


async def record_smtp_result(
    db: AsyncSession, domain: str, result_type: str
) -> None:
    """Record an SMTP probe outcome for a domain.

    Args:
        domain: The email domain that was probed.
        result_type: One of "success", "catch_all", "blocked", "greylist".
    """
    domain = domain.lower().strip()
    now = datetime.now(timezone.utc)

    result = await db.execute(
        select(SmtpDomainResult).where(SmtpDomainResult.domain == domain)
    )
    record = result.scalar_one_or_none()

    if not record:
        record = SmtpDomainResult(domain=domain)
        db.add(record)

    if result_type == "success":
        record.success_count = (record.success_count or 0) + 1
        record.last_success_at = now
        # A success proves the domain responds — clear any block
        record.blocked_count = 0
        record.blocked_until = None

    elif result_type == "catch_all":
        record.catch_all_count = (record.catch_all_count or 0) + 1
        record.last_failure_at = now
        record.blocked_until = now + timedelta(days=SMTP_CATCH_ALL_TTL_DAYS)

    elif result_type == "blocked":
        record.blocked_count = (record.blocked_count or 0) + 1
        record.last_failure_at = now
        if record.blocked_count >= SMTP_BLOCK_THRESHOLD:
            record.blocked_until = now + timedelta(days=SMTP_BLOCK_TTL_DAYS)
            logger.info(
                "Domain %s blocked for SMTP probing (failures=%d, until=%s)",
                domain,
                record.blocked_count,
                record.blocked_until.isoformat(),
            )

    elif result_type == "infrastructure_blocked":
        # MX resolves to a known SEG provider — block immediately for 6 months.
        # Only set if not already blocked to avoid resetting a longer existing block.
        record.blocked_count = SMTP_BLOCK_THRESHOLD
        record.last_failure_at = now
        if not record.blocked_until or record.blocked_until < now:
            record.blocked_until = now + timedelta(days=SMTP_INFRASTRUCTURE_BLOCK_TTL_DAYS)

    elif result_type == "greylist":
        record.greylist_count = (record.greylist_count or 0) + 1
        record.last_failure_at = now
        # Greylisting doesn't trigger a block — it's a temporary server behavior

    record.updated_at = now
    await db.flush()


async def get_domain_stats(db: AsyncSession, domain: str) -> dict | None:
    """Get SMTP probe stats for a domain (for debugging/admin)."""
    domain = domain.lower().strip()
    result = await db.execute(
        select(SmtpDomainResult).where(SmtpDomainResult.domain == domain)
    )
    record = result.scalar_one_or_none()
    if not record:
        return None

    return {
        "domain": record.domain,
        "success_count": record.success_count,
        "catch_all_count": record.catch_all_count,
        "blocked_count": record.blocked_count,
        "greylist_count": record.greylist_count,
        "last_success_at": record.last_success_at.isoformat() if record.last_success_at else None,
        "last_failure_at": record.last_failure_at.isoformat() if record.last_failure_at else None,
        "blocked_until": record.blocked_until.isoformat() if record.blocked_until else None,
        "is_blocked": record.blocked_until is not None and record.blocked_until > datetime.now(timezone.utc),
    }
