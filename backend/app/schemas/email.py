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
    verified_email: str | None = None
    best_guess_email: str | None = None
    confidence: int | None = None
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


class StageDraftRequest(BaseModel):
    message_id: str
    provider: str  # gmail | outlook


class StageDraftResponse(BaseModel):
    draft_id: str
    provider: str
    message_id: str | None = None


class EmailConnectionStatus(BaseModel):
    gmail_connected: bool
    outlook_connected: bool
