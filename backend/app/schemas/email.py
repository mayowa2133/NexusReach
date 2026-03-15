from pydantic import BaseModel


class OAuthCallbackRequest(BaseModel):
    code: str
    redirect_uri: str


class OAuthUrlResponse(BaseModel):
    auth_url: str


class EmailFindResponse(BaseModel):
    email: str | None
    source: str
    verified: bool
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
