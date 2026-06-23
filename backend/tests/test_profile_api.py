"""API tests for profile endpoints — Phase 2."""

import base64
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

pytestmark = pytest.mark.asyncio


def _mock_profile(user_id, **overrides):
    p = MagicMock()
    p.id = str(uuid.uuid4())
    p.user_id = user_id
    p.full_name = overrides.get("full_name", "Test User")
    p.bio = overrides.get("bio", "A test bio")
    p.goals = overrides.get("goals", ["Find a job"])
    p.tone = overrides.get("tone", "conversational")
    p.target_industries = overrides.get("target_industries", ["Tech"])
    p.target_company_sizes = overrides.get("target_company_sizes", None)
    p.target_roles = overrides.get("target_roles", ["SWE"])
    p.target_locations = overrides.get("target_locations", ["NYC"])
    p.linkedin_url = overrides.get("linkedin_url", None)
    p.github_url = overrides.get("github_url", None)
    p.portfolio_url = overrides.get("portfolio_url", None)
    p.resume_parsed = overrides.get("resume_parsed", None)
    return p


async def test_get_profile_success(client, mock_user_id):
    """GET /api/profile returns profile when it exists."""
    profile = _mock_profile(mock_user_id)

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = profile

    mock_db = AsyncMock()
    mock_db.execute.return_value = mock_result

    from app.database import get_db
    from app.main import app

    app.dependency_overrides[get_db] = lambda: mock_db

    resp = await client.get("/api/profile")

    app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200
    data = resp.json()
    assert data["full_name"] == "Test User"
    assert data["tone"] == "conversational"


async def test_get_profile_not_found(client, mock_user_id):
    """GET /api/profile returns 404 when no profile exists."""
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None

    mock_db = AsyncMock()
    mock_db.execute.return_value = mock_result

    from app.database import get_db
    from app.main import app

    app.dependency_overrides[get_db] = lambda: mock_db

    resp = await client.get("/api/profile")

    app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 404


async def test_upload_resume_rejects_html(client):
    """POST /api/profile/resume rejects non-PDF/DOCX files."""
    from app.database import get_db
    from app.main import app

    mock_db = AsyncMock()
    app.dependency_overrides[get_db] = lambda: mock_db

    resp = await client.post(
        "/api/profile/resume",
        files={"file": ("test.html", b"<html>content</html>", "text/html")},
    )

    app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 400
    assert "Unsupported file type" in resp.json()["error"]["message"]


async def test_upload_resume_json_success(client, mock_user_id):
    """POST /api/profile/resume-json accepts base64 payloads and updates the profile."""
    profile = _mock_profile(mock_user_id)
    profile.id = uuid.uuid4()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = profile

    mock_db = AsyncMock()
    mock_db.execute.return_value = mock_result

    from app.database import get_db
    from app.main import app

    app.dependency_overrides[get_db] = lambda: mock_db

    payload = {
        "filename": "resume.pdf",
        "content_type": "application/pdf",
        "file_base64": base64.b64encode(b"%PDF-sample").decode("ascii"),
    }

    with patch("app.routers.profile.extract_text", return_value="Jane Doe\nSkills\nPython"), \
         patch("app.routers.profile.parse_resume_text", return_value={
             "contact": {
                 "name": "Jane Doe",
                 "urls": ["https://linkedin.com/in/janedoe", "https://github.com/janedoe"],
             },
             "skills": ["Python"],
         }), \
         patch("app.tasks.jobs.rescore_user_jobs.delay") as mock_delay:
        resp = await client.post("/api/profile/resume-json", json=payload)

    app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == str(profile.id)
    assert data["full_name"] == "Test User"
    assert data["resume_parsed"]["skills"] == ["Python"]
    mock_db.commit.assert_awaited_once()
    mock_db.refresh.assert_awaited_once_with(profile)
    mock_delay.assert_called_once_with(str(mock_user_id))


async def test_update_profile(client, mock_user_id):
    """PUT /api/profile updates fields."""
    profile = _mock_profile(mock_user_id)

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = profile

    mock_db = AsyncMock()
    mock_db.execute.return_value = mock_result

    from app.database import get_db
    from app.main import app

    app.dependency_overrides[get_db] = lambda: mock_db

    resp = await client.put(
        "/api/profile",
        json={"full_name": "Updated Name", "bio": "New bio"},
    )

    app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200


from types import SimpleNamespace  # noqa: E402

from app.routers.profile import _seed_queries_from_profile  # noqa: E402


def _seed_profile(**kw):
    return SimpleNamespace(
        target_roles=kw.get("target_roles"),
        target_occupations=kw.get("target_occupations"),
        target_locations=kw.get("target_locations"),
    )


def test_seed_queries_prefers_explicit_target_roles():
    profile = _seed_profile(
        target_roles=["Backend Engineer", "Platform Engineer", "SRE", "Extra"],
        target_occupations=["software_engineering"],
    )
    # First 3 roles, occupations ignored when roles are present.
    assert _seed_queries_from_profile(profile) == [
        "Backend Engineer", "Platform Engineer", "SRE",
    ]


def test_seed_queries_falls_back_to_occupations_when_no_roles():
    """The core fix: an occupation-only profile must still seed queries."""
    profile = _seed_profile(target_roles=[], target_occupations=["software_engineering"])
    queries = _seed_queries_from_profile(profile)
    assert queries == ["Software Engineer"]  # occupation's representative query


def test_seed_queries_filters_blank_roles_then_uses_occupations():
    profile = _seed_profile(
        target_roles=["", "   "], target_occupations=["data_analyst"],
    )
    queries = _seed_queries_from_profile(profile)
    assert queries and all(q.strip() for q in queries)


def test_seed_queries_empty_when_nothing_targeted():
    assert _seed_queries_from_profile(_seed_profile()) == []
