"""Proof tests for audit Batch 4 (LOW) fixes — 2026-05-29.

Covers L1, L2, L9, L11, L13, L15. (L3-L8, L10, L12, L14 are documented as
known external-scraping limitations / deliberate no-ops in AUDIT_2026-05-29.md.)
"""

import httpx
import pytest


# ---------------------------------------------------------------------------
# L1 — interview_rounds annotation allows list
# ---------------------------------------------------------------------------
def test_l1_interview_rounds_annotation_includes_list():
    import inspect

    from app.models import job as job_model

    src = inspect.getsource(job_model)
    assert "interview_rounds: Mapped[list | dict | None]" in src


# ---------------------------------------------------------------------------
# L2 — Amazon external_id is source-prefixed
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_l2_amazon_external_id_prefixed():
    from app.clients import amazon_client

    payload = {
        "jobs": [
            {
                "id_icims": "123456",
                "title": "Software Engineer",
                "normalized_location": "Seattle, WA",
                "posted_date": "",
            }
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    transport = httpx.MockTransport(handler)
    orig = amazon_client.httpx.AsyncClient

    def _factory(*args, **kwargs):
        kwargs["transport"] = transport
        return orig(*args, **kwargs)

    amazon_client.httpx.AsyncClient = _factory
    try:
        jobs = await amazon_client.search_amazon_jobs("engineer", limit=5)
    finally:
        amazon_client.httpx.AsyncClient = orig

    assert jobs
    assert jobs[0]["external_id"] == "amzn_123456"


# ---------------------------------------------------------------------------
# L9 — Apollo search honors larger per_page
# ---------------------------------------------------------------------------
def test_l9_apollo_per_page_not_capped_at_25():
    import inspect

    from app.clients import apollo_client

    src = inspect.getsource(apollo_client.search_people)
    assert "min(limit, 100)" in src
    assert "min(limit, 25)" not in src


# ---------------------------------------------------------------------------
# L11 — job alert digest escapes HTML
# ---------------------------------------------------------------------------
def test_l11_job_alert_digest_escapes_html():
    from app.models.job import Job
    from app.services.job_alert_service import _render_digest_html

    malicious = Job(
        title='Engineer "><script>alert(1)</script>',
        company_name="Acme & Co",
        location="<b>NYC</b>",
        url='https://x.com/"><img src=x>',
        source="greenhouse",
    )
    html_out = _render_digest_html([malicious], "user@example.com")
    assert "<script>alert(1)" not in html_out
    assert "&lt;script&gt;" in html_out
    assert "Acme &amp; Co" in html_out
    # The raw injected img/url breakout must not appear unescaped.
    assert '"><img src=x>' not in html_out


# ---------------------------------------------------------------------------
# L13 — email_source prefers explicit email-specific source
# ---------------------------------------------------------------------------
def test_l13_email_source_prefers_explicit():
    import inspect

    from app.services.people import persistence

    src = inspect.getsource(persistence)
    assert 'data.get("email_source") or data.get("source")' in src


# ---------------------------------------------------------------------------
# L15 — Dice URL decode tolerates non-UTF-8 payloads
# ---------------------------------------------------------------------------
def test_l15_dice_url_decode_handles_bad_unicode():
    import base64

    from app.clients.remote_jobs_client import _extract_dice_configured_url

    # A base64 payload that decodes to invalid UTF-8 bytes.
    bad = base64.b64encode(b"\xff\xfe\xfa").decode("ascii")
    url = f"https://www.dice.com/apply?applyData={bad}"
    # Must return None instead of raising UnicodeDecodeError.
    assert _extract_dice_configured_url(url) is None
