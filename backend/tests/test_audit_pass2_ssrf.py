"""Proof tests for audit pass-2 P4 — SSRF protection on user-fetched URLs.

Uses IP literals / localhost so the checks are deterministic and DNS-independent.
"""

import pytest

from app.utils.url_safety import is_safe_public_url


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/x",
        "http://127.0.0.1:6379/",
        "http://169.254.169.254/latest/meta-data/iam/security-credentials/",
        "http://10.0.0.5/admin",
        "http://192.168.1.1/",
        "http://172.16.0.1/",
        "http://[::1]/",
        "http://localhost:8000/",
        "http://metadata.google.internal/computeMetadata/v1/",
        "http://0.0.0.0/",
        "file:///etc/passwd",
        "gopher://127.0.0.1/",
        "ftp://10.0.0.1/",
        "",
        None,
    ],
)
def test_p4_blocks_unsafe_targets(url):
    assert is_safe_public_url(url) is False


@pytest.mark.parametrize(
    "url",
    [
        "https://boards.greenhouse.io/acme/jobs/123",
        "https://careers.example.com/jobs/platform-engineer",
        "http://93.184.216.34/",  # a public IP literal
    ],
)
def test_p4_allows_public_targets(url):
    # Public hosts are allowed. (Unresolvable hosts are allowed too — they can't
    # be fetched anyway — but public IP literals prove the allow path explicitly.)
    assert is_safe_public_url(url) is True


@pytest.mark.asyncio
async def test_p4_generic_exact_url_rejected_at_parse():
    from app.clients import ats_client

    # The generic adapter must refuse an internal host at parse time so the
    # server never fetches it.
    assert ats_client.parse_ats_job_url("http://127.0.0.1:6379/") is None
    assert ats_client.parse_ats_job_url("http://169.254.169.254/latest/meta-data/") is None
    # A normal public exact-job URL still parses.
    parsed = ats_client.parse_ats_job_url("https://careers.example.com/jobs/eng")
    assert parsed is not None and parsed.ats_type == "generic_exact"


@pytest.mark.asyncio
async def test_p4_safe_get_refuses_redirect_to_internal():
    """A public response that 302s to an internal host must not be followed."""
    import httpx

    from app.utils import url_safety

    hops = []

    class _Resp:
        def __init__(self, status_code, location=None, url="https://public.example.com/"):
            self.status_code = status_code
            self.headers = {"location": location} if location else {}
            self.url = httpx.URL(url)
            self.text = "ok"

    class _Client:
        async def get(self, url, headers=None):
            hops.append(str(url))
            # First (public) hop redirects to a loopback target.
            return _Resp(302, location="http://127.0.0.1:9999/secret")

    # Pretend the initial public host is safe; the redirect target is loopback.
    resp = await url_safety.safe_get("https://public.example.com/", client=_Client())
    assert resp is None  # refused before fetching the internal redirect target
    # Only the first public hop was requested; the internal target was never fetched.
    assert hops == ["https://public.example.com/"]
