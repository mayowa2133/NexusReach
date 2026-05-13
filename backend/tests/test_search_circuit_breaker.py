"""Unit tests for the search provider circuit breaker."""

import time

import pytest

from app.clients.search_circuit_breaker import (
    CircuitState,
    get_circuit,
    is_provider_available,
    record_failure,
    record_success,
    reset_all,
    status_summary,
)


@pytest.fixture(autouse=True)
def _clean_circuits():
    reset_all()
    yield
    reset_all()


def test_new_circuit_is_closed_and_allows_requests():
    assert is_provider_available("searxng") is True
    circuit = get_circuit("searxng")
    assert circuit.state == CircuitState.CLOSED


def test_circuit_opens_after_failure_threshold():
    for _ in range(3):
        record_failure("searxng")
    assert is_provider_available("searxng") is False
    circuit = get_circuit("searxng")
    assert circuit.state == CircuitState.OPEN


def test_circuit_stays_closed_below_threshold():
    record_failure("searxng")
    record_failure("searxng")
    assert is_provider_available("searxng") is True
    circuit = get_circuit("searxng")
    assert circuit.state == CircuitState.CLOSED


def test_success_resets_failure_count():
    record_failure("searxng")
    record_failure("searxng")
    record_success("searxng")
    # After reset, need 3 fresh failures to open
    record_failure("searxng")
    record_failure("searxng")
    assert is_provider_available("searxng") is True


def test_circuit_transitions_to_half_open_after_recovery():
    circuit = get_circuit("searxng", recovery_seconds=0.1)
    for _ in range(3):
        circuit.record_failure()
    assert circuit.state == CircuitState.OPEN
    assert circuit.should_allow_request() is False

    # Wait for recovery
    time.sleep(0.15)
    assert circuit.should_allow_request() is True
    assert circuit.state == CircuitState.HALF_OPEN


def test_half_open_success_closes_circuit():
    circuit = get_circuit("searxng", recovery_seconds=0.1)
    for _ in range(3):
        circuit.record_failure()
    time.sleep(0.15)
    circuit.should_allow_request()  # moves to HALF_OPEN
    circuit.record_success()
    assert circuit.state == CircuitState.CLOSED
    assert circuit.consecutive_failures == 0


def test_half_open_failure_reopens_circuit():
    circuit = get_circuit("searxng", recovery_seconds=0.1)
    for _ in range(3):
        circuit.record_failure()
    time.sleep(0.15)
    circuit.should_allow_request()  # moves to HALF_OPEN
    circuit.record_failure()
    assert circuit.state == CircuitState.OPEN


def test_status_summary_reports_all_tracked_providers():
    record_failure("searxng")
    record_failure("brave")
    summary = status_summary()
    assert "searxng" in summary
    assert "brave" in summary
    assert summary["searxng"]["state"] == "closed"
    assert summary["searxng"]["consecutive_failures"] == 1


def test_reset_all_clears_circuits():
    record_failure("searxng")
    reset_all()
    summary = status_summary()
    assert summary == {}


def test_different_providers_have_independent_circuits():
    for _ in range(3):
        record_failure("searxng")
    assert is_provider_available("searxng") is False
    assert is_provider_available("brave") is True
