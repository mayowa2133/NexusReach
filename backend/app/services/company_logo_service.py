"""Company logo proxy: resolve + cache company favicons server-side.

The job-card UI used to load a third-party favicon service directly from the
browser (one request per company, per page view, leaking which companies a user
browses). This proxies that through our backend instead: the browser only talks
to us, and each domain is fetched at most once per TTL and shared across users
via Redis. Unknown domains resolve to the favicon service's generic globe, which
we detect and treat as "no logo" so the UI falls back to a clean initials badge.
"""

from __future__ import annotations

import base64
import logging
import re

import httpx

from app.clients import search_cache_client
from app.config import settings

logger = logging.getLogger(__name__)

_FAVICON_URL = "https://www.google.com/s2/favicons?domain={domain}&sz=64"
_LOGO_TTL_SECONDS = 60 * 60 * 24 * 30  # real logos: cache 30 days
_MISS_TTL_SECONDS = 60 * 60 * 24  # unknown/globe: re-check daily
_GLOBE_SIG_KEY = "logo:globe-signature"
_GLOBE_SENTINEL_DOMAIN = "nonexistent-company-zzzqq-000.com"
_MISS_MARKER = "MISS"
_DOMAIN_RE = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?:\.[a-z0-9-]{1,63})+$")
_CACHE_INDEX_KEY = "logo:index"
_CAP_CACHE_LUA = """
redis.call('ZADD', KEYS[1], ARGV[1], KEYS[2])
local count = redis.call('ZCARD', KEYS[1])
local overflow = count - tonumber(ARGV[2])
if overflow > 0 then
  local victims = redis.call('ZRANGE', KEYS[1], 0, overflow - 1)
  for _, victim in ipairs(victims) do redis.call('DEL', victim) end
  redis.call('ZREM', KEYS[1], unpack(victims))
end
return count
"""


async def _track_bounded_cache_key(key: str) -> None:
    """Keep arbitrary-domain logo cache cardinality within a hard ceiling."""
    try:
        import time

        await search_cache_client._client().eval(
            _CAP_CACHE_LUA,
            2,
            _CACHE_INDEX_KEY,
            key,
            time.time(),
            settings.logo_cache_max_entries,
        )
    except Exception:
        # Caching is optional; request limits still bound outbound work.
        logger.debug("logo cache index update failed", exc_info=True)


def is_valid_domain(domain: str) -> bool:
    """True for a plausible public hostname (blocks IPs, localhost, junk)."""
    candidate = (domain or "").strip().lower()
    if not candidate or len(candidate) > 253 or ".." in candidate:
        return False
    return _DOMAIN_RE.match(candidate) is not None


async def _fetch_favicon(client: httpx.AsyncClient, domain: str) -> bytes | None:
    try:
        resp = await client.get(_FAVICON_URL.format(domain=domain))
    except httpx.HTTPError as exc:
        logger.debug("favicon fetch failed for %s: %s", domain, exc)
        return None
    content_type = resp.headers.get("content-type", "")
    if resp.status_code == 200 and resp.content and content_type.startswith("image"):
        return resp.content
    return None


async def _globe_signature(client: httpx.AsyncClient) -> bytes | None:
    """The bytes the favicon service returns for a domain it has no icon for.

    Captured once (and cached) so a generic globe can be treated as "no logo".
    """
    try:
        cached = await search_cache_client._client().get(_GLOBE_SIG_KEY)
    except Exception:
        cached = None
    if cached:
        try:
            return base64.b64decode(cached)
        except (ValueError, TypeError):
            pass
    signature = await _fetch_favicon(client, _GLOBE_SENTINEL_DOMAIN)
    if signature:
        try:
            await search_cache_client._client().set(
                _GLOBE_SIG_KEY, base64.b64encode(signature).decode(), ex=_LOGO_TTL_SECONDS
            )
        except Exception:
            pass
    return signature


async def get_logo_png(domain: str) -> bytes | None:
    """Return cached favicon bytes for *domain*, or None when unknown/unavailable."""
    domain = (domain or "").strip().lower()
    if not is_valid_domain(domain):
        return None

    key = f"logo:{domain}"
    try:
        cached = await search_cache_client._client().get(key)
    except Exception:
        cached = None
    if cached == _MISS_MARKER:
        return None
    if cached:
        try:
            return base64.b64decode(cached)
        except (ValueError, TypeError):
            pass

    data: bytes | None = None
    async with httpx.AsyncClient(timeout=8, follow_redirects=True) as client:
        fetched = await _fetch_favicon(client, domain)
        if fetched is not None:
            globe = await _globe_signature(client)
            data = None if globe is not None and fetched == globe else fetched

    try:
        if data:
            await search_cache_client._client().set(
                key, base64.b64encode(data).decode(), ex=_LOGO_TTL_SECONDS
            )
        else:
            await search_cache_client._client().set(
                key, _MISS_MARKER, ex=_MISS_TTL_SECONDS
            )
        await _track_bounded_cache_key(key)
    except Exception:
        pass
    return data
