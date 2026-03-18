import uuid

from pydantic import BaseModel


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
    email_verified: bool
    email_confidence: int | None = None
    person_type: str | None
    profile_data: dict | None
    github_data: dict | None
    source: str | None
    apollo_id: str | None = None
    relevance_score: int | None = None
    match_quality: str | None = None
    match_reason: str | None = None
    company: CompanyResponse | None = None

    model_config = {"from_attributes": True}


class PeopleSearchRequest(BaseModel):
    company_name: str
    roles: list[str] | None = None
    github_org: str | None = None
    job_id: str | None = None
    min_relevance_score: int = 1


class ManualPersonRequest(BaseModel):
    linkedin_url: str


class JobContextResponse(BaseModel):
    department: str
    team_keywords: list[str]
    seniority: str


class PeopleSearchResponse(BaseModel):
    company: CompanyResponse | None
    recruiters: list[PersonResponse]
    hiring_managers: list[PersonResponse]
    peers: list[PersonResponse]
    job_context: JobContextResponse | None = None
