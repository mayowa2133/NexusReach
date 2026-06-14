"""Job read/CRUD + the per-job command center and next-action logic."""

import logging
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.company import Company
from sqlalchemy import Date
from app.models.job import Job
from app.models.message import Message
from app.models.outreach import OutreachLog
from app.models.person import Person
from app.models.profile import Profile
from app.models.resume_artifact import ResumeArtifact
from app.utils.startup_jobs import STARTUP_TAG
from app.models.tailored_resume import TailoredResume
from app.utils.job_metadata import country_code_for_name
from datetime import datetime
from app.utils.job_metadata import geocode_location_query
from app.services.job_research_snapshot_service import get_job_research_snapshot
from app.utils.company_identity import normalize_company_name
from sqlalchemy import not_
from app.services.occupation_taxonomy import occupation_tag
from sqlalchemy import or_
from sqlalchemy import func as sa_func
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from app.services.job_research_snapshot_service import serialize_snapshot
from datetime import timezone
import uuid
from app.services.jobs import normalize
from app.services.jobs import search as _search_mod


logger = logging.getLogger(__name__)


async def toggle_job_starred(
    db: AsyncSession,
    user_id: uuid.UUID,
    job_id: uuid.UUID,
    starred: bool,
) -> Job:
    """Toggle a job's starred status."""
    result = await db.execute(
        select(Job).where(Job.id == job_id, Job.user_id == user_id)
    )
    job = result.scalar_one_or_none()
    if not job:
        raise ValueError("Job not found.")

    job.starred = starred
    await db.commit()
    await db.refresh(job)
    return job


async def get_jobs(
    db: AsyncSession,
    user_id: uuid.UUID,
    stage: str | None = None,
    sort_by: str = "score",
    starred: bool | None = None,
    *,
    employment_type: str | None = None,
    experience_level: str | None = None,
    salary_min: float | None = None,
    country: str | None = None,
    near: str | None = None,
    near_lat: float | None = None,
    near_lng: float | None = None,
    radius_km: float | None = None,
    include_remote_in_radius: bool = False,
    remote: bool | None = None,
    startup: bool | None = None,
    occupations: list[str] | None = None,
    search: str | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> tuple[list[Job], int]:
    """Get saved jobs for a user with optional filtering and pagination.

    Returns ``(jobs, total_count)``.
    """
    from app.utils.pagination import paginate

    query = select(Job).where(Job.user_id == user_id)
    distance_expr = None
    if stage:
        query = query.where(Job.stage == stage)
    if starred is not None:
        query = query.where(Job.starred == starred)
    if employment_type:
        if employment_type.strip().lower() == "internship":
            query = query.where(
                or_(
                    sa_func.lower(Job.employment_type) == "internship",
                    Job.experience_level == "intern",
                )
            )
        else:
            query = query.where(Job.employment_type == employment_type)
    if experience_level:
        query = query.where(Job.experience_level == experience_level)
    if salary_min is not None:
        query = query.where(
            or_(Job.salary_max >= salary_min, Job.salary_min >= salary_min)
        )
    if country:
        country_name = country.strip()
        country_code = country_code_for_name(country_name)
        clauses = []
        if country_code:
            clauses.append(Job.country_codes.contains([country_code]))
        if country_name:
            clauses.append(Job.countries.contains([country_name]))
            clauses.append(Job.location.ilike(f"%{country_name}%"))
        if clauses:
            query = query.where(or_(*clauses))
    if near_lat is None or near_lng is None:
        geocode = geocode_location_query(near)
        if geocode:
            near_lat = geocode.latitude
            near_lng = geocode.longitude
            if radius_km is None:
                radius_km = geocode.radius_km
    if near_lat is not None and near_lng is not None:
        effective_radius_km = radius_km if radius_km is not None else 50.0
        distance_expr = normalize._distance_km_expression(near_lat, near_lng)
        local_clause = (
            Job.location_lat.is_not(None)
            & Job.location_lng.is_not(None)
            & (distance_expr <= effective_radius_km)
        )
        if include_remote_in_radius:
            query = query.where(or_(local_clause, Job.remote.is_(True)))
        else:
            query = query.where(local_clause)
    elif near:
        # Last-resort fallback for unrecognized manual entries. Known cities and
        # metro aliases use the coordinate path above.
        query = query.where(Job.location.ilike(f"%{near.strip()}%"))
    if remote is not None:
        query = query.where(Job.remote == remote)
    if startup is not None:
        if startup:
            query = query.where(Job.tags.contains([STARTUP_TAG]))
        else:
            query = query.where(or_(Job.tags.is_(None), not_(Job.tags.contains([STARTUP_TAG]))))
    if occupations:
        occupation_clauses = [
            Job.tags.contains([occupation_tag(key)]) for key in occupations if key
        ]
        if occupation_clauses:
            query = query.where(or_(*occupation_clauses))
    if search:
        term = f"%{search}%"
        query = query.where(
            Job.title.ilike(term) | Job.company_name.ilike(term)
        )

    if sort_by == "score":
        query = query.order_by(Job.match_score.desc().nullslast())
    elif sort_by == "distance" and distance_expr is not None:
        query = query.order_by(distance_expr.asc().nullslast())
    else:
        # Date sort (and default). Order by the pre-parsed, calendar-validated
        # `posted_date` column (populated at ingest), falling back to the ingest
        # timestamp. The previous approach cast a substring of the free-form
        # `posted_at` string to ::date at query time, which raised and aborted
        # the whole query on a date-shaped-but-invalid value like "2026-02-30"
        # (audit pass-2 P3). Using a real Date column is crash-proof and indexed.
        recency = sa_func.coalesce(Job.posted_date, sa_func.cast(Job.created_at, Date))
        query = query.order_by(recency.desc().nullslast(), Job.created_at.desc())

    jobs, total = await paginate(db, query, limit=limit, offset=offset)
    await _search_mod._repair_missing_apply_urls(db, jobs)
    return jobs, total


async def update_job_stage(
    db: AsyncSession,
    user_id: uuid.UUID,
    job_id: uuid.UUID,
    stage: str,
    notes: str | None = None,
) -> Job:
    """Update a job's kanban stage."""
    from datetime import datetime as _dt
    from datetime import timezone as _tz

    result = await db.execute(
        select(Job).where(Job.id == job_id, Job.user_id == user_id)
    )
    job = result.scalar_one_or_none()
    if not job:
        raise ValueError("Job not found.")

    old_stage = job.stage
    job.stage = stage
    if notes is not None:
        job.notes = notes

    # Auto-set applied_at when moving to 'applied' for the first time
    if stage == "applied" and old_stage != "applied" and not job.applied_at:
        job.applied_at = _dt.now(_tz.utc)

    await db.commit()
    await db.refresh(job)

    # Auto-draft outreach when moving to 'applied' (if enabled)
    if stage == "applied" and old_stage != "applied":
        try:
            from app.services.settings_service import get_auto_prospect  # noqa: PLC0415

            auto_settings = await get_auto_prospect(db, user_id)
            if auto_settings.get("auto_draft_on_apply"):
                from app.tasks.auto_prospect import auto_draft_for_job  # noqa: PLC0415
                auto_draft_for_job.delay(str(user_id), str(job_id))
                logger.info(
                    "Auto-draft queued on apply: user=%s job=%s", user_id, job_id,
                )
        except Exception:
            logger.debug("Auto-draft trigger check failed", exc_info=True)

    return job


async def update_interview_rounds(
    db: AsyncSession,
    user_id: uuid.UUID,
    job_id: uuid.UUID,
    rounds: list[dict],
) -> Job:
    """Update a job's interview rounds (full replacement)."""
    result = await db.execute(
        select(Job).where(Job.id == job_id, Job.user_id == user_id)
    )
    job = result.scalar_one_or_none()
    if not job:
        raise ValueError("Job not found.")

    job.interview_rounds = rounds
    await db.commit()
    await db.refresh(job)
    return job


async def update_offer_details(
    db: AsyncSession,
    user_id: uuid.UUID,
    job_id: uuid.UUID,
    offer: dict,
) -> Job:
    """Update a job's offer details."""
    result = await db.execute(
        select(Job).where(Job.id == job_id, Job.user_id == user_id)
    )
    job = result.scalar_one_or_none()
    if not job:
        raise ValueError("Job not found.")

    job.offer_details = offer
    await db.commit()
    await db.refresh(job)
    return job


async def get_job(
    db: AsyncSession,
    user_id: uuid.UUID,
    job_id: uuid.UUID,
) -> Job | None:
    """Get a single job by ID."""
    result = await db.execute(
        select(Job).where(Job.id == job_id, Job.user_id == user_id)
    )
    job = result.scalar_one_or_none()
    if job:
        await _search_mod._repair_missing_apply_urls(db, [job])
    return job


async def get_job_command_center(
    db: AsyncSession,
    user_id: uuid.UUID,
    job_id: uuid.UUID,
) -> dict | None:
    """Build a compact command-center summary for a single saved job."""
    job = await get_job(db, user_id, job_id)
    if not job:
        return None

    normalized_company = normalize_company_name(job.company_name)
    now = datetime.now(timezone.utc)

    profile_result = await db.execute(
        select(Profile).where(Profile.user_id == user_id)
    )
    profile = profile_result.scalar_one_or_none()

    contacts_result = await db.execute(
        select(Person)
        .join(Company, Person.company_id == Company.id)
        .where(
            Person.user_id == user_id,
            Company.user_id == user_id,
            Company.normalized_name == normalized_company,
        )
        .order_by(
            Person.current_company_verified.desc().nullslast(),
            Person.email_verified.desc().nullslast(),
            Person.relevance_score.desc().nullslast(),
            Person.created_at.desc(),
        )
        .options(selectinload(Person.company))
    )
    contacts = list(contacts_result.scalars().all())
    top_contacts = contacts[:4]

    tailored_result = await db.execute(
        select(TailoredResume.id)
        .where(
            TailoredResume.user_id == user_id,
            TailoredResume.job_id == job_id,
        )
        .limit(1)
    )
    has_tailored_resume = tailored_result.scalar_one_or_none() is not None

    artifact_result = await db.execute(
        select(ResumeArtifact.id)
        .where(
            ResumeArtifact.user_id == user_id,
            ResumeArtifact.job_id == job_id,
        )
        .limit(1)
    )
    has_resume_artifact = artifact_result.scalar_one_or_none() is not None

    messages_result = await db.execute(
        select(Message, Person)
        .join(Person, Message.person_id == Person.id)
        .where(
            Message.user_id == user_id,
            Message.context_snapshot["job_id"].astext == str(job_id),
        )
        .order_by(Message.created_at.desc())
        .limit(5)
    )
    recent_messages_rows = messages_result.all()

    outreach_result = await db.execute(
        select(OutreachLog)
        .where(
            OutreachLog.user_id == user_id,
            OutreachLog.job_id == job_id,
        )
        .options(selectinload(OutreachLog.person), selectinload(OutreachLog.job))
        .order_by(OutreachLog.updated_at.desc())
    )
    outreach_logs = list(outreach_result.scalars().all())
    recent_outreach = outreach_logs[:5]

    verified_contacts_count = sum(1 for person in contacts if person.current_company_verified)
    reachable_contacts_count = sum(1 for person in contacts if person.work_email or person.linkedin_url)
    active_outreach_count = sum(
        1 for log in outreach_logs if log.status in {"sent", "connected", "following_up"}
    )
    responded_outreach_count = sum(
        1 for log in outreach_logs if log.response_received or log.status in {"responded", "met", "closed"}
    )
    due_follow_ups_count = sum(
        1
        for log in outreach_logs
        if log.next_follow_up_at is not None
        and log.next_follow_up_at <= now
        and log.status != "closed"
    )

    checklist = {
        "resume_uploaded": bool(profile and profile.resume_parsed),
        "match_scored": job.match_score is not None,
        "resume_tailored": has_tailored_resume,
        "resume_artifact_generated": has_resume_artifact,
        "contacts_saved": len(contacts) > 0,
        "outreach_started": len(outreach_logs) > 0,
        "applied": job.stage in {"applied", "interviewing", "offer", "accepted", "rejected", "withdrawn"},
        "interview_rounds_logged": bool(job.interview_rounds),
    }

    stats = {
        "saved_contacts_count": len(contacts),
        "verified_contacts_count": verified_contacts_count,
        "reachable_contacts_count": reachable_contacts_count,
        "drafted_messages_count": len(recent_messages_rows),
        "outreach_count": len(outreach_logs),
        "active_outreach_count": active_outreach_count,
        "responded_outreach_count": responded_outreach_count,
        "due_follow_ups_count": due_follow_ups_count,
    }

    snapshot = await get_job_research_snapshot(db, user_id=user_id, job_id=job_id)
    research_snapshot = serialize_snapshot(snapshot)

    next_action = _determine_job_next_action(
        job=job,
        checklist=checklist,
        stats=stats,
        research_snapshot=research_snapshot,
    )

    return {
        "job_id": str(job.id),
        "research_snapshot": research_snapshot,
        "stage": job.stage,
        "checklist": checklist,
        "stats": stats,
        "next_action": next_action,
        "top_contacts": [
            {
                "id": str(person.id),
                "full_name": person.full_name,
                "title": person.title,
                "person_type": person.person_type,
                "work_email": person.work_email,
                "linkedin_url": person.linkedin_url,
                "email_verified": bool(person.email_verified),
                "current_company_verified": person.current_company_verified,
            }
            for person in top_contacts
        ],
        "recent_messages": [
            {
                "id": str(message.id),
                "person_id": str(person.id),
                "person_name": person.full_name,
                "channel": message.channel,
                "goal": message.goal,
                "status": message.status,
                "created_at": message.created_at.isoformat(),
            }
            for message, person in recent_messages_rows
        ],
        "recent_outreach": [
            {
                "id": str(log.id),
                "person_id": str(log.person_id),
                "person_name": log.person.full_name if log.person else None,
                "channel": log.channel,
                "status": log.status,
                "response_received": log.response_received,
                "last_contacted_at": log.last_contacted_at.isoformat() if log.last_contacted_at else None,
                "next_follow_up_at": log.next_follow_up_at.isoformat() if log.next_follow_up_at else None,
                "created_at": log.created_at.isoformat(),
            }
            for log in recent_outreach
        ],
    }


def _determine_job_next_action(
    *,
    job: Job,
    checklist: dict,
    stats: dict,
    research_snapshot: dict | None = None,
) -> dict:
    """Return the single highest-leverage next action for the job command center."""
    has_live_targets = bool(research_snapshot and research_snapshot.get("total_candidates", 0) > 0)
    if not checklist["resume_uploaded"]:
        return {
            "key": "upload_resume",
            "title": "Upload your resume first",
            "detail": "Resume-backed scoring and tailoring are unavailable until your profile has a parsed resume.",
            "cta_label": "Open Profile",
            "cta_section": "profile",
        }

    if not checklist["contacts_saved"] and not has_live_targets:
        return {
            "key": "find_people",
            "title": "Find people at this company",
            "detail": "You do not have saved or fresh recruiter, hiring manager, or peer matches for this role yet.",
            "cta_label": "Find People",
            "cta_section": "people",
        }

    if (
        has_live_targets
        and stats["outreach_count"] == 0
        and job.stage in {"discovered", "interested", "researching", "networking"}
    ):
        total = research_snapshot["total_candidates"] if research_snapshot else 0
        return {
            "key": "draft_live_outreach",
            "title": "Work the saved people-search results",
            "detail": (
                f"You have {total} live candidate{'s' if total != 1 else ''} stored from your latest "
                "people search. Convert that targeting into outreach."
            ),
            "cta_label": "Draft Message",
            "cta_section": "people",
        }

    if stats["due_follow_ups_count"] > 0:
        return {
            "key": "follow_up_due",
            "title": "Review overdue follow-ups",
            "detail": "At least one job-linked outreach thread is due for follow-up now.",
            "cta_label": "Review Outreach",
            "cta_section": "activity",
        }

    if not checklist["resume_tailored"] and checklist["match_scored"]:
        return {
            "key": "tailor_resume",
            "title": "Tailor your resume for this role",
            "detail": "You have a scored job but no saved tailoring suggestions for this application yet.",
            "cta_label": "Tailor Resume",
            "cta_section": "resume",
        }

    if checklist["resume_tailored"] and not checklist["resume_artifact_generated"] and job.stage in {"discovered", "interested", "researching", "networking", "applied"}:
        return {
            "key": "generate_resume_artifact",
            "title": "Generate a submission-ready resume variant",
            "detail": "Tailoring suggestions exist, but you have not saved a concrete resume artifact for this role yet.",
            "cta_label": "Generate Resume",
            "cta_section": "resume",
        }

    if job.stage in {"interviewing", "offer"} and not checklist["interview_rounds_logged"]:
        return {
            "key": "log_interviews",
            "title": "Log interview rounds",
            "detail": "Interview stage is active, but no rounds are saved on this job yet.",
            "cta_label": "Update Tracker",
            "cta_section": "stage",
        }

    if job.stage in {"discovered", "interested", "researching", "networking"} and stats["outreach_count"] == 0:
        return {
            "key": "draft_first_outreach",
            "title": "Draft your first message",
            "detail": "You already have company contacts saved for this role, but no outreach has been logged yet.",
            "cta_label": "Open Messages",
            "cta_section": "activity",
        }

    if job.stage == "applied" and stats["outreach_count"] == 0:
        return {
            "key": "post_apply_outreach",
            "title": "Start post-apply outreach",
            "detail": "This role is already in the pipeline, but no recruiter, hiring manager, or peer contact has been logged for it yet.",
            "cta_label": "Open Messages",
            "cta_section": "activity",
        }

    return {
        "key": "review_job",
        "title": "Keep this job moving",
        "detail": "The core workflow is in place. Review activity, update stage, or re-run people search if the context has changed.",
        "cta_label": "Review Activity",
        "cta_section": "activity",
    }
