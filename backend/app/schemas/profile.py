from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator

_MAX_URL_LEN = 500
# Chars that never legitimately appear in a URL but carry meaning downstream
# (LaTeX argument delimiters / control sequences, HTML angle brackets, quotes).
_UNSAFE_URL_CHARS = frozenset('<>{}\\"\'` ')


class JobPreferences(BaseModel):
    work_authorization_countries: list[str] = Field(default_factory=list)
    requires_sponsorship: bool | None = None
    languages: list[str] = Field(default_factory=list)
    licenses: list[str] = Field(default_factory=list)
    clearances: list[str] = Field(default_factory=list)
    allowed_schedules: list[str] = Field(default_factory=list)
    max_travel_percent: int | None = Field(default=None, ge=0, le=100)
    minimum_contract_months: int | None = Field(default=None, ge=1, le=120)
    required_salary_currency: str | None = Field(default=None, min_length=3, max_length=3)
    required_salary_period: str | None = Field(default=None, pattern=r"^(hour|day|week|month|year)$")
    minimum_salary_confidence: float | None = Field(default=None, ge=0, le=1)
    excluded_employers: list[str] = Field(default_factory=list)
    blocked_keywords: list[str] = Field(default_factory=list)

    @field_validator(
        "work_authorization_countries",
        "languages",
        "licenses",
        "clearances",
        "allowed_schedules",
        "excluded_employers",
        "blocked_keywords",
    )
    @classmethod
    def _normalize_lists(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for value in values[:50]:
            cleaned = " ".join(str(value).split()).strip()[:100]
            key = cleaned.casefold()
            if cleaned and key not in seen:
                seen.add(key)
                normalized.append(cleaned)
        return normalized

    @field_validator("required_salary_currency", mode="before")
    @classmethod
    def _normalize_currency(cls, value: str | None) -> str | None:
        return value.strip().upper() if value else None


def _validate_optional_url(value: str | None) -> str | None:
    """Reject non-http(s) schemes and unsafe characters on user-supplied URLs.

    Blocks ``javascript:``/``data:``/``file:`` and similar schemes (defense
    against a stored link ever being rendered as an ``href``), plus control
    chars and LaTeX/HTML metacharacters that could break out of a rendering
    context. Scheme-less values (bare domains like ``linkedin.com/in/foo``) are
    allowed — without a scheme they can't be a dangerous-scheme URL. Empty
    values normalize to ``None``.
    """
    if value is None:
        return None
    trimmed = value.strip()
    if not trimmed:
        return None
    if len(trimmed) > _MAX_URL_LEN:
        raise ValueError("URL is too long.")
    if any((ch in _UNSAFE_URL_CHARS) or (not ch.isprintable()) for ch in trimmed):
        raise ValueError("URL contains invalid characters.")
    scheme = urlparse(trimmed).scheme.lower()
    if scheme and scheme not in {"http", "https"}:
        raise ValueError("URL must use http or https.")
    return trimmed


class ProfileResponse(BaseModel):
    id: str
    full_name: str | None
    bio: str | None
    goals: list[str] | None
    tone: str
    target_industries: list[str] | None
    target_company_sizes: list[str] | None
    target_roles: list[str] | None
    target_occupations: list[str] | None = None
    target_locations: list[str] | None
    job_preferences: JobPreferences = Field(default_factory=JobPreferences)
    linkedin_url: str | None
    github_url: str | None
    portfolio_url: str | None
    resume_parsed: dict | None
    resume_auto_accept_inferred: bool = False

    model_config = {"from_attributes": True}


class AutofillProfileResponse(BaseModel):
    """Lightweight profile for the Chrome extension autofill."""
    full_name: str | None
    first_name: str | None
    last_name: str | None
    email: str | None
    phone: str | None
    linkedin_url: str | None
    github_url: str | None
    portfolio_url: str | None
    location: str | None
    current_company: str | None
    current_title: str | None
    years_experience: str | None
    education: str | None
    skills: list[str]
    target_roles: list[str]


class ProfileUpdate(BaseModel):
    full_name: str | None = None
    bio: str | None = None
    goals: list[str] | None = None
    tone: str | None = None
    target_industries: list[str] | None = None
    target_company_sizes: list[str] | None = None
    target_roles: list[str] | None = None
    target_occupations: list[str] | None = None
    target_locations: list[str] | None = None
    job_preferences: JobPreferences | None = None
    linkedin_url: str | None = None
    github_url: str | None = None
    portfolio_url: str | None = None
    resume_auto_accept_inferred: bool | None = None

    @field_validator("linkedin_url", "github_url", "portfolio_url")
    @classmethod
    def _validate_urls(cls, value: str | None) -> str | None:
        return _validate_optional_url(value)


class ResumeUploadJsonRequest(BaseModel):
    filename: str
    content_type: str
    file_base64: str


class LinkedInPositionInput(BaseModel):
    title: str | None = None
    company: str | None = None


class LinkedInEducationInput(BaseModel):
    school: str | None = None
    degree: str | None = None


class LinkedInProfileImportRequest(BaseModel):
    """Self-captured LinkedIn profile from the companion (Workstream F)."""

    linkedin_url: str | None = None
    full_name: str | None = None
    headline: str | None = None
    location: str | None = None
    positions: list[LinkedInPositionInput] = []
    education: list[LinkedInEducationInput] = []
    skills: list[str] = []


class LinkedInProfileImportResponse(BaseModel):
    profile: ProfileResponse
    filled_name: bool
    filled_bio: bool
    filled_linkedin_url: bool
    skills_added: int
    positions_added: int
    education_added: int
