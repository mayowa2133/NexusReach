import uuid

from pydantic import model_validator
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
    searxng_base_url: str = "http://localhost:8888"
    search_cache_ttl_seconds: int = 86_400
    search_linkedin_provider_order: str = "searxng,serper,brave,google_cse"
    search_exact_linkedin_provider_order: str = "searxng,brave,serper,google_cse"
    search_hiring_team_provider_order: str = "searxng,serper,brave"
    search_public_provider_order: str = "searxng,serper,brave,tavily"
    search_employment_provider_order: str = "tavily,searxng,serper,brave"
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

    # Discovery rate limiting
    discovery_rate_limit: str = "10/minute"
    discovery_daily_limit: int = 100

    # LinkedIn graph sync
    linkedin_graph_sync_session_ttl_seconds: int = 900
    linkedin_graph_max_import_batch_size: int = 250
    linkedin_graph_refresh_recommended_days: int = 30
    linkedin_graph_stale_after_days: int = 90

    # Stale contact re-verification
    reverify_stale_days: int = 14
    reverify_batch_size: int = 20

    @model_validator(mode="after")
    def _validate_production_config(self) -> "Settings":
        """Fail fast if production is missing critical config."""
        if self.environment != "production":
            return self
        errors: list[str] = []
        if "localhost" in self.database_url:
            errors.append("NEXUSREACH_DATABASE_URL still points at localhost")
        if "localhost" in self.redis_url:
            errors.append("NEXUSREACH_REDIS_URL still points at localhost")
        if not self.supabase_url:
            errors.append("NEXUSREACH_SUPABASE_URL is empty")
        if not self.supabase_key:
            errors.append("NEXUSREACH_SUPABASE_KEY is empty")
        if not self.supabase_jwt_secret:
            errors.append("NEXUSREACH_SUPABASE_JWT_SECRET is empty")
        if self.auth_mode == "dev":
            errors.append("NEXUSREACH_AUTH_MODE=dev must not be used in production")
        if errors:
            raise ValueError(
                "Production configuration errors:\n  - " + "\n  - ".join(errors)
            )
        return self


settings = Settings()
