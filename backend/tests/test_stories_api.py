"""API tests for /api/stories — Story Bank CRUD."""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.asyncio


def _mock_story(user_id, **overrides):
    s = MagicMock()
    s.id = overrides.get("id", uuid.uuid4())
    s.user_id = user_id
    s.title = overrides.get("title", "Cut deploy time 40%")
    s.summary = overrides.get("summary", "Reduced CI runtime via parallelization.")
    s.situation = overrides.get("situation", "CI took 30 minutes per PR.")
    s.action = overrides.get("action", "Sharded test suite, cached deps.")
    s.result = overrides.get("result", "Reduced to 18 minutes.")
    s.impact_metric = overrides.get("impact_metric", "40% faster")
    s.role_focus = overrides.get("role_focus", "Platform Engineer")
    s.tags = overrides.get("tags", ["platform", "performance"])
    s.created_at = datetime(2026, 4, 18, tzinfo=timezone.utc)
    s.updated_at = datetime(2026, 4, 18, tzinfo=timezone.utc)
    return s


async def test_list_stories_empty(client, mock_user_id):
    with patch("app.routers.stories.list_stories", new_callable=AsyncMock) as m:
        m.return_value = []
        resp = await client.get("/api/stories")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_list_stories_returns_payload(client, mock_user_id):
    story = _mock_story(mock_user_id)
    with patch("app.routers.stories.list_stories", new_callable=AsyncMock) as m:
        m.return_value = [story]
        resp = await client.get("/api/stories")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["title"] == "Cut deploy time 40%"
    assert body[0]["tags"] == ["platform", "performance"]


async def test_create_story(client, mock_user_id):
    story = _mock_story(mock_user_id, title="New Story")
    with patch("app.routers.stories.create_story", new_callable=AsyncMock) as m:
        m.return_value = story
        resp = await client.post(
            "/api/stories",
            json={"title": "New Story", "summary": "x", "tags": ["leadership"]},
        )
    assert resp.status_code == 201
    assert resp.json()["title"] == "New Story"


async def test_get_story_not_found(client, mock_user_id):
    with patch("app.routers.stories.get_story", new_callable=AsyncMock) as m:
        m.return_value = None
        resp = await client.get(f"/api/stories/{uuid.uuid4()}")
    assert resp.status_code == 404


async def test_update_story(client, mock_user_id):
    story = _mock_story(mock_user_id, title="Updated Title")
    with patch("app.routers.stories.update_story", new_callable=AsyncMock) as m:
        m.return_value = story
        resp = await client.patch(
            f"/api/stories/{story.id}",
            json={"title": "Updated Title"},
        )
    assert resp.status_code == 200
    assert resp.json()["title"] == "Updated Title"


async def test_update_story_not_found(client, mock_user_id):
    with patch("app.routers.stories.update_story", new_callable=AsyncMock) as m:
        m.return_value = None
        resp = await client.patch(
            f"/api/stories/{uuid.uuid4()}", json={"title": "x"}
        )
    assert resp.status_code == 404


async def test_delete_story(client, mock_user_id):
    with patch("app.routers.stories.delete_story", new_callable=AsyncMock) as m:
        m.return_value = True
        resp = await client.delete(f"/api/stories/{uuid.uuid4()}")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "deleted": True}


async def test_delete_story_not_found(client, mock_user_id):
    with patch("app.routers.stories.delete_story", new_callable=AsyncMock) as m:
        m.return_value = False
        resp = await client.delete(f"/api/stories/{uuid.uuid4()}")
    assert resp.status_code == 404
