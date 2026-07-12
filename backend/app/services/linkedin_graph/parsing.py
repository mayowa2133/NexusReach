"""LinkedIn connections CSV/ZIP parsing and payload normalization."""

from __future__ import annotations

import csv
import io
import logging
import re
import zipfile
from itertools import chain
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urlparse


from app.config import settings
from app.utils.company_identity import (
    extract_public_identity_hints,
    normalize_company_name,
)
from app.utils.linkedin import normalize_linkedin_url

logger = logging.getLogger(__name__)


CSV_EXTENSIONS = {".csv"}


ZIP_EXTENSIONS = {".zip"}


LINKEDIN_GRAPH_SOURCES = {"local_sync", "manual_import"}


FOLLOW_ENTITY_TYPES = {"person", "company"}


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split()).strip()


def _canonicalize_header(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (value or "").strip().lower()).strip("_")


def _canonicalize_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        _canonicalize_header(key): value
        for key, value in row.items()
        if _canonicalize_header(key)
    }


def _lookup_value(row: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        text = _clean_text(value)
        if text:
            return text
    return ""


def _linkedin_slug_from_url(url: str | None) -> str | None:
    normalized = normalize_linkedin_url(url)
    if not normalized:
        return None
    return normalized.rstrip("/").rsplit("/", 1)[-1]


def _normalize_company_linkedin_url(url: str | None) -> str | None:
    clean = _clean_text(url)
    if not clean:
        return None
    if clean.startswith("linkedin.com") or clean.startswith("www.linkedin.com"):
        clean = f"https://{clean}"
    try:
        parsed = PurePosixPath(urlparse(clean).path)
        parts = [part for part in parsed.parts if part != "/"]
        if len(parts) >= 2 and parts[0] in {"company", "showcase"}:
            return f"https://www.linkedin.com/{parts[0]}/{parts[1].strip().lower()}"
    except Exception:
        pass
    hints = extract_public_identity_hints(clean)
    if hints.get("page_type") != "linkedin_company":
        return clean
    company_slug = hints.get("company_slug")
    if not company_slug:
        return clean
    return f"https://www.linkedin.com/company/{company_slug}"


def _company_slug_from_url(url: str | None) -> str | None:
    normalized = _normalize_company_linkedin_url(url)
    if not normalized:
        return None
    try:
        parts = [part for part in PurePosixPath(urlparse(normalized).path).parts if part != "/"]
        if len(parts) >= 2 and parts[0] in {"company", "showcase"}:
            return parts[1].strip().lower() or None
    except Exception:
        pass
    hints = extract_public_identity_hints(normalized)
    slug = hints.get("company_slug")
    return slug.lower() if isinstance(slug, str) and slug else None


def normalize_connection_payload(
    payload: dict[str, Any],
    *,
    source: str,
) -> dict[str, Any] | None:
    if source not in LINKEDIN_GRAPH_SOURCES:
        raise ValueError(f"Unsupported LinkedIn graph source: {source}")

    row = _canonicalize_row(payload)
    full_name = _lookup_value(row, "full_name", "name")
    if not full_name:
        first_name = _lookup_value(row, "first_name", "firstname")
        last_name = _lookup_value(row, "last_name", "lastname")
        full_name = " ".join(part for part in (first_name, last_name) if part).strip()
    if not full_name:
        return None

    linkedin_url = normalize_linkedin_url(
        _lookup_value(row, "linkedin_url", "profile_url", "url")
    )
    company_linkedin_url = _normalize_company_linkedin_url(
        _lookup_value(row, "company_linkedin_url", "company_url", "company_profile_url")
    )
    current_company_name = _lookup_value(
        row,
        "current_company_name",
        "company_name",
        "company",
    )
    headline = _lookup_value(row, "headline", "position", "title")
    normalized_company_name = normalize_company_name(current_company_name) or None

    return {
        "linkedin_url": linkedin_url,
        "linkedin_slug": _linkedin_slug_from_url(linkedin_url),
        "display_name": full_name,
        "headline": headline or None,
        "current_company_name": current_company_name or None,
        "normalized_company_name": normalized_company_name,
        "company_linkedin_url": company_linkedin_url,
        "company_linkedin_slug": _company_slug_from_url(company_linkedin_url),
        "source": source,
    }


def dedupe_connection_candidates(
    rows: list[dict[str, Any]],
    *,
    source: str,
) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    by_slug: dict[str, dict[str, Any]] = {}
    by_name_company: dict[tuple[str, str], dict[str, Any]] = {}

    for raw in rows:
        normalized = normalize_connection_payload(raw, source=source)
        if not normalized:
            continue

        slug = normalized.get("linkedin_slug")
        name_company_key: tuple[str, str] | None = None
        if normalized.get("display_name") and normalized.get("normalized_company_name"):
            name_company_key = (
                normalized["display_name"].strip().lower(),
                normalized["normalized_company_name"],
            )

        target = None
        if slug:
            target = by_slug.get(slug)
        if target is None and name_company_key:
            target = by_name_company.get(name_company_key)

        if target is None:
            deduped.append(normalized)
            if slug:
                by_slug[slug] = normalized
            if name_company_key:
                by_name_company[name_company_key] = normalized
            continue

        for key, value in normalized.items():
            if value and not target.get(key):
                target[key] = value
        if slug and slug not in by_slug:
            by_slug[slug] = target
        if name_company_key and name_company_key not in by_name_company:
            by_name_company[name_company_key] = target

    return deduped


def normalize_follow_payload(
    payload: dict[str, Any],
    *,
    source: str,
) -> dict[str, Any] | None:
    if source not in LINKEDIN_GRAPH_SOURCES:
        raise ValueError(f"Unsupported LinkedIn graph source: {source}")

    row = _canonicalize_row(payload)
    entity_type = _lookup_value(row, "entity_type").lower()
    if entity_type not in FOLLOW_ENTITY_TYPES:
        return None

    display_name = _lookup_value(row, "display_name", "full_name", "name")
    if not display_name:
        return None

    raw_url = _lookup_value(row, "linkedin_url", "profile_url", "url")
    company_url = _lookup_value(
        row,
        "company_linkedin_url",
        "company_profile_url",
        "company_url",
    )
    headline = _lookup_value(row, "headline", "position", "title")
    current_company_name = _lookup_value(
        row,
        "current_company_name",
        "company_name",
        "company",
    )

    if entity_type == "company":
        linkedin_url = _normalize_company_linkedin_url(raw_url)
        linkedin_slug = _company_slug_from_url(linkedin_url)
        normalized_company_name = normalize_company_name(display_name) or None
        current_company_name = display_name
        company_linkedin_url = linkedin_url
        company_linkedin_slug = linkedin_slug
    else:
        linkedin_url = normalize_linkedin_url(raw_url)
        linkedin_slug = _linkedin_slug_from_url(linkedin_url)
        company_linkedin_url = _normalize_company_linkedin_url(company_url)
        company_linkedin_slug = _company_slug_from_url(company_linkedin_url)
        normalized_company_name = normalize_company_name(current_company_name) or None

    return {
        "entity_type": entity_type,
        "linkedin_url": linkedin_url,
        "linkedin_slug": linkedin_slug,
        "display_name": display_name,
        "headline": headline or None,
        "current_company_name": current_company_name or None,
        "normalized_company_name": normalized_company_name,
        "company_linkedin_url": company_linkedin_url,
        "company_linkedin_slug": company_linkedin_slug,
        "source": source,
    }


def dedupe_follow_candidates(
    rows: list[dict[str, Any]],
    *,
    source: str,
) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    by_type_slug: dict[tuple[str, str], dict[str, Any]] = {}
    by_type_name: dict[tuple[str, str], dict[str, Any]] = {}

    for raw in rows:
        normalized = normalize_follow_payload(raw, source=source)
        if not normalized:
            continue

        entity_type = normalized["entity_type"]
        slug = normalized.get("linkedin_slug")
        display_name = _clean_text(normalized.get("display_name")).lower()
        target = by_type_slug.get((entity_type, slug)) if slug else None
        if target is None and display_name:
            target = by_type_name.get((entity_type, display_name))

        if target is None:
            deduped.append(normalized)
            if slug:
                by_type_slug[(entity_type, slug)] = normalized
            if display_name:
                by_type_name[(entity_type, display_name)] = normalized
            continue

        for key, value in normalized.items():
            if value and not target.get(key):
                target[key] = value
        if slug and (entity_type, slug) not in by_type_slug:
            by_type_slug[(entity_type, slug)] = target
        if display_name and (entity_type, display_name) not in by_type_name:
            by_type_name[(entity_type, display_name)] = target

    return deduped


def _find_csv_header_index(lines: list[list[str]]) -> int | None:
    for index, row in enumerate(lines[:25]):
        headers = {_canonicalize_header(cell) for cell in row if _canonicalize_header(cell)}
        has_name = "first_name" in headers and "last_name" in headers
        has_profile = any(key in headers for key in ("url", "profile_url", "linkedin_url"))
        if has_name and has_profile:
            return index
    return None


def parse_linkedin_connections_csv(file_bytes: bytes) -> list[dict[str, Any]]:
    decoded = file_bytes.decode("utf-8-sig", errors="replace")
    reader = csv.reader(io.StringIO(decoded))
    prefix: list[list[str]] = []
    header_index = None
    for _ in range(25):
        try:
            row = next(reader)
        except StopIteration:
            break
        prefix.append(row)
        header_index = _find_csv_header_index(prefix)
        if header_index is not None:
            break
    if header_index is None:
        raise ValueError("Could not find a LinkedIn connections CSV header.")

    header = prefix[header_index]
    if not header or len(header) > settings.max_linkedin_csv_columns:
        raise ValueError("LinkedIn CSV has too many columns.")
    payload_rows: list[dict[str, Any]] = []
    rows = chain(prefix[header_index + 1:], reader)
    for row_number, row in enumerate(rows, start=1):
        if row_number > settings.max_linkedin_csv_rows:
            raise ValueError("LinkedIn CSV has too many rows.")
        if len(row) > settings.max_linkedin_csv_columns:
            raise ValueError("LinkedIn CSV has too many columns.")
        if any(len(value) > settings.max_linkedin_csv_cell_chars for value in row):
            raise ValueError("LinkedIn CSV contains an oversized cell.")
        if not any(_clean_text(value) for value in row):
            continue
        payload_rows.append(
            {
                header[position]: row[position] if position < len(row) else ""
                for position in range(len(header))
            }
        )

    return dedupe_connection_candidates(payload_rows, source="manual_import")


def _zip_connection_candidates(names: list[str]) -> list[str]:
    return sorted(
        [
            name
            for name in names
            if name.lower().endswith(".csv")
            and "connections" in PurePosixPath(name).name.lower()
        ],
        key=lambda name: (
            0 if PurePosixPath(name).name.lower() == "connections.csv" else 1,
            len(name),
            name.lower(),
        ),
    )


def parse_linkedin_connections_zip(
    file_bytes: bytes,
    *,
    max_decompressed_bytes: int | None = None,
) -> list[dict[str, Any]]:
    # Bound the decompressed size to defuse zip bombs (audit H2): a tiny ZIP can
    # declare/expand to gigabytes of CSV and OOM the worker.
    cap = (
        max_decompressed_bytes
        if max_decompressed_bytes is not None
        else settings.max_linkedin_zip_decompressed_bytes
    )
    try:
        archive = zipfile.ZipFile(io.BytesIO(file_bytes))
    except zipfile.BadZipFile as exc:
        raise ValueError("Invalid LinkedIn data export ZIP.") from exc

    with archive:
        infos = archive.infolist()
        if len(infos) > settings.max_linkedin_zip_entries:
            raise ValueError("LinkedIn export contains too many archive entries.")
        total_expanded = 0
        for entry in infos:
            path = PurePosixPath(entry.filename)
            if path.is_absolute() or ".." in path.parts or entry.flag_bits & 0x1:
                raise ValueError("LinkedIn export contains an unsafe archive entry.")
            if entry.filename.lower().endswith((".zip", ".jar")):
                raise ValueError("Nested archives are not allowed in LinkedIn exports.")
            total_expanded += entry.file_size
            if total_expanded > cap:
                raise ValueError("LinkedIn export is too large after decompression.")
            if entry.file_size and entry.file_size / max(1, entry.compress_size) > settings.max_archive_compression_ratio:
                raise ValueError("LinkedIn export compression ratio is unsafe.")
        candidates = _zip_connection_candidates([entry.filename for entry in infos])
        if not candidates:
            raise ValueError("No LinkedIn connections CSV was found in the ZIP export.")
        info = archive.getinfo(candidates[0])
        # Reject up front when the declared size is already over the cap.
        if info.file_size > cap:
            raise ValueError("LinkedIn connections file in the ZIP is too large.")
        with archive.open(candidates[0]) as extracted:
            # Never trust the declared size — read at most cap+1 bytes and reject
            # if the real stream exceeds the cap.
            data = extracted.read(cap + 1)
            if len(data) > cap:
                raise ValueError("LinkedIn connections file in the ZIP is too large.")
        return parse_linkedin_connections_csv(data)


def parse_linkedin_connections_file(
    filename: str | None,
    file_bytes: bytes,
    *,
    max_decompressed_bytes: int | None = None,
) -> list[dict[str, Any]]:
    suffix = PurePosixPath(filename or "").suffix.lower()
    if suffix in CSV_EXTENSIONS:
        return parse_linkedin_connections_csv(file_bytes)
    if suffix in ZIP_EXTENSIONS:
        return parse_linkedin_connections_zip(
            file_bytes, max_decompressed_bytes=max_decompressed_bytes
        )
    raise ValueError("Upload a LinkedIn connections CSV or ZIP export.")
