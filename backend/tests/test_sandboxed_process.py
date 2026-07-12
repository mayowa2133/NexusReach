import pytest

from app.utils.sandboxed_process import SandboxedProcessError, run_in_sandbox


LIMITS = {
    "memory_bytes": 256 * 1024 * 1024,
    "cpu_seconds": 1,
    "output_bytes": 1024 * 1024,
}


def test_sandbox_round_trips_bytes_without_pickle():
    result = run_in_sandbox(
        "base64", "b64decode", "c2FmZQ==", timeout_seconds=2, **LIMITS
    )
    assert result == b"safe"


def test_sandbox_kills_work_after_wall_timeout():
    with pytest.raises(SandboxedProcessError, match="timed out"):
        run_in_sandbox("time", "sleep", 5, timeout_seconds=0.2, **LIMITS)


def test_sandbox_denies_network_access():
    with pytest.raises(SandboxedProcessError, match="Network access is disabled"):
        run_in_sandbox(
            "socket",
            "create_connection",
            ("example.com", 80),
            timeout_seconds=2,
            **LIMITS,
        )
