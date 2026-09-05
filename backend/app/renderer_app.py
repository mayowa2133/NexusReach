"""Dedicated Celery app that registers only bounded render work."""

import os
from pathlib import Path

from celery import Celery

from app.renderer_runtime import MAX_RENDER_INPUT_BYTES, render_pdf as compile_pdf

broker = os.environ.get("NEXUSREACH_RENDERER_REDIS_URL", "")
if not broker or not broker.startswith(("redis://", "rediss://")):
    raise RuntimeError("NEXUSREACH_RENDERER_REDIS_URL is required")


def _read_limit(path: str) -> str:
    try:
        return Path(path).read_text().strip()
    except OSError:
        return ""


def _mount_is_read_only(path: str) -> bool:
    """Return whether the Linux mount containing *path* is mounted read-only."""
    target = Path(path).resolve()
    best_match: tuple[int, bool] | None = None
    try:
        lines = Path("/proc/self/mountinfo").read_text().splitlines()
    except OSError:
        return False
    for line in lines:
        left, separator, _right = line.partition(" - ")
        if not separator:
            continue
        fields = left.split()
        if len(fields) < 6:
            continue
        mountpoint = Path(
            fields[4]
            .replace("\\040", " ")
            .replace("\\011", "\t")
            .replace("\\012", "\n")
            .replace("\\134", "\\")
        )
        try:
            target.relative_to(mountpoint)
        except ValueError:
            continue
        candidate = (len(mountpoint.parts), "ro" in fields[5].split(","))
        if best_match is None or candidate[0] > best_match[0]:
            best_match = candidate
    return bool(best_match and best_match[1])


def _validate_production_isolation() -> None:
    if os.environ.get("NEXUSREACH_ENVIRONMENT") != "production":
        return
    errors: list[str] = []
    if os.getuid() == 0:
        errors.append("renderer must not run as root")
    forbidden = (
        "NEXUSREACH_DATABASE_URL",
        "NEXUSREACH_SUPABASE_SERVICE_ROLE_KEY",
        "NEXUSREACH_SUPABASE_JWT_SECRET",
        "NEXUSREACH_GOOGLE_CLIENT_SECRET",
        "NEXUSREACH_MICROSOFT_CLIENT_SECRET",
        "NEXUSREACH_OPENAI_API_KEY",
        "NEXUSREACH_ANTHROPIC_API_KEY",
        "NEXUSREACH_GROQ_API_KEY",
        "NEXUSREACH_HUNTER_API_KEY",
        "NEXUSREACH_RESEND_API_KEY",
        "NEXUSREACH_TOKEN_ENCRYPTION_KEYS",
    )
    errors.extend(f"{name} must be absent" for name in forbidden if os.environ.get(name))
    if os.environ.get("NEXUSREACH_RENDERER_EGRESS_ENFORCED") != "true":
        errors.append("broker-only renderer egress has not been attested")

    memory = _read_limit("/sys/fs/cgroup/memory.max")
    if not memory.isdigit() or int(memory) > 1024 * 1024 * 1024:
        errors.append("renderer memory cgroup must be at most 1 GiB")
    pids = _read_limit("/sys/fs/cgroup/pids.max")
    if not pids.isdigit() or int(pids) > 64:
        errors.append("renderer PID cgroup must be at most 64")
    cpu = _read_limit("/sys/fs/cgroup/cpu.max").split()
    if len(cpu) != 2 or not all(part.isdigit() for part in cpu) or int(cpu[0]) > int(cpu[1]):
        errors.append("renderer CPU cgroup must be at most one CPU")

    scratch = Path(os.environ.get("NEXUSREACH_RENDER_SCRATCH_DIR", "/scratch"))
    try:
        stats = os.statvfs(scratch)
        if stats.f_blocks * stats.f_frsize > 128 * 1024 * 1024:
            errors.append("renderer scratch filesystem must be at most 128 MiB")
    except OSError:
        errors.append("bounded renderer scratch filesystem is unavailable")
    if not _mount_is_read_only("/app"):
        errors.append("renderer application filesystem must be read-only")
    if errors:
        raise RuntimeError("Renderer isolation requirements failed: " + "; ".join(errors))


_validate_production_isolation()

renderer_app = Celery("nexusreach-renderer", broker=broker, backend=broker)
renderer_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    result_expires=600,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    worker_concurrency=1,
    task_routes={"renderer.render_pdf": {"queue": "render"}},
)


@renderer_app.task(
    name="renderer.render_pdf",
    soft_time_limit=25,
    time_limit=30,
    acks_late=True,
)
def render_pdf(content: str) -> bytes:
    if not isinstance(content, str) or len(content.encode("utf-8")) > MAX_RENDER_INPUT_BYTES:
        raise ValueError("Render payload is invalid or oversized.")
    return compile_pdf(content)
