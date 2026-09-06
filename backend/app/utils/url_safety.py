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
import time
import uuid
import zlib
from contextlib import asynccontextmanager
from urllib.parse import urlparse

import httpx
from fastapi import HTTPException

from app.config import settings

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


def is_safe_url_syntax(url: str | None) -> bool:
    """Cheap admission check; fetch-time DNS validation remains mandatory."""
    try:
        parsed = urlparse((url or "").strip())
        host = (parsed.hostname or "").lower().rstrip(".")
        _ = parsed.port  # force malformed-port validation
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"} or not host or parsed.username or parsed.password:
        return False
    if host in _BLOCKED_HOSTNAMES:
        return False
    try:
        return not _ip_is_blocked(ipaddress.ip_address(host))
    except ValueError:
        # Public hostnames have at least one label boundary. DNS is resolved and
        # pinned only at connection time so parsing remains deterministic.
        return "." in host


def is_safe_public_url(url: str | None) -> bool:
    """Return True only for an http(s) URL whose host resolves to public IPs.

    Rejects non-http(s) schemes, missing hosts, IP literals in private/loopback/
    link-local/reserved/multicast ranges, blocked metadata hostnames, and any
    hostname that resolves to a blocked IP. Hosts that cannot be resolved fail
    closed.
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
    # (catches internal hostnames and DNS that resolves to private IPs). Direct
    # clients will resolve again when connecting; rendered fetchers are opt-in
    # and must be protected by outbound network policy.
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
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


async def is_safe_public_url_async(url: str | None) -> bool:
    """Async wrapper that runs the (DNS-resolving) check off the event loop."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, is_safe_public_url, url)


def _resolve_public_address(url: str) -> tuple[str, str] | None:
    """Resolve once and return the original hostname plus a vetted public IP."""
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return None
    host = parsed.hostname
    if parsed.scheme not in {"http", "https"} or not host:
        return None
    if host.lower() in _BLOCKED_HOSTNAMES:
        return None
    try:
        literal = ipaddress.ip_address(host)
        return None if _ip_is_blocked(literal) else (host, str(literal))
    except ValueError:
        pass

    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except OSError:
        return None
    addresses: list[str] = []
    for info in infos:
        raw = info[4][0].split("%")[0]
        try:
            ip = ipaddress.ip_address(raw)
        except ValueError:
            return None
        if _ip_is_blocked(ip):
            return None
        normalized = str(ip)
        if normalized not in addresses:
            addresses.append(normalized)
    return (host, addresses[0]) if addresses else None


async def _resolve_public_address_async(url: str) -> tuple[str, str] | None:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _resolve_public_address, url)


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


MAX_PAGE_BYTES = 5 * 1024 * 1024
_FETCH_SLOTS = asyncio.Semaphore(10)

_ACQUIRE_FETCH_SLOT = """
local now = tonumber(ARGV[1])
local expires = tonumber(ARGV[2])
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now)
redis.call('ZREMRANGEBYSCORE', KEYS[2], '-inf', now)
if redis.call('ZCARD', KEYS[1]) >= 10 or redis.call('ZCARD', KEYS[2]) >= 2 then
  return 0
end
redis.call('ZADD', KEYS[1], expires, ARGV[3])
redis.call('ZADD', KEYS[2], expires, ARGV[3])
redis.call('EXPIRE', KEYS[1], 30)
redis.call('EXPIRE', KEYS[2], 30)
return 1
"""


@asynccontextmanager
async def _fetch_capacity():
    """Enforce two fetches per account and ten across all API workers."""
    if settings.environment in {"test", "e2e"}:
        async with _FETCH_SLOTS:
            yield
        return
    from app.services.paid_context import get_subject
    from app.utils.discovery_rate_limit import _client

    subject = get_subject()
    if subject is None:
        raise HTTPException(503, "Retrieval account context is unavailable.")
    lease = uuid.uuid4().hex
    account_key = f"nr:fetch:account:{subject}"
    global_key = "nr:fetch:global"
    try:
        redis = _client()
        now = time.time()
        accepted = await redis.eval(
            _ACQUIRE_FETCH_SLOT,
            2,
            global_key,
            account_key,
            now,
            now + 25,
            lease,
        )
        if accepted != 1:
            raise HTTPException(
                429,
                "Too many page retrievals are already running.",
                headers={"Retry-After": "5"},
            )
        try:
            yield
        finally:
            await redis.zrem(global_key, lease)
            await redis.zrem(account_key, lease)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, "Retrieval capacity could not be established.") from None


async def _bounded_body(response: httpx.Response) -> bytes:
    """Bound wire bytes and incremental decompression independently."""
    length = response.headers.get("content-length")
    if length and int(length) > MAX_PAGE_BYTES:
        raise ValueError("Page too large")
    if response.is_stream_consumed:
        # In-memory transports can provide pre-read bodies; real sends stream.
        if len(response.content) > MAX_PAGE_BYTES:
            raise ValueError("Page too large")
        return response.content
    encoding = response.headers.get("content-encoding", "identity").lower()
    if encoding not in {"identity", "gzip", "deflate"}:
        raise ValueError("Unsupported page encoding")
    decoder = zlib.decompressobj(31 if encoding == "gzip" else 15) if encoding != "identity" else None
    body = bytearray()
    wire = 0
    async for chunk in response.aiter_raw(chunk_size=65536):
        wire += len(chunk)
        if wire > MAX_PAGE_BYTES:
            raise ValueError("Page too large")
        decoded = decoder.decompress(chunk, MAX_PAGE_BYTES-len(body)+1) if decoder else chunk
        body.extend(decoded)
        if len(body) > MAX_PAGE_BYTES or (decoder and decoder.unconsumed_tail):
            raise ValueError("Decoded page too large")
    if decoder:
        if not decoder.eof or decoder.unused_data:
            raise ValueError("Invalid compressed page")
    return bytes(body)


async def safe_get(
    url: str, *, headers: dict | None = None, timeout_seconds: float = 20,
    max_redirects: int = 5, client: httpx.AsyncClient | None = None,
) -> httpx.Response | None:
    """Fetch only public pinned addresses under one time and byte budget."""
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=timeout_seconds, follow_redirects=False)
    try:
        async with asyncio.timeout(min(timeout_seconds, 20)), _fetch_capacity():
            current = url
            for _ in range(min(max_redirects, 5) + 1):
                resolved = await _resolve_public_address_async(current)
                if not resolved:
                    return None
                original_host, resolved_ip = resolved
                if isinstance(client, httpx.AsyncClient):
                    original_url = httpx.URL(current)
                    request_headers = dict(headers or {})
                    request_headers.update({"Host": original_url.netloc.decode("ascii"),
                                            "Connection": "close", "Accept-Encoding": "gzip, deflate"})
                    request = client.build_request("GET", original_url.copy_with(host=resolved_ip), headers=request_headers)
                    request.extensions["sni_hostname"] = original_host
                    response = await client.send(request, stream=True, follow_redirects=False)
                    try:
                        if response.status_code in {301, 302, 303, 307, 308}:
                            location = response.headers.get("location")
                            if not location:
                                return None
                            current = str(original_url.join(location))
                            continue
                        content = await _bounded_body(response)
                        response_headers = {k: v for k, v in response.headers.items()
                                            if k.lower() not in {"content-encoding", "content-length"}}
                        request.url = original_url
                        return httpx.Response(response.status_code, headers=response_headers, content=content, request=request)
                    finally:
                        await response.aclose()
                else:
                    # Legacy non-network test doubles; production uses AsyncClient.
                    response = await client.get(current, headers=headers)
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if not location:
                            return response
                        current = str(httpx.URL(current).join(location))
                        continue
                    return response
            return None
    except (httpx.HTTPError, TimeoutError, ValueError, zlib.error):
        return None
    finally:
        if own_client:
            await client.aclose()
