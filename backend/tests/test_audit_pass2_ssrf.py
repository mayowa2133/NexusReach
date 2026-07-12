"""Proof tests for audit pass-2 P4 — SSRF protection on user-fetched URLs.

Uses IP literals / localhost so the checks are deterministic and DNS-independent.
"""

import pytest

from app.utils.url_safety import is_safe_public_url, is_safe_url_syntax


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
        "http://93.184.216.34/",  # a public IP literal
    ],
)
def test_p4_allows_public_targets(url):
    # Public hosts and public IP literals pass the admission check.
    assert is_safe_public_url(url) is True


@pytest.mark.asyncio
async def test_p4_generic_exact_url_rejected_at_parse():
    from app.clients import ats_client

    # The generic adapter must refuse an internal host at parse time so the
    # server never fetches it.
    assert ats_client.parse_ats_job_url("http://127.0.0.1:6379/") is None
    assert ats_client.parse_ats_job_url("http://169.254.169.254/latest/meta-data/") is None
    # A normal public exact-job URL still parses.
    parsed = ats_client.parse_ats_job_url("http://93.184.216.34/jobs/eng")
    assert parsed is not None and parsed.ats_type == "generic_exact"


@pytest.mark.parametrize(
    "url",
    [
        "https://greenhouse.io.attacker.example/acme/jobs/1",
        "https://evil-lever.co/acme/1",
        "https://apply.workable.com.attacker.example/acme/j/1",
        "https://jobs.ashbyhq.com.attacker.example/acme/1",
        "https://evil-icims.com/jobs/1",
    ],
)
def test_provider_url_parsers_reject_lookalike_hosts(url):
    from app.clients import ats_client

    parsed = ats_client.parse_ats_job_url(url)
    assert parsed is None or parsed.ats_type == "generic_exact"


@pytest.mark.asyncio
async def test_p4_safe_get_refuses_redirect_to_internal(monkeypatch):
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

    def _resolve(url):
        if "127.0.0.1" in url:
            return None
        return ("public.example.com", "93.184.216.34")

    monkeypatch.setattr(url_safety, "_resolve_public_address", _resolve)

    # Pretend the initial public host is safe; the redirect target is loopback.
    resp = await url_safety.safe_get("https://public.example.com/", client=_Client())
    assert resp is None  # refused before fetching the internal redirect target
    # Only the first public hop was requested; the internal target was never fetched.
    assert hops == ["https://public.example.com/"]


def test_p4_unresolvable_host_fails_closed(monkeypatch):
    import socket
    from app.utils import url_safety

    def _fail(*_args, **_kwargs):
        raise OSError("no DNS answer")

    monkeypatch.setattr(socket, "getaddrinfo", _fail)
    assert url_safety.is_safe_public_url("https://does-not-resolve.invalid/x") is False
    assert is_safe_url_syntax("https://does-not-resolve.invalid/x") is True


@pytest.mark.asyncio
async def test_p4_safe_get_pins_connection_to_vetted_ip(monkeypatch):
    import httpx
    from app.utils import url_safety

    seen = {}

    async def handler(request):
        seen["url"] = str(request.url)
        seen["host"] = request.headers.get("host")
        seen["sni"] = request.extensions.get("sni_hostname")
        return httpx.Response(200, text="ok", request=request)

    monkeypatch.setattr(
        url_safety,
        "_resolve_public_address",
        lambda _url: ("public.example.com", "93.184.216.34"),
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        response = await url_safety.safe_get("https://public.example.com/path", client=client)

    assert response is not None
    assert seen == {
        "url": "https://93.184.216.34/path",
        "host": "public.example.com",
        "sni": "public.example.com",
    }
    assert str(response.url) == "https://public.example.com/path"
