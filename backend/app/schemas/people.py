from datetime import datetime
import uuid

from pydantic import BaseModel, field_validator


class CompanyResponse(BaseModel):
    id: uuid.UUID
    name: str
    domain: str | None
    size: str | None
    industry: str | None
    description: str | None
    careers_url: str | None

    model_config = {"from_attributes": True}


class PersonResponse(BaseModel):
    id: uuid.UUID
    full_name: str | None
    title: str | None
    department: str | None
    seniority: str | None
    linkedin_url: str | None
    github_url: str | None
    work_email: str | None
    email_source: str | None = None
    email_verified: bool
    email_confidence: int | None = None
    email_verification_status: str | None = None
    email_verification_method: str | None = None
    email_verification_label: str | None = None
    email_verification_evidence: str | None = None
    email_verified_at: datetime | None = None
    person_type: str | None
    profile_data: dict | None
    github_data: dict | None
    source: str | None
    apollo_id: str | None = None
    relevance_score: int | None = None
    usefulness_score: int | None = None
    match_quality: str | None = None
    match_reason: str | None = None
    company_match_confidence: str | None = None
    fallback_reason: str | None = None
    employment_status: str | None = None
    org_level: str | None = None
    current_company_verified: bool | None = None
    current_company_verification_status: str | None = None
    current_company_verification_source: str | None = None
    current_company_verification_confidence: int | None = None
    current_company_verification_evidence: str | None = None
    current_company_verified_at: datetime | None = None
    company: CompanyResponse | None = None

    model_config = {"from_attributes": True}


class PeopleSearchRequest(BaseModel):
    company_name: str
    roles: list[str] | None = None
    github_org: str | None = None
    job_id: str | None = None
    min_relevance_score: int = 1
    target_count_per_bucket: int = 3

    @field_validator("target_count_per_bucket", mode="before")
    @classmethod
    def clamp_target_count_per_bucket(cls, value: object) -> int:
        try:
            parsed = int(value) if value is not None else 3
        except (TypeError, ValueError):
            parsed = 3
        return max(1, min(parsed, 10))


class ManualPersonRequest(BaseModel):
    linkedin_url: str


class JobContextResponse(BaseModel):
    department: str
    team_keywords: list[str]
    seniority: str


class SearchErrorDetail(BaseModel):
    provider: str
    error_code: str
    message: str
    bucket: str | None = None


class PeopleSearchResponse(BaseModel):
    company: CompanyResponse | None
    recruiters: list[PersonResponse]
    hiring_managers: list[PersonResponse]
    peers: list[PersonResponse]
    job_context: JobContextResponse | None = None
    errors: list[SearchErrorDetail] | None = None


class SearchLogResponse(BaseModel):
    id: str
    company_name: str
    search_type: str
    recruiter_count: int
    manager_count: int
    peer_count: int
    errors: dict | None = None
    duration_seconds: float | None = None
    created_at: str
