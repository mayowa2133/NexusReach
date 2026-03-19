from pydantic import BaseModel


class DraftRequest(BaseModel):
    person_id: str
    channel: str  # linkedin_note | linkedin_message | email | follow_up | thank_you
    goal: str  # interview | referral | warm_intro | follow_up | thank_you (+ legacy aliases)
    job_id: str | None = None


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
    person_name: str | None = None
    person_title: str | None = None
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
