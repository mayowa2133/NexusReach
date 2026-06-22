"""Tests for posting-time parsing — accurate dates + honest sub-day freshness.

`_parse_posting_time` returns ``(precise_ts, posted_date)``:
- precise_ts is set ONLY when the source gives genuine sub-day precision (ISO
  datetime, epoch, "30 minutes ago"), so "15 minutes ago" in the UI is real.
- posted_date is the calendar day, resolved even from coarse relative phrases
  ("3 days ago"), so recency ordering uses the true posting time — not our
  ingest time — and invalid dates still resolve to None.
"""

from datetime import date, datetime, timezone

import pytest

from app.services.jobs.normalize import _parse_posting_time, _parse_posted_date

NOW = datetime(2026, 6, 22, 14, 30, 0, tzinfo=timezone.utc)


def parse(value):
    return _parse_posting_time(value, now=NOW)


# --- Precise sources: posted_ts is set -------------------------------------

def test_iso_datetime_z_is_precise():
    ts, day = parse("2026-06-22T14:00:00Z")
    assert ts == datetime(2026, 6, 22, 14, 0, 0, tzinfo=timezone.utc)
    assert day == date(2026, 6, 22)


def test_iso_datetime_with_offset_normalizes_to_utc():
    ts, day = parse("2026-06-22T10:00:00-04:00")
    assert ts == datetime(2026, 6, 22, 14, 0, 0, tzinfo=timezone.utc)
    assert day == date(2026, 6, 22)


def test_epoch_seconds_is_precise():
    # 2026-06-22T14:00:00Z
    epoch = int(datetime(2026, 6, 22, 14, 0, 0, tzinfo=timezone.utc).timestamp())
    ts, day = parse(str(epoch))
    assert ts == datetime(2026, 6, 22, 14, 0, 0, tzinfo=timezone.utc)
    assert day == date(2026, 6, 22)


def test_epoch_millis_is_precise():
    epoch_ms = int(datetime(2026, 6, 22, 14, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
    ts, day = parse(str(epoch_ms))
    assert ts == datetime(2026, 6, 22, 14, 0, 0, tzinfo=timezone.utc)


def test_minutes_ago_is_precise():
    ts, day = parse("30 minutes ago")
    assert ts == datetime(2026, 6, 22, 14, 0, 0, tzinfo=timezone.utc)
    assert day == date(2026, 6, 22)


def test_hours_ago_is_precise():
    ts, _ = parse("2 hours ago")
    assert ts == datetime(2026, 6, 22, 12, 30, 0, tzinfo=timezone.utc)


def test_an_hour_ago_is_precise():
    ts, _ = parse("an hour ago")
    assert ts == datetime(2026, 6, 22, 13, 30, 0, tzinfo=timezone.utc)


def test_just_now_is_precise():
    ts, day = parse("just now")
    assert ts == NOW
    assert day == date(2026, 6, 22)


# --- Coarse sources: day only, posted_ts stays None ------------------------

def test_iso_date_only_is_day_precision():
    ts, day = parse("2026-06-20")
    assert ts is None  # no fabricated time
    assert day == date(2026, 6, 20)


def test_days_ago_is_day_precision():
    ts, day = parse("3 days ago")
    assert ts is None
    assert day == date(2026, 6, 19)


def test_today_is_day_precision():
    ts, day = parse("today")
    assert ts is None
    assert day == date(2026, 6, 22)


def test_yesterday_is_day_precision():
    ts, day = parse("yesterday")
    assert ts is None
    assert day == date(2026, 6, 21)


def test_one_week_ago_is_day_precision():
    ts, day = parse("1 week ago")
    assert ts is None
    assert day == date(2026, 6, 15)


# --- Unparseable / invalid -> (None, None) ---------------------------------

@pytest.mark.parametrize("value", ["2026-02-30", "2026-13-01", "0000-00-00", "asap", "", None])
def test_invalid_returns_none(value):
    assert parse(value) == (None, None)


def test_parse_posted_date_wrapper_returns_day():
    """The back-compat wrapper returns just the day component."""
    assert _parse_posted_date("2026-06-22T14:00:00Z") == date(2026, 6, 22)
    assert _parse_posted_date("2026-02-30") is None
