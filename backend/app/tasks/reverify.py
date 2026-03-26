"""Celery task: re-verify stale saved contacts.

Runs on a beat schedule and re-checks employment status for contacts
whose verification has gone stale (older than ``reverify_stale_days``)
or was never performed.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import async_session
from app.models.person import Person
from app.services.employment_verification_service import (
    _apply_verification_result,
    _verify_person,
)
from app.tasks import celery_app
from app.utils.company_identity import effective_public_identity_slugs

logger = logging.getLogger(__name__)


async def _reverify_stale_contacts() -> dict:
    """Find and re-verify contacts whose verification has gone stale."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.reverify_stale_days)

    async with async_session() as db:
        query = (
            select(Person)
            .options(selectinload(Person.company))
            .where(
                (Person.current_company_verified_at < cutoff)
                | (Person.current_company_verified_at.is_(None))
            )
            .order_by(Person.current_company_verified_at.asc().nulls_first())
            .limit(settings.reverify_batch_size)
        )
        result = await db.execute(query)
        stale_people = list(result.scalars().all())

    verified_count = 0
    failed_count = 0
    skipped_count = 0

    for person in stale_people:
        if not person.company:
            skipped_count += 1
            continue

        try:
            company = person.company
            company_name = company.name
            company_domain = (
                company.domain
                if getattr(company, "domain_trusted", False)
                else None
            )
            company_slugs = effective_public_identity_slugs(
                company.name,
                getattr(company, "public_identity_slugs", None),
                identity_hints=getattr(company, "identity_hints", None),
            )

            verification = await _verify_person(
                person,
                company_name=company_name,
                company_domain=company_domain,
                company_public_identity_slugs=company_slugs,
            )
            _apply_verification_result(person, verification)

            async with async_session() as db:
                db.add(person)
                await db.commit()

            verified_count += 1
        except Exception:
            logger.exception("Failed to re-verify person %s", person.id)
            failed_count += 1

    summary = {
        "total_stale": len(stale_people),
        "verified": verified_count,
        "failed": failed_count,
        "skipped": skipped_count,
    }
    logger.info("Re-verification complete: %s", summary)
    return summary


@celery_app.task(name="app.tasks.reverify.reverify_stale_contacts")
def reverify_stale_contacts() -> dict:
    """Celery entry point for stale contact re-verification."""
    return asyncio.run(_reverify_stale_contacts())
