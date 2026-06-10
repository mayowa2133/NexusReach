"""Bounded upload reading (audit H2).

``UploadFile.read()`` with no argument pulls the entire body into memory. A
single large (or maliciously crafted) upload can therefore OOM-kill the web
worker. ``read_upload_capped`` reads in fixed chunks and aborts with HTTP 413 as
soon as the running total exceeds the caller's ceiling, so memory use is bounded
regardless of what the client sends.
"""

from __future__ import annotations

from fastapi import HTTPException, UploadFile

_CHUNK_BYTES = 1024 * 1024  # 1 MiB


async def read_upload_capped(file: UploadFile, max_bytes: int) -> bytes:
    """Read an ``UploadFile`` fully, but never more than ``max_bytes``.

    Raises ``HTTPException(413)`` if the stream exceeds the cap. The declared
    ``Content-Length`` is not trusted — the chunked read is the real guard.
    """
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(_CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            limit_mb = max(1, max_bytes // (1024 * 1024))
            raise HTTPException(
                status_code=413,
                detail=f"Upload exceeds the maximum size of {limit_mb} MB.",
            )
        chunks.append(chunk)
    return b"".join(chunks)
