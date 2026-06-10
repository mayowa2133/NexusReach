"""Regression tests for the High-severity launch-hardening audit fixes.

H1 — blocking pdflatex / resume parsing must run off the event loop.
H2 — uploads must be size-capped and zip-bomb safe.
H3 — account deletion must delete app data before the auth identity.
H4 — the global known-people cache must not share work_email across users.
"""

import io
import threading
import uuid
import zipfile
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.services import (
    known_people_service,
    linkedin_graph_service,
    resume_artifact_service,
)
from app.utils.uploads import read_upload_capped


# ---------------------------------------------------------------------------
# H1 — PDF rendering / parsing offloaded to a worker thread
# ---------------------------------------------------------------------------


async def test_render_pdf_async_runs_off_event_loop(monkeypatch):
    """render_resume_artifact_pdf_async must execute the blocking render in a
    worker thread, never inline on the event loop thread."""
    main_thread = threading.get_ident()
    seen: dict[str, int] = {}

    def fake_render(content: str) -> bytes:
        seen["thread"] = threading.get_ident()
        return b"%PDF-fake"

    monkeypatch.setattr(
        resume_artifact_service, "render_resume_artifact_pdf", fake_render
    )

    result = await resume_artifact_service.render_resume_artifact_pdf_async("hello")

    assert result == b"%PDF-fake"
    assert seen["thread"] != main_thread


async def test_render_redline_pdf_async_forwards_args(monkeypatch):
    """The redline async wrapper must forward all args to the sync renderer."""
    captured: dict[str, object] = {}

    def fake_redline(content, rewrites, decisions, *, auto_accept_inferred=False):
        captured.update(
            content=content,
            rewrites=rewrites,
            decisions=decisions,
            auto_accept_inferred=auto_accept_inferred,
        )
        return b"%PDF-redline"

    monkeypatch.setattr(
        resume_artifact_service,
        "render_resume_artifact_redline_pdf",
        fake_redline,
    )

    result = await resume_artifact_service.render_resume_artifact_redline_pdf_async(
        "body",
        [{"id": "r1"}],
        {"r1": "accepted"},
        auto_accept_inferred=True,
    )

    assert result == b"%PDF-redline"
    assert captured == {
        "content": "body",
        "rewrites": [{"id": "r1"}],
        "decisions": {"r1": "accepted"},
        "auto_accept_inferred": True,
    }


async def test_pdf_render_concurrency_is_bounded():
    """The module must cap concurrent pdflatex compilations (audit H1)."""
    assert resume_artifact_service._PDF_RENDER_SEMAPHORE._value <= 2


# ---------------------------------------------------------------------------
# H2 — bounded uploads + zip-bomb guard
# ---------------------------------------------------------------------------


class _FakeUpload:
    """Minimal UploadFile stand-in exposing an async chunked read."""

    def __init__(self, data: bytes):
        self._buf = io.BytesIO(data)

    async def read(self, size: int = -1) -> bytes:
        return self._buf.read(size)


async def test_read_upload_capped_allows_within_limit():
    payload = b"x" * 1000
    out = await read_upload_capped(_FakeUpload(payload), max_bytes=4096)
    assert out == payload


async def test_read_upload_capped_rejects_oversized():
    payload = b"x" * (5 * 1024 * 1024)  # 5 MiB
    with pytest.raises(HTTPException) as exc:
        await read_upload_capped(_FakeUpload(payload), max_bytes=1024 * 1024)
    assert exc.value.status_code == 413


def _make_connections_zip(csv_text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("Connections.csv", csv_text)
    return buf.getvalue()


def test_zip_parse_within_cap_ok():
    csv_text = (
        "First Name,Last Name,URL,Company,Position\n"
        "Ada,Lovelace,https://www.linkedin.com/in/adalovelace,Analytical,Engineer\n"
    )
    rows = linkedin_graph_service.parse_linkedin_connections_zip(
        _make_connections_zip(csv_text),
        max_decompressed_bytes=1024 * 1024,
    )
    assert len(rows) == 1
    assert rows[0]["display_name"] == "Ada Lovelace"


def test_zip_parse_rejects_decompressed_bomb():
    # A highly compressible CSV that expands well past a tiny cap.
    header = "First Name,Last Name,URL,Company,Position\n"
    big = header + ("A,B,https://www.linkedin.com/in/x,C,D\n" * 100000)
    bomb = _make_connections_zip(big)
    # The compressed ZIP is small, but decompressed it blows the 50 KiB cap.
    assert len(bomb) < 50 * 1024
    with pytest.raises(ValueError, match="too large"):
        linkedin_graph_service.parse_linkedin_connections_zip(
            bomb, max_decompressed_bytes=50 * 1024
        )


# ---------------------------------------------------------------------------
# H4 — global known-people cache must not share emails across users
# ---------------------------------------------------------------------------


def test_known_people_candidate_dict_omits_work_email():
    """Cached candidates returned to other users must carry no work_email."""
    kp = SimpleNamespace(
        id=uuid.uuid4(),
        full_name="Grace Hopper",
        title="Engineer",
        department="Eng",
        seniority="senior",
        linkedin_url="https://www.linkedin.com/in/gracehopper",
        github_url=None,
        work_email="grace@navy.mil",  # present on the row, must NOT be returned
        apollo_id=None,
        profile_data={"headline": "Compiler pioneer"},
        github_data=None,
        primary_source="public_web",
        discovery_count=3,
        verification_status="fresh",
    )
    kpc = SimpleNamespace(
        title_at_company="Engineer",
        company_name="Navy",
        company_domain="navy.mil",
    )

    candidate = known_people_service._to_candidate_dict(kp, kpc)

    assert "work_email" not in candidate
    assert "grace@navy.mil" not in str(candidate)


def test_known_people_write_does_not_persist_work_email():
    """The KnownPerson create path must not set work_email (audit H4).

    Guards the source so a future edit can't silently re-introduce caching of a
    discovered email into the global row.
    """
    import inspect

    source = inspect.getsource(known_people_service.write_candidates_to_cache)
    assert "work_email=" not in source


def test_sanitize_profile_data_strips_email_and_search_keys():
    cleaned = known_people_service._sanitize_profile_data_for_cache(
        {
            "headline": "keep me",
            "search_query": "drop",
            "email": "drop@x.com",
            "Work_Email": "drop2@x.com",
            "emails": ["a@x.com"],
        }
    )
    assert cleaned == {"headline": "keep me"}


# ---------------------------------------------------------------------------
# PostHog telemetry guard — capture must never break a request
# ---------------------------------------------------------------------------


def test_capture_event_noop_when_unconfigured(monkeypatch):
    import posthog as posthog_mod

    from app import observability

    monkeypatch.setattr(observability.settings, "posthog_api_key", "")

    def _boom(*_a, **_k):  # would raise if called
        raise AssertionError("posthog.capture must not be called when unconfigured")

    monkeypatch.setattr(posthog_mod, "capture", _boom)
    # Must return without calling posthog.capture.
    observability.capture_event("user-1", "evt", properties={"a": 1})


def test_capture_event_swallows_posthog_errors(monkeypatch):
    import posthog as posthog_mod

    from app import observability

    monkeypatch.setattr(observability.settings, "posthog_api_key", "phc_test")

    def _boom(*_a, **_k):
        raise RuntimeError("api_key must have ...")

    monkeypatch.setattr(posthog_mod, "capture", _boom)
    # A telemetry failure must not propagate to the caller.
    observability.capture_event("user-1", "evt")
