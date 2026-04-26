from datetime import datetime

from pydantic import BaseModel, Field


class LinkedInGraphConnectionResponse(BaseModel):
    id: str
    display_name: str
    headline: str | None = None
    current_company_name: str | None = None
    linkedin_url: str | None = None
    company_linkedin_url: str | None = None
    source: str
    last_synced_at: datetime | None = None
    freshness: str | None = None
    days_since_sync: int | None = None
    refresh_recommended: bool = False
    stale: bool = False
    caution: str | None = None


class LinkedInGraphFollowResponse(BaseModel):
    id: str
    entity_type: str
    display_name: str
    headline: str | None = None
    current_company_name: str | None = None
    linkedin_url: str | None = None
    company_linkedin_url: str | None = None
    source: str
    last_synced_at: datetime | None = None
    freshness: str | None = None
    days_since_sync: int | None = None
    refresh_recommended: bool = False
    stale: bool = False
    caution: str | None = None


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
    followed_people_count: int = 0
    followed_companies_count: int = 0
    freshness: str = "empty"
    days_since_last_sync: int | None = None
    refresh_recommended: bool = False
    stale_after_days: int = 90
    recommended_resync_every_days: int = 30
    status_message: str | None = None
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


class LinkedInGraphBatchFollowInput(BaseModel):
    entity_type: str
    display_name: str | None = None
    full_name: str | None = None
    name: str | None = None
    linkedin_url: str | None = None
    profile_url: str | None = None
    url: str | None = None
    headline: str | None = None
    position: str | None = None
    current_company_name: str | None = None
    company_name: str | None = None
    company: str | None = None
    company_linkedin_url: str | None = None
    company_url: str | None = None


class LinkedInGraphImportBatchRequest(BaseModel):
    session_token: str
    connections: list[LinkedInGraphBatchConnectionInput]
    is_final_batch: bool = False


class LinkedInGraphImportFollowBatchRequest(BaseModel):
    session_token: str
    follows: list[LinkedInGraphBatchFollowInput]
    is_final_batch: bool = False
