from pydantic import BaseModel

from app.schemas.people import PersonResponse


class MessageWarmPathResponse(BaseModel):
    type: str
    reason: str | None = None
    connection_name: str | None = None
    connection_headline: str | None = None
    connection_linkedin_url: str | None = None
    freshness: str | None = None
    days_since_sync: int | None = None
    refresh_recommended: bool = False
    stale: bool = False
    caution: str | None = None


class LinkedInSignalResponse(BaseModel):
    type: str
    reason: str | None = None
    display_name: str | None = None
    headline: str | None = None
    linkedin_url: str | None = None
    freshness: str | None = None
    days_since_sync: int | None = None
    refresh_recommended: bool = False
    stale: bool = False
    caution: str | None = None


class DraftRequest(BaseModel):
    person_id: str
    channel: str  # linkedin_note | linkedin_message | email | follow_up | thank_you
    goal: str  # interview | referral | warm_intro | follow_up | thank_you (+ legacy aliases)
    job_id: str | None = None
    pinned_story_ids: list[str] | None = None


class EditRequest(BaseModel):
    body: str
    subject: str | None = None


class MessageResponse(BaseModel):
    id: str
    person_id: str
    channel: str
    goal: str
    subject: str | None
    body: str
    reasoning: str | None
    ai_model: str | None
    status: str
    version: int
    parent_id: str | None
    recipient_strategy: str | None = None
    primary_cta: str | None = None
    fallback_cta: str | None = None
    job_id: str | None = None
    warm_path: MessageWarmPathResponse | None = None
    linkedin_signal: LinkedInSignalResponse | None = None
    story_ids: list[str] = []
    person_name: str | None = None
    person_title: str | None = None
    scheduled_send_at: str | None = None
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


class DraftResponse(BaseModel):
    message: MessageResponse
    reasoning: str
    token_usage: dict | None = None
    recipient_strategy: str | None = None
    primary_cta: str | None = None
    fallback_cta: str | None = None
    job_id: str | None = None
    warm_path: MessageWarmPathResponse | None = None
    linkedin_signal: LinkedInSignalResponse | None = None


class BatchDraftRequest(BaseModel):
    person_ids: list[str]
    goal: str
    job_id: str | None = None
    include_recent_contacts: bool = False


class BatchDraftItem(BaseModel):
    status: str  # ready | skipped | failed
    person: PersonResponse | None = None
    message: MessageResponse | None = None
    reason: str | None = None


class BatchDraftResponse(BaseModel):
    requested_count: int
    ready_count: int
    skipped_count: int
    failed_count: int
    items: list[BatchDraftItem]
