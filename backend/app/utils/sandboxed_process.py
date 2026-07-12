"""Killable, resource-limited subprocess execution for untrusted file work."""

from __future__ import annotations

import asyncio
import base64
import importlib
import json
import os
import platform
import signal
import socket
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


class SandboxedProcessError(ValueError):
    """Raised when isolated work fails, times out, or exceeds a limit."""


def _json_safe(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"__nexusreach_bytes__": base64.b64encode(value).decode("ascii")}
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"Unsupported sandbox value type: {type(value).__name__}")


def _json_restore(value: Any) -> Any:
    if isinstance(value, dict):
        if set(value) == {"__nexusreach_bytes__"}:
            return base64.b64decode(value["__nexusreach_bytes__"], validate=True)
        return {key: _json_restore(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_restore(item) for item in value]
    return value


def _apply_resource_limits(memory_bytes: int, cpu_seconds: int, output_bytes: int) -> None:
    try:
        import resource

        if platform.system() == "Linux":
            resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 1))
        resource.setrlimit(resource.RLIMIT_FSIZE, (output_bytes, output_bytes))
        resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    except (ImportError, OSError, ValueError):
        # Parent wall timeout remains mandatory on platforms lacking rlimits.
        pass


def _deny_network() -> None:
    def denied(*_args, **_kwargs):
        raise PermissionError("Network access is disabled in the parser sandbox")

    socket.socket = denied  # type: ignore[assignment]
    socket.create_connection = denied  # type: ignore[assignment]
    socket.getaddrinfo = denied  # type: ignore[assignment]


def _worker_main(request_path: str, result_path: str) -> int:
    request = json.loads(Path(request_path).read_text(encoding="utf-8"))
    os.umask(0o077)
    _apply_resource_limits(
        int(request["memory_bytes"]),
        int(request["cpu_seconds"]),
        int(request["output_bytes"]),
    )
    try:
        module = importlib.import_module(request["module"])
        function = getattr(module, request["function"])
        _deny_network()
        value = function(
            *_json_restore(request.get("args", [])),
            **_json_restore(request.get("kwargs", {})),
        )
        payload = {"status": "ok", "value": _json_safe(value)}
    except BaseException as exc:
        payload = {"status": "error", "value": f"{type(exc).__name__}: {str(exc)[:300]}"}
    data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    if len(data) > int(request["output_bytes"]):
        data = b'{"status":"error","value":"Sandbox result exceeded its size limit."}'
    Path(result_path).write_bytes(data)
    return 0


def run_in_sandbox(
    module_name: str,
    function_name: str,
    *args: Any,
    timeout_seconds: float,
    memory_bytes: int,
    cpu_seconds: int,
    output_bytes: int,
    **kwargs: Any,
) -> Any:
    """Run a module function in a fresh interpreter and kill its process group."""
    with tempfile.TemporaryDirectory(prefix="nexusreach-sandbox-") as work_dir:
        work_path = Path(work_dir)
        request_path = work_path / "request.json"
        result_path = work_path / "result.json"
        request_path.write_text(
            json.dumps(
                {
                    "module": module_name,
                    "function": function_name,
                    "args": _json_safe(args),
                    "kwargs": _json_safe(kwargs),
                    "memory_bytes": memory_bytes,
                    "cpu_seconds": cpu_seconds,
                    "output_bytes": output_bytes,
                },
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
        backend_root = str(Path(__file__).resolve().parents[2])
        env = {
            key: os.environ[key]
            for key in ("PATH", "HOME", "TMPDIR", "SYSTEMROOT")
            if key in os.environ
        }
        env["PYTHONPATH"] = backend_root
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "app.utils.sandboxed_process",
                "--worker",
                str(request_path),
                str(result_path),
            ],
            cwd=work_dir,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        try:
            process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                process.kill()
            process.wait()
            raise SandboxedProcessError("Sandboxed processing timed out.") from exc
        if process.returncode != 0 or not result_path.exists():
            raise SandboxedProcessError("Sandboxed processing failed safely.")
        data = result_path.read_bytes()
        if len(data) > output_bytes:
            raise SandboxedProcessError("Sandboxed processing returned too much data.")
        payload = json.loads(data)
        if payload.get("status") != "ok":
            raise SandboxedProcessError(str(payload.get("value")))
        return _json_restore(payload.get("value"))


async def run_in_sandbox_async(
    module_name: str,
    function_name: str,
    *args: Any,
    timeout_seconds: float,
    memory_bytes: int,
    cpu_seconds: int,
    output_bytes: int,
    **kwargs: Any,
) -> Any:
    return await asyncio.to_thread(
        run_in_sandbox,
        module_name,
        function_name,
        *args,
        timeout_seconds=timeout_seconds,
        memory_bytes=memory_bytes,
        cpu_seconds=cpu_seconds,
        output_bytes=output_bytes,
        **kwargs,
    )


if __name__ == "__main__":
    if len(sys.argv) != 4 or sys.argv[1] != "--worker":
        raise SystemExit(2)
    raise SystemExit(_worker_main(sys.argv[2], sys.argv[3]))
