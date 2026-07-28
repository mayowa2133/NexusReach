"""Waitlist goals + optional resume upload tests.

Follows the repo convention: pure helpers tested directly, DB mocked with
``AsyncMock``, endpoints via the ``client`` fixture with services patched.
"""

import base64
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.models.waitlist import WaitlistSignup
from app.schemas.waitlist import WaitlistSignupCreate
from app.services import waitlist_resume_service as wrs
from app.utils.resume_upload import (
    ensure_resume_magic_bytes,
    normalize_resume_content_type,
)
from app.utils.waitlist_goals import clean_goals

PDF_BYTES = b"%PDF-1.4\n% tiny fake pdf for validation tests\n"
DOCX_BYTES = b"PK\x03\x04" + b"\x00" * 40
DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _payload(**kw) -> WaitlistSignupCreate:
    base = {"name": "Jordan Rivera", "email": "jordan@example.com"}
    base.update(kw)
    return WaitlistSignupCreate(**base)


def _signup() -> WaitlistSignup:
    return WaitlistSignup(
        id=uuid.uuid4(),
        email="jordan@example.com",
        name="Jordan Rivera",
        referral_code="ABCDEFGHJK",
        email_verified=False,
        verified_referral_count=0,
        resume_parse_status="none",
        created_at=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# Goals
# ---------------------------------------------------------------------------


def test_clean_goals_keeps_known_keys_in_order():
    assert clean_goals(["warm_intros", "land_first_role"]) == [
        "warm_intros",
        "land_first_role",
    ]


def test_clean_goals_drops_unknown_and_duplicates():
    assert clean_goals(["land_first_role", "not_a_goal", "land_first_role"]) == [
        "land_first_role"
    ]


def test_clean_target_occupation_accepts_a_real_taxonomy_key():
    from app.utils.waitlist_goals import clean_target_occupation

    assert clean_target_occupation('software_engineering') == 'software_engineering'
    assert clean_target_occupation('  marketing  ') == 'marketing'


def test_clean_target_occupation_drops_anything_not_in_the_taxonomy():
    """A junk key would silently seed the wrong saved searches at launch."""
    from app.utils.waitlist_goals import clean_target_occupation

    assert clean_target_occupation('definitely_not_an_occupation') is None
    assert clean_target_occupation('Software Engineer') is None  # label, not key
    assert clean_target_occupation('') is None
    assert clean_target_occupation(None) is None


def test_clean_goals_empty_is_none():
    assert clean_goals(None) is None
    assert clean_goals([]) is None
    assert clean_goals(["bogus"]) is None


# ---------------------------------------------------------------------------
# Upload validation
# ---------------------------------------------------------------------------


def test_normalize_content_type_accepts_declared_and_extension():
    assert normalize_resume_content_type("application/pdf", None) == "application/pdf"
    # Wrong/missing declared type falls back to the filename extension.
    assert normalize_resume_content_type(None, "resume.pdf") == "application/pdf"
    assert normalize_resume_content_type("", "resume.docx") == DOCX_TYPE


def test_normalize_content_type_rejects_other_types():
    with pytest.raises(HTTPException) as exc:
        normalize_resume_content_type("image/png", "photo.png")
    assert exc.value.status_code == 400


def test_magic_bytes_accepts_real_headers():
    ensure_resume_magic_bytes(PDF_BYTES, "application/pdf")
    ensure_resume_magic_bytes(DOCX_BYTES, DOCX_TYPE)


def test_magic_bytes_rejects_content_lying_about_its_type():
    with pytest.raises(HTTPException) as exc:
        ensure_resume_magic_bytes(b"<html>not a pdf</html>", "application/pdf")
    assert exc.value.status_code == 422


# ---------------------------------------------------------------------------
# decode_and_validate
# ---------------------------------------------------------------------------


def test_decode_returns_none_without_a_resume():
    assert wrs.decode_and_validate(_payload()) is None


def test_decode_accepts_valid_pdf():
    payload = _payload(
        resume_file_base64=_b64(PDF_BYTES),
        resume_filename="resume.pdf",
        resume_content_type="application/pdf",
    )
    data, content_type = wrs.decode_and_validate(payload)
    assert data == PDF_BYTES
    assert content_type == "application/pdf"


def test_decode_rejects_bad_base64():
    payload = _payload(
        resume_file_base64="!!!not-base64!!!",
        resume_filename="resume.pdf",
        resume_content_type="application/pdf",
    )
    with pytest.raises(HTTPException) as exc:
        wrs.decode_and_validate(payload)
    assert exc.value.status_code == 400


def test_decode_rejects_oversize(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "max_waitlist_resume_bytes", 10)
    payload = _payload(
        resume_file_base64=_b64(PDF_BYTES + b"x" * 100),
        resume_filename="resume.pdf",
        resume_content_type="application/pdf",
    )
    with pytest.raises(HTTPException) as exc:
        wrs.decode_and_validate(payload)
    assert exc.value.status_code == 413


# ---------------------------------------------------------------------------
# attach_resume — storage success vs failure
# ---------------------------------------------------------------------------


async def test_attach_resume_marks_pending_on_successful_upload():
    entry = _signup()
    with patch(
        "app.services.waitlist_resume_service.supabase_storage_client.upload_object",
        new_callable=AsyncMock,
        return_value=True,
    ):
        await wrs.attach_resume(entry, PDF_BYTES, "application/pdf", "resume.pdf")

    assert entry.resume_path == f"{entry.id}/resume.pdf"
    assert entry.resume_parse_status == "pending"
    assert entry.resume_size_bytes == len(PDF_BYTES)
    assert entry.resume_filename == "resume.pdf"


async def test_attach_resume_fails_soft_when_storage_unavailable():
    entry = _signup()
    with patch(
        "app.services.waitlist_resume_service.supabase_storage_client.upload_object",
        new_callable=AsyncMock,
        return_value=False,
    ):
        await wrs.attach_resume(entry, PDF_BYTES, "application/pdf", "resume.pdf")

    # Signup is preserved; only the resume is flagged.
    assert entry.resume_path is None
    assert entry.resume_parse_status == "failed"


def test_object_path_never_uses_the_user_supplied_filename():
    entry = _signup()
    path = wrs.build_object_path(entry, "application/pdf")
    assert path == f"{entry.id}/resume.pdf"
    assert ".." not in path and "/" == path[len(str(entry.id))]


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


_STATUS_PAYLOAD = {
    "referral_code": "ABCDEFGHJK",
    "position": 1,
    "total_verified": 0,
    "launch_target": 3000,
    "share_url": "http://localhost:5173/?ref=ABCDEFGHJK",
    "email_verified": False,
    "verified_referral_count": 0,
    "earned_tier": 0,
    "tier_thresholds": [1, 3, 5, 10],
}


def _patched_join(entry):
    """Common patches for the join endpoint."""
    from app.services.waitlist_service import WaitlistUpsertResult

    return (
        patch(
            "app.routers.waitlist.upsert_waitlist_signup",
            new_callable=AsyncMock,
            return_value=WaitlistUpsertResult(
                entry=entry,
                already_on_list=False,
                access_token="nrw_secret",
                emailed_access_token=None,
                verification_token="nrv_secret",
            ),
        ),
        patch(
            "app.routers.waitlist.referral_service.enforce_signup_ip_limit",
            new_callable=AsyncMock,
        ),
        patch(
            "app.routers.waitlist.referral_service.referral_status_payload",
            new_callable=AsyncMock,
            return_value=dict(_STATUS_PAYLOAD),
        ),
        patch("app.routers.waitlist.send_verification_email.delay"),
    )


async def test_join_with_resume_stores_and_queues_parse(client):
    entry = _signup()
    p1, p2, p3, p4 = _patched_join(entry)
    with (
        p1,
        p2,
        p3,
        p4,
        patch(
            "app.services.waitlist_resume_service.supabase_storage_client.upload_object",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch("app.routers.waitlist.parse_waitlist_resume.delay") as mock_parse,
    ):
        resp = await client.post(
            "/api/waitlist",
            json={
                "name": "Jordan Rivera",
                "email": "jordan@example.com",
                "goals": ["land_first_role", "warm_intros"],
                "resume_filename": "resume.pdf",
                "resume_content_type": "application/pdf",
                "resume_file_base64": _b64(PDF_BYTES),
            },
        )

    assert resp.status_code == 200
    assert entry.resume_parse_status == "pending"
    mock_parse.assert_called_once()


async def test_resubmission_cannot_overwrite_an_existing_resume(client):
    """A stranger must not be able to replace someone's stored resume.

    The Storage object path is derived from the row id and uploads use
    `x-upsert`, so attaching on the existing-row branch overwrites the owner's
    file in place. The upload must not be attempted at all.
    """
    from app.services.waitlist_service import WaitlistUpsertResult

    entry = _signup()
    entry.resume_path = f"{entry.id}/resume.pdf"
    entry.resume_filename = "owners-real-resume.pdf"
    entry.resume_parse_status = "ready"

    with (
        patch(
            "app.routers.waitlist.upsert_waitlist_signup",
            new_callable=AsyncMock,
            return_value=WaitlistUpsertResult(
                entry=entry,
                already_on_list=True,
                access_token=None,
                emailed_access_token=None,
                verification_token="nrv_secret",
            ),
        ),
        patch(
            "app.routers.waitlist.referral_service.enforce_signup_ip_limit",
            new_callable=AsyncMock,
        ),
        patch("app.routers.waitlist.send_verification_email.delay"),
        patch(
            "app.services.waitlist_resume_service.supabase_storage_client.upload_object",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_upload,
        patch("app.routers.waitlist.parse_waitlist_resume.delay") as mock_parse,
    ):
        resp = await client.post(
            "/api/waitlist",
            json={
                "name": "Attacker",
                "email": "jordan@example.com",
                "resume_filename": "attacker.pdf",
                "resume_content_type": "application/pdf",
                "resume_file_base64": _b64(PDF_BYTES),
            },
        )

    assert resp.status_code == 200  # the form still succeeds for the visitor
    mock_upload.assert_not_awaited()
    mock_parse.assert_not_called()
    assert entry.resume_filename == "owners-real-resume.pdf"
    assert entry.resume_parse_status == "ready"


async def test_resubmission_still_reports_an_invalid_resume(client):
    """Validation runs before the branch, so the error contract is identical.

    Diverging here would turn a malformed upload into an "is this email already
    registered?" oracle.
    """
    resp = await client.post(
        "/api/waitlist",
        json={
            "name": "Someone",
            "email": "jordan@example.com",
            "resume_filename": "resume.pdf",
            "resume_content_type": "application/pdf",
            "resume_file_base64": _b64(b"<html>not a pdf</html>"),
        },
    )
    assert resp.status_code == 422


async def test_join_still_succeeds_when_storage_fails(client):
    entry = _signup()
    p1, p2, p3, p4 = _patched_join(entry)
    with (
        p1,
        p2,
        p3,
        p4,
        patch(
            "app.services.waitlist_resume_service.supabase_storage_client.upload_object",
            new_callable=AsyncMock,
            return_value=False,
        ),
        patch("app.routers.waitlist.parse_waitlist_resume.delay") as mock_parse,
    ):
        resp = await client.post(
            "/api/waitlist",
            json={
                "name": "Jordan Rivera",
                "email": "jordan@example.com",
                "resume_filename": "resume.pdf",
                "resume_content_type": "application/pdf",
                "resume_file_base64": _b64(PDF_BYTES),
            },
        )

    # Infrastructure failure must not cost the visitor their signup.
    assert resp.status_code == 200
    assert entry.resume_parse_status == "failed"
    mock_parse.assert_not_called()


async def test_join_rejects_a_file_lying_about_its_type(client):
    entry = _signup()
    p1, p2, p3, p4 = _patched_join(entry)
    with p1, p2, p3, p4:
        resp = await client.post(
            "/api/waitlist",
            json={
                "name": "Jordan Rivera",
                "email": "jordan@example.com",
                "resume_filename": "resume.pdf",
                "resume_content_type": "application/pdf",
                "resume_file_base64": _b64(b"<html>definitely not a pdf</html>"),
            },
        )
    assert resp.status_code == 422


async def test_join_without_resume_is_unaffected(client):
    entry = _signup()
    p1, p2, p3, p4 = _patched_join(entry)
    with p1, p2, p3, p4, patch("app.routers.waitlist.parse_waitlist_resume.delay") as mp:
        resp = await client.post(
            "/api/waitlist",
            json={"name": "Jordan Rivera", "email": "jordan@example.com"},
        )
    assert resp.status_code == 200
    mp.assert_not_called()


# ---------------------------------------------------------------------------
# Retention + erasure (finding #10)
# ---------------------------------------------------------------------------


async def test_delete_signup_removes_the_stored_resume_too():
    """Erasure must not leave an orphaned object in the private bucket."""
    from app.services import waitlist_retention_service as wrs

    entry = _signup()
    entry.resume_path = f"{entry.id}/resume.pdf"
    db = AsyncMock()

    with patch(
        "app.services.waitlist_retention_service.supabase_storage_client.delete_object",
        new_callable=AsyncMock,
        return_value=True,
    ) as mock_delete:
        result = await wrs.delete_signup(db, entry)

    mock_delete.assert_awaited_once_with(entry.resume_path)
    db.delete.assert_awaited_once_with(entry)
    assert result == {"deleted": True, "resume_deleted": True}


async def test_delete_signup_without_a_resume_touches_no_storage():
    from app.services import waitlist_retention_service as wrs

    entry = _signup()
    db = AsyncMock()

    with patch(
        "app.services.waitlist_retention_service.supabase_storage_client.delete_object",
        new_callable=AsyncMock,
    ) as mock_delete:
        result = await wrs.delete_signup(db, entry)

    mock_delete.assert_not_awaited()
    assert result["resume_deleted"] is False


async def test_retention_keeps_the_row_when_storage_delete_fails():
    """A failed object delete must not orphan the file.

    Clearing the metadata anyway would leave the row claiming "no resume" while
    the file is still in the bucket, and nothing would ever retry it.
    """
    from app.services import waitlist_retention_service as wrs

    entry = _signup()
    entry.resume_path = f"{entry.id}/resume.pdf"
    entry.resume_filename = "cv.pdf"
    entry.resume_parse_status = "ready"

    db = AsyncMock()
    scalars = MagicMock()
    scalars.all.return_value = [entry]
    result_obj = MagicMock()
    result_obj.scalars.return_value = scalars
    db.execute.return_value = result_obj

    with patch(
        "app.services.waitlist_retention_service.supabase_storage_client.delete_object",
        new_callable=AsyncMock,
        return_value=False,
    ):
        cleared = await wrs.purge_expired_resumes(db)

    assert cleared == 0
    assert entry.resume_path is not None
    assert entry.resume_filename == "cv.pdf"
    db.commit.assert_not_awaited()


async def test_delete_endpoint_requires_the_owner_token(client):
    with patch(
        "app.routers.referrals.referral_service.resolve_signup_by_token",
        new_callable=AsyncMock,
        return_value=None,
    ):
        resp = await client.delete("/api/referrals/me?code=ABCDEFGHJK&t=nrw_wrong")
    assert resp.status_code == 404


async def test_delete_endpoint_erases_with_a_valid_token(client):
    entry = _signup()
    with (
        patch(
            "app.routers.referrals.referral_service.resolve_signup_by_token",
            new_callable=AsyncMock,
            return_value=entry,
        ),
        patch(
            "app.routers.referrals.waitlist_retention_service.delete_signup",
            new_callable=AsyncMock,
            return_value={"deleted": True, "resume_deleted": True},
        ) as mock_delete,
    ):
        resp = await client.delete("/api/referrals/me?code=ABCDEFGHJK&t=nrw_ok")

    assert resp.status_code == 200
    assert resp.json() == {"deleted": True, "resume_deleted": True}
    mock_delete.assert_awaited_once()
