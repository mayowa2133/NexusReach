"""Message drafting service — assembles context, calls Claude, stores drafts."""

import uuid
from datetime import datetime, timezone, timedelta

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.clients import claude_client
from app.models.message import Message
from app.models.person import Person
from app.models.profile import Profile
from app.models.company import Company


# --- Prompt templates ---

SYSTEM_PROMPT = """You are NexusReach, an AI assistant that helps job seekers write personalized, authentic networking messages. You draft messages that feel human — not templated or salesy.

RULES:
- Be genuine and specific. Reference real details about the person and the user.
- Keep the tone {tone}. Match the user's natural voice.
- Never be pushy. The goal is starting a real conversation, not closing a deal.
- For LinkedIn connection notes, keep it under 300 characters.
- For LinkedIn messages, keep it under 1000 characters.
- For emails, include a clear subject line on the first line formatted as "Subject: ..."
- For follow-ups, acknowledge the previous outreach without being passive-aggressive.
- For thank-yous, be specific about what you're grateful for.

OUTPUT FORMAT:
First, wrap your reasoning in <reasoning>...</reasoning> tags explaining:
- Why you chose this angle
- What specific details you leveraged
- Why this approach will resonate with this person

Then write the message directly (no extra formatting or labels).
{channel_instructions}"""

CHANNEL_INSTRUCTIONS = {
    "linkedin_note": "\nThis is a LinkedIn connection request note. Max 300 characters. Be concise — one compelling reason to connect.",
    "linkedin_message": "\nThis is a LinkedIn direct message. Be conversational but respectful. Keep it under 1000 characters.",
    "email": "\nThis is a professional email. Start with 'Subject: ...' on the first line, then a blank line, then the body. Include a greeting, body, and sign-off.",
    "follow_up": "\nThis is a follow-up message to previous outreach. Acknowledge the prior contact. Add new value — don't just say 'bumping this.'",
    "thank_you": "\nThis is a thank-you message after a conversation or meeting. Be specific about what was valuable.",
}

GOAL_CONTEXT = {
    "intro": "The user wants to introduce themselves and start a professional relationship.",
    "coffee_chat": "The user wants to request a casual informational chat (virtual coffee).",
    "referral": "The user wants to ask about internal referral opportunities for open roles.",
    "informational": "The user wants to learn about the person's role, team, or company culture.",
    "follow_up": "The user is following up on a previous message that didn't get a response.",
    "thank_you": "The user wants to thank this person after a conversation or interaction.",
}


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

    # Resume highlights
    if profile.resume_parsed:
        parsed = profile.resume_parsed
        if parsed.get("skills"):
            parts.append(f"Key skills: {', '.join(parsed['skills'][:10])}")
        if parsed.get("experience"):
            latest = parsed["experience"][0]
            parts.append(f"Current/recent role: {latest.get('title', '')} at {latest.get('company', '')}")
        if parsed.get("projects"):
            proj_names = [p.get("name", "") for p in parsed["projects"][:3] if p.get("name")]
            if proj_names:
                parts.append(f"Notable projects: {', '.join(proj_names)}")

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

    # Company info
    if person.company:
        company = person.company
        parts.append(f"Company: {company.name}")
        if company.industry:
            parts.append(f"Industry: {company.industry}")
        if company.size:
            parts.append(f"Company size: {company.size}")
        if company.description:
            parts.append(f"Company description: {company.description[:200]}")

    # GitHub activity
    if person.github_data:
        gh = person.github_data
        if gh.get("languages"):
            parts.append(f"GitHub languages: {', '.join(gh['languages'])}")
        if gh.get("repos"):
            repo_names = [r.get("name", "") for r in gh["repos"][:3] if r.get("name")]
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

    lines.append("\nIMPORTANT: The user has contacted this person before. Acknowledge the history naturally — don't repeat the same approach.")
    return "\n".join(lines)


async def draft_message(
    db: AsyncSession,
    user_id: uuid.UUID,
    person_id: uuid.UUID,
    channel: str,
    goal: str,
) -> dict:
    """Draft a personalized message for a person.

    Returns the created Message record plus reasoning and token usage.
    """
    # Load user profile
    result = await db.execute(
        select(Profile).where(Profile.user_id == user_id)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise ValueError("Please complete your profile before drafting messages.")

    # Load target person with company
    result = await db.execute(
        select(Person)
        .options(selectinload(Person.company))
        .where(Person.id == person_id, Person.user_id == user_id)
    )
    person = result.scalar_one_or_none()
    if not person:
        raise ValueError("Person not found.")

    # Load prior messages to this person (re-engagement awareness)
    result = await db.execute(
        select(Message)
        .where(Message.user_id == user_id, Message.person_id == person_id)
        .order_by(Message.created_at.desc())
        .limit(5)
    )
    prior_messages = list(result.scalars().all())

    # Build prompts
    tone = profile.tone or "conversational"
    channel_instr = CHANNEL_INSTRUCTIONS.get(channel, "")
    system = SYSTEM_PROMPT.format(tone=tone, channel_instructions=channel_instr)

    user_context = _build_user_context(profile)
    person_context = _build_person_context(person)
    history_context = _build_history_context(prior_messages)
    goal_context = GOAL_CONTEXT.get(goal, f"The user's goal: {goal}")

    user_prompt = f"""Draft a {channel.replace('_', ' ')} message.

GOAL: {goal_context}

ABOUT ME (the sender):
{user_context}

ABOUT THE RECIPIENT:
{person_context}
{history_context}"""

    # Call Claude
    ai_result = await claude_client.generate_message(
        system_prompt=system,
        user_prompt=user_prompt,
    )

    # Parse email subject if channel is email
    subject = None
    body = ai_result["draft"]
    if channel == "email" and body.lower().startswith("subject:"):
        lines = body.split("\n", 1)
        subject = lines[0].replace("Subject:", "").replace("subject:", "").strip()
        body = lines[1].strip() if len(lines) > 1 else ""

    # Determine version number
    version = len(prior_messages) + 1

    # Store the message
    message = Message(
        user_id=user_id,
        person_id=person_id,
        channel=channel,
        goal=goal,
        subject=subject,
        body=body,
        reasoning=ai_result["reasoning"],
        ai_model=ai_result["model"],
        token_usage=ai_result["usage"],
        context_snapshot={
            "user_context": user_context,
            "person_context": person_context,
            "goal": goal,
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
