from pydantic import BaseModel


class JobSearchRequest(BaseModel):
    query: str
    location: str | None = None
    remote_only: bool = False
    sources: list[str] | None = None


class ATSSearchRequest(BaseModel):
    company_slug: str
    ats_type: str  # greenhouse | lever | ashby


class JobStageUpdate(BaseModel):
    stage: str  # discovered | interested | researching | networking | applied | interviewing | offer
    notes: str | None = None


class JobResponse(BaseModel):
    id: str
    title: str
    company_name: str
    company_logo: str | None
    location: str | None
    remote: bool
    url: str | None
    description: str | None
    employment_type: str | None
    salary_min: float | None
    salary_max: float | None
    salary_currency: str | None
    source: str
    ats: str | None
    posted_at: str | None
    match_score: float | None
    score_breakdown: dict | None
    stage: str
    tags: list[str] | None
    department: str | None
    notes: str | None
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}
