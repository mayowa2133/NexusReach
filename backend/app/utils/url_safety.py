"""SSRF protection for fetching user-influenced URLs (audit pass-2 P4).

The exact-job import lets a user submit an arbitrary ``job_url`` that the server
then fetches. Without validation, a user can point it at cloud-metadata
(``169.254.169.254``), loopback, or internal-network hosts and exfiltrate the
response. These helpers reject private/loopback/link-local/reserved targets and
re-validate every redirect hop so a public host can't bounce to an internal one.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlparse

import httpx

# Hostnames that resolve to cloud-metadata or internal services on some platforms.
_BLOCKED_HOSTNAMES = {
    "metadata.google.internal",
    "metadata",
    "localhost",
}


def _ip_is_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def is_safe_public_url(url: str | None) -> bool:
    """Return True only for an http(s) URL whose host resolves to public IPs.

    Rejects non-http(s) schemes, missing hosts, IP literals in private/loopback/
    link-local/reserved/multicast ranges, blocked metadata hostnames, and any
    hostname that fails to resolve or resolves to a blocked IP.
    """
    try:
        parsed = urlparse((url or "").strip())
    except ValueError:
        return False

    if parsed.scheme not in {"http", "https"}:
        return False

    host = parsed.hostname
    if not host:
        return False
    if host.lower() in _BLOCKED_HOSTNAMES:
        return False

    # IP literal — check directly.
    try:
        return not _ip_is_blocked(ipaddress.ip_address(host))
    except ValueError:
        pass

    # Hostname — resolve and block if it points at a private/internal address
    # (catches internal hostnames and DNS that resolves to private IPs). If the
    # host can't be resolved we ALLOW it: an unresolvable host can't be fetched,
    # so it poses no SSRF risk, and failing closed would break legitimate public
    # imports in DNS-restricted environments.
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except OSError:
        return True
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr.split("%")[0])
        except ValueError:
            continue
        if _ip_is_blocked(ip):
            return False
    return True


async def is_safe_public_url_async(url: str | None) -> bool:
    """Async wrapper that runs the (DNS-resolving) check off the event loop."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, is_safe_public_url, url)


def is_safe_public_host(host: str | None) -> bool:
    """Return True only if a bare hostname resolves entirely to public IPs.

    Used before opening a raw socket to a host derived from user input (e.g. an
    MX target before an SMTP probe) — audit M5. Unlike ``is_safe_public_url``,
    an unresolvable host fails CLOSED here: we are about to connect to it, so if
    it can't be safely resolved we refuse rather than allow.
    """
    if not host:
        return False
    host = host.strip().rstrip(".")
    if not host or host.lower() in _BLOCKED_HOSTNAMES:
        return False

    # IP literal — check directly.
    try:
        return not _ip_is_blocked(ipaddress.ip_address(host))
    except ValueError:
        pass

    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except OSError:
        return False
    saw_address = False
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr.split("%")[0])
        except ValueError:
            continue
        saw_address = True
        if _ip_is_blocked(ip):
            return False
    return saw_address


async def is_safe_public_host_async(host: str | None) -> bool:
    """Async wrapper that runs the (DNS-resolving) host check off the event loop."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, is_safe_public_host, host)


async def safe_get(
    url: str,
    *,
    headers: dict | None = None,
    timeout_seconds: float = 20,
    max_redirects: int = 5,
    client: httpx.AsyncClient | None = None,
) -> httpx.Response | None:
    """GET a URL with SSRF protection on the initial host and every redirect hop.

    Returns None if any hop targets a non-public host. Redirects are followed
    manually so each ``Location`` is validated before connecting — a public URL
    that 302s to ``169.254.169.254`` is refused. An existing ``client`` may be
    passed (it must have ``follow_redirects=False``); otherwise one is created
    and closed here.
    """
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=timeout_seconds, follow_redirects=False)
    try:
        current = url
        for _ in range(max_redirects + 1):
            if not await is_safe_public_url_async(current):
                return None
            try:
                resp = await client.get(current, headers=headers)
            except httpx.HTTPError:
                return None
            if resp.status_code in {301, 302, 303, 307, 308}:
                location = resp.headers.get("location")
                if not location:
                    return resp
                current = str(resp.url.join(location))
                continue
            return resp
        return None
    finally:
        if own_client:
            await client.aclose()
