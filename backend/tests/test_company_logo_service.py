import base64
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import company_logo_service as svc

pytestmark = pytest.mark.asyncio


def test_is_valid_domain_accepts_real_hostnames_rejects_junk():
    assert svc.is_valid_domain("salesforce.com")
    assert svc.is_valid_domain("Sub.Example.co.uk")  # lowercased internally
    assert not svc.is_valid_domain("")
    assert not svc.is_valid_domain("localhost")  # no dot
    assert not svc.is_valid_domain("has space.com")
    assert not svc.is_valid_domain("bad..com")


async def test_get_logo_png_short_circuits_invalid_domain_without_redis():
    with patch.object(svc.search_cache_client, "_client") as client:
        assert await svc.get_logo_png("localhost") is None
    client.assert_not_called()


async def test_get_logo_png_returns_cached_bytes():
    redis = MagicMock()
    redis.get = AsyncMock(return_value=base64.b64encode(b"PNGDATA").decode())
    redis.set = AsyncMock()
    with patch.object(svc.search_cache_client, "_client", return_value=redis):
        assert await svc.get_logo_png("salesforce.com") == b"PNGDATA"


async def test_get_logo_png_miss_marker_returns_none():
    redis = MagicMock()
    redis.get = AsyncMock(return_value=svc._MISS_MARKER)
    with patch.object(svc.search_cache_client, "_client", return_value=redis):
        assert await svc.get_logo_png("salesforce.com") is None


async def test_get_logo_png_real_logo_distinct_from_globe():
    redis = MagicMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock()

    def fake_fetch(_client, domain):
        return b"REALLOGO" if domain == "salesforce.com" else b"GLOBE"

    with (
        patch.object(svc.search_cache_client, "_client", return_value=redis),
        patch.object(svc, "_fetch_favicon", new=AsyncMock(side_effect=fake_fetch)),
    ):
        assert await svc.get_logo_png("salesforce.com") == b"REALLOGO"


async def test_get_logo_png_treats_generic_globe_as_no_logo():
    """A domain with no real icon returns the globe; we serve None so the UI
    falls back to initials instead of a generic globe."""
    redis = MagicMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock()

    with (
        patch.object(svc.search_cache_client, "_client", return_value=redis),
        patch.object(svc, "_fetch_favicon", new=AsyncMock(return_value=b"GLOBE")),
    ):
        assert await svc.get_logo_png("whatever-unknown.com") is None
    # the miss is cached so we don't refetch every page load
    assert any(call.args and call.args[1] == svc._MISS_MARKER for call in redis.set.call_args_list)
