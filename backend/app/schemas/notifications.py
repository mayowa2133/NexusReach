from pydantic import BaseModel


class NotificationResponse(BaseModel):
    id: str
    type: str
    title: str
    body: str | None
    job_id: str | None
    company_id: str | None
    read: bool
    created_at: str

    model_config = {"from_attributes": True}


class NotificationMarkRead(BaseModel):
    notification_ids: list[str]


class UnreadCountResponse(BaseModel):
    count: int
