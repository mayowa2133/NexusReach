import uuid

from cryptography.fernet import Fernet
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
    db_pool_size: int = 3
    db_max_overflow: int = 0
    db_pool_timeout_seconds: int = 30
    db_pool_recycle_seconds: int = 1800

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Supabase
    supabase_url: str = ""
    supabase_key: str = ""
    supabase_jwt_secret: str = ""
    supabase_service_role_key: str = ""
    auth_mode: str = "supabase"
    dev_auth_bypass_enabled: bool = False
    dev_user_id: uuid.UUID = uuid.UUID("00000000-0000-0000-0000-000000000001")
    dev_user_email: str = "dev@nexusreach.local"

    # External APIs (populated later per phase)
    apollo_api_key: str = ""
    apollo_master_api_key: str = ""
    hunter_api_key: str = ""
    github_token: str = ""
    jsearch_api_key: str = ""
    adzuna_app_id: str = ""
    adzuna_api_key: str = ""
    dice_api_key: str = ""
    # USAJobs (federal government jobs). Free key from developer.usajobs.gov;
    # user_agent must be the email registered with the key. Optional/fail-soft.
    usajobs_api_key: str = ""
    usajobs_user_agent: str = ""
    # The Muse public jobs API — free, all-industry, no key required. A key
    # (free from themuse.com/developers) only raises the rate limit; the client
    # works keyless and fails soft. This is the cross-industry curated-breadth
    # source that backstops JSearch/Adzuna for every non-tech occupation.
    themuse_api_key: str = ""
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    google_api_key: str = ""
    google_cse_id: str = ""
    groq_api_key: str = ""
    brave_api_key: str = ""
    serper_api_key: str = ""
    tavily_api_key: str = ""
    # Additional datacenter-safe search APIs (off until a key is set). You.com is
    # a Google-style SERP API (site:/boolean) used as a LinkedIn x-ray fallback;
    # Exa is a neural "people" search used as a semantic people-discovery fallback.
    youcom_api_key: str = ""
    exa_api_key: str = ""
    firecrawl_base_url: str = ""
    firecrawl_api_key: str = ""
    scrapegraph_api_key: str = ""
    # Optional dedicated Google CSE restricted to linkedin.com, used only for the
    # LinkedIn x-ray queries. A site-restricted CSE keeps working free after
    # Google sunsets whole-web CSE search (2027-01-01) and has the best
    # `site:linkedin.com/in` recall. Falls back to google_cse_id when unset.
    google_linkedin_cse_id: str = ""
    searxng_base_url: str = "http://localhost:8888"
    search_cache_ttl_seconds: int = 86_400
    # Provider order defaults. SearXNG is intentionally NOT in the defaults:
    # self-hosted SearXNG on a cloud/datacenter IP gets its scraping engines
    # CAPTCHA'd/blocked and returns 0 results (verified on Railway 2026-06-23), so
    # the authenticated APIs are primary. For LinkedIn x-ray, Google-backed
    # sources have by far the best `site:linkedin.com/in` recall, so lead with
    # Google CSE (free 100/day) then Serper (Google SERPs) then Brave (independent
    # index, weaker LinkedIn). Local dev with a residential-IP SearXNG can re-add
    # it via the NEXUSREACH_SEARCH_*_PROVIDER_ORDER env vars.
    search_linkedin_provider_order: str = "google_cse,serper,brave,youcom,exa"
    search_exact_linkedin_provider_order: str = "google_cse,serper,brave,youcom"
    search_hiring_team_provider_order: str = "serper,brave"
    search_public_provider_order: str = "brave,serper,tavily"
    search_employment_provider_order: str = "tavily,brave,serper"
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
    token_encryption_primary_version: str = "v1"
    token_encryption_keys: dict[str, str] = {}

    # App
    environment: str = "development"
    app_release: str = ""
    frontend_url: str = "http://localhost:5173"
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    companion_extension_origins: list[str] = []
    companion_extension_origin_regex: str = ""
    sentry_dsn: str = ""
    sentry_traces_sample_rate: float = 0.05
    sentry_profiles_sample_rate: float = 0.0

    # PostHog
    posthog_api_key: str = ""
    posthog_host: str = "https://us.i.posthog.com"

    # Usage limits
    daily_llm_token_limit: int = 100_000
    daily_api_call_limit: int = 50
    hunter_pattern_monthly_budget: int = 25
    employment_verify_top_n: int = 10
    employment_verify_timeout_seconds: int = 20
    employment_verify_enabled: bool = True
    employment_verify_concurrency: int = 3

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
    # Employment verification can invoke multiple search providers per contact.
    # Keep scheduled batches small enough for the 1 GB Railway worker while the
    # six-hour cadence still drains stale contacts steadily.
    reverify_batch_size: int = 5

    # Upload size limits (audit H2). Bound in-memory upload reads so a single
    # request can't OOM the worker; the ZIP cap bounds decompressed size.
    max_resume_upload_bytes: int = 10 * 1024 * 1024  # 10 MiB
    max_linkedin_upload_bytes: int = 25 * 1024 * 1024  # 25 MiB
    max_linkedin_zip_decompressed_bytes: int = 50 * 1024 * 1024  # 50 MiB

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
        if not self.supabase_service_role_key:
            errors.append("NEXUSREACH_SUPABASE_SERVICE_ROLE_KEY is empty")
        if self.auth_mode == "dev":
            errors.append("NEXUSREACH_AUTH_MODE=dev must not be used in production")
        if self.dev_auth_bypass_enabled:
            errors.append("NEXUSREACH_DEV_AUTH_BYPASS_ENABLED must not be true in production")
        if not self.sentry_dsn:
            errors.append("NEXUSREACH_SENTRY_DSN is empty")
        if not self.token_encryption_keys:
            errors.append("NEXUSREACH_TOKEN_ENCRYPTION_KEYS is empty")
        elif self.token_encryption_primary_version not in self.token_encryption_keys:
            errors.append(
                "NEXUSREACH_TOKEN_ENCRYPTION_PRIMARY_VERSION has no matching key"
            )
        else:
            for version, key in self.token_encryption_keys.items():
                try:
                    Fernet(key.encode("utf-8"))
                except (TypeError, ValueError):
                    errors.append(
                        f"NEXUSREACH_TOKEN_ENCRYPTION_KEYS[{version}] is invalid"
                    )
        if errors:
            raise ValueError(
                "Production configuration errors:\n  - " + "\n  - ".join(errors)
            )
        return self


settings = Settings()
