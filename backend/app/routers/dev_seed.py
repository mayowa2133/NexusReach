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
from app.models.person import Person

router = APIRouter(prefix="/dev", tags=["dev"])


class SeedOpportunity(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    company: str = Field(min_length=1, max_length=255)
    location: str | None = Field(default=None, max_length=255)
    stage: str = Field(default="applied", max_length=50)


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


class SeedRequest(BaseModel):
    opportunity: SeedOpportunity | None = None
    contact: SeedContact | None = None
    message: SeedMessage | None = None


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

        if existing_person is None:
            existing_person = Person(user_id=user_id, full_name=contact.name, title=contact.role)
            db.add(existing_person)
            response.created.append("person")
        else:
            existing_person.title = contact.role
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

    await db.commit()
    return response
