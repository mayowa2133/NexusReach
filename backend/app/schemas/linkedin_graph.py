from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class LinkedInGraphConnectionResponse(BaseModel):
    id: str
    display_name: str
    headline: str | None = None
    current_company_name: str | None = None
    linkedin_url: str | None = None
    company_linkedin_url: str | None = None
    source: str
    last_synced_at: datetime | None = None
    relevance_score: int | None = None
    relevance_label: str | None = None

    model_config = {"from_attributes": True}

    @field_validator("id", mode="before")
    @classmethod
    def _coerce_id(cls, value):
        return None if value is None else str(value)


class LinkedInGraphLastRunResponse(BaseModel):
    id: str
    source: str
    status: str
    processed_count: int
    created_count: int
    updated_count: int
    started_at: datetime | None = None
    completed_at: datetime | None = None
    session_expires_at: datetime | None = None
    last_error: str | None = None


class LinkedInGraphStatusResponse(BaseModel):
    connected: bool = False
    source: str | None = None
    last_synced_at: datetime | None = None
    sync_status: str = "idle"
    last_error: str | None = None
    connection_count: int = 0
    last_run: LinkedInGraphLastRunResponse | None = None


class LinkedInGraphSyncSessionResponse(BaseModel):
    sync_run_id: str
    session_token: str
    expires_at: datetime
    upload_path: str = "/api/linkedin-graph/import-batch"
    max_batch_size: int = Field(default=250, ge=1)


class LinkedInGraphBatchConnectionInput(BaseModel):
    full_name: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    linkedin_url: str | None = None
    url: str | None = None
    headline: str | None = None
    position: str | None = None
    current_company_name: str | None = None
    company: str | None = None
    company_linkedin_url: str | None = None
    company_url: str | None = None


class LinkedInGraphImportBatchRequest(BaseModel):
    session_token: str
    connections: list[LinkedInGraphBatchConnectionInput]
    is_final_batch: bool = False
