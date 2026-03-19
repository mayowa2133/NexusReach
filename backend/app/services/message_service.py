"""Message drafting service — assembles context, calls Claude, stores drafts."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import nullslast, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.clients import llm_client
from app.models.job import Job
from app.models.message import Message
from app.models.outreach import OutreachLog
from app.models.person import Person
from app.models.profile import Profile
from app.models.settings import UserSettings
from app.services import api_usage_service
from app.services.email_finder_service import find_email_for_person
from app.utils.job_context import extract_job_context


LEGACY_GOAL_ALIASES = {
    "intro": "warm_intro",
    "coffee_chat": "warm_intro",
    "informational": "warm_intro",
}

SYSTEM_PROMPT = """You are NexusReach, an AI assistant that helps job seekers write personalized, authentic networking messages. You are writing with one objective: help the user move closer to getting this job or the right internal path toward it.

RULES:
- Be genuine and specific. Reference real details about the person, company, user, and role when available.
- Keep the tone {tone}. Match the user's natural voice.
- Give the message one clear primary ask and at most one fallback ask.
- The fallback ask should only appear as a brief redirect if this person is not the right owner.
- Do not use generic "let's connect" wording unless the goal is explicitly warm_intro.
- Never ask a peer directly for an interview. Ask for the best path into the team, a referral, or the right contact instead.
- For LinkedIn connection notes, keep it under 300 characters.
- For LinkedIn messages, keep it under 1000 characters.
- For emails, include a clear subject line on the first line formatted as "Subject: ..."
- For follow-ups, acknowledge the previous outreach without being passive-aggressive.
- For thank-yous, be specific about what was valuable and reinforce the next job-relevant step.

RECIPIENT PLAYBOOK:
{recipient_playbook}

GOAL PLAYBOOK:
{goal_instructions}

PRIMARY CTA:
{primary_cta_instruction}

FALLBACK CTA:
{fallback_instructions}

OUTPUT FORMAT:
First, wrap your reasoning in <reasoning>...</reasoning> tags explaining:
- Why you chose this angle
- What specific details you leveraged
- Why this approach will resonate with this person

Then write the message directly (no extra formatting or labels).
{channel_instructions}"""

CHANNEL_INSTRUCTIONS = {
    "linkedin_note": "\nThis is a LinkedIn connection request note. Max 300 characters. Be concise with one compelling reason to connect.",
    "linkedin_message": "\nThis is a LinkedIn direct message. Be conversational but respectful. Keep it under 1000 characters.",
    "email": "\nThis is a professional email. Start with 'Subject: ...' on the first line, then a blank line, then the body. Include a greeting, body, and sign-off.",
    "follow_up": "\nThis is a follow-up message to previous outreach. Acknowledge the prior contact and add fresh value tied to the role or ask.",
    "thank_you": "\nThis is a thank-you message after a conversation or meeting. Be specific about what was valuable and reinforce the next step when appropriate.",
}

GOAL_CONTEXT = {
    "interview": "The user wants to move closer to interview consideration for a specific role or team.",
    "referral": "The user wants to ask for a referral or for the best internal path toward a referral.",
    "warm_intro": "The user wants a warm introduction, advice, or a pointer to the best person to speak with.",
    "follow_up": "The user is following up on a previous message and should continue the original job-focused angle.",
    "thank_you": "The user wants to thank this person while reinforcing the relevant next step toward the role or referral path.",
}

RECIPIENT_PLAYBOOKS = {
    "recruiter": """Recruiter strategy: emphasize role fit, signal readiness, and ask for the next step toward interview consideration. If they are not the owner, briefly ask who on recruiting or the hiring team is best for this role.""",
    "hiring_manager": """Hiring manager strategy: emphasize fit for the team, role, or problem space. Ask about the best path into the team or openness to brief consideration. If they are not the right contact, briefly ask which recruiter or teammate is best.""",
    "peer": """Peer strategy: keep the tone collaborative. Ask for advice, referral comfort, or the best path to the right person. Do not ask the peer to give you an interview directly.""",
}

PRIMARY_CTA_INSTRUCTIONS = {
    "interview": "The message should ask for the clearest next step toward interview consideration or team review.",
    "referral": "The message should ask whether the recipient would feel comfortable referring the user or pointing them to the referral path.",
    "warm_intro": "The message should ask for a warm intro, relevant advice, or the best person to contact next.",
    "redirect": "The message should ask for the right recruiter, hiring manager, or teammate if this person is not the best contact.",
}

STRATEGY_HINTS = {
    "recruiter": "Recruiter strategy: fit + next step",
    "hiring_manager": "Hiring manager strategy: team fit + best path in",
    "peer": "Peer strategy: intro/referral path",
}

HTML_TAG_RE = re.compile(r"<[^>]+>")
WHITESPACE_RE = re.compile(r"\s+")
BATCH_DRAFT_LIMIT = 10


def _normalize_goal(goal: str) -> str:
    return LEGACY_GOAL_ALIASES.get(goal, goal)


def _normalize_person_type(person_type: str | None) -> str:
    if person_type in {"recruiter", "hiring_manager", "peer"}:
        return person_type
    return "peer"


def _strip_html(text: str | None) -> str:
    if not text:
        return ""
    return WHITESPACE_RE.sub(" ", HTML_TAG_RE.sub(" ", text)).strip()


def _extract_prior_strategy(prior_messages: list[Message]) -> tuple[str | None, str | None]:
    for message in prior_messages:
        snapshot = message.context_snapshot if isinstance(message.context_snapshot, dict) else {}
        primary = snapshot.get("primary_cta")
        fallback = snapshot.get("fallback_cta")
        if primary:
            return primary, fallback if isinstance(fallback, str) else None
    return None, None


def _resolve_cta_plan(
    recipient_strategy: str,
    goal: str,
    prior_messages: list[Message],
) -> tuple[str, str | None]:
    prior_primary, prior_fallback = _extract_prior_strategy(prior_messages)
    if goal in {"follow_up", "thank_you"}:
        if prior_primary:
            return prior_primary, prior_fallback
        if recipient_strategy == "peer":
            return "warm_intro", "redirect"
        return "interview", "redirect"

    if recipient_strategy == "peer":
        if goal == "interview":
            return "redirect", "referral"
        if goal == "referral":
            return "referral", "redirect"
        return "warm_intro", "redirect"

    if goal == "referral":
        return "referral", "redirect"
    if goal == "warm_intro":
        return "warm_intro", "redirect"
    return "interview", "redirect"


def _build_goal_instructions(
    normalized_goal: str,
    primary_cta: str,
    recipient_strategy: str,
) -> str:
    goal_context = GOAL_CONTEXT.get(normalized_goal, f"The user's goal is: {normalized_goal}")
    extras: list[str] = [goal_context]
    if recipient_strategy == "peer" and normalized_goal == "interview":
        extras.append("Because this is a peer, the message should ask for the best path into the team rather than asking for an interview outright.")
    if normalized_goal == "referral":
        extras.append("Keep the referral ask respectful and easy to decline.")
    if normalized_goal == "warm_intro":
        extras.append("The message can ask for advice or the right internal contact, but it should still be tied to the job search outcome.")
    if normalized_goal in {"follow_up", "thank_you"}:
        extras.append("Reuse the established angle from prior outreach rather than changing to a new generic networking ask.")
    extras.append(f"The primary ask for this draft is: {primary_cta}.")
    return " ".join(extras)


def _build_fallback_instructions(fallback_cta: str | None) -> str:
    if fallback_cta == "redirect":
        return "If the recipient does not seem like the right owner, briefly ask who on recruiting, the hiring team, or the adjacent team would be the best person to speak with."
    if fallback_cta == "referral":
        return "If the direct ask is not appropriate, briefly ask whether they would feel comfortable referring the user or introducing them to the right person."
    return "Do not include a fallback ask."


def _build_strategy_hint(recipient_strategy: str, goal: str) -> str:
    if recipient_strategy == "peer" and goal == "interview":
        return "Peer strategy: best path into the team, not a direct interview ask"
    return STRATEGY_HINTS.get(recipient_strategy, "Job-focused strategy")


def _build_job_context(job: Job | None) -> tuple[str, dict | None]:
    if not job:
        return "", None

    context = extract_job_context(job.title, job.description)
    summary = _strip_html(job.description)[:280]
    summary = f"{summary}..." if len(_strip_html(job.description)) > 280 else summary

    details = [
        f"Target job title: {job.title}",
        f"Company: {job.company_name}",
    ]
    if job.location:
        details.append(f"Location: {job.location}")
    if job.remote:
        details.append("Remote: yes")
    if job.department or context.department:
        details.append(f"Department: {job.department or context.department}")
    if context.seniority:
        details.append(f"Seniority: {context.seniority}")
    if context.team_keywords:
        details.append(f"Technical focus: {', '.join(context.team_keywords)}")
    if context.domain_keywords:
        details.append(f"Domain focus: {', '.join(context.domain_keywords)}")
    if summary:
        details.append(f"Role summary: {summary}")

    snapshot = {
        "id": str(job.id),
        "title": job.title,
        "company_name": job.company_name,
        "location": job.location,
        "remote": job.remote,
        "department": job.department or context.department,
        "seniority": context.seniority,
        "team_keywords": context.team_keywords,
        "domain_keywords": context.domain_keywords,
        "summary": summary or None,
    }

    return "\n".join(details), snapshot


def _build_user_context(profile: Profile) -> str:
    """Build the user context section from their profile."""
    parts = [f"Name: {profile.full_name or 'Not provided'}"]

    if profile.bio:
        parts.append(f"Bio: {profile.bio}")

    if profile.goals:
        parts.append(f"Goals: {', '.join(profile.goals)}")

    if profile.target_roles:
        parts.append(f"Target roles: {', '.join(profile.target_roles)}")

    if profile.target_industries:
        parts.append(f"Target industries: {', '.join(profile.target_industries)}")

    if profile.resume_parsed:
        parsed = profile.resume_parsed
        if parsed.get("skills"):
            parts.append(f"Key skills: {', '.join(parsed['skills'][:10])}")
        if parsed.get("experience"):
            latest = parsed["experience"][0]
            parts.append(f"Current/recent role: {latest.get('title', '')} at {latest.get('company', '')}")
        if parsed.get("projects"):
            project_names = [project.get("name", "") for project in parsed["projects"][:3] if project.get("name")]
            if project_names:
                parts.append(f"Notable projects: {', '.join(project_names)}")

    if profile.linkedin_url:
        parts.append(f"LinkedIn: {profile.linkedin_url}")
    if profile.github_url:
        parts.append(f"GitHub: {profile.github_url}")

    return "\n".join(parts)


def _build_person_context(person: Person) -> str:
    """Build the target person context section."""
    parts = [f"Name: {person.full_name or 'Unknown'}"]

    if person.title:
        parts.append(f"Title: {person.title}")
    if person.department:
        parts.append(f"Department: {person.department}")
    if person.person_type:
        parts.append(f"Role type: {person.person_type}")

    if person.company:
        company = person.company
        parts.append(f"Company: {company.name}")
        if company.industry:
            parts.append(f"Industry: {company.industry}")
        if company.size:
            parts.append(f"Company size: {company.size}")
        if company.description:
            parts.append(f"Company description: {company.description[:200]}")

    if person.github_data:
        github = person.github_data
        if github.get("languages"):
            parts.append(f"GitHub languages: {', '.join(github['languages'])}")
        if github.get("repos"):
            repo_names = [repo.get("name", "") for repo in github["repos"][:3] if repo.get("name")]
            if repo_names:
                parts.append(f"Notable repos: {', '.join(repo_names)}")

    if person.linkedin_url:
        parts.append(f"LinkedIn: {person.linkedin_url}")
    if person.github_url:
        parts.append(f"GitHub: {person.github_url}")

    return "\n".join(parts)


def _build_history_context(prior_messages: list[Message]) -> str:
    """Build outreach history context for re-engagement awareness."""
    if not prior_messages:
        return ""

    lines = ["PREVIOUS OUTREACH HISTORY (most recent first):"]
    for msg in prior_messages[:5]:
        date_str = msg.created_at.strftime("%Y-%m-%d")
        lines.append(f"- [{date_str}] {msg.channel} ({msg.goal}): {msg.body[:100]}...")

    lines.append("\nIMPORTANT: The user has contacted this person before. Acknowledge the history naturally and continue the same job-focused strategy unless the context clearly changed.")
    return "\n".join(lines)


async def _load_guardrails(db: AsyncSession, user_id: uuid.UUID) -> tuple[bool, int]:
    result = await db.execute(select(UserSettings).where(UserSettings.user_id == user_id))
    settings = result.scalar_one_or_none()
    if not settings:
        return True, 7
    return settings.min_message_gap_enabled, settings.min_message_gap_days


async def _recent_outreach_by_person(
    db: AsyncSession,
    user_id: uuid.UUID,
    person_ids: list[uuid.UUID],
) -> dict[uuid.UUID, datetime]:
    if not person_ids:
        return {}

    result = await db.execute(
        select(OutreachLog)
        .where(
            OutreachLog.user_id == user_id,
            OutreachLog.person_id.in_(person_ids),
        )
        .order_by(
            OutreachLog.person_id,
            nullslast(OutreachLog.last_contacted_at.desc()),
            OutreachLog.created_at.desc(),
        )
    )
    recent: dict[uuid.UUID, datetime] = {}
    for log in result.scalars().all():
        if log.person_id in recent:
            continue
        recent[log.person_id] = log.last_contacted_at or log.created_at
    return recent


def _is_recent_contact(
    last_contacted_at: datetime | None,
    *,
    gap_days: int,
) -> bool:
    if not last_contacted_at:
        return False
    if last_contacted_at.tzinfo is None:
        last_contacted_at = last_contacted_at.replace(tzinfo=timezone.utc)
    return last_contacted_at >= datetime.now(timezone.utc) - timedelta(days=gap_days)


def _item_reason(email_result: dict | None, default_reason: str) -> str:
    if email_result and email_result.get("failure_reasons"):
        return str(email_result["failure_reasons"][0])
    return default_reason


async def batch_draft_messages(
    db: AsyncSession,
    user_id: uuid.UUID,
    person_ids: list[uuid.UUID],
    goal: str,
    job_id: uuid.UUID | None = None,
    include_recent_contacts: bool = False,
) -> dict:
    """Draft individualized email messages for multiple saved people."""
    if not person_ids:
        raise ValueError("Select at least one person.")
    if len(person_ids) > BATCH_DRAFT_LIMIT:
        raise ValueError(f"Batch drafting is limited to {BATCH_DRAFT_LIMIT} contacts.")

    result = await db.execute(select(Profile).where(Profile.user_id == user_id))
    profile = result.scalar_one_or_none()
    if not profile:
        raise ValueError("Please complete your profile before drafting messages.")

    unique_person_ids = list(dict.fromkeys(person_ids))
    result = await db.execute(
        select(Person)
        .options(selectinload(Person.company))
        .where(Person.id.in_(unique_person_ids), Person.user_id == user_id)
    )
    people_map = {person.id: person for person in result.scalars().all()}
    min_gap_enabled, min_gap_days = await _load_guardrails(db, user_id)
    recent_outreach_map = await _recent_outreach_by_person(db, user_id, unique_person_ids)

    items: list[dict] = []
    seen: set[uuid.UUID] = set()
    ready_count = 0
    skipped_count = 0
    failed_count = 0

    for person_id in person_ids:
        if person_id in seen:
            skipped_count += 1
            items.append(
                {
                    "status": "skipped",
                    "person": people_map.get(person_id),
                    "message": None,
                    "reason": "duplicate_selection",
                }
            )
            continue
        seen.add(person_id)

        person = people_map.get(person_id)
        if not person:
            skipped_count += 1
            items.append(
                {
                    "status": "skipped",
                    "person": None,
                    "message": None,
                    "reason": "person_not_found",
                }
            )
            continue

        last_contacted_at = recent_outreach_map.get(person_id)
        if min_gap_enabled and not include_recent_contacts and _is_recent_contact(
            last_contacted_at,
            gap_days=min_gap_days,
        ):
            skipped_count += 1
            items.append(
                {
                    "status": "skipped",
                    "person": person,
                    "message": None,
                    "reason": "recent_outreach_within_gap",
                }
            )
            continue

        try:
            email_result = await find_email_for_person(
                db=db,
                user_id=user_id,
                person_id=person_id,
                mode="best_effort",
            )
            await db.refresh(person)
        except ValueError:
            skipped_count += 1
            items.append(
                {
                    "status": "skipped",
                    "person": None,
                    "message": None,
                    "reason": "person_not_found",
                }
            )
            continue

        if not email_result.get("email"):
            skipped_count += 1
            items.append(
                {
                    "status": "skipped",
                    "person": person,
                    "message": None,
                    "reason": _item_reason(email_result, "no_usable_email"),
                }
            )
            continue

        if email_result.get("result_type") not in {"verified", "best_guess"}:
            skipped_count += 1
            items.append(
                {
                    "status": "skipped",
                    "person": person,
                    "message": None,
                    "reason": "email_not_eligible",
                }
            )
            continue

        try:
            draft_result = await draft_message(
                db=db,
                user_id=user_id,
                person_id=person_id,
                channel="email",
                goal=goal,
                job_id=job_id,
            )
        except ValueError:
            failed_count += 1
            items.append(
                {
                    "status": "failed",
                    "person": person,
                    "message": None,
                    "reason": "draft_generation_failed",
                }
            )
            continue

        ready_count += 1
        items.append(
            {
                "status": "ready",
                "person": person,
                "message": draft_result["message"],
                "reason": None,
            }
        )

    return {
        "requested_count": len(person_ids),
        "ready_count": ready_count,
        "skipped_count": skipped_count,
        "failed_count": failed_count,
        "items": items,
    }


async def draft_message(
    db: AsyncSession,
    user_id: uuid.UUID,
    person_id: uuid.UUID,
    channel: str,
    goal: str,
    job_id: uuid.UUID | None = None,
) -> dict:
    """Draft a personalized message for a person."""
    result = await db.execute(select(Profile).where(Profile.user_id == user_id))
    profile = result.scalar_one_or_none()
    if not profile:
        raise ValueError("Please complete your profile before drafting messages.")

    result = await db.execute(
        select(Person)
        .options(selectinload(Person.company))
        .where(Person.id == person_id, Person.user_id == user_id)
    )
    person = result.scalar_one_or_none()
    if not person:
        raise ValueError("Person not found.")

    result = await db.execute(
        select(Message)
        .where(Message.user_id == user_id, Message.person_id == person_id)
        .order_by(Message.created_at.desc())
        .limit(5)
    )
    prior_messages = list(result.scalars().all())

    job = None
    if job_id:
        result = await db.execute(
            select(Job).where(Job.id == job_id, Job.user_id == user_id)
        )
        job = result.scalar_one_or_none()
        if not job:
            raise ValueError("Saved job not found.")

    normalized_goal = _normalize_goal(goal)
    recipient_strategy = _normalize_person_type(person.person_type)
    primary_cta, fallback_cta = _resolve_cta_plan(recipient_strategy, normalized_goal, prior_messages)
    strategy_hint = _build_strategy_hint(recipient_strategy, normalized_goal)

    tone = profile.tone or "conversational"
    system = SYSTEM_PROMPT.format(
        tone=tone,
        channel_instructions=CHANNEL_INSTRUCTIONS.get(channel, ""),
        recipient_playbook=RECIPIENT_PLAYBOOKS[recipient_strategy],
        goal_instructions=_build_goal_instructions(normalized_goal, primary_cta, recipient_strategy),
        primary_cta_instruction=PRIMARY_CTA_INSTRUCTIONS[primary_cta],
        fallback_instructions=_build_fallback_instructions(fallback_cta),
    )

    user_context = _build_user_context(profile)
    person_context = _build_person_context(person)
    history_context = _build_history_context(prior_messages)
    job_context_text, job_context_snapshot = _build_job_context(job)

    user_prompt_sections = [
        f"Draft a {channel.replace('_', ' ')} message.",
        "",
        f"REQUESTED GOAL: {goal}",
        f"NORMALIZED GOAL: {normalized_goal}",
        f"RECIPIENT STRATEGY: {recipient_strategy}",
        f"PRIMARY CTA: {primary_cta}",
        f"FALLBACK CTA: {fallback_cta or 'none'}",
        f"STRATEGY HINT: {strategy_hint}",
        "",
        "ABOUT ME (the sender):",
        user_context,
        "",
        "ABOUT THE RECIPIENT:",
        person_context,
    ]

    if job_context_text:
        user_prompt_sections.extend([
            "",
            "TARGET JOB CONTEXT:",
            job_context_text,
            "Prefer wording like 'this role' or 'this team' over generic references to opportunities at the company.",
        ])

    if history_context:
        user_prompt_sections.extend(["", history_context])

    user_prompt = "\n".join(user_prompt_sections)

    await api_usage_service.check_daily_limit(db, user_id)
    ai_result = await llm_client.generate_message(
        system_prompt=system,
        user_prompt=user_prompt,
    )

    usage = ai_result.get("usage", {})
    await api_usage_service.record_usage(
        db=db,
        user_id=user_id,
        service=ai_result.get("provider", "unknown"),
        endpoint="messages.draft",
        tokens_in=usage.get("input_tokens"),
        tokens_out=usage.get("output_tokens"),
    )

    subject = None
    body = ai_result["draft"]
    if channel == "email" and body.lower().startswith("subject:"):
        lines = body.split("\n", 1)
        subject = lines[0].replace("Subject:", "").replace("subject:", "").strip()
        body = lines[1].strip() if len(lines) > 1 else ""

    version = len(prior_messages) + 1
    message = Message(
        user_id=user_id,
        person_id=person_id,
        channel=channel,
        goal=normalized_goal,
        subject=subject,
        body=body,
        reasoning=ai_result["reasoning"],
        ai_model=ai_result["model"],
        token_usage=ai_result["usage"],
        context_snapshot={
            "user_context": user_context,
            "person_context": person_context,
            "goal": normalized_goal,
            "requested_goal": goal,
            "recipient_strategy": recipient_strategy,
            "primary_cta": primary_cta,
            "fallback_cta": fallback_cta,
            "job_id": str(job.id) if job else None,
            "job_context": job_context_snapshot,
            "strategy_hint": strategy_hint,
        },
        status="draft",
        version=version,
        parent_id=prior_messages[0].id if prior_messages else None,
    )
    db.add(message)
    await db.commit()
    await db.refresh(message)

    return {
        "message": message,
        "person": person,
        "reasoning": ai_result["reasoning"],
        "token_usage": ai_result["usage"],
        "recipient_strategy": recipient_strategy,
        "primary_cta": primary_cta,
        "fallback_cta": fallback_cta,
        "job_id": str(job.id) if job else None,
    }


async def update_message(
    db: AsyncSession,
    user_id: uuid.UUID,
    message_id: uuid.UUID,
    body: str,
    subject: str | None = None,
) -> Message:
    """Update a message draft (user editing)."""
    result = await db.execute(
        select(Message).where(
            Message.id == message_id,
            Message.user_id == user_id,
        )
    )
    message = result.scalar_one_or_none()
    if not message:
        raise ValueError("Message not found.")

    message.body = body
    if subject is not None:
        message.subject = subject
    message.status = "edited"
    await db.commit()
    await db.refresh(message)
    return message


async def mark_copied(
    db: AsyncSession,
    user_id: uuid.UUID,
    message_id: uuid.UUID,
) -> Message:
    """Mark a message as copied to clipboard."""
    result = await db.execute(
        select(Message).where(
            Message.id == message_id,
            Message.user_id == user_id,
        )
    )
    message = result.scalar_one_or_none()
    if not message:
        raise ValueError("Message not found.")

    message.status = "copied"
    await db.commit()
    await db.refresh(message)
    return message


async def get_messages(
    db: AsyncSession,
    user_id: uuid.UUID,
    person_id: uuid.UUID | None = None,
) -> list[Message]:
    """Get all messages for a user, optionally filtered by person."""
    query = select(Message).where(Message.user_id == user_id)
    if person_id:
        query = query.where(Message.person_id == person_id)
    query = query.order_by(Message.created_at.desc())

    result = await db.execute(query)
    return list(result.scalars().all())


async def get_message(
    db: AsyncSession,
    user_id: uuid.UUID,
    message_id: uuid.UUID,
) -> Message | None:
    """Get a single message by ID."""
    result = await db.execute(
        select(Message).where(
            Message.id == message_id,
            Message.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()
