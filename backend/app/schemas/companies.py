from pydantic import BaseModel


class CompanyResponse(BaseModel):
    id: str
    name: str
    domain: str | None
    size: str | None
    industry: str | None
    funding_stage: str | None
    tech_stack: list[str] | None
    description: str | None
    careers_url: str | None
    starred: bool = False
    enriched_at: str | None
    created_at: str

    model_config = {"from_attributes": True}


class CompanyStarToggle(BaseModel):
    starred: bool
