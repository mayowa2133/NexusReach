"""Privacy posture of the GLOBAL known-people cache (finding #11).

Rows here describe third parties who never used the product and never
consented, and the table is shared across every user — so what it holds and how
long it holds it matters more than anywhere else in the schema.
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

from app.models.known_person import KnownPerson
from app.services import known_people_service as kps


def test_the_model_has_no_email_column():
    """A shared row must never carry a contact email (audit H4).

    Emails belong on the finding user's own `Person` row. The legacy column was
    nulled by migration 048 and dropped by 064; this fails if anyone re-adds it.
    """
    assert not hasattr(KnownPerson, "work_email")
    columns = {c.name for c in KnownPerson.__table__.columns}
    assert not {c for c in columns if "email" in c}


def test_profile_data_sanitizer_strips_every_email_shape():
    dirty = {
        "email": "a@b.com",
        "work_email": "a@b.com",
        "personal_email": "a@b.com",
        "email_address": "a@b.com",
        "emails": ["a@b.com"],
        "search_query": "engineers at acme",
        "title": "Staff Engineer",
    }
    clean = kps._sanitize_profile_data_for_cache(dirty)
    assert clean == {"title": "Staff Engineer"}


def test_candidate_dict_exposes_no_email_field():
    kp = KnownPerson(
        id=uuid.uuid4(),
        full_name="Jordan Rivera",
        normalized_name="jordan rivera",
        primary_source="github",
        last_discovered_at=datetime.now(timezone.utc),
    )
    kpc = MagicMock()
    kpc.company_name = "Acme"
    kpc.company_domain = "acme.com"
    kpc.title_at_company = None
    payload = kps._to_candidate_dict(kp, kpc)
    assert not any("email" in key for key in payload)


async def test_purge_deletes_records_nobody_has_touched_in_a_long_time():
    """Flagging alone kept third-party PII forever; expiry now deletes."""
    db = AsyncMock()
    result = MagicMock()
    result.rowcount = 7
    db.execute.return_value = result

    deleted = await kps.purge_expired_records(db, purge_days=180)

    assert deleted == 7
    db.commit.assert_awaited()


async def test_erase_requires_an_identifier():
    import pytest

    db = AsyncMock()
    with pytest.raises(ValueError):
        await kps.erase_known_person(db)
    db.execute.assert_not_awaited()


async def test_erase_by_linkedin_url_deletes():
    db = AsyncMock()
    result = MagicMock()
    result.rowcount = 1
    db.execute.return_value = result

    deleted = await kps.erase_known_person(
        db, linkedin_url="https://www.linkedin.com/in/someone"
    )

    assert deleted == 1
    db.commit.assert_awaited()


def test_purge_window_is_bounded_and_sane():
    from app.config import settings

    assert 0 < settings.known_people_purge_days <= 365
    # Must be older than the 90-day expiry flag, or rows would vanish while the
    # cache still considers them live.
    assert settings.known_people_purge_days > 90
    assert timedelta(days=settings.known_people_purge_days) > timedelta(days=90)
