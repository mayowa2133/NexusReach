"""Ambient 'Save to NexusReach' profile capture (Workstream E)."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.company import Company
from app.models.person import Person
from app.services.people.persistence import capture_linkedin_profile

pytestmark = pytest.mark.asyncio

USER_ID = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")


def _db_with_existing(person: Person | None) -> AsyncMock:
    db = AsyncMock()
    db.add = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = person
    db.execute.return_value = result
    return db


def _company() -> Company:
    return Company(
        id=uuid.uuid4(),
        user_id=USER_ID,
        name="Acme",
        normalized_name="acme",
    )


PAYLOAD = {
    "linkedin_url": "https://www.linkedin.com/in/jane-doe/",
    "visible_name": "Jane Doe",
    "current_role_title": "Staff Engineer",
    "current_company_label": "Acme",
    "headline": "Staff Engineer at Acme",
    "location": "Toronto",
}


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


async def test_requires_linkedin_url():
    db = _db_with_existing(None)
    with pytest.raises(ValueError):
        await capture_linkedin_profile(db, USER_ID, {"visible_name": "No URL"})


async def test_creates_person_and_verifies_company():
    db = _db_with_existing(None)
    with patch(
        "app.services.people.persistence.get_or_create_company",
        new_callable=AsyncMock,
    ) as mock_company:
        mock_company.return_value = _company()
        await capture_linkedin_profile(db, USER_ID, PAYLOAD)

    person = db.add.call_args.args[0]
    assert person.full_name == "Jane Doe"
    assert person.title == "Staff Engineer"
    assert person.source == "companion_capture"
    assert person.linkedin_url == "https://www.linkedin.com/in/jane-doe"
    assert person.profile_data["linkedin_live"]["source"] == "companion_capture"
    # User viewed the live profile -> current company is verified evidence.
    assert person.current_company_verified is True
    assert person.current_company_verification_source == "companion_capture"
    db.commit.assert_awaited()


async def test_no_company_label_skips_verification():
    db = _db_with_existing(None)
    payload = {k: v for k, v in PAYLOAD.items() if k != "current_company_label"}
    with patch(
        "app.services.people.persistence.get_or_create_company",
        new_callable=AsyncMock,
    ) as mock_company:
        await capture_linkedin_profile(db, USER_ID, payload)
        mock_company.assert_not_awaited()

    person = db.add.call_args.args[0]
    assert person.current_company_verified is None


async def test_existing_person_fills_blanks_without_clobbering():
    existing = Person(
        id=uuid.uuid4(),
        user_id=USER_ID,
        full_name="Jane Doe",
        title="Senior Engineer",  # stronger existing value — must survive
        linkedin_url="https://www.linkedin.com/in/jane-doe",
        source="public_web",
        profile_data={"existing": True},
    )
    db = _db_with_existing(existing)
    with patch(
        "app.services.people.persistence.get_or_create_company",
        new_callable=AsyncMock,
    ) as mock_company:
        mock_company.return_value = _company()
        result = await capture_linkedin_profile(db, USER_ID, PAYLOAD)

    # No new row; source not downgraded; title preserved.
    db.add.assert_not_called()
    assert result.title == "Senior Engineer"
    assert result.source == "public_web"
    assert result.profile_data["linkedin_live"]["visible_name"] == "Jane Doe"
    assert result.profile_data["existing"] is True


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


def _serialized_person_dict() -> dict:
    # Minimal shape satisfying PersonResponse's required (no-default) fields.
    return {
        "id": uuid.uuid4(),
        "full_name": "Jane Doe",
        "title": "Staff Engineer",
        "department": None,
        "seniority": None,
        "linkedin_url": "https://www.linkedin.com/in/jane-doe",
        "github_url": None,
        "work_email": None,
        "email_verified": False,
        "person_type": "peer",
        "profile_data": {},
        "github_data": None,
        "source": "companion_capture",
    }


async def test_capture_endpoint_wires_service(client):
    with (
        patch(
            "app.routers.people.capture_linkedin_profile",
            new_callable=AsyncMock,
        ) as mock_capture,
        patch("app.routers.people._serialize_person", return_value=_serialized_person_dict()),
    ):
        mock_capture.return_value = Person(id=uuid.uuid4(), user_id=USER_ID)
        response = await client.post(
            "/api/people/capture-linkedin-profile",
            json=PAYLOAD,
        )

    assert response.status_code == 200
    assert mock_capture.await_args.kwargs["payload"]["linkedin_url"] == PAYLOAD["linkedin_url"]


async def test_capture_endpoint_400_on_bad_url(client):
    with patch(
        "app.routers.people.capture_linkedin_profile",
        new_callable=AsyncMock,
    ) as mock_capture:
        mock_capture.side_effect = ValueError("A valid LinkedIn profile URL is required.")
        response = await client.post(
            "/api/people/capture-linkedin-profile",
            json={"linkedin_url": "not-a-url"},
        )

    assert response.status_code == 400
