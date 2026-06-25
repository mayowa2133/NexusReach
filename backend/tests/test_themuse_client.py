"""Tests for the free, keyless The Muse cross-industry job source."""

import pytest

from app.clients import themuse_client
from app.services.occupation_taxonomy import occupation_keys


def _muse_job(
    job_id: int,
    name: str,
    *,
    company: str = "Acme",
    location: str = "New York, NY",
    category: str = "Healthcare",
) -> dict:
    return {
        "id": job_id,
        "name": name,
        "type": "external",
        "publication_date": "2026-06-22T04:33:05Z",
        "company": {"id": 1, "name": company, "short_name": company.lower()},
        "locations": [{"name": location}],
        "levels": [{"name": "Mid Level", "short_name": "mid"}],
        "categories": [{"name": category}],
        "refs": {"landing_page": f"https://www.themuse.com/jobs/acme/{job_id}"},
        "contents": "<div>About the role</div>",
    }


def test_normalize_muse_job_maps_core_fields():
    job = themuse_client._normalize_muse_job(
        _muse_job(42, "Registered Nurse", location="Boston, MA")
    )
    assert job is not None
    assert job["external_id"] == "themuse_42"
    assert job["title"] == "Registered Nurse"
    assert job["company_name"] == "Acme"
    assert job["location"] == "Boston, MA"
    assert job["remote"] is False
    assert job["source"] == "themuse"
    assert job["url"].endswith("/42")
    assert job["apply_url"] == job["url"]
    # publication_date is a precise ISO datetime -> drives a real posted_ts.
    assert job["posted_at"] == "2026-06-22T04:33:05Z"


def test_normalize_detects_remote_location():
    job = themuse_client._normalize_muse_job(
        _muse_job(7, "Backend Engineer", location="Flexible / Remote")
    )
    assert job is not None and job["remote"] is True


def test_normalize_drops_untitled_job():
    raw = _muse_job(1, "")
    assert themuse_client._normalize_muse_job(raw) is None


def test_every_occupation_has_a_muse_category():
    """Each taxonomy occupation must route to at least one Muse category."""
    missing = [
        key
        for key in occupation_keys()
        if not themuse_client.MUSE_CATEGORY_BY_OCCUPATION.get(key)
    ]
    assert missing == []


def test_distinctive_vocab_excludes_generic_role_words():
    """Cross-functional words must not be distinctive, or every title 'matches'."""
    vocab = themuse_client._DISTINCTIVE_VOCAB
    for generic in ("manager", "director", "senior", "analyst"):
        offenders = [key for key, toks in vocab.items() if generic in toks]
        assert offenders == [], f"{generic!r} leaked into {offenders}"
    # Distinctive role nouns survive.
    assert "marketing" in vocab["marketing"]
    assert "nurse" in vocab["healthcare"]
    assert "attorney" in vocab["legal_compliance"]


def test_relevance_gate_drops_off_category_noise():
    # Catch-all categories surface unrelated roles; the gate rejects them.
    assert not themuse_client._relevant_to_occupation(
        "Data Center Chiller Serviceman", "business_analyst"
    )
    # On-target titles pass.
    assert themuse_client._relevant_to_occupation(
        "Senior Business Analyst, Operations", "business_analyst"
    )
    assert themuse_client._relevant_to_occupation("Registered Nurse", "healthcare")


@pytest.mark.asyncio
async def test_search_themuse_filters_dedupes_and_limits(monkeypatch):
    pages = {
        1: (
            [
                _muse_job(1, "Registered Nurse", category="Healthcare"),
                _muse_job(2, "Data Center Chiller Serviceman", category="Healthcare"),
                _muse_job(1, "Registered Nurse", category="Healthcare"),  # dup id
            ],
            2,
        ),
        2: ([_muse_job(3, "Nurse Practitioner", category="Healthcare")], 2),
    }

    async def fake_page(client, *, category, page):
        return pages.get(page, ([], 0))

    monkeypatch.setattr(themuse_client, "_fetch_category_page", fake_page)

    jobs = await themuse_client.search_themuse(occupation="healthcare", limit=10)
    titles = [j["title"] for j in jobs]
    # Off-category noise dropped, duplicate id collapsed, healthcare roles kept.
    assert "Data Center Chiller Serviceman" not in titles
    assert titles.count("Registered Nurse") == 1
    assert "Nurse Practitioner" in titles


@pytest.mark.asyncio
async def test_search_themuse_query_path_token_filters(monkeypatch):
    async def fake_page(client, *, category, page):
        if page != 1:
            return ([], 1)
        return (
            [
                _muse_job(10, "Marketing Manager", category="Advertising and Marketing"),
                _muse_job(11, "Sales Associate", category="Advertising and Marketing"),
            ],
            1,
        )

    monkeypatch.setattr(themuse_client, "_fetch_category_page", fake_page)

    jobs = await themuse_client.search_themuse("Marketing Manager", limit=10)
    titles = [j["title"] for j in jobs]
    assert "Marketing Manager" in titles
    assert "Sales Associate" not in titles


class _FakeResp:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, behavior):
        self._behavior = behavior

    async def get(self, url, params=None, headers=None):
        return self._behavior()


@pytest.mark.asyncio
async def test_fetch_category_page_fails_soft_on_http_error():
    import httpx

    def raise_err():
        raise httpx.ConnectError("network down")

    results, page_count = await themuse_client._fetch_category_page(
        _FakeClient(raise_err), category="Healthcare", page=1
    )
    assert results == [] and page_count == 0


@pytest.mark.asyncio
async def test_fetch_category_page_fails_soft_on_rate_limit():
    results, page_count = await themuse_client._fetch_category_page(
        _FakeClient(lambda: _FakeResp(429)), category="Healthcare", page=1
    )
    assert results == [] and page_count == 0
