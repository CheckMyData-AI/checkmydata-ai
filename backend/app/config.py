from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "eSIM Database Agent"
    debug: bool = False

    database_url: str = "sqlite+aiosqlite:///./data/agent.db"

    @model_validator(mode="after")
    def _fix_database_url(self) -> "Settings":
        """Heroku provides postgres:// but SQLAlchemy 2+ requires postgresql://."""
        url = self.database_url
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+asyncpg://", 1)
            self.database_url = url
        elif url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
            self.database_url = url
        return self

    master_encryption_key: str = ""

    chroma_persist_dir: str = "./data/chroma"
    chroma_server_url: str = ""

    default_llm_provider: str = "openai"
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    openrouter_api_key: str = ""

    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440  # 24 hours

    google_client_id: str = ""

    custom_rules_dir: str = "./rules"

    repo_clone_base_dir: str = "./data/repos"

    include_sample_data: bool = False

    # Query validation loop settings
    query_max_retries: int = 3
    query_enable_explain: bool = True
    query_enable_schema_validation: bool = True
    query_empty_result_retry: bool = False
    query_explain_row_warning_threshold: int = 100_000
    query_timeout_seconds: int = 30

    max_history_tokens: int = 4000
    history_summary_model: str = ""

    cors_origins: list[str] = ["http://localhost:3000"]


settings = Settings()
