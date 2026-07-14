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


class ScoreCalibrationStatus(BaseModel):
    schema_version: int = 1
    score_kind: str
    calibrated: bool = False
    display_mode: Literal["dimensions_only", "calibrated_overall"] = "dimensions_only"
    reason: str


class JobSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=200)
    location: str | None = Field(default=None, max_length=200)
    remote_only: bool = False
    sources: list[str] | None = Field(default=None, max_length=20)


class ATSSearchRequest(BaseModel):
    company_slug: str | None = Field(default=None, max_length=255)
    ats_type: str | None = Field(default=None, max_length=50)
    job_url: str | None = Field(default=None, max_length=2048)


class JobStageUpdate(BaseModel):
    stage: str
    notes: str | None = None


# --- Interview round tracking ---

class InterviewRound(BaseModel):
    round: int = Field(ge=1, description="Round number (1-based)")
    interview_type: str = Field(description="phone_screen | technical | behavioral | system_design | onsite | hiring_manager | final | take_home | other")
    scheduled_at: str | None = None
    completed: bool = False
    completed_at: str | None = Field(
        default=None, description="ISO-8601 datetime when round was completed"
    )
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
    locations: list[dict] | None = None
    country_codes: list[str] | None = None
    countries: list[str] | None = None
    location_lat: float | None = None
    location_lng: float | None = None
    location_radius_km: float | None = None
    location_geocode_label: str | None = None
    remote: bool
    work_mode: str | None = None
    url: str | None
    apply_url: str | None = None
    description: str | None
    # True when this response carries only a preview of the description (the
    # list endpoint truncates to keep the feed payload small). Fetch
    # GET /api/jobs/{id} for the full text.
    description_truncated: bool = False
    employment_type: str | None
    experience_level: str | None
    experience_level_confidence: float | None = None
    salary_min: float | None
    salary_max: float | None
    salary_currency: str | None
    salary_period: str | None = None
    source: str
    ats: str | None
    posted_at: str | None
    # Precise posting time (ISO, set only when the source gives sub-day precision)
    # and the day-granularity posting date. The UI shows granular relative time
    # ("15 minutes ago") from posted_ts, falling back to posted_date ("Today").
    posted_ts: str | None = None
    posted_date: str | None = None
    source_status: str = "active"
    last_seen_at: str | None = None
    closed_at: str | None = None
    not_seen_count: int = 0
    match_score: float | None
    match_score_calibration: ScoreCalibrationStatus
    score_breakdown: dict | None
    stage: str
    tags: list[str] | None
    metadata_provenance: dict | None = None
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
    last_attempted_at: str | None = None
    last_success_at: str | None = None
    last_error: str | None = None
    last_duration_seconds: float | None = None
    new_jobs_found: int = 0
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


class SearchPreferenceToggle(BaseModel):
    enabled: bool


class DiscoverRequest(BaseModel):
    queries: list[str] | None = Field(default=None, max_length=20)
    occupations: list[str] | None = Field(default=None, max_length=50)
    mode: Literal["default", "startup"] = "default"


class RefreshResponse(BaseModel):
    new_jobs_found: int


class EnsureFreshResponse(BaseModel):
    """Result of the debounced, button-free feed nudge fired when Jobs opens."""

    triggered: bool
    # "discover" = full cold-start fill (empty feed), "refresh" = light top-up
    # (warm but stale feed), None = nothing needed / debounced.
    mode: str | None = None


class DiscoverOccupationsRequest(BaseModel):
    """Chip-driven discovery: the occupations the user has selected on Jobs."""

    occupations: list[str] = Field(default_factory=list, max_length=50)


class JobSourceRunResponse(BaseModel):
    id: str
    refresh_run_id: str
    source: str
    status: str
    raw_count: int = 0
    new_count: int = 0
    existing_count: int = 0
    duplicate_count: int = 0
    skipped_count: int = 0
    error: str | None = None
    duration_seconds: float | None = None
    started_at: str
    finished_at: str | None = None
    details: dict | None = None


class JobRefreshRunResponse(BaseModel):
    id: str
    search_preference_id: str | None = None
    mode: str
    query: str | None = None
    location: str | None = None
    remote_only: bool = False
    status: str
    total_new: int = 0
    total_seen: int = 0
    total_existing: int = 0
    total_duplicates: int = 0
    total_errors: int = 0
    error: str | None = None
    duration_seconds: float | None = None
    started_at: str
    finished_at: str | None = None
    source_runs: list[JobSourceRunResponse] = []


class MatchAnalysisResponse(BaseModel):
    summary: str
    strengths: list[str]
    gaps: list[str]
    recommendations: list[str]
    match_score: float | None = None
    match_score_calibration: ScoreCalibrationStatus
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


class ResumeQualitySourceAttribution(BaseModel):
    name: str
    url: str
    license: str
    adaptation: str


class ResumeQualityDimension(BaseModel):
    score: float
    max: float = 100
    evidence: list[str] = Field(default_factory=list)
    improvements: list[str] = Field(default_factory=list)


class ResumeQualityCategory(ResumeQualityDimension):
    key: str
    label: str


class ResumeQualityTruthfulness(BaseModel):
    unverified_inferred_additions_excluded: int = 0
    excluded_phrases: list[str] = Field(default_factory=list)


class ResumeQualityEvaluation(BaseModel):
    schema_version: int = 1
    rubric_version: str
    status: Literal["ready", "unavailable"]
    evaluation_mode: str
    source_attribution: ResumeQualitySourceAttribution
    evaluated_at: str
    profile: str | None = None
    profile_label: str | None = None
    overall_score: float | None = None
    readiness: str | None = None
    calibration: ScoreCalibrationStatus | None = None
    axes: dict[str, ResumeQualityDimension] = Field(default_factory=dict)
    categories: list[ResumeQualityCategory] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    improvements: list[str] = Field(default_factory=list)
    truthfulness: ResumeQualityTruthfulness | None = None
    disclaimer: str
    reason: str | None = None


class ResumeArtifactResponse(BaseModel):
    id: str
    job_id: str
    tailored_resume_id: str | None = None
    reused_from_artifact_id: str | None = None
    reuse_score: float | None = None
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
    quality_score: float | None = None
    quality_evaluation: ResumeQualityEvaluation | None = None


class ResumeArtifactDecisionsUpdate(BaseModel):
    decisions: dict[str, str]


class ResumeReuseCandidate(BaseModel):
    artifact_id: str
    source_job_id: str
    source_job_title: str | None = None
    source_company_name: str | None = None
    filename: str
    score: float
    quality_score: float | None = None
    threshold: float
    quality_threshold: float | None = None
    job_family: str
    generated_at: str
    updated_at: str
    reason: str


class ResumeReuseCandidatesResponse(BaseModel):
    threshold: float
    auto_reuse_enabled: bool = False
    candidates: list[ResumeReuseCandidate] = []


class ResumeArtifactReuseResponse(ResumeArtifactResponse):
    reused: bool = True
    source_job_title: str | None = None
    source_company_name: str | None = None


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
