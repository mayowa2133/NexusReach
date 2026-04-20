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
    mode: Literal["default", "startup"] = "default"
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


# --- Resume Tailoring ---

class BulletRewrite(BaseModel):
    original: str
    rewritten: str
    reason: str
    experience_index: int | None = None


class SectionSuggestion(BaseModel):
    section: str
    suggestion: str


class TailoredResumeResponse(BaseModel):
    id: str | None = None
    job_id: str
    summary: str
    skills_to_emphasize: list[str]
    skills_to_add: list[str]
    keywords_to_add: list[str]
    bullet_rewrites: list[BulletRewrite]
    section_suggestions: list[SectionSuggestion]
    overall_strategy: str
    model: str | None = None
    created_at: str | None = None


class JobCommandCenterChecklist(BaseModel):
    resume_uploaded: bool
    match_scored: bool
    resume_tailored: bool
    resume_artifact_generated: bool
    contacts_saved: bool
    outreach_started: bool
    applied: bool
    interview_rounds_logged: bool


class JobCommandCenterStats(BaseModel):
    saved_contacts_count: int
    verified_contacts_count: int
    reachable_contacts_count: int
    drafted_messages_count: int
    outreach_count: int
    active_outreach_count: int
    responded_outreach_count: int
    due_follow_ups_count: int


class JobCommandCenterContact(BaseModel):
    id: str
    full_name: str | None = None
    title: str | None = None
    person_type: str | None = None
    work_email: str | None = None
    linkedin_url: str | None = None
    email_verified: bool = False
    current_company_verified: bool | None = None


class JobCommandCenterMessage(BaseModel):
    id: str
    person_id: str
    person_name: str | None = None
    channel: str
    goal: str
    status: str
    created_at: str


class JobCommandCenterOutreach(BaseModel):
    id: str
    person_id: str
    person_name: str | None = None
    channel: str | None = None
    status: str
    response_received: bool
    last_contacted_at: str | None = None
    next_follow_up_at: str | None = None
    created_at: str


class JobCommandCenterNextAction(BaseModel):
    key: str
    title: str
    detail: str
    cta_label: str
    cta_section: str


class JobResearchSnapshotResponse(BaseModel):
    id: str
    job_id: str
    company_name: str | None = None
    target_count_per_bucket: int | None = None
    recruiters: list[dict] = []
    hiring_managers: list[dict] = []
    peers: list[dict] = []
    your_connections: list[dict] = []
    recruiter_count: int = 0
    manager_count: int = 0
    peer_count: int = 0
    warm_path_count: int = 0
    verified_count: int = 0
    total_candidates: int = 0
    errors: list[dict] | None = None
    created_at: str | None = None
    updated_at: str | None = None


class ResumeBulletRewritePreview(BaseModel):
    id: str
    section: str
    experience_index: int | None = None
    project_index: int | None = None
    original: str
    rewritten: str
    reason: str = ""
    change_type: str = "reframe"
    inferred_additions: list[str] = []
    requires_user_confirm: bool = False
    decision: str = "pending"


class ResumeArtifactResponse(BaseModel):
    id: str
    job_id: str
    tailored_resume_id: str | None = None
    format: str
    filename: str
    content: str
    generated_at: str
    created_at: str
    updated_at: str
    rewrite_decisions: dict[str, str] = {}
    rewrite_previews: list[ResumeBulletRewritePreview] = []
    auto_accept_inferred: bool = False
    body_ats_score: float | None = None


class ResumeArtifactDecisionsUpdate(BaseModel):
    decisions: dict[str, str]


class ResumeArtifactLibraryEntry(BaseModel):
    id: str
    job_id: str
    job_title: str | None = None
    company_name: str | None = None
    filename: str
    generated_at: str
    updated_at: str
    pending_inferred_count: int = 0


class JobCommandCenterResponse(BaseModel):
    job_id: str
    stage: str
    checklist: JobCommandCenterChecklist
    stats: JobCommandCenterStats
    next_action: JobCommandCenterNextAction
    top_contacts: list[JobCommandCenterContact]
    recent_messages: list[JobCommandCenterMessage]
    recent_outreach: list[JobCommandCenterOutreach]
    research_snapshot: JobResearchSnapshotResponse | None = None
