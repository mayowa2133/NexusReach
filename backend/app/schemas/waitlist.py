from pydantic import BaseModel, EmailStr, Field, field_validator


class WaitlistSignupCreate(BaseModel):
    """Public payload from the landing-page waitlist form."""

    email: EmailStr
    name: str = Field(min_length=1, max_length=200)
    linkedin_url: str | None = Field(default=None, max_length=500)
    current_title: str | None = Field(default=None, max_length=300)
    target_role: str | None = Field(default=None, max_length=300)
    note: str | None = Field(default=None, max_length=2000)
    source: str | None = Field(default=None, max_length=100)

    @field_validator("name", "linkedin_url", "current_title", "target_role", "note", "source")
    @classmethod
    def _strip(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        return v or None


class WaitlistSignupResponse(BaseModel):
    """Confirmation returned to the browser. Deliberately minimal."""

    ok: bool = True
    already_on_list: bool = False


class WaitlistEntry(BaseModel):
    """Full row, only exposed through the token-gated admin export."""

    id: str
    email: str
    name: str
    linkedin_url: str | None
    current_title: str | None
    target_role: str | None
    note: str | None
    source: str | None
    invited: bool
    created_at: str

    model_config = {"from_attributes": True}


class WaitlistExportResponse(BaseModel):
    count: int
    entries: list[WaitlistEntry]
