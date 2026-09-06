"""Security invariants from the September 2026 audit."""
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.observability import _before_send
from app.services.known_people_service import is_cache_eligible
from app.services.people.hiring_team_capture import ingest_hiring_team_capture
from app.services.email_lookup_service import resolve_company_domain
from app.services import paid_context, paid_work


def test_capture_flags_cannot_be_laundered_through_public_source():
    for source in ('client_capture', 'linkedin_hiring_team'):
        assert not is_cache_eligible({'source': source})
    assert not is_cache_eligible({'source': 'apollo', '_hiring_team_capture': True})
    assert not is_cache_eligible({'source': 'apollo', 'profile_data': {'hiring_team_capture': True}})
    assert is_cache_eligible({'source': 'apollo'})


@pytest.mark.asyncio
async def test_foreign_job_capture_rejected_before_any_write():
    db = AsyncMock()
    db.scalar.return_value = None
    with pytest.raises(HTTPException) as exc:
        await ingest_hiring_team_capture(db, uuid.uuid4(), company_name='Synthetic', members=[{'name': 'A B'}], job_id=uuid.uuid4())
    assert exc.value.status_code == 404
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_company_query_is_bound_to_authenticated_owner():
    owner = uuid.uuid4()
    db = AsyncMock()
    db.execute.return_value = MagicMock(scalar_one_or_none=lambda: None)
    await resolve_company_domain(db, 'Synthetic', None, user_id=owner)
    statement = db.execute.call_args.args[0].compile()
    assert 'companies.user_id =' in str(statement)
    assert owner in statement.params.values()


def test_tokens_are_scrubbed_from_nested_spans_and_request():
    event = {'request': {'query_string': 't=nrw_testowner&v=nrv_testverify', 'url': 'https://example.test/?t=nrw_testowner'}, 'spans': [{'description': 'GET /?v=nrv_testverify'}], 'extra': {'receipt_token': 'secret'}}
    result = repr(_before_send(event, None))
    assert 'nrw_testowner' not in result
    assert 'nrv_testverify' not in result
    assert 'secret' not in result


@pytest.mark.asyncio
async def test_task_operation_ids_are_stable_across_redelivery():
    async def build_id():
        return paid_context.operation_id("provider:synthetic", "same-request")

    first = await paid_context.run_in_operation_scope(build_id(), "celery:task:id")
    second = await paid_context.run_in_operation_scope(build_id(), "celery:task:id")
    assert first == second


@pytest.mark.asyncio
async def test_failed_dispatch_claim_releases_before_provider_io(monkeypatch):
    monkeypatch.setattr("app.config.settings.environment", "development")
    paid_context.set_subject(uuid.uuid4())
    reservation = SimpleNamespace(state="reserved")
    with (
        patch("app.services.paid_work.reserve", new=AsyncMock(return_value=reservation)),
        patch(
            "app.services.paid_work.mark_dispatched",
            new=AsyncMock(side_effect=HTTPException(503, "database unavailable")),
        ),
        patch("app.services.paid_work.release", new=AsyncMock()) as release,
    ):
        with pytest.raises(HTTPException):
            async with paid_work.provider_call("synthetic"):
                raise AssertionError("provider boundary must not be entered")
    release.assert_awaited_once()
