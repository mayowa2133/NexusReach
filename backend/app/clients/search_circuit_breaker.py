"""In-memory circuit breaker for search providers.

Prevents burning the full provider timeout on every request when a provider
(e.g. SearXNG) is unreachable.  After ``failure_threshold`` consecutive
failures the circuit *opens* and the provider is skipped for
``recovery_seconds``.  After the cooldown, a single probe request is allowed
(*half-open*); if it succeeds the circuit resets, otherwise it opens again.

Thread safety is not required — the FastAPI event loop is single-threaded.
"""

from __future__ import annotations

import logging
import time
from enum import Enum

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DEFAULT_FAILURE_THRESHOLD = 3
DEFAULT_RECOVERY_SECONDS = 60


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class _ProviderCircuit:
    __slots__ = (
        "provider",
        "state",
        "consecutive_failures",
        "failure_threshold",
        "recovery_seconds",
        "last_failure_time",
        "total_requests",
        "total_successes",
        "total_failures",
        "total_cache_hits",
        "total_results_returned",
    )

    def __init__(
        self,
        provider: str,
        *,
        failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
        recovery_seconds: float = DEFAULT_RECOVERY_SECONDS,
    ) -> None:
        self.provider = provider
        self.state = CircuitState.CLOSED
        self.consecutive_failures = 0
        self.failure_threshold = failure_threshold
        self.recovery_seconds = recovery_seconds
        self.last_failure_time: float = 0.0
        # Telemetry counters (in-memory, reset on restart)
        self.total_requests: int = 0
        self.total_successes: int = 0
        self.total_failures: int = 0
        self.total_cache_hits: int = 0
        self.total_results_returned: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def should_allow_request(self) -> bool:
        """Return True if the provider should be tried."""
        if self.state == CircuitState.CLOSED:
            return True
        if self.state == CircuitState.OPEN:
            elapsed = time.monotonic() - self.last_failure_time
            if elapsed >= self.recovery_seconds:
                self.state = CircuitState.HALF_OPEN
                logger.info(
                    "circuit breaker half-open (probe allowed)",
                    extra={"provider": self.provider},
                )
                return True
            return False
        # HALF_OPEN — already probing; allow exactly one request
        return True

    def record_success(self, *, result_count: int = 0) -> None:
        if self.state != CircuitState.CLOSED:
            logger.info(
                "circuit breaker reset after success",
                extra={"provider": self.provider, "prev_state": self.state.value},
            )
        self.state = CircuitState.CLOSED
        self.consecutive_failures = 0
        self.total_successes += 1
        self.total_results_returned += result_count

    def record_failure(self) -> None:
        self.consecutive_failures += 1
        self.last_failure_time = time.monotonic()
        self.total_failures += 1
        if self.consecutive_failures >= self.failure_threshold:
            self.state = CircuitState.OPEN
            logger.warning(
                "circuit breaker opened — provider skipped until recovery",
                extra={
                    "provider": self.provider,
                    "consecutive_failures": self.consecutive_failures,
                    "recovery_seconds": self.recovery_seconds,
                },
            )
        elif self.state == CircuitState.HALF_OPEN:
            # Probe failed — re-open
            self.state = CircuitState.OPEN
            logger.warning(
                "circuit breaker re-opened after failed probe",
                extra={"provider": self.provider},
            )


# ---------------------------------------------------------------------------
# Registry — one circuit per provider name
# ---------------------------------------------------------------------------
_circuits: dict[str, _ProviderCircuit] = {}


def get_circuit(
    provider: str,
    *,
    failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
    recovery_seconds: float = DEFAULT_RECOVERY_SECONDS,
) -> _ProviderCircuit:
    circuit = _circuits.get(provider)
    if circuit is None:
        circuit = _ProviderCircuit(
            provider,
            failure_threshold=failure_threshold,
            recovery_seconds=recovery_seconds,
        )
        _circuits[provider] = circuit
    return circuit


def is_provider_available(provider: str) -> bool:
    """Check if a provider's circuit allows requests."""
    return get_circuit(provider).should_allow_request()


def record_success(provider: str, *, result_count: int = 0) -> None:
    get_circuit(provider).record_success(result_count=result_count)


def record_failure(provider: str) -> None:
    get_circuit(provider).record_failure()


def record_request(provider: str) -> None:
    """Increment the total request counter for a provider."""
    get_circuit(provider).total_requests += 1


def record_cache_hit(provider: str) -> None:
    """Increment the cache hit counter for a provider."""
    get_circuit(provider).total_cache_hits += 1


def reset_all() -> None:
    """Reset all circuits — useful in tests."""
    _circuits.clear()


def status_summary() -> dict[str, dict]:
    """Return a snapshot of all tracked provider circuits."""
    return {
        name: {
            "state": circuit.state.value,
            "consecutive_failures": circuit.consecutive_failures,
        }
        for name, circuit in _circuits.items()
    }


def telemetry_summary() -> dict[str, dict]:
    """Return telemetry counters for all tracked providers.

    This supplements ``status_summary()`` with request/success/failure/cache
    counts accumulated since the process started.
    """
    return {
        name: {
            "state": circuit.state.value,
            "consecutive_failures": circuit.consecutive_failures,
            "total_requests": circuit.total_requests,
            "total_successes": circuit.total_successes,
            "total_failures": circuit.total_failures,
            "total_cache_hits": circuit.total_cache_hits,
            "total_results_returned": circuit.total_results_returned,
            "success_rate": (
                round(circuit.total_successes / circuit.total_requests, 3)
                if circuit.total_requests > 0
                else None
            ),
        }
        for name, circuit in _circuits.items()
    }
