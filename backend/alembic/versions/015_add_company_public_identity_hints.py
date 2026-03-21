"""Add company public identity hints for trusted public matching.

Revision ID: 015_add_company_public_identity_hints
Revises: 014_add_company_identity_and_job_dedupe
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "015_add_company_public_identity_hints"
down_revision = "014_add_company_identity_and_job_dedupe"
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


def _slugify_company_name(value: str | None) -> str:
    return "-".join(_normalize_company_name(value).split())


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


def upgrade() -> None:
    bind = op.get_bind()
    companies = sa.table(
        "companies",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("public_identity_slugs", postgresql.ARRAY(sa.String())),
        sa.column("identity_hints", postgresql.JSONB(astext_type=sa.Text())),
    )

    op.add_column("companies", sa.Column("public_identity_slugs", postgresql.ARRAY(sa.String()), nullable=True))
    op.add_column("companies", sa.Column("identity_hints", postgresql.JSONB(astext_type=sa.Text()), nullable=True))

    company_rows = bind.execute(
        sa.text(
            """
            SELECT id, name, normalized_name, domain, careers_url
            FROM companies
            """
        )
    ).mappings().all()

    for row in company_rows:
        slugs: set[str] = set()
        normalized_slug = _slugify_company_name(row["name"] or row["normalized_name"])
        if normalized_slug:
            slugs.add(normalized_slug)

        domain_slug = _domain_root(row["domain"])
        careers_host = urlparse(row["careers_url"]).netloc.lower() if row["careers_url"] else ""
        careers_slug = _domain_root(row["careers_url"])
        if domain_slug:
            slugs.add(domain_slug)
        if careers_slug:
            slugs.add(careers_slug)

        hints = {
            "normalized_slug": normalized_slug,
            "domain_root": domain_slug or None,
            "careers_host": careers_host or None,
        }

        bind.execute(
            companies.update()
            .where(companies.c.id == row["id"])
            .values(
                public_identity_slugs=sorted(slugs) or None,
                identity_hints=hints,
            )
        )


def downgrade() -> None:
    op.drop_column("companies", "identity_hints")
    op.drop_column("companies", "public_identity_slugs")
