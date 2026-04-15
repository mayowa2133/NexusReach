from pydantic import BaseModel, Field
from typing import Literal


VALID_STAGES = {
    "discovered", "interested", "researching", "networking",
    "applied", "interviewing", "offer", "accepted", "rejected", "withdrawn",
}

VALID_INTERVIEW_TYPES = {
    "phone_screen", "technical", "behavioral", "system_design",
    "onsite", "hiring_manager", "final", "take_home", "other",
}

VALID_OFFER_STATUSES = {"pending", "accepted", "declined", "expired"}


class JobSearchRequest(BaseModel):
    query: str
    location: str | None = None
    remote_only: bool = False
    sources: list[str] | None = None


class ATSSearchRequest(BaseModel):
    company_slug: str | None = None
    ats_type: str | None = None  # board-backed ATS type when not using job_url
    job_url: str | None = None


class JobStageUpdate(BaseModel):
    stage: str
    notes: str | None = None


# --- Interview round tracking ---

class InterviewRound(BaseModel):
    round: int = Field(ge=1, description="Round number (1-based)")
    interview_type: str = Field(description="phone_screen | technical | behavioral | system_design | onsite | hiring_manager | final | take_home | other")
    scheduled_at: str | None = None
    completed: bool = False
    interviewer: str | None = None
    notes: str | None = None


class InterviewRoundsUpdate(BaseModel):
    interview_rounds: list[InterviewRound]


# --- Offer tracking ---

class OfferDetails(BaseModel):
    salary: float | None = None
    salary_currency: str | None = Field(default="USD", max_length=10)
    equity: str | None = None
    bonus: float | None = None
    deadline: str | None = None
    status: str = Field(default="pending", description="pending | accepted | declined | expired")
    start_date: str | None = None
    notes: str | None = None


class OfferDetailsUpdate(BaseModel):
    offer_details: OfferDetails


class JobResponse(BaseModel):
    id: str
    title: str
    company_name: str
    company_logo: str | None
    location: str | None
    remote: bool
    url: str | None
    apply_url: str | None = None
    description: str | None
    employment_type: str | None
    experience_level: str | None
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
    starred: bool = False
    applied_at: str | None = None
    interview_rounds: list[InterviewRound] | None = None
    offer_details: OfferDetails | None = None
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


class JobStarToggle(BaseModel):
    starred: bool


class SearchPreferenceResponse(BaseModel):
    id: str
    query: str
    location: str | None
    remote_only: bool
    enabled: bool
    last_refreshed_at: str | None = None
    new_jobs_found: int = 0
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


class SearchPreferenceToggle(BaseModel):
    enabled: bool


class DiscoverRequest(BaseModel):
    queries: list[str] | None = None
    mode: Literal["default", "startup"] = "default"


class RefreshResponse(BaseModel):
    new_jobs_found: int


class MatchAnalysisResponse(BaseModel):
    summary: str
    strengths: list[str]
    gaps: list[str]
    recommendations: list[str]
    match_score: float | None = None
    model: str | None = None
