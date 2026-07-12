import io
import zipfile

import pytest

from app.config import settings
from app.services.linkedin_graph.parsing import parse_linkedin_connections_csv
from app.services.resume_parser import _validate_docx_archive


def _zip(entries: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return output.getvalue()


def test_docx_rejects_path_traversal_entry():
    payload = _zip(
        {
            "[Content_Types].xml": b"types",
            "word/document.xml": b"document",
            "../escape.txt": b"bad",
        }
    )
    with pytest.raises(ValueError, match="unsafe archive entry"):
        _validate_docx_archive(payload)


def test_docx_rejects_unsafe_compression_ratio(monkeypatch):
    monkeypatch.setattr(settings, "max_archive_compression_ratio", 10)
    payload = _zip(
        {
            "[Content_Types].xml": b"types",
            "word/document.xml": b"A" * 100_000,
        }
    )
    with pytest.raises(ValueError, match="compression ratio"):
        _validate_docx_archive(payload)


def test_linkedin_csv_enforces_row_and_cell_limits(monkeypatch):
    header = b"First Name,Last Name,URL\n"
    monkeypatch.setattr(settings, "max_linkedin_csv_rows", 1)
    with pytest.raises(ValueError, match="too many rows"):
        parse_linkedin_connections_csv(
            header
            + b"A,B,https://www.linkedin.com/in/a\n"
            + b"C,D,https://www.linkedin.com/in/c\n"
        )

    monkeypatch.setattr(settings, "max_linkedin_csv_rows", 10)
    monkeypatch.setattr(settings, "max_linkedin_csv_cell_chars", 5)
    with pytest.raises(ValueError, match="oversized cell"):
        parse_linkedin_connections_csv(header + b"LongName,B,https://x\n")
