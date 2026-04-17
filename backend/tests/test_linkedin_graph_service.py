import io
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services.linkedin_graph_service import (
    apply_warm_path_annotations,
    connection_matches_company,
    dedupe_connection_candidates,
    graph_freshness_metadata,
    parse_linkedin_connections_csv,
    parse_linkedin_connections_zip,
    resolve_warm_path_for_person,
)


def test_parse_linkedin_connections_csv_handles_preamble_and_normalizes_fields():
    file_bytes = b"""LinkedIn Connections Export\r\nGenerated for testing\r\nFirst Name,Last Name,URL,Email Address,Company,Position,Connected On\r\nJane,Doe,https://www.linkedin.com/in/jane-doe,,Acme,Senior Recruiter,2026-01-01\r\n"""

    rows = parse_linkedin_connections_csv(file_bytes)

    assert rows == [
        {
            "linkedin_url": "https://www.linkedin.com/in/jane-doe",
            "linkedin_slug": "jane-doe",
            "display_name": "Jane Doe",
            "headline": "Senior Recruiter",
            "current_company_name": "Acme",
            "normalized_company_name": "acme",
            "company_linkedin_url": None,
            "company_linkedin_slug": None,
            "source": "manual_import",
        }
    ]


def test_parse_linkedin_connections_zip_extracts_connections_csv():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "Connections/Connections.csv",
            "First Name,Last Name,URL,Company,Position\nJohn,Smith,https://www.linkedin.com/in/john-smith,Stripe,Engineer\n",
        )

    rows = parse_linkedin_connections_zip(buffer.getvalue())

    assert len(rows) == 1
    assert rows[0]["display_name"] == "John Smith"
    assert rows[0]["normalized_company_name"] == "stripe"


def test_dedupe_connection_candidates_prefers_slug_then_merges_missing_fields():
    rows = dedupe_connection_candidates(
        [
            {
                "full_name": "Jane Doe",
                "linkedin_url": "https://www.linkedin.com/in/jane-doe",
                "company": "Acme",
            },
            {
                "full_name": "Jane Doe",
                "url": "https://linkedin.com/in/jane-doe",
                "company": "Acme",
                "headline": "Recruiter",
            },
        ],
        source="manual_import",
    )

    assert len(rows) == 1
    assert rows[0]["linkedin_slug"] == "jane-doe"
    assert rows[0]["headline"] == "Recruiter"


def test_dedupe_connection_candidates_falls_back_to_name_and_company():
    rows = dedupe_connection_candidates(
        [
            {"full_name": "Alex Lee", "company": "Affirm"},
            {"first_name": "Alex", "last_name": "Lee", "company_name": "Affirm", "position": "Engineer"},
        ],
        source="manual_import",
    )

    assert len(rows) == 1
    assert rows[0]["display_name"] == "Alex Lee"
    assert rows[0]["headline"] == "Engineer"


def test_connection_matches_company_requires_trusted_slug_for_ambiguous_brand():
    connection = {
        "display_name": "Andre Nguyen",
        "normalized_company_name": "zip",
        "company_linkedin_slug": "ziphq",
    }

    assert connection_matches_company(
        connection,
        company_name="Zip",
        public_identity_slugs=["zip", "ziphq"],
    ) is True
    assert connection_matches_company(
        connection,
        company_name="Zip",
        public_identity_slugs=["zip"],
    ) is False


def test_apply_warm_path_annotations_marks_direct_and_bridge_matches():
    connection_direct = SimpleNamespace(
        id=uuid.uuid4(),
        linkedin_slug="jane-doe",
        display_name="Jane Doe",
        headline="Recruiter",
        current_company_name="Acme",
        linkedin_url="https://www.linkedin.com/in/jane-doe",
        company_linkedin_url=None,
        source="manual_import",
        last_synced_at=None,
    )
    connection_bridge = SimpleNamespace(
        id=uuid.uuid4(),
        linkedin_slug="maria-chan",
        display_name="Maria Chan",
        headline="Engineer",
        current_company_name="Acme",
        linkedin_url="https://www.linkedin.com/in/maria-chan",
        company_linkedin_url=None,
        source="manual_import",
        last_synced_at=None,
    )
    direct_person = SimpleNamespace(linkedin_url="https://www.linkedin.com/in/jane-doe")
    cold_person = SimpleNamespace(linkedin_url="https://www.linkedin.com/in/sarah-roe")

    bucketed = {
        "recruiters": [direct_person],
        "hiring_managers": [],
        "peers": [cold_person],
    }

    apply_warm_path_annotations(
        bucketed,
        company_name="Acme",
        your_connections=[connection_direct, connection_bridge],
    )

    assert direct_person.warm_path_type == "direct_connection"
    assert direct_person.warm_path_connection is connection_direct
    assert "already connected" in direct_person.warm_path_reason.lower()
    assert cold_person.warm_path_type == "same_company_bridge"
    assert cold_person.warm_path_connection is connection_direct
    assert "you already know" in cold_person.warm_path_reason.lower()


def test_graph_freshness_metadata_flags_aging_and_stale():
    aging = graph_freshness_metadata(datetime.now(timezone.utc) - timedelta(days=45))
    stale = graph_freshness_metadata(datetime.now(timezone.utc) - timedelta(days=120))

    assert aging["freshness"] == "aging"
    assert aging["refresh_recommended"] is True
    assert aging["stale"] is False
    assert stale["freshness"] == "stale"
    assert stale["stale"] is True


@pytest.mark.asyncio
async def test_resolve_warm_path_for_person_returns_direct_match():
    connection = SimpleNamespace(
        id=uuid.uuid4(),
        linkedin_slug="jane-doe",
        display_name="Jane Doe",
        headline="Senior Recruiter",
        current_company_name="Acme",
        linkedin_url="https://www.linkedin.com/in/jane-doe",
        company_linkedin_url=None,
        source="manual_import",
        last_synced_at=None,
    )
    person = SimpleNamespace(
        linkedin_url="https://www.linkedin.com/in/jane-doe",
        department=None,
        company=SimpleNamespace(name="Acme", public_identity_slugs=["acme"]),
    )

    with patch(
        "app.services.linkedin_graph_service.get_connections_for_company",
        new=AsyncMock(return_value=[connection]),
    ):
        result = await resolve_warm_path_for_person(
            db=None, user_id=uuid.uuid4(), person=person
        )

    assert result["type"] == "direct_connection"
    assert result["connection_name"] == "Jane Doe"
    assert "directly connected" in result["reason"].lower()


@pytest.mark.asyncio
async def test_resolve_warm_path_for_person_picks_recruiter_bridge():
    recruiter = SimpleNamespace(
        id=uuid.uuid4(),
        linkedin_slug="tal-rec",
        display_name="Tal Recruiter",
        headline="Senior Recruiter",
        current_company_name="Acme",
        linkedin_url="https://www.linkedin.com/in/tal-rec",
        company_linkedin_url=None,
        source="manual_import",
        last_synced_at=None,
    )
    engineer = SimpleNamespace(
        id=uuid.uuid4(),
        linkedin_slug="eve-eng",
        display_name="Eve Engineer",
        headline="Software Engineer",
        current_company_name="Acme",
        linkedin_url="https://www.linkedin.com/in/eve-eng",
        company_linkedin_url=None,
        source="manual_import",
        last_synced_at=None,
    )
    # Cold recipient (not in connections).
    person = SimpleNamespace(
        linkedin_url="https://www.linkedin.com/in/cold-target",
        department=None,
        company=SimpleNamespace(name="Acme", public_identity_slugs=["acme"]),
    )

    with patch(
        "app.services.linkedin_graph_service.get_connections_for_company",
        new=AsyncMock(return_value=[engineer, recruiter]),
    ):
        result = await resolve_warm_path_for_person(
            db=None, user_id=uuid.uuid4(), person=person, job_title="Engineer"
        )

    assert result["type"] == "same_company_bridge"
    # Recruiter outranks peer engineer.
    assert result["connection_name"] == "Tal Recruiter"


@pytest.mark.asyncio
async def test_resolve_warm_path_for_person_returns_none_without_company_or_connections():
    no_company = SimpleNamespace(linkedin_url=None, department=None, company=None)
    assert (
        await resolve_warm_path_for_person(
            db=None, user_id=uuid.uuid4(), person=no_company
        )
        is None
    )

    person = SimpleNamespace(
        linkedin_url=None,
        department=None,
        company=SimpleNamespace(name="Acme", public_identity_slugs=[]),
    )
    with patch(
        "app.services.linkedin_graph_service.get_connections_for_company",
        new=AsyncMock(return_value=[]),
    ):
        assert (
            await resolve_warm_path_for_person(
                db=None, user_id=uuid.uuid4(), person=person
            )
            is None
        )
