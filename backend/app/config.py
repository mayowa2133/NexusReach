import uuid

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="NEXUSREACH_",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/nexusreach"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Supabase
    supabase_url: str = ""
    supabase_key: str = ""
    supabase_jwt_secret: str = ""
    auth_mode: str = "supabase"
    dev_user_id: uuid.UUID = uuid.UUID("00000000-0000-0000-0000-000000000001")
    dev_user_email: str = "dev@nexusreach.local"

    # External APIs (populated later per phase)
    apollo_api_key: str = ""
    apollo_master_api_key: str = ""
    proxycurl_api_key: str = ""
    hunter_api_key: str = ""
    github_token: str = ""
    jsearch_api_key: str = ""
    adzuna_app_id: str = ""
    adzuna_api_key: str = ""
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    google_api_key: str = ""
    google_cse_id: str = ""
    groq_api_key: str = ""
    brave_api_key: str = ""
    serper_api_key: str = ""
    tavily_api_key: str = ""
    firecrawl_base_url: str = ""
    firecrawl_api_key: str = ""
    search_cache_ttl_seconds: int = 86_400
    search_linkedin_provider_order: str = "serper,brave,google_cse"
    search_exact_linkedin_provider_order: str = "brave,serper,google_cse"
    search_hiring_team_provider_order: str = "serper,brave"
    search_public_provider_order: str = "serper,brave,tavily"
    search_employment_provider_order: str = "tavily,serper,brave"
    theorg_traversal_enabled: bool = True
    theorg_cache_ttl_hours: int = 24
    theorg_max_team_pages: int = 3
    theorg_max_manager_pages: int = 3
    theorg_max_harvested_people: int = 25
    theorg_timeout_seconds: int = 20

    # LLM provider selection (anthropic | openai | gemini | groq)
    llm_provider: str = "anthropic"

    # OAuth (Gmail / Outlook)
    google_client_id: str = ""
    google_client_secret: str = ""
    microsoft_client_id: str = ""
    microsoft_client_secret: str = ""

    # App
    environment: str = "development"
    frontend_url: str = "http://localhost:5173"
    cors_origins: list[str] = ["http://localhost:5173"]

    # Usage limits
    daily_llm_token_limit: int = 100_000
    daily_api_call_limit: int = 50
    hunter_pattern_monthly_budget: int = 25
    employment_verify_top_n: int = 10
    employment_verify_timeout_seconds: int = 20
    employment_verify_enabled: bool = True


settings = Settings()
