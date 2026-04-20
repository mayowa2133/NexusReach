from pydantic import BaseModel


class ProfileResponse(BaseModel):
    id: str
    full_name: str | None
    bio: str | None
    goals: list[str] | None
    tone: str
    target_industries: list[str] | None
    target_company_sizes: list[str] | None
    target_roles: list[str] | None
    target_locations: list[str] | None
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
    target_locations: list[str] | None = None
    linkedin_url: str | None = None
    github_url: str | None = None
    portfolio_url: str | None = None
    resume_auto_accept_inferred: bool | None = None
