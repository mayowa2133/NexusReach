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

    model_config = {"from_attributes": True}


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
