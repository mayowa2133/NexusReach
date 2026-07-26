"""Resolve the real client IP behind a known number of trusted proxies.

Every per-IP control in the app (the slowapi burst limits, the per-IP daily
signup cap, the ``signup_ip`` we store) is only as good as this function. Behind
Railway's edge the socket peer is the proxy, so keying on ``request.client.host``
puts *every visitor in the world into one bucket* — which silently converts a
50/day anti-fraud cap into a 50/day global ceiling that locks out real users.

Why this is not delegated to uvicorn's ``--forwarded-allow-ips``
---------------------------------------------------------------
Uvicorn's ``ProxyHeadersMiddleware`` in ``*`` (always-trust) mode takes
``x_forwarded_for_hosts[0]`` — the **leftmost** entry. That entry is written by
the *client*, not by any proxy: a request carrying ``X-Forwarded-For: 9.9.9.9``
arrives at the app as ``9.9.9.9, <real client>`` once the edge appends, and
uvicorn would report ``9.9.9.9``. Turning that flag on to "fix" the shared
bucket would hand every attacker a one-header bypass of every rate limit. So we
never run uvicorn with ``--forwarded-allow-ips='*'`` and do the parse here.

The model
---------
``X-Forwarded-For`` grows left-to-right: each proxy *appends the address it
received the connection from*. With ``N`` trusted proxies in front of us the
real client is therefore the **Nth entry from the right**, and everything to its
left is client-supplied and worthless:

    hops=1 (Railway edge only)   "<spoof>, <client>"              -> [-1]
    hops=2 (CDN in front of it)  "<spoof>, <client>, <edge>"      -> [-2]

``settings.trusted_proxy_hops = 0`` means "no proxy in front" and we use the
socket peer, which is correct for local dev and direct exposure.

Fails safe, never open: if the header is missing, too short for the configured
hop count, or the extracted value isn't an IP, we fall back to the socket peer.
The worst outcome is the old shared bucket; the one outcome we never allow is
trusting an attacker-chosen value.
"""

from __future__ import annotations

import ipaddress

from starlette.requests import Request

from app.config import settings

_FALLBACK = "127.0.0.1"


def _peer(request: Request) -> str:
    return request.client.host if request.client else _FALLBACK


def _valid_ip(value: str) -> str | None:
    candidate = value.strip()
    # IPv6 in XFF may be bracketed, and some proxies append :port.
    if candidate.startswith("[") and "]" in candidate:
        candidate = candidate[1 : candidate.index("]")]
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        pass
    # "1.2.3.4:5678" — strip a single trailing port for IPv4 only (an unbracketed
    # IPv6 literal is all colons and must not be split).
    if candidate.count(":") == 1:
        head = candidate.rsplit(":", 1)[0]
        try:
            return str(ipaddress.ip_address(head))
        except ValueError:
            return None
    return None


def client_ip(request: Request) -> str:
    """The caller's IP, honoring exactly ``settings.trusted_proxy_hops`` proxies."""
    hops = settings.trusted_proxy_hops
    if hops < 1:
        return _peer(request)

    forwarded = request.headers.get("x-forwarded-for")
    if not forwarded:
        return _peer(request)

    parts = [p for p in (item.strip() for item in forwarded.split(",")) if p]
    # Fewer entries than trusted hops means the header did not traverse the
    # proxy chain we were promised — treat it as untrustworthy rather than
    # reaching for whatever is left.
    if len(parts) < hops:
        return _peer(request)

    return _valid_ip(parts[-hops]) or _peer(request)
