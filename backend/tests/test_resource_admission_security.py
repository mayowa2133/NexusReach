"""Real Redis races and HTTP/provider boundaries for SEC-02/03/05."""

import asyncio
import base64
import os
import shutil
import socket
import subprocess
import time
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
import redis as sync_redis
import redis.asyncio as async_redis
from fastapi import HTTPException

from app.config import settings
from app.utils import resource_limits as limits
from app.utils.sandboxed_process import run_in_sandbox_async


@pytest_asyncio.fixture
async def admission_redis(tmp_path, monkeypatch):
    binary = shutil.which("redis-server")
    if binary is None:
        pytest.skip("requires a local disposable redis-server")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    process = subprocess.Popen([
        binary, "--bind", "127.0.0.1", "--port", str(port),
        "--save", "", "--appendonly", "no", "--dir", str(tmp_path),
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    probe = sync_redis.Redis(host="127.0.0.1", port=port)
    try:
        for _ in range(100):
            try:
                probe.ping()
                break
            except sync_redis.ConnectionError:
                await asyncio.sleep(0.02)
        else:
            pytest.fail("disposable Redis did not start")
        client = async_redis.Redis(host="127.0.0.1", port=port)
        monkeypatch.setattr(limits, "_client", lambda: client)
        monkeypatch.setattr(settings, "environment", "development")
        yield client
        await client.aclose()
    finally:
        probe.close()
        process.terminate()
        process.wait(timeout=5)


@pytest.mark.asyncio
async def test_atomic_global_cap_under_concurrent_distinct_identities(admission_redis):
    async def attempt(index):
        try:
            await limits.consume([("global", 17, 1), (f"account:{index}", 2, 1)])
            return 202
        except HTTPException as exc:
            return exc.status_code
    results = await asyncio.gather(*(attempt(i) for i in range(100)))
    assert results.count(202) == 17
    assert results.count(429) == 83
    keys = await admission_redis.keys("nr:resource:account:*")
    assert len(keys) == 17  # Rejected multi-limit charges are atomic.


@pytest.mark.asyncio
async def test_weighted_bytes_and_unavailable_redis_fail_closed(admission_redis, monkeypatch):
    await limits.consume([("files", 5, 1), ("bytes", 10, 8)])
    with pytest.raises(HTTPException) as rejected:
        await limits.consume([("files", 5, 1), ("bytes", 10, 3)])
    assert rejected.value.status_code == 429
    file_key = (await admission_redis.keys("nr:resource:files:*"))[0]
    assert await admission_redis.get(file_key) == b"1"
    monkeypatch.setattr(limits, "_client", lambda: AsyncMock(eval=AsyncMock(side_effect=ConnectionError)))
    with pytest.raises(HTTPException) as unavailable:
        await limits.consume([("files", 5, 1)])
    assert unavailable.value.status_code == 503


@pytest.mark.asyncio
async def test_waitlist_global_limit_before_storage_email_or_mirror(client, admission_redis, monkeypatch):
    monkeypatch.setattr(settings, "waitlist_daily_submission_limit", 2)
    result = SimpleNamespace(entry=SimpleNamespace(id=uuid.uuid4()), already_on_list=False,
                             verification_token="nrv_synthetic")
    with patch("app.routers.waitlist.referral_service.enforce_signup_ip_limit", new=AsyncMock()), \
         patch("app.routers.waitlist.upsert_waitlist_signup", new=AsyncMock(return_value=result)) as upsert, \
         patch("app.routers.waitlist.send_verification_email.delay") as mail, \
         patch("app.routers.waitlist.sheets_mirror_client.is_configured", return_value=False):
        responses = [await client.post("/api/waitlist", json={"email": f"guest{i}@example.com"},
                                       headers={"X-Forwarded-For": f"198.51.100.{i}"}) for i in range(3)]
    assert [r.status_code for r in responses] == [202, 202, 429]
    assert upsert.await_count == mail.call_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("verified", [False, True])
async def test_resume_requires_verified_owner_before_storage(client, admission_redis, verified):
    from app.database import get_db
    from app.main import app

    app.dependency_overrides[get_db] = lambda: AsyncMock()
    signup = SimpleNamespace(id=uuid.uuid4(), email_verified=verified, resume_path=None)
    with patch("app.routers.referrals.referral_service.resolve_signup_by_token", new=AsyncMock(return_value=signup)), \
         patch("app.services.waitlist_resume_service.attach_resume", new=AsyncMock()) as attach:
        response = await client.post("/api/referrals/resume?code=ABC", headers={"Authorization": "Bearer nrw_synthetic"},
                                     json={"resume_filename": "resume.pdf", "resume_content_type": "application/pdf",
                                           "resume_file_base64": base64.b64encode(b"%PDF-1.4\n").decode()})
    assert response.status_code == (202 if verified else 404)
    assert attach.await_count == int(verified)


@pytest.mark.asyncio
async def test_email_recipient_aliases_and_global_budget_precede_network(admission_redis, monkeypatch):
    from app.clients import resend_client

    monkeypatch.setattr(settings, "resend_api_key", "synthetic-no-network")
    monkeypatch.setattr(settings, "resend_from_email", "test@example.com")
    monkeypatch.setattr(settings, "system_email_recipient_daily_limit", 1)
    monkeypatch.setattr(settings, "system_email_daily_limit", 2)
    provider = AsyncMock()
    provider.post.return_value = SimpleNamespace(status_code=200)
    manager = MagicMock()
    manager.__aenter__ = AsyncMock(return_value=provider)
    manager.__aexit__ = AsyncMock()
    with patch.object(resend_client.httpx, "AsyncClient", return_value=manager):
        results = [await resend_client.send_email(to=email, subject="test", html="test") for email in (
            "m.e+one@gmail.com", "me+two@googlemail.com", "other@example.com", "third@example.com",
        )]
    assert results == [True, False, True, False]
    assert provider.post.await_count == 2


@pytest.mark.asyncio
async def test_verified_owner_resume_global_budget_cannot_be_bypassed_by_other_owners(client, admission_redis, monkeypatch):
    from app.database import get_db
    from app.main import app

    monkeypatch.setattr(settings, "waitlist_resume_daily_limit", 1)
    app.dependency_overrides[get_db] = lambda: AsyncMock()
    owners = [SimpleNamespace(id=uuid.uuid4(), email_verified=True, resume_path=None) for _ in range(2)]
    with patch("app.routers.referrals.referral_service.resolve_signup_by_token", new=AsyncMock(side_effect=owners)), \
         patch("app.services.waitlist_resume_service.attach_resume", new=AsyncMock()) as storage:
        responses = [await client.post("/api/referrals/resume?code=ABC", headers={"Authorization": "Bearer nrw_synthetic"},
                                       json={"resume_filename": "resume.pdf", "resume_content_type": "application/pdf",
                                             "resume_file_base64": base64.b64encode(b"%PDF-1.4\n").decode()}) for _ in owners]
    assert [response.status_code for response in responses] == [202, 429]
    storage.assert_awaited_once()


@pytest.mark.asyncio
async def test_verified_owner_recovery_delivers_exchange_and_unverified_signup_cannot_notify_owner():
    from app.tasks import referrals

    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=AsyncMock())
    session.__aexit__ = AsyncMock()
    signup = SimpleNamespace(email_verified=True, referral_code="ABC", email="owner@example.com", name="Owner")
    with patch.object(referrals, "async_session", return_value=session), \
         patch.object(referrals, "_load_signup", new=AsyncMock(return_value=signup)), \
         patch.object(referrals.resend_client, "send_email", new=AsyncMock(return_value=True)) as mail:
        assert await referrals._run_verification(str(uuid.uuid4()), "nrv_synthetic") == {"sent": True}
        mail.assert_awaited_once()
        signup.email_verified = False
        mail.reset_mock()
        with patch.object(settings, "waitlist_notify_email", "founder@example.com"):
            result = await referrals._run_signup_notification(str(uuid.uuid4()))
        assert result == {"sent": False, "reason": "mailbox_not_verified"}
        mail.assert_not_awaited()


@pytest.mark.asyncio
async def test_parser_capacity_is_shared_and_released_after_killing_child(admission_redis, monkeypatch):
    monkeypatch.setattr(settings, "parser_global_concurrency", 1)
    original_spawn = asyncio.create_subprocess_exec
    spawned = []

    async def spawn(*args, **kwargs):
        process = await original_spawn(*args, **kwargs)
        spawned.append(process)
        return process

    with patch("app.utils.sandboxed_process.asyncio.create_subprocess_exec", side_effect=spawn):
        task = asyncio.create_task(run_in_sandbox_async(
            "time", "sleep", 10, timeout_seconds=12, memory_bytes=128 * 1024**2,
            cpu_seconds=2, output_bytes=4096,
        ))
        for _ in range(100):
            if spawned:
                break
            await asyncio.sleep(0.01)
        assert spawned
        assert await admission_redis.zcard("nr:process:global") == 1
        with pytest.raises(HTTPException) as busy:
            async with limits.process_capacity(1):
                pytest.fail("second process admitted")
        assert busy.value.status_code == 429
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert spawned[0].returncode is not None
        with pytest.raises(ProcessLookupError):
            os.kill(spawned[0].pid, 0)
        assert await admission_redis.zcard("nr:process:global") == 0
        # A killed worker's stale lease also expires, rather than wedging service.
        await admission_redis.zadd("nr:process:global", {"expired-worker": time.time() - 1})
        async with limits.process_capacity(1):
            assert await admission_redis.zcard("nr:process:global") == 1
