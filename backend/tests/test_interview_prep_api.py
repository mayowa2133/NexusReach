"""API tests for /api/jobs/{job_id}/interview-prep."""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.asyncio


def _mock_brief(user_id, job_id, **overrides):
    b = MagicMock()
    b.id = overrides.get("id", uuid.uuid4())
    b.user_id = user_id
    b.job_id = job_id
    b.company_overview = overrides.get("company_overview", "Great company.")
    b.role_summary = overrides.get("role_summary", "Senior backend role.")
    b.likely_rounds = overrides.get(
        "likely_rounds",
        [
            {
                "name": "Recruiter screen",
                "type": "recruiter_screen",
                "description": "d",
                "inferred": True,
            }
        ],
    )
    b.question_categories = overrides.get(
        "question_categories",
        [
            {
                "key": "behavioral",
                "label": "Behavioral / STAR",
                "examples": ["x"],
                "inferred": True,
            }
        ],
    )
    b.prep_themes = overrides.get(
        "prep_themes",
        [{"title": "Why Acme", "reason": "r", "inferred": True}],
    )
    b.story_map = overrides.get(
        "story_map",
        [{"category": "behavioral", "story_ids": []}],
    )
    b.sourced_signals = overrides.get("sourced_signals", {"title": "x"})
    b.user_notes = overrides.get("user_notes", None)
    b.generated_at = datetime(2026, 4, 18, tzinfo=timezone.utc)
    b.created_at = datetime(2026, 4, 18, tzinfo=timezone.utc)
    b.updated_at = datetime(2026, 4, 18, tzinfo=timezone.utc)
    return b


async def test_get_interview_prep_not_found(client, mock_user_id):
    with patch(
        "app.routers.interview_prep.get_brief", new_callable=AsyncMock
    ) as m:
        m.return_value = None
        resp = await client.get(f"/api/jobs/{uuid.uuid4()}/interview-prep")
    assert resp.status_code == 404


async def test_get_interview_prep_returns_payload(client, mock_user_id):
    job_id = uuid.uuid4()
    brief = _mock_brief(mock_user_id, job_id)
    with patch(
        "app.routers.interview_prep.get_brief", new_callable=AsyncMock
    ) as m:
        m.return_value = brief
        resp = await client.get(f"/api/jobs/{job_id}/interview-prep")
    assert resp.status_code == 200
    body = resp.json()
    assert body["role_summary"] == "Senior backend role."
    assert body["likely_rounds"][0]["type"] == "recruiter_screen"


async def test_generate_interview_prep(client, mock_user_id):
    job_id = uuid.uuid4()
    brief = _mock_brief(mock_user_id, job_id)
    with patch(
        "app.routers.interview_prep.generate_or_refresh_brief",
        new_callable=AsyncMock,
    ) as m:
        m.return_value = brief
        resp = await client.post(
            f"/api/jobs/{job_id}/interview-prep", json={"regenerate": True}
        )
    assert resp.status_code == 201
    assert resp.json()["role_summary"] == "Senior backend role."


async def test_generate_interview_prep_job_missing(client, mock_user_id):
    with patch(
        "app.routers.interview_prep.generate_or_refresh_brief",
        new_callable=AsyncMock,
    ) as m:
        m.return_value = None
        resp = await client.post(
            f"/api/jobs/{uuid.uuid4()}/interview-prep", json={"regenerate": False}
        )
    assert resp.status_code == 404


async def test_patch_interview_prep_notes(client, mock_user_id):
    job_id = uuid.uuid4()
    brief = _mock_brief(mock_user_id, job_id, user_notes="My notes")
    with patch(
        "app.routers.interview_prep.update_brief", new_callable=AsyncMock
    ) as m:
        m.return_value = brief
        resp = await client.patch(
            f"/api/jobs/{job_id}/interview-prep",
            json={"user_notes": "My notes"},
        )
    assert resp.status_code == 200
    assert resp.json()["user_notes"] == "My notes"


async def test_patch_interview_prep_not_found(client, mock_user_id):
    with patch(
        "app.routers.interview_prep.update_brief", new_callable=AsyncMock
    ) as m:
        m.return_value = None
        resp = await client.patch(
            f"/api/jobs/{uuid.uuid4()}/interview-prep", json={"user_notes": "x"}
        )
    assert resp.status_code == 404


async def test_delete_interview_prep(client, mock_user_id):
    with patch(
        "app.routers.interview_prep.delete_brief", new_callable=AsyncMock
    ) as m:
        m.return_value = True
        resp = await client.delete(f"/api/jobs/{uuid.uuid4()}/interview-prep")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "deleted": True}


async def test_delete_interview_prep_not_found(client, mock_user_id):
    with patch(
        "app.routers.interview_prep.delete_brief", new_callable=AsyncMock
    ) as m:
        m.return_value = False
        resp = await client.delete(f"/api/jobs/{uuid.uuid4()}/interview-prep")
    assert resp.status_code == 404
