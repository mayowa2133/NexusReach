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

    def record_success(self) -> None:
        if self.state != CircuitState.CLOSED:
            logger.info(
                "circuit breaker reset after success",
                extra={"provider": self.provider, "prev_state": self.state.value},
            )
        self.state = CircuitState.CLOSED
        self.consecutive_failures = 0

    def record_failure(self) -> None:
        self.consecutive_failures += 1
        self.last_failure_time = time.monotonic()
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


def record_success(provider: str) -> None:
    get_circuit(provider).record_success()


def record_failure(provider: str) -> None:
    get_circuit(provider).record_failure()


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
