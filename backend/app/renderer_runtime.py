"""Credential-free LaTeX compiler used only by the isolated renderer service."""

from __future__ import annotations

import io
import os
import shutil
import signal
import subprocess
import tempfile
from pathlib import Path

from pypdf import PdfReader

MAX_RENDER_INPUT_BYTES = 2 * 1024 * 1024
MAX_RENDER_OUTPUT_BYTES = 16 * 1024 * 1024


def _timeout_seconds() -> int:
    try:
        return min(30, max(1, int(os.environ.get("NEXUSREACH_RENDER_TIMEOUT_SECONDS", "25"))))
    except ValueError:
        return 25


def _verify_pdf(data: bytes) -> None:
    if not data.startswith(b"%PDF") or len(data) > MAX_RENDER_OUTPUT_BYTES:
        raise ValueError("Renderer produced an invalid or oversized PDF.")
    reader = PdfReader(io.BytesIO(data))
    if not 1 <= len(reader.pages) <= 25:
        raise ValueError("Renderer produced an invalid page count.")


def render_pdf(content: str) -> bytes:
    """Compile bounded LaTeX with shell escape and external file access disabled."""
    encoded = content.encode("utf-8")
    if not encoded or len(encoded) > MAX_RENDER_INPUT_BYTES:
        raise ValueError("Render input is empty or oversized.")
    pdflatex = shutil.which("pdflatex")
    if not pdflatex:
        raise ValueError("pdflatex is unavailable.")

    scratch = os.environ.get("NEXUSREACH_RENDER_SCRATCH_DIR")
    with tempfile.TemporaryDirectory(prefix="nr-render-", dir=scratch) as temporary:
        directory = Path(temporary)
        source = directory / "resume.tex"
        output = directory / "resume.pdf"
        source.write_bytes(encoded)
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": temporary,
            "TMPDIR": temporary,
            "openin_any": "p",
            "openout_any": "p",
        }
        process = subprocess.Popen(
            [
                pdflatex,
                "-interaction=nonstopmode",
                "-halt-on-error",
                "-no-shell-escape",
                "-output-directory",
                temporary,
                str(source),
            ],
            cwd=temporary,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        try:
            process.communicate(timeout=_timeout_seconds())
        except subprocess.TimeoutExpired as exc:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            raise ValueError("LaTeX rendering timed out safely.") from exc
        if process.returncode != 0 or not output.exists():
            raise ValueError("LaTeX rendering failed safely.")
        data = output.read_bytes()
        _verify_pdf(data)
        return data
