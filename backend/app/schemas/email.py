from pydantic import BaseModel


class OAuthCallbackRequest(BaseModel):
    code: str
    redirect_uri: str


class OAuthUrlResponse(BaseModel):
    auth_url: str


class EmailSuggestion(BaseModel):
    email: str
    confidence: int


class EmailFindResponse(BaseModel):
    email: str | None
    source: str
    verified: bool
    result_type: str = "not_found"
    usable_for_outreach: bool = False
    guess_basis: str | None = None
    verified_email: str | None = None
    best_guess_email: str | None = None
    confidence: int | None = None
    email_verification_status: str | None = None
    email_verification_method: str | None = None
    email_verification_label: str | None = None
    email_verification_evidence: str | None = None
    email_verified_at: str | None = None
    suggestions: list[EmailSuggestion] | None = None
    alternate_guesses: list[EmailSuggestion] | None = None
    failure_reasons: list[str] = []
    tried: list[str]


class EmailVerifyResponse(BaseModel):
    email: str
    status: str
    result: str
    score: int = 0
    disposable: bool = False
    webmail: bool = False
    email_verification_status: str | None = None
    email_verification_method: str | None = None
    email_verification_label: str | None = None
    email_verification_evidence: str | None = None


class StageDraftRequest(BaseModel):
    message_id: str
    provider: str  # gmail | outlook


class StageDraftResponse(BaseModel):
    draft_id: str
    provider: str
    message_id: str | None = None


class StageDraftsRequest(BaseModel):
    message_ids: list[str]
    provider: str  # gmail | outlook


class StageDraftsItem(BaseModel):
    message_id: str
    person_id: str | None = None
    draft_id: str | None = None
    provider: str
    outreach_log_id: str | None = None
    status: str  # staged | failed
    error: str | None = None


class StageDraftsResponse(BaseModel):
    requested_count: int
    staged_count: int
    failed_count: int
    items: list[StageDraftsItem]


class SendMessageRequest(BaseModel):
    message_id: str
    provider: str | None = None  # gmail | outlook — auto-detected if omitted


class SendMessageResponse(BaseModel):
    message_id: str
    provider: str
    status: str


class CancelSendResponse(BaseModel):
    message_id: str
    status: str


class EmailConnectionStatus(BaseModel):
    gmail_connected: bool
    outlook_connected: bool
