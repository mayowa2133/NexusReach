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
    # Public referral code of whoever invited this person (from the ?ref= link).
    referred_by_code: str | None = Field(default=None, max_length=16)
    # Selected goal chips. Unknown keys are dropped server-side (see
    # app.utils.waitlist_goals.clean_goals); the free-text detail uses `note`.
    goals: list[str] | None = Field(default=None, max_length=20)
    # Optional resume, carried as base64 in the JSON body — mirroring
    # /api/profile/resume-json, which the codebase adopted because multipart was
    # flaky in production browsers (and FastAPI can't mix File() with a body model).
    resume_filename: str | None = Field(default=None, max_length=300)
    resume_content_type: str | None = Field(default=None, max_length=120)
    resume_file_base64: str | None = Field(default=None)

    @field_validator(
        "name",
        "linkedin_url",
        "current_title",
        "target_role",
        "note",
        "source",
        "referred_by_code",
        "resume_filename",
        "resume_content_type",
    )
    @classmethod
    def _strip(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        return v or None


class ReferralStatus(BaseModel):
    """The referral state shown on the post-signup panel and the dashboard."""

    referral_code: str
    position: int
    total_verified: int
    launch_target: int
    share_url: str
    email_verified: bool
    verified_referral_count: int
    earned_tier: int
    tier_thresholds: list[int]
    name: str | None = None


class WaitlistSignupResponse(ReferralStatus):
    """Confirmation returned to the browser on join.

    Extends :class:`ReferralStatus` with the one-time secret ``access_token``
    (the browser stores it to reach the dashboard / verification link) and the
    idempotency flag.
    """

    ok: bool = True
    already_on_list: bool = False
    access_token: str


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
    # Referral fields — so rewards can be honored manually at launch.
    referral_code: str
    referred_by_id: str | None
    email_verified: bool
    verified_referral_count: int
    earned_tier: int
    # Goals + resume, for segmenting the list pre-launch.
    goals: list[str] | None
    has_resume: bool
    resume_filename: str | None
    resume_parse_status: str

    model_config = {"from_attributes": True}


class WaitlistExportResponse(BaseModel):
    count: int
    entries: list[WaitlistEntry]
