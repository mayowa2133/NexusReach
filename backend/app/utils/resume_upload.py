"""Shared validation for uploaded resume files.

Promoted out of ``routers/profile.py`` so the public waitlist route can reuse it
without a router-to-router import. Two layers:

* ``normalize_resume_content_type`` — declared content-type / filename-extension
  allowlist (what the authenticated upload has always done).
* ``ensure_resume_magic_bytes`` — sniffs the actual file header. Declared types
  are attacker-controlled, so on the *unauthenticated* waitlist route we also
  require the bytes to really start like a PDF or a ZIP (DOCX is a ZIP).
"""

from fastapi import HTTPException, status

ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

ALLOWED_EXTENSIONS = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

_PDF_MAGIC = b"%PDF-"
_ZIP_MAGIC = b"PK\x03\x04"  # DOCX is an OOXML zip archive


def normalize_resume_content_type(
    content_type: str | None, filename: str | None
) -> str:
    """Resolve a trusted content type, falling back to the filename extension.

    Raises ``HTTPException(400)`` when neither the declared type nor the
    extension is an allowed resume format.
    """
    normalized = (content_type or "").strip().lower()
    if normalized in ALLOWED_CONTENT_TYPES:
        return normalized

    lowered_name = (filename or "").lower()
    for extension, inferred_type in ALLOWED_EXTENSIONS.items():
        if lowered_name.endswith(extension):
            return inferred_type

    allowed = ", ".join(sorted(ALLOWED_EXTENSIONS))
    raise HTTPException(
        status_code=400,
        detail=f"Unsupported file type: {content_type}. Upload a {allowed} resume.",
    )


def ensure_resume_magic_bytes(data: bytes, content_type: str) -> None:
    """Verify the bytes actually look like the claimed format.

    Raises ``HTTPException(422)`` on a mismatch. Cheap defense for a public
    endpoint: a caller can claim ``application/pdf`` for arbitrary content, and
    we would otherwise hand it to the parser sandbox on trust alone.
    """
    if content_type == "application/pdf":
        if not data.startswith(_PDF_MAGIC):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="That file doesn't look like a valid PDF.",
            )
        return

    if not data.startswith(_ZIP_MAGIC):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="That file doesn't look like a valid DOCX.",
        )
