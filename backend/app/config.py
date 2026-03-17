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


settings = Settings()
