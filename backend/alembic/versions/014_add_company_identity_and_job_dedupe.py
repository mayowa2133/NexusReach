"""Add company identity trust fields and dedupe ATS jobs.

Revision ID: 014_add_company_identity_and_job_dedupe
Revises: 013_add_email_verification_fields
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

import sqlalchemy as sa
from alembic import op

revision = "014_add_company_identity_and_job_dedupe"
down_revision = "013_add_email_verification_fields"
branch_labels = None
depends_on = None

LEGAL_SUFFIX_TOKENS = {
    "co",
    "company",
    "inc",
    "incorporated",
    "corp",
    "corporation",
    "ltd",
    "limited",
    "llc",
    "plc",
    "gmbh",
    "ag",
    "pte",
    "pty",
}
LEADING_STOP_TOKENS = {"the"}


def _tokens(value: str | None) -> list[str]:
    return re.findall(r"[a-z0-9]+", (value or "").lower())


def _normalize_company_name(value: str | None) -> str:
    tokens = _tokens(value)
    filtered = [token for token in tokens if token not in LEGAL_SUFFIX_TOKENS]
    while filtered and filtered[0] in LEADING_STOP_TOKENS:
        filtered = filtered[1:]
    canonical = filtered or tokens
    return " ".join(canonical)


def _is_ambiguous_company_name(value: str | None) -> bool:
    normalized = _normalize_company_name(value)
    if not normalized:
        return False
    tokens = normalized.split()
    return len(tokens) == 1 and len(tokens[0]) <= 4


def _domain_root(value: str | None) -> str:
    raw = (value or "").strip().lower()
    if not raw:
        return ""
    host = urlparse(raw if "://" in raw else f"https://{raw}").netloc.lower()
    if not host:
        host = raw.split("/")[0]
    parts = [part for part in host.split(".") if part]
    if len(parts) >= 3 and len(parts[-1]) == 2 and parts[-2] in {"co", "com", "org", "net"}:
        return parts[-3]
    if len(parts) >= 2:
        return parts[-2]
    return parts[0] if parts else ""


def _is_trusted_domain(name: str | None, domain: str | None) -> bool:
    normalized_name = _normalize_company_name(name)
    if not normalized_name or not domain or _is_ambiguous_company_name(name):
        return False
    return _normalize_company_name(_domain_root(domain)) == normalized_name


def upgrade() -> None:
    bind = op.get_bind()

    op.add_column("companies", sa.Column("normalized_name", sa.String(length=255), nullable=True))
    op.add_column(
        "companies",
        sa.Column("domain_trusted", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    company_rows = bind.execute(
        sa.text(
            """
            SELECT id, user_id, name, domain, email_pattern, email_pattern_confidence,
                   size, industry, description, careers_url, enriched_at, created_at
            FROM companies
            ORDER BY created_at ASC NULLS FIRST, id ASC
            """
        )
    ).mappings().all()

    company_groups: dict[tuple[object, str], list[dict]] = {}
    for row in company_rows:
        normalized_name = _normalize_company_name(row["name"])
        trusted = _is_trusted_domain(row["name"], row["domain"])
        sanitized_domain = row["domain"] if trusted else None
        sanitized_pattern = row["email_pattern"] if trusted else None
        sanitized_confidence = row["email_pattern_confidence"] if trusted else None
        bind.execute(
            sa.text(
                """
                UPDATE companies
                SET normalized_name = :normalized_name,
                    domain = :domain,
                    domain_trusted = :domain_trusted,
                    email_pattern = :email_pattern,
                    email_pattern_confidence = :email_pattern_confidence
                WHERE id = :id
                """
            ),
            {
                "id": row["id"],
                "normalized_name": normalized_name,
                "domain": sanitized_domain,
                "domain_trusted": trusted,
                "email_pattern": sanitized_pattern,
                "email_pattern_confidence": sanitized_confidence,
            },
        )
        company_groups.setdefault((row["user_id"], normalized_name), []).append(
            {
                **dict(row),
                "normalized_name": normalized_name,
                "domain": sanitized_domain,
                "domain_trusted": trusted,
                "email_pattern": sanitized_pattern,
                "email_pattern_confidence": sanitized_confidence,
            }
        )

    for group in company_groups.values():
        keep = group[0]
        merged_name = min(
            [candidate["name"] for candidate in group if candidate.get("name")],
            key=len,
            default=keep["name"],
        )
        merged = {
            "id": keep["id"],
            "name": merged_name,
            "domain": keep["domain"],
            "domain_trusted": keep["domain_trusted"],
            "email_pattern": keep["email_pattern"],
            "email_pattern_confidence": keep["email_pattern_confidence"],
            "size": keep["size"],
            "industry": keep["industry"],
            "description": keep["description"],
            "careers_url": keep["careers_url"],
            "enriched_at": keep["enriched_at"],
        }

        for duplicate in group[1:]:
            if duplicate["domain_trusted"] and not merged["domain_trusted"]:
                merged["domain"] = duplicate["domain"]
                merged["domain_trusted"] = True
                merged["email_pattern"] = duplicate["email_pattern"]
                merged["email_pattern_confidence"] = duplicate["email_pattern_confidence"]

            for field in ("size", "industry", "description", "careers_url", "enriched_at"):
                if not merged[field] and duplicate[field]:
                    merged[field] = duplicate[field]

            bind.execute(
                sa.text("UPDATE persons SET company_id = :keep_id WHERE company_id = :duplicate_id"),
                {"keep_id": keep["id"], "duplicate_id": duplicate["id"]},
            )
            bind.execute(
                sa.text("UPDATE jobs SET company_id = :keep_id WHERE company_id = :duplicate_id"),
                {"keep_id": keep["id"], "duplicate_id": duplicate["id"]},
            )
            bind.execute(
                sa.text("UPDATE notifications SET company_id = :keep_id WHERE company_id = :duplicate_id"),
                {"keep_id": keep["id"], "duplicate_id": duplicate["id"]},
            )
            bind.execute(
                sa.text("DELETE FROM companies WHERE id = :duplicate_id"),
                {"duplicate_id": duplicate["id"]},
            )

        bind.execute(
            sa.text(
                """
                UPDATE companies
                SET name = :name,
                    domain = :domain,
                    domain_trusted = :domain_trusted,
                    email_pattern = :email_pattern,
                    email_pattern_confidence = :email_pattern_confidence,
                    size = :size,
                    industry = :industry,
                    description = :description,
                    careers_url = :careers_url,
                    enriched_at = :enriched_at
                WHERE id = :id
                """
            ),
            merged,
        )

    job_rows = bind.execute(
        sa.text(
            """
            SELECT id, user_id, ats, external_id, url, description, location, company_id, created_at
            FROM jobs
            WHERE external_id IS NOT NULL
            ORDER BY created_at ASC NULLS FIRST, id ASC
            """
        )
    ).mappings().all()
    job_groups: dict[tuple[object, object, object], list[dict]] = {}
    for row in job_rows:
        job_groups.setdefault((row["user_id"], row["ats"], row["external_id"]), []).append(dict(row))

    for group in job_groups.values():
        keep = group[0]
        merged = {
            "id": keep["id"],
            "url": keep["url"],
            "description": keep["description"],
            "location": keep["location"],
            "company_id": keep["company_id"],
        }

        for duplicate in group[1:]:
            for field in ("url", "description", "location", "company_id"):
                if not merged[field] and duplicate[field]:
                    merged[field] = duplicate[field]

            bind.execute(
                sa.text("UPDATE outreach_logs SET job_id = :keep_id WHERE job_id = :duplicate_id"),
                {"keep_id": keep["id"], "duplicate_id": duplicate["id"]},
            )
            bind.execute(
                sa.text("UPDATE notifications SET job_id = :keep_id WHERE job_id = :duplicate_id"),
                {"keep_id": keep["id"], "duplicate_id": duplicate["id"]},
            )
            bind.execute(
                sa.text("DELETE FROM jobs WHERE id = :duplicate_id"),
                {"duplicate_id": duplicate["id"]},
            )

        bind.execute(
            sa.text(
                """
                UPDATE jobs
                SET url = :url,
                    description = :description,
                    location = :location,
                    company_id = :company_id
                WHERE id = :id
                """
            ),
            merged,
        )

    op.alter_column("companies", "normalized_name", nullable=False)
    op.alter_column("companies", "domain_trusted", server_default=None)
    op.create_index(
        "ux_companies_user_id_normalized_name",
        "companies",
        ["user_id", "normalized_name"],
        unique=True,
    )
    op.create_index(
        "ux_jobs_user_id_ats_external_id",
        "jobs",
        ["user_id", "ats", "external_id"],
        unique=True,
        postgresql_where=sa.text("external_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ux_jobs_user_id_ats_external_id", table_name="jobs")
    op.drop_index("ux_companies_user_id_normalized_name", table_name="companies")
    op.drop_column("companies", "domain_trusted")
    op.drop_column("companies", "normalized_name")
