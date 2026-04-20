"""Unit tests for the cadence engine rule helpers."""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from app.services.cadence_service import (
    URGENCY_RANK,
    _rule_applied_untouched,
    _rule_awaiting_reply,
    _rule_draft_unsent,
    _rule_live_targets_unused,
    _rule_reply_needed,
    _rule_thank_you_due,
)


def _now():
    return datetime.now(timezone.utc)


def _outreach(**kw):
    log = MagicMock()
    log.id = kw.get("id", uuid.uuid4())
    log.user_id = kw.get("user_id", uuid.uuid4())
    log.person_id = kw.get("person_id", uuid.uuid4())
    log.job_id = kw.get("job_id")
    log.message_id = kw.get("message_id")
    log.status = kw.get("status", "sent")
    log.channel = kw.get("channel", "email")
    log.response_received = kw.get("response_received", False)
    log.last_contacted_at = kw.get("last_contacted_at")
    log.sent_at = kw.get("sent_at")
    log.updated_at = kw.get("updated_at", _now())
    person = MagicMock()
    person.full_name = kw.get("person_name", "Jane Doe")
    log.person = person
    return log


def _job(**kw):
    j = MagicMock()
    j.id = kw.get("id", uuid.uuid4())
    j.user_id = kw.get("user_id", uuid.uuid4())
    j.title = kw.get("title", "Software Engineer")
    j.company_name = kw.get("company_name", "TechCorp")
    j.stage = kw.get("stage", "applied")
    j.applied_at = kw.get("applied_at")
    j.interview_rounds = kw.get("interview_rounds")
    return j


def _message(**kw):
    m = MagicMock()
    m.id = kw.get("id", uuid.uuid4())
    m.person_id = kw.get("person_id", uuid.uuid4())
    m.status = kw.get("status", "draft")
    m.channel = kw.get("channel", "email")
    m.goal = kw.get("goal", "interview")
    m.created_at = kw.get("created_at", _now())
    m.context_snapshot = kw.get("context_snapshot", {})
    person = MagicMock()
    person.full_name = kw.get("person_name", "Jane Doe")
    m.person = person
    return m


def _snapshot(**kw):
    s = MagicMock()
    s.job_id = kw.get("job_id", uuid.uuid4())
    s.user_id = kw.get("user_id", uuid.uuid4())
    s.verified_count = kw.get("verified_count", 2)
    s.warm_path_count = kw.get("warm_path_count", 1)
    s.company_name = kw.get("company_name", "TechCorp")
    s.updated_at = kw.get("updated_at", _now())
    return s


# --- reply_needed ----------------------------------------------------------


def test_reply_needed_emits_when_responded_received():
    log = _outreach(status="responded", response_received=True)
    actions = _rule_reply_needed([log])
    assert len(actions) == 1
    assert actions[0].kind == "reply_needed"
    assert actions[0].urgency == "high"


def test_reply_needed_skips_if_no_response():
    log = _outreach(status="sent", response_received=False)
    assert _rule_reply_needed([log]) == []


def test_reply_needed_skips_if_already_advanced():
    log = _outreach(status="met", response_received=True)
    assert _rule_reply_needed([log]) == []


# --- awaiting_reply --------------------------------------------------------


def test_awaiting_reply_after_threshold():
    old = _now() - timedelta(days=10)
    log = _outreach(status="sent", last_contacted_at=old)
    actions = _rule_awaiting_reply([log])
    assert len(actions) == 1
    assert actions[0].suggested_goal == "follow_up"


def test_awaiting_reply_recent_skipped():
    log = _outreach(status="sent", last_contacted_at=_now() - timedelta(days=1))
    assert _rule_awaiting_reply([log]) == []


def test_awaiting_reply_skips_responded():
    log = _outreach(
        status="sent",
        response_received=True,
        last_contacted_at=_now() - timedelta(days=10),
    )
    assert _rule_awaiting_reply([log]) == []


# --- draft_unsent ----------------------------------------------------------


def test_draft_unsent_after_24h():
    msg = _message(status="draft", created_at=_now() - timedelta(hours=48))
    actions = _rule_draft_unsent([msg], [])
    assert len(actions) == 1
    assert actions[0].urgency == "high"


def test_draft_unsent_recent_skipped():
    msg = _message(status="draft", created_at=_now() - timedelta(hours=2))
    assert _rule_draft_unsent([msg], []) == []


def test_draft_unsent_sent_status_skipped():
    msg = _message(status="copied", created_at=_now() - timedelta(hours=48))
    assert _rule_draft_unsent([msg], []) == []


# --- thank_you_due ---------------------------------------------------------


def test_thank_you_due_recent_interview():
    interview_at = (_now() - timedelta(hours=12)).isoformat()
    job = _job(stage="interviewing", interview_rounds=[{"scheduled_at": interview_at}])
    actions = _rule_thank_you_due([job], [])
    assert len(actions) == 1
    assert actions[0].suggested_goal == "thank_you"


def test_thank_you_due_skipped_if_already_sent():
    interview_dt = _now() - timedelta(hours=12)
    job = _job(
        stage="interviewing",
        interview_rounds=[{"scheduled_at": interview_dt.isoformat()}],
    )
    msg = _message(
        goal="thank_you",
        created_at=interview_dt + timedelta(hours=1),
        context_snapshot={"job_id": str(job.id)},
    )
    assert _rule_thank_you_due([job], [msg]) == []


def test_thank_you_due_skipped_for_non_interviewing_stage():
    job = _job(stage="applied")
    assert _rule_thank_you_due([job], []) == []


# --- live_targets_unused ---------------------------------------------------


def test_live_targets_unused_when_snapshot_has_verified_and_no_outreach():
    job = _job()
    snap = _snapshot(job_id=job.id, verified_count=3)
    actions = _rule_live_targets_unused([snap], [], {job.id: job})
    assert len(actions) == 1
    assert actions[0].meta["verified_count"] == 3


def test_live_targets_unused_skipped_when_outreach_exists():
    job = _job()
    snap = _snapshot(job_id=job.id, verified_count=3)
    log = _outreach(job_id=job.id)
    assert _rule_live_targets_unused([snap], [log], {job.id: job}) == []


# --- applied_untouched -----------------------------------------------------


def test_applied_untouched_after_threshold():
    job = _job(stage="applied", applied_at=_now() - timedelta(days=10))
    actions = _rule_applied_untouched([job], [])
    assert len(actions) == 1
    assert actions[0].urgency == "low"


def test_applied_untouched_skipped_if_recent():
    job = _job(stage="applied", applied_at=_now() - timedelta(days=1))
    assert _rule_applied_untouched([job], []) == []


def test_applied_untouched_skipped_if_outreach_exists():
    job = _job(stage="applied", applied_at=_now() - timedelta(days=10))
    log = _outreach(job_id=job.id)
    assert _rule_applied_untouched([job], [log]) == []


# --- ranking ---------------------------------------------------------------


def test_urgency_rank_order():
    assert URGENCY_RANK["high"] < URGENCY_RANK["medium"] < URGENCY_RANK["low"]
