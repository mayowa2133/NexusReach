"""Company-match predicates over imported LinkedIn graph rows."""

from __future__ import annotations

import logging
from typing import Any


from app.models.linkedin_graph import (
    LinkedInGraphConnection,
    LinkedInGraphFollow,
)
from app.utils.company_identity import (
    company_family,
    is_ambiguous_company_name,
    normalize_company_name,
)

logger = logging.getLogger(__name__)


def connection_matches_company(
    connection: LinkedInGraphConnection | dict[str, Any],
    *,
    company_name: str,
    public_identity_slugs: list[str] | None = None,
) -> bool:
    normalized_company_name = normalize_company_name(company_name)
    trusted_slugs = [slug.strip().lower() for slug in (public_identity_slugs or []) if slug]

    company_slug = (
        connection.get("company_linkedin_slug")
        if isinstance(connection, dict)
        else connection.company_linkedin_slug
    )
    connection_company_name = (
        connection.get("normalized_company_name")
        if isinstance(connection, dict)
        else connection.normalized_company_name
    )

    if is_ambiguous_company_name(company_name):
        return bool(company_slug and company_slug in trusted_slugs)

    if connection_company_name and connection_company_name == normalized_company_name:
        return True
    if company_slug and company_slug in trusted_slugs:
        return True

    # Parent/subsidiary family match: e.g. ByteDance ↔ TikTok
    if connection_company_name:
        family = company_family(company_name)
        if len(family) > 1 and connection_company_name in family:
            return True

    return False


def follow_matches_company(
    follow: LinkedInGraphFollow | dict[str, Any],
    *,
    company_name: str,
    public_identity_slugs: list[str] | None = None,
) -> bool:
    normalized_company_name = normalize_company_name(company_name)
    trusted_slugs = [slug.strip().lower() for slug in (public_identity_slugs or []) if slug]

    linkedin_slug = (
        follow.get("linkedin_slug")
        if isinstance(follow, dict)
        else follow.linkedin_slug
    )
    normalized_follow_company = (
        follow.get("normalized_company_name")
        if isinstance(follow, dict)
        else follow.normalized_company_name
    )

    if is_ambiguous_company_name(company_name):
        return bool(linkedin_slug and linkedin_slug in trusted_slugs)

    if normalized_follow_company and normalized_follow_company == normalized_company_name:
        return True
    if linkedin_slug and linkedin_slug in trusted_slugs:
        return True

    if normalized_follow_company:
        family = company_family(company_name)
        if len(family) > 1 and normalized_follow_company in family:
            return True

    return False
