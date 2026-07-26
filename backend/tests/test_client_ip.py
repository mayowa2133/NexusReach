"""Client-IP resolution behind trusted proxies.

Every per-IP control depends on this: the slowapi burst limits, the per-IP daily
signup cap, and the stored `signup_ip`. Two ways to get it wrong, and the tests
below pin both — resolving to the proxy (everyone shares one bucket, the daily
cap becomes a site-wide ceiling) and trusting a client-supplied header entry
(every limit bypassable with one header).
"""

from unittest.mock import patch

from starlette.datastructures import Headers

from app.config import settings
from app.utils.client_ip import client_ip

CLIENT = "203.0.113.7"
EDGE = "10.1.2.3"


class _Request:
    """Minimal stand-in: `client_ip` only reads `.headers` and `.client`."""

    def __init__(self, xff: str | None = None, peer: str | None = EDGE):
        raw = [(b"x-forwarded-for", xff.encode())] if xff is not None else []
        self.headers = Headers(raw=raw)
        self.client = type("C", (), {"host": peer})() if peer else None


def _with_hops(hops: int):
    return patch.object(settings, "trusted_proxy_hops", hops)


# --- hops = 0: directly exposed -------------------------------------------


def test_no_proxy_uses_the_socket_peer():
    with _with_hops(0):
        assert client_ip(_Request(peer=CLIENT)) == CLIENT


def test_no_proxy_ignores_the_header_entirely():
    """With nothing in front of us, X-Forwarded-For is pure client input."""
    with _with_hops(0):
        assert client_ip(_Request(xff="9.9.9.9", peer=CLIENT)) == CLIENT


# --- hops = 1: one edge proxy (the Railway topology) ----------------------


def test_single_proxy_takes_the_rightmost_entry():
    with _with_hops(1):
        assert client_ip(_Request(xff=CLIENT)) == CLIENT


def test_single_proxy_ignores_a_spoofed_prefix():
    """The attack this whole module exists to stop.

    A caller sending `X-Forwarded-For: 9.9.9.9` arrives as "9.9.9.9, <real>"
    once the edge appends. Reading the leftmost entry — which is what uvicorn's
    --forwarded-allow-ips='*' does — would hand out a one-header bypass of every
    rate limit.
    """
    with _with_hops(1):
        assert client_ip(_Request(xff=f"9.9.9.9, {CLIENT}")) == CLIENT


def test_single_proxy_ignores_a_long_spoofed_chain():
    with _with_hops(1):
        forged = "1.1.1.1, 2.2.2.2, 3.3.3.3"
        assert client_ip(_Request(xff=f"{forged}, {CLIENT}")) == CLIENT


# --- hops = 2: CDN in front of the edge -----------------------------------


def test_two_proxies_take_the_second_from_the_right():
    with _with_hops(2):
        assert client_ip(_Request(xff=f"9.9.9.9, {CLIENT}, {EDGE}")) == CLIENT


# --- fail safe, never open -------------------------------------------------


def test_missing_header_falls_back_to_the_peer():
    with _with_hops(1):
        assert client_ip(_Request(xff=None)) == EDGE


def test_chain_shorter_than_configured_hops_falls_back():
    """Header didn't traverse the promised chain — don't reach for what's left.

    Falling back costs us a shared bucket; guessing would let a caller that
    reaches the app off-path choose its own key.
    """
    with _with_hops(2):
        assert client_ip(_Request(xff=CLIENT)) == EDGE


def test_garbage_entry_falls_back_to_the_peer():
    with _with_hops(1):
        assert client_ip(_Request(xff="not-an-ip")) == EDGE
        assert client_ip(_Request(xff="")) == EDGE


def test_missing_client_never_raises():
    with _with_hops(1):
        assert client_ip(_Request(xff=None, peer=None)) == "127.0.0.1"


# --- real-world formatting -------------------------------------------------


def test_handles_whitespace_and_ipv6():
    with _with_hops(1):
        assert client_ip(_Request(xff="  9.9.9.9 ,  2001:db8::1  ")) == "2001:db8::1"


def test_strips_a_bracketed_ipv6_port():
    with _with_hops(1):
        assert client_ip(_Request(xff="[2001:db8::1]:443")) == "2001:db8::1"


def test_strips_an_ipv4_port():
    with _with_hops(1):
        assert client_ip(_Request(xff=f"{CLIENT}:51234")) == CLIENT


# --- the limiter and the signup cap actually use it ------------------------


def test_rate_limit_key_uses_the_resolved_client():
    from app.middleware.rate_limit import _get_user_key

    with _with_hops(1):
        assert _get_user_key(_Request(xff=f"9.9.9.9, {CLIENT}")) == CLIENT
