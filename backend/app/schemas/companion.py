from datetime import datetime

from pydantic import BaseModel


class CompanionTokenResponse(BaseModel):
    """Returned once at mint time — the plaintext token is never retrievable again."""

    token: str
    expires_at: datetime


class CompanionStatusResponse(BaseModel):
    connected: bool
    created_at: datetime | None = None
    last_used_at: datetime | None = None
    expires_at: datetime | None = None


class CompanionRevokeResponse(BaseModel):
    revoked: int
