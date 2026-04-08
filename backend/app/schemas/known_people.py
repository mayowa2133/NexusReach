"""Pydantic schemas for the global known people cache."""

from __future__ import annotations

from pydantic import BaseModel


class KnownPersonResponse(BaseModel):
    id: str
    full_name: str | None
    title: str | None
    department: str | None
    seniority: str | None
    linkedin_url: str | None
    github_url: str | None
    primary_source: str
    discovery_count: int = 1
    last_verified_at: str | None = None
    verification_status: str | None = "fresh"
    company_name: str | None = None
    company_domain: str | None = None

    model_config = {"from_attributes": True}


class KnownPeopleSearchResponse(BaseModel):
    items: list[KnownPersonResponse]
    total: int
    cache_freshness: str = "fresh"  # fresh | mixed | stale


class KnownPeopleCountResponse(BaseModel):
    company_name: str
    count: int
