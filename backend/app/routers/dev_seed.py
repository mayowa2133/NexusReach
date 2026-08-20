"""Dev-only fixture seeding for screen capture.

Gideon records product screens to build short-form marketing videos, and the
angle of the video decides what has to be on those screens: a film about landing
a marketing internship needs a marketing role in the tracker and a marketing lead
in the contacts, not whatever happened to be in the database when somebody
recorded a different video.

The product has no way to put a specific record on a specific screen. Jobs and
people arrive through discovery -- /api/jobs/search, /api/people/search -- which
reaches external services and cannot be asked for an exact row. So capture used
to assert that a record already existed and fail if it did not, which meant
somebody had put it there by hand.

This endpoint is that hand, made explicit and reproducible.

It is registered only when dev auth bypass is on, so in any other mode the route
does not exist at all rather than existing and refusing. An unmounted route
cannot be probed, and config.py already rejects that mode in production.
"""

import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user_id
from app.models.company import Company
from app.models.job import Job
from app.models.message import Message
from app.models.outreach import OutreachLog
from app.models.person import Person
from app.models.profile import Profile
from app.services.occupation_taxonomy import OCCUPATION_TAG_PREFIX
from app.services.people.classify import _classify_person

router = APIRouter(prefix="/dev", tags=["dev"])


class SeedOpportunity(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    company: str = Field(min_length=1, max_length=255)
    location: str | None = Field(default=None, max_length=255)
    stage: str = Field(default="applied", max_length=50)
    # Where this row ranks, when the caller needs it surfaced rather than merely
    # present.
    #
    # Seeding an exact record is only half of putting it on a screen. The
    # dashboard's first-win path renders the top job, and "top" is
    # match_score DESC NULLS LAST -- so an unscored seed sorts behind every
    # scored row and the panel shows a different role than the one that was
    # asked for. A screen recording of that panel then says "Product Engineer"
    # over a film about a marketing manager, which is the exact class of wrong
    # data this endpoint exists to prevent.
    #
    # Left unset the row stays unscored, which is the honest default: a seeded
    # job has not been scored by anything.
    match_score: float | None = Field(default=None, ge=0, le=100)
    # The occupation this role belongs to, as a taxonomy key ("marketing").
    #
    # Ranking is not the only thing that decides what a screen shows. The
    # dashboard buckets jobs by their occupation tag and round-robins across the
    # occupations the profile targets, so a job with no tag lands in the
    # fallback bucket and is never picked at all, whatever it scores.
    occupation: str | None = Field(default=None, max_length=100)


class SeedContact(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    role: str = Field(min_length=1, max_length=255)
    company: str | None = Field(default=None, max_length=255)
    reason: str | None = Field(default=None, max_length=500)


class SeedMessage(BaseModel):
    subject: str = Field(min_length=1, max_length=500)
    body: str = Field(min_length=1)
    channel: str = Field(default="email", max_length=50)
    goal: str = Field(default="referral", max_length=100)


class SeedOutreachEntry(BaseModel):
    """One past piece of outreach, as the account would already hold it."""

    name: str = Field(min_length=1, max_length=255)
    role: str = Field(min_length=1, max_length=255)
    company: str | None = Field(default=None, max_length=255)
    # draft | sent | connected | responded | met | following_up | closed.
    # The response rate counts responded/met/closed over everything that is not
    # a draft, so the status is the whole point of the entry.
    status: str = Field(default="sent", max_length=50)
    channel: str = Field(default="email", max_length=50)
    reply: str | None = Field(default=None, max_length=500)


class SeedRequest(BaseModel):
    # Which occupations this persona is chasing, in priority order.
    #
    # The angle decides this the same way it decides the role: a film about
    # landing a marketing manager job is a film about somebody who is looking
    # for marketing work, and the dashboard reads the profile to know that. A
    # seeded marketing role on a profile targeting software engineering is a
    # true row the product will correctly never surface.
    target_occupations: list[str] | None = None
    opportunity: SeedOpportunity | None = None
    contact: SeedContact | None = None
    message: SeedMessage | None = None
    # Outreach the account has already done.
    #
    # The response rate is computed, not stored: responded over everything that
    # is not a draft. A workspace seeded with nothing but drafts therefore reads
    # 0% forever, which is what a capture of it showed -- true of the seed,
    # false of the product, and the least useful number a demo could put on
    # screen. Seeding the history rather than the rate keeps the metric the
    # product's own arithmetic; if these entries are wrong the number is wrong
    # in the same direction, which is the point.
    outreach_history: list[SeedOutreachEntry] | None = None


class SeedResponse(BaseModel):
    job_id: uuid.UUID | None = None
    person_id: uuid.UUID | None = None
    company_id: uuid.UUID | None = None
    message_id: uuid.UUID | None = None
    created: list[str] = []
    updated: list[str] = []


def _guard() -> None:
    """Second lock on a door that should not be there at all.

    Registration is conditional, so reaching this means the settings changed
    under a running process. Refusing is cheaper than reasoning about whether
    that can happen.
    """
    if settings.auth_mode != "dev" or not settings.dev_auth_bypass_enabled:
        raise HTTPException(status_code=404, detail="Not found")


@router.post("/seed", response_model=SeedResponse)
async def seed_fixture(
    payload: SeedRequest,
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SeedResponse:
    """Put an exact record on an exact screen, idempotently.

    Idempotent by natural key -- title plus company for a job, name plus company
    for a person -- because a capture run is repeated until the framing is right,
    and a seed that appended each time would fill the tracker with duplicates of
    the row the film is meant to show.
    """
    _guard()
    response = SeedResponse()

    if payload.target_occupations is not None:
        profile = (
            await db.execute(select(Profile).where(Profile.user_id == user_id))
        ).scalars().first()
        if profile is None:
            raise HTTPException(status_code=404, detail="No profile to target")
        profile.target_occupations = payload.target_occupations
        response.updated.append("profile")

    if payload.opportunity is not None:
        opportunity = payload.opportunity
        existing = (
            await db.execute(
                select(Job).where(
                    Job.user_id == user_id,
                    Job.title == opportunity.title,
                    Job.company_name == opportunity.company,
                )
            )
        ).scalars().first()

        if existing is None:
            existing = Job(
                user_id=user_id,
                title=opportunity.title,
                company_name=opportunity.company,
                location=opportunity.location,
                stage=opportunity.stage,
                # `source` is NOT NULL: every other row arrives from a discovery
                # provider and says which. Naming this one "dev-seed" keeps that
                # column honest -- a seeded row should never be mistaken for a
                # job the product found, in a query or in a screenshot.
                source="dev-seed",
                external_id=f"dev-seed:{uuid.uuid4()}",
            )
            db.add(existing)
            response.created.append("job")
        else:
            existing.location = opportunity.location
            existing.stage = opportunity.stage
            response.updated.append("job")

        # Set on both paths, and only when asked. `scored_at` travels with it
        # because a score without a time is a row that claims to have been
        # scored by nobody, ever. `score_breakdown` is deliberately left alone:
        # it is the scorer's evidence, and inventing one would put a fabricated
        # rationale behind a number a human chose.
        if opportunity.match_score is not None:
            existing.match_score = opportunity.match_score
            existing.scored_at = datetime.now(timezone.utc)
        if opportunity.occupation:
            # Merged, not replaced: `tags` also carries skill tags the seed knows
            # nothing about, and one occupation key per job is what
            # `primaryOccupation` reads.
            tag = f"{OCCUPATION_TAG_PREFIX}{opportunity.occupation}"
            kept = [
                value
                for value in (existing.tags or [])
                if not value.startswith(OCCUPATION_TAG_PREFIX)
            ]
            existing.tags = [tag, *kept]

        await db.flush()
        response.job_id = existing.id

    if payload.contact is not None:
        contact = payload.contact
        existing_person = (
            await db.execute(
                select(Person).where(
                    Person.user_id == user_id,
                    Person.full_name == contact.name,
                )
            )
        ).scalars().first()

        # A contact needs its company as a row, not a string. The people list
        # renders the company from the relation, so a Person seeded without one
        # is a record that exists and never appears -- which is how the first
        # run captured the tracker and nothing else.
        company = None
        if contact.company:
            normalized = contact.company.strip().lower()
            company = (
                await db.execute(
                    select(Company).where(Company.user_id == user_id, Company.normalized_name == normalized)
                )
            ).scalars().first()
            if company is None:
                company = Company(
                    user_id=user_id, name=contact.company, normalized_name=normalized, domain_trusted=False
                )
                db.add(company)
                response.created.append("company")
            await db.flush()
            response.company_id = company.id

        # The bucket follows from the title, using the product's own classifier.
        #
        # A seeded Avery Chen carried person_type "recruiter" from an older
        # fixture while her title said "Head of Marketing", and the people list
        # recomputes its reason from that bucket -- so the demo told the reader
        # she was a recruiting contact. A seed that asserts a role and a bucket
        # separately is two representations of one fact, and this one had already
        # drifted apart. Assert the role; derive the bucket.
        person_type = _classify_person(contact.role)
        if existing_person is None:
            existing_person = Person(
                user_id=user_id, full_name=contact.name, title=contact.role, person_type=person_type
            )
            db.add(existing_person)
            response.created.append("person")
        else:
            existing_person.title = contact.role
            existing_person.person_type = person_type
            response.updated.append("person")
        if company is not None:
            existing_person.company_id = company.id
        # "Why matched" is read from profile_data.match_reason, not a column.
        # Merging rather than replacing: profile_data carries enrichment the
        # seed knows nothing about and must not drop.
        if contact.reason:
            existing_person.profile_data = {**(existing_person.profile_data or {}), "match_reason": contact.reason}

        await db.flush()
        response.person_id = existing_person.id

    if payload.message is not None:
        # The draft screen shows a message attached to a person, so seeding one
        # without a contact in the same call has nothing to hang off.
        if response.person_id is None:
            raise HTTPException(status_code=400, detail="message requires contact in the same request")
        message = payload.message
        existing_message = (
            await db.execute(
                select(Message).where(Message.user_id == user_id, Message.person_id == response.person_id)
            )
        ).scalars().first()
        if existing_message is None:
            existing_message = Message(
                user_id=user_id, person_id=response.person_id,
                channel=message.channel, goal=message.goal, body=message.body,
            )
            db.add(existing_message)
            response.created.append("message")
        else:
            existing_message.body = message.body
            response.updated.append("message")
        if hasattr(existing_message, "subject"):
            existing_message.subject = message.subject

        await db.flush()
        response.message_id = existing_message.id

    if payload.outreach_history:
        # Each entry becomes a person and a log, reusing either if it is already
        # there, so re-seeding is idempotent rather than cumulative -- a seed run
        # twice must not double the denominator of a rate.
        responded_states = ("responded", "met", "closed")
        now = datetime.now(timezone.utc)
        for entry in payload.outreach_history:
            person = (
                await db.execute(
                    select(Person).where(Person.user_id == user_id, Person.full_name == entry.name)
                )
            ).scalars().first()
            company = None
            if entry.company:
                normalized = entry.company.strip().lower()
                company = (
                    await db.execute(
                        select(Company).where(Company.user_id == user_id, Company.normalized_name == normalized)
                    )
                ).scalars().first()
                if company is None:
                    company = Company(
                        user_id=user_id, name=entry.company, normalized_name=normalized, domain_trusted=False
                    )
                    db.add(company)
                await db.flush()
            if person is None:
                person = Person(user_id=user_id, full_name=entry.name, title=entry.role)
                db.add(person)
                response.created.append(f"person:{entry.name}")
            else:
                person.title = entry.role
            if company is not None:
                person.company_id = company.id
            await db.flush()

            log = (
                await db.execute(
                    select(OutreachLog).where(
                        OutreachLog.user_id == user_id, OutreachLog.person_id == person.id
                    )
                )
            ).scalars().first()
            if log is None:
                log = OutreachLog(user_id=user_id, person_id=person.id)
                db.add(log)
                response.created.append(f"outreach:{entry.name}")
            else:
                response.updated.append(f"outreach:{entry.name}")
            log.status = entry.status
            log.channel = entry.channel
            # The timestamps a real log would carry, kept consistent with the
            # status: anything past draft has been sent, and only a reply has a
            # reply time. An inconsistent row would be a demo that teaches the
            # reader something untrue about the product's own model.
            replied = entry.status in responded_states
            log.sent_at = None if entry.status == "draft" else now
            log.last_contacted_at = log.sent_at
            log.response_received = replied
            log.replied_at = now if replied else None
            log.last_reply_snippet = entry.reply if replied else None
        await db.flush()

    await db.commit()
    return response
