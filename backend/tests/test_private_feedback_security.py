"""SEC-07: private assertions cannot modify a shared people cache."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.database import get_db
from app.main import app


@pytest.mark.asyncio
@pytest.mark.parametrize("source,verified", [("client_capture", False), ("apollo", True)])
@pytest.mark.parametrize("feedback", ["wrong_person", "not_at_company"])
async def test_private_feedback_only_evicts_callers_snapshots(client, mock_user_id, source, verified, feedback):
    person = SimpleNamespace(id=uuid.uuid4(), user_id=mock_user_id, full_name="Shared Name",
                             company_id=uuid.uuid4(), company=SimpleNamespace(name="Shared Company"),
                             profile_data={}, current_company_verified=verified, source=source,
                             person_type="hiring_manager")
    result = MagicMock()
    result.scalar_one_or_none.return_value = person
    db = AsyncMock()
    db.execute.return_value = result
    app.dependency_overrides[get_db] = lambda: db
    with patch("app.services.known_people_service.expire_known_person", new=AsyncMock()) as global_expire, \
         patch("app.routers.people.evict_person_from_job_research_snapshots", new=AsyncMock(return_value=1)) as private_expire, \
         patch("app.routers.people.capture_event"):
        response = await client.post(f"/api/people/{person.id}/feedback", json={"feedback": feedback})
    assert response.status_code == 200
    assert response.json() == {"ok": True, "cache_evicted": False, "snapshots_updated": 1}
    global_expire.assert_not_awaited()
    private_expire.assert_awaited_once_with(db, user_id=mock_user_id, person_id=person.id)
    assert db.execute.await_count == 1  # Only the owned Person read, no shared writes.
    assert person.profile_data["user_feedback"] == feedback
    if feedback == "not_at_company":
        assert person.current_company_verified is False
