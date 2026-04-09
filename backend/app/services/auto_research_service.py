"""Auto research preferences and job research snapshot service."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.company_auto_research import CompanyAutoResearchPreference
from app.models.job import Job
from app.schemas.linkedin_graph import LinkedInGraphConnectionResponse
from app.schemas.people import CompanyResponse, JobContextResponse, PersonResponse
from app.services.email_finder_service import find_email_for_person
from app.services.people_service import (
    DEFAULT_TARGET_COUNT_PER_BUCKET,
    search_people_for_job,
)
from app.utils.company_identity import canonical_company_display_name, normalize_company_name

logger = logging.getLogger(__name__)

JOB_RESEARCH_STATUS_NOT_CONFIGURED = "not_configured"
JOB_RESEARCH_STATUS_QUEUED = "queued"
JOB_RESEARCH_STATUS_RUNNING = "running"
JOB_RESEARCH_STATUS_COMPLETED = "completed"
JOB_RESEARCH_STATUS_FAILED = "failed"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_company_for_preference(company_name: str) -> tuple[str, str]:
    canonical = canonical_company_display_name(company_name or "")
    normalized = normalize_company_name(canonical)
    if not normalized:
        raise ValueError("Company name is required.")
    return canonical, normalized


def _serialize_company(company) -> dict | None:
    if company is None:
        return None
    return CompanyResponse.model_validate(company).model_dump(mode="json")


def _serialize_connection(connection) -> dict | None:
    if connection is None:
        return None
    return LinkedInGraphConnectionResponse.model_validate(connection).model_dump(mode="json")


def _serialize_person(person) -> dict:
    payload = {
        field: getattr(person, field, None)
        for field in PersonResponse.model_fields
        if field not in {"company", "warm_path_connection"}
    }
    payload["company"] = _serialize_company(getattr(person, "company", None))
    warm_path_connection = _serialize_connection(getattr(person, "warm_path_connection", None))
    if warm_path_connection is not None:
        payload["warm_path_connection"] = warm_path_connection
    return PersonResponse(**payload).model_dump(mode="json")


def _serialize_job_context(job_context: dict | None) -> dict | None:
    if not job_context:
        return None
    return JobContextResponse(**job_context).model_dump(mode="json")


def _serialize_people_search_result(result: dict) -> dict:
    return {
        "company": _serialize_company(result.get("company")),
        "your_connections": [
            _serialize_connection(connection)
            for connection in result.get("your_connections", [])
            if connection is not None
        ],
        "recruiters": [_serialize_person(person) for person in result.get("recruiters", [])],
        "hiring_managers": [
            _serialize_person(person) for person in result.get("hiring_managers", [])
        ],
        "peers": [_serialize_person(person) for person in result.get("peers", [])],
        "job_context": _serialize_job_context(result.get("job_context")),
        "errors": result.get("errors"),
    }


def _job_research_payload(
    *,
    job: Job,
    enabled_for_company: bool,
    auto_find_emails: bool,
    snapshot: dict | None = None,
) -> dict:
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    return {
        "status": (
            job.auto_research_status
            or (
                JOB_RESEARCH_STATUS_NOT_CONFIGURED
                if not enabled_for_company
                else JOB_RESEARCH_STATUS_NOT_CONFIGURED
            )
        ),
        "enabled_for_company": enabled_for_company,
        "auto_find_emails": auto_find_emails,
        "requested_at": job.auto_research_requested_at,
        "completed_at": job.auto_research_completed_at,
        "error": job.auto_research_error,
        "company": snapshot.get("company"),
        "your_connections": snapshot.get("your_connections", []),
        "recruiters": snapshot.get("recruiters", []),
        "hiring_managers": snapshot.get("hiring_managers", []),
        "peers": snapshot.get("peers", []),
        "job_context": snapshot.get("job_context"),
        "errors": snapshot.get("errors"),
        "email_attempted_count": int(snapshot.get("email_attempted_count") or 0),
        "email_found_count": int(snapshot.get("email_found_count") or 0),
    }


def _top_people_for_email(result: dict) -> list:
    ordered = []
    seen: set[uuid.UUID] = set()
    for bucket in ("recruiters", "hiring_managers", "peers"):
        for person in result.get(bucket, []):
            person_id = getattr(person, "id", None)
            if person_id is None or person_id in seen:
                continue
            if getattr(person, "work_email", None):
                continue
            seen.add(person_id)
            ordered.append(person)
            break
    return ordered


def _update_serialized_email_fields(people_payload: list[dict], person_id: str, email_result: dict) -> None:
    for person in people_payload:
        if person.get("id") != person_id:
            continue
        person["work_email"] = email_result.get("email")
        person["email_source"] = email_result.get("source")
        person["email_verified"] = bool(email_result.get("verified"))
        person["email_confidence"] = email_result.get("confidence")
        person["email_verification_status"] = email_result.get("email_verification_status")
        person["email_verification_method"] = email_result.get("email_verification_method")
        person["email_verification_label"] = email_result.get("email_verification_label")
        person["email_verification_evidence"] = email_result.get("email_verification_evidence")
        person["email_verified_at"] = email_result.get("email_verified_at")
        return


async def list_auto_research_preferences(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> list[CompanyAutoResearchPreference]:
    result = await db.execute(
        select(CompanyAutoResearchPreference)
        .where(CompanyAutoResearchPreference.user_id == user_id)
        .order_by(CompanyAutoResearchPreference.company_name.asc())
    )
    return list(result.scalars().all())


async def get_auto_research_preference_for_company(
    db: AsyncSession,
    user_id: uuid.UUID,
    company_name: str,
) -> CompanyAutoResearchPreference | None:
    _, normalized = _normalize_company_for_preference(company_name)
    result = await db.execute(
        select(CompanyAutoResearchPreference).where(
            CompanyAutoResearchPreference.user_id == user_id,
            CompanyAutoResearchPreference.normalized_company_name == normalized,
        )
    )
    return result.scalar_one_or_none()


async def upsert_auto_research_preference(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    company_name: str,
    auto_find_people: bool,
    auto_find_emails: bool,
) -> CompanyAutoResearchPreference:
    canonical, normalized = _normalize_company_for_preference(company_name)
    result = await db.execute(
        select(CompanyAutoResearchPreference).where(
            CompanyAutoResearchPreference.user_id == user_id,
            CompanyAutoResearchPreference.normalized_company_name == normalized,
        )
    )
    preference = result.scalar_one_or_none()
    if preference is None:
        preference = CompanyAutoResearchPreference(
            user_id=user_id,
            company_name=canonical,
            normalized_company_name=normalized,
        )
        db.add(preference)

    preference.company_name = canonical
    preference.auto_find_people = bool(auto_find_people)
    preference.auto_find_emails = bool(auto_find_people and auto_find_emails)
    await db.commit()
    await db.refresh(preference)
    return preference


async def delete_auto_research_preference(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    company_name: str,
) -> None:
    preference = await get_auto_research_preference_for_company(db, user_id, company_name)
    if preference is None:
        raise ValueError("Company auto research preference not found.")
    await db.delete(preference)
    await db.commit()


async def enqueue_auto_research_for_jobs(
    db: AsyncSession,
    user_id: uuid.UUID,
    jobs: list[Job],
) -> list[uuid.UUID]:
    if not jobs:
        return []

    normalized_names = {
        normalize_company_name(job.company_name)
        for job in jobs
        if job.company_name
    }
    result = await db.execute(
        select(CompanyAutoResearchPreference).where(
            CompanyAutoResearchPreference.user_id == user_id,
            CompanyAutoResearchPreference.auto_find_people == True,  # noqa: E712
            CompanyAutoResearchPreference.normalized_company_name.in_(normalized_names),
        )
    )
    preferences = {
        preference.normalized_company_name: preference
        for preference in result.scalars().all()
    }
    if not preferences:
        return []

    queued_job_ids: list[uuid.UUID] = []
    for job in jobs:
        normalized_name = normalize_company_name(job.company_name)
        if normalized_name not in preferences:
            continue
        if job.auto_research_status in {
            JOB_RESEARCH_STATUS_QUEUED,
            JOB_RESEARCH_STATUS_RUNNING,
            JOB_RESEARCH_STATUS_COMPLETED,
        }:
            continue
        job.auto_research_status = JOB_RESEARCH_STATUS_QUEUED
        job.auto_research_requested_at = _now()
        job.auto_research_completed_at = None
        job.auto_research_error = None
        queued_job_ids.append(job.id)

    if not queued_job_ids:
        return []

    await db.commit()

    try:
        from app.tasks.job_research import run_job_auto_research  # noqa: PLC0415

        for job_id in queued_job_ids:
            run_job_auto_research.delay(str(user_id), str(job_id))
    except Exception as exc:
        logger.exception("Failed to enqueue auto research jobs", exc_info=exc)
        for job in jobs:
            if job.id in queued_job_ids:
                job.auto_research_status = JOB_RESEARCH_STATUS_FAILED
                job.auto_research_error = f"Failed to enqueue auto research: {exc}"
        await db.commit()
        return []

    return queued_job_ids


async def run_job_research(
    db: AsyncSession,
    user_id: uuid.UUID,
    job_id: uuid.UUID,
    *,
    target_count_per_bucket: int = DEFAULT_TARGET_COUNT_PER_BUCKET,
    force: bool = False,
    auto_find_emails: bool | None = None,
) -> dict:
    result = await db.execute(select(Job).where(Job.id == job_id, Job.user_id == user_id))
    job = result.scalar_one_or_none()
    if job is None:
        raise ValueError("Job not found.")

    preference = await get_auto_research_preference_for_company(db, user_id, job.company_name)
    effective_auto_find_emails = (
        bool(preference.auto_find_emails)
        if auto_find_emails is None and preference is not None
        else bool(auto_find_emails)
    )

    if (
        not force
        and job.auto_research_status == JOB_RESEARCH_STATUS_COMPLETED
        and isinstance(job.auto_research_snapshot, dict)
    ):
        return job.auto_research_snapshot

    job.auto_research_status = JOB_RESEARCH_STATUS_RUNNING
    job.auto_research_requested_at = _now()
    job.auto_research_completed_at = None
    job.auto_research_error = None
    await db.commit()

    try:
        research_result = await search_people_for_job(
            db=db,
            user_id=user_id,
            job_id=job_id,
            target_count_per_bucket=target_count_per_bucket,
        )
        serialized_result = _serialize_people_search_result(research_result)

        email_attempted_person_ids: list[str] = []
        email_found_person_ids: list[str] = []
        if effective_auto_find_emails:
            for person in _top_people_for_email(research_result):
                person_id = str(person.id)
                email_attempted_person_ids.append(person_id)
                try:
                    email_result = await find_email_for_person(
                        db=db,
                        user_id=user_id,
                        person_id=person.id,
                        mode="best_effort",
                    )
                except Exception:
                    logger.exception("Auto email lookup failed for person %s", person_id)
                    continue

                if email_result.get("email"):
                    email_found_person_ids.append(person_id)
                for bucket_name in ("recruiters", "hiring_managers", "peers"):
                    _update_serialized_email_fields(
                        serialized_result[bucket_name],
                        person_id,
                        email_result,
                    )

        job.auto_research_snapshot = {
            **serialized_result,
            "email_attempted_person_ids": email_attempted_person_ids,
            "email_found_person_ids": email_found_person_ids,
            "email_attempted_count": len(email_attempted_person_ids),
            "email_found_count": len(email_found_person_ids),
        }
        job.auto_research_status = JOB_RESEARCH_STATUS_COMPLETED
        job.auto_research_completed_at = _now()
        job.auto_research_error = None
        await db.commit()
        return research_result
    except Exception as exc:
        job.auto_research_status = JOB_RESEARCH_STATUS_FAILED
        job.auto_research_completed_at = _now()
        job.auto_research_error = str(exc)
        await db.commit()
        raise


async def get_job_research(
    db: AsyncSession,
    user_id: uuid.UUID,
    job_id: uuid.UUID,
) -> dict:
    result = await db.execute(select(Job).where(Job.id == job_id, Job.user_id == user_id))
    job = result.scalar_one_or_none()
    if job is None:
        raise ValueError("Job not found.")

    preference = await get_auto_research_preference_for_company(db, user_id, job.company_name)
    enabled_for_company = preference is not None and preference.auto_find_people
    auto_find_emails = bool(preference.auto_find_emails) if preference is not None else False
    snapshot = job.auto_research_snapshot if isinstance(job.auto_research_snapshot, dict) else None

    return _job_research_payload(
        job=job,
        enabled_for_company=enabled_for_company,
        auto_find_emails=auto_find_emails,
        snapshot=snapshot,
    )
