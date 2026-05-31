"""Proof tests for audit pass-2 MEDIUM/LOW fixes (P6, P8, P12, P13, P14, P15, P16, P17)."""

import uuid

import pytest


# ---------------------------------------------------------------------------
# P6 — cadence weekly digest escapes scraped names
# ---------------------------------------------------------------------------
def test_p6_cadence_digest_escapes_html():
    from app.services.cadence_digest_service import _render_html
    from app.services.cadence_service import NextAction

    # person_name path (the realistic injection vector from scraped data).
    action = NextAction(
        kind="reply_needed",
        urgency="high",
        reason="They replied",
        person_name='<img src=x onerror=alert(1)>',
    )
    # company_name path (used when person_name is absent).
    company_action = NextAction(
        kind="awaiting_reply",
        urgency="medium",
        reason="Sent 5+ days ago",
        company_name="Acme & Co<script>",
    )
    html = _render_html([action, company_action], "user@example.com")
    assert "<img src=x onerror" not in html
    assert "&lt;img src=x" in html
    assert "Acme &amp; Co&lt;script&gt;" in html
    assert "<script>" not in html


# ---------------------------------------------------------------------------
# P8 — senior-IC hiring-manager fallback survives id dedup
# ---------------------------------------------------------------------------
def test_p8_synthetic_fallback_survives_dedup():
    from app.models.person import Person
    from app.services.people_service import _dedupe_bucket_assignments, _detached_person_copy

    pid = uuid.uuid4()
    peer = Person(id=pid, full_name="Jane Doe", person_type="peer", title="Staff Software Engineer")
    peer.match_quality = "direct"

    clone = _detached_person_copy(peer)
    clone.person_type = "hiring_manager"
    clone.match_quality = "next_best"
    clone._synthetic_fallback = True

    bucketed = {"recruiters": [], "hiring_managers": [clone], "peers": [peer]}
    result = _dedupe_bucket_assignments(bucketed)

    # The original stays in peers AND the synthetic clone survives in managers.
    assert any(p.id == pid for p in result["peers"]), "original peer dropped"
    assert any(p.id == pid for p in result["hiring_managers"]), "synthetic fallback dropped (P8)"


# ---------------------------------------------------------------------------
# P12 — detached copy deep-copies mutable profile_data
# ---------------------------------------------------------------------------
def test_p12_detached_copy_does_not_alias_profile_data():
    from app.models.person import Person
    from app.services.people_service import _detached_person_copy

    person = Person(full_name="Jane", profile_data={"headline": "x", "nested": {"k": 1}})
    clone = _detached_person_copy(person)

    assert clone.profile_data is not person.profile_data
    assert clone.profile_data["nested"] is not person.profile_data["nested"]
    # Mutating the clone must not corrupt the original.
    clone.profile_data["nested"]["k"] = 999
    clone.profile_data["new"] = "y"
    assert person.profile_data["nested"]["k"] == 1
    assert "new" not in person.profile_data


# ---------------------------------------------------------------------------
# P13 — global cache strips per-user search context
# ---------------------------------------------------------------------------
def test_p13_sanitize_strips_search_context():
    from app.services.known_people_service import _sanitize_profile_data_for_cache

    cleaned = _sanitize_profile_data_for_cache(
        {
            "headline": "Engineer at Acme",
            "search_query": "platform engineer toronto",
            "search_geo_terms": ["Toronto"],
            "search_provider": "searxng",
        }
    )
    assert cleaned == {"headline": "Engineer at Acme"}


def test_p13_lookup_ages_by_last_discovered():
    import inspect

    from app.services import known_people_service

    src = inspect.getsource(known_people_service.lookup_known_people)
    assert "KnownPerson.last_discovered_at >= cutoff" in src
    assert "KnownPerson.created_at >= cutoff" not in src


# ---------------------------------------------------------------------------
# P14 — legacy URL-dedup escapes LIKE metacharacters
# ---------------------------------------------------------------------------
def test_p14_legacy_ilike_escapes_like_metacharacters():
    import inspect

    from app.services import job_service

    src = inspect.getsource(job_service._find_existing_job)
    assert 'escape="\\\\"' in src
    assert 'replace("%", "\\\\%")' in src


# ---------------------------------------------------------------------------
# P15 — OAuth redirect_uri validated against allowed origins
# ---------------------------------------------------------------------------
def test_p15_redirect_uri_rejects_foreign_origin():
    from fastapi import HTTPException

    from app.routers.email import _validate_redirect_uri

    # Default allowed origins include http://localhost:5173.
    assert _validate_redirect_uri("http://localhost:5173/callback") == "http://localhost:5173/callback"
    for bad in [
        "https://evil.example.com/steal",
        "javascript:alert(1)",
        "not-a-url",
        "ftp://localhost:5173/",
    ]:
        with pytest.raises(HTTPException):
            _validate_redirect_uri(bad)


# ---------------------------------------------------------------------------
# P16 — account export includes refresh-run history
# ---------------------------------------------------------------------------
def test_p16_export_includes_job_refresh_runs():
    from app.models.job_refresh_run import JobRefreshRun
    from app.services.account_service import EXPORT_MODELS

    assert JobRefreshRun in EXPORT_MODELS


# ---------------------------------------------------------------------------
# P17 — Google feed-level category doesn't bleed into the first entry
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_p17_google_feed_level_category_does_not_leak():
    from unittest.mock import patch

    import app.clients.google_client as gc

    sample = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Feed</title>
  <category>FEED_LEVEL_ONLY</category>
  <entry>
    <title>Software Engineer</title><jobid>1</jobid><employer>Google</employer>
    <url>https://careers.google.com/jobs/1</url>
    <category>Engineering</category><location>Mountain View, CA</location><description>Build</description>
  </entry>
</feed>"""

    class _Resp:
        status_code = 200

        async def aiter_bytes(self, chunk_size=65536):
            for i in range(0, len(sample), 31):
                yield sample[i : i + 31]

    class _Ctx:
        async def __aenter__(self):
            return _Resp()

        async def __aexit__(self, *a):
            return False

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def stream(self, *a, **k):
            return _Ctx()

    with patch.object(gc.httpx, "AsyncClient", _Client):
        leaked = await gc.search_google_jobs("FEED_LEVEL_ONLY")
        real = await gc.search_google_jobs("Engineering")
    assert leaked == []  # feed-level category did not seed the entry
    assert [j["title"] for j in real] == ["Software Engineer"]  # real category still works
