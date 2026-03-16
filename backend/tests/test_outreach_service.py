"""Unit tests for outreach service constants and validation logic — Phase 7.

Since the service functions require a real async DB session (PostgreSQL),
we test the pure validation logic and constants here.
"""

from app.services.outreach_service import VALID_STATUSES


class TestValidStatuses:
    """Tests for the VALID_STATUSES constant."""

    def test_contains_all_expected_statuses(self):
        expected = {"draft", "sent", "connected", "responded", "met", "following_up", "closed"}
        assert VALID_STATUSES == expected

    def test_draft_is_valid(self):
        assert "draft" in VALID_STATUSES

    def test_sent_is_valid(self):
        assert "sent" in VALID_STATUSES

    def test_connected_is_valid(self):
        assert "connected" in VALID_STATUSES

    def test_responded_is_valid(self):
        assert "responded" in VALID_STATUSES

    def test_met_is_valid(self):
        assert "met" in VALID_STATUSES

    def test_following_up_is_valid(self):
        assert "following_up" in VALID_STATUSES

    def test_closed_is_valid(self):
        assert "closed" in VALID_STATUSES

    def test_invalid_status_not_in_set(self):
        assert "potato" not in VALID_STATUSES
        assert "pending" not in VALID_STATUSES
        assert "archived" not in VALID_STATUSES

    def test_status_count(self):
        """Exactly 7 valid statuses."""
        assert len(VALID_STATUSES) == 7

    def test_statuses_are_lowercase(self):
        for status in VALID_STATUSES:
            assert status == status.lower(), f"{status} is not lowercase"
