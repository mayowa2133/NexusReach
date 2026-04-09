"""Schemas for company auto research preferences."""

from __future__ import annotations

from pydantic import BaseModel, Field


class CompanyAutoResearchPreferenceResponse(BaseModel):
    company_name: str
    normalized_company_name: str
    auto_find_people: bool = True
    auto_find_emails: bool = False
    created_at: str
    updated_at: str


class CompanyAutoResearchPreferenceUpsert(BaseModel):
    company_name: str = Field(min_length=1, max_length=255)
    auto_find_people: bool = True
    auto_find_emails: bool = False
