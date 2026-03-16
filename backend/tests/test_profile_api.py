"""API tests for profile endpoints — Phase 2."""

import uuid
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

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
