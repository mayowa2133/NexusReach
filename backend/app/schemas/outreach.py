from pydantic import BaseModel


class CreateOutreachRequest(BaseModel):
    person_id: str
    job_id: str | None = None
    message_id: str | None = None
    status: str = "draft"
    channel: str | None = None
    notes: str | None = None
    last_contacted_at: str | None = None
    next_follow_up_at: str | None = None


class UpdateOutreachRequest(BaseModel):
    status: str | None = None
    channel: str | None = None
    notes: str | None = None
    job_id: str | None = None
    message_id: str | None = None
    last_contacted_at: str | None = None
    next_follow_up_at: str | None = None
    response_received: bool | None = None


class OutreachResponse(BaseModel):
    id: str
    person_id: str
    job_id: str | None
    message_id: str | None
    status: str
    channel: str | None
    notes: str | None
    last_contacted_at: str | None
    next_follow_up_at: str | None
    response_received: bool
    person_name: str | None = None
    person_title: str | None = None
    company_name: str | None = None
    job_title: str | None = None
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


class OutreachStats(BaseModel):
    total_contacts: int
    by_status: dict[str, int]
    response_rate: float
    upcoming_follow_ups: int
