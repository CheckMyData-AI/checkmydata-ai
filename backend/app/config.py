import logging

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_config_logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "CheckMyData.ai"
    environment: str = "development"
    debug: bool = False
    sql_echo: bool = False

    database_url: str = "sqlite+aiosqlite:///./data/agent.db"

    # Connection pool settings
    db_pool_size: int = 5
    db_pool_overflow: int = 10
    db_pool_recycle: int = 3600
    db_pool_timeout: int = 30

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
    chroma_embedding_model: str = ""

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

    # Database index settings
    db_index_ttl_hours: int = 24
    db_index_batch_size: int = 5
    auto_index_db_on_test: bool = False

    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://localhost:3100",
        "https://checkmydata.ai",
    ]

    # Agent settings
    max_orchestrator_iterations: int = 5
    max_sub_agent_retries: int = 2
    max_sql_iterations: int = 3
    max_mcp_iterations: int = 5
    max_knowledge_iterations: int = 2
    rag_relevance_threshold: float = 1.3
    schema_cache_ttl_seconds: int = 300
    max_pie_categories: int = 20

    # Pipeline settings
    pipeline_run_ttl_days: int = 7
    max_stage_retries: int = 2

    # Streaming settings
    stream_timeout_seconds: int = 120
    stream_safety_margin_seconds: int = 30

    # Backup settings
    backup_enabled: bool = True
    backup_hour: int = 0
    backup_retention_days: int = 7
    backup_dir: str = "./data/backups"

    # Request limits
    max_request_body_bytes: int = 10 * 1024 * 1024  # 10 MB
    max_concurrent_agent_calls: int = 3
    max_agent_calls_per_hour: int = 100

    # External service settings
    model_cache_ttl_seconds: int = 3600
    health_degraded_latency_ms: int = 3000
    ssh_connect_timeout: int = 30
    ssh_command_timeout: int = 60

    @model_validator(mode="after")
    def _validate_production_secrets(self) -> "Settings":
        """Prevent insecure defaults from being used in production."""
        is_prod = self.environment.lower() in ("production", "prod")
        if not is_prod:
            return self
        if self.jwt_secret == "change-me-in-production":
            raise ValueError(
                "JWT_SECRET must be set to a secure value in production. "
                "Do not use the default 'change-me-in-production'."
            )
        if not self.master_encryption_key:
            raise ValueError(
                "MASTER_ENCRYPTION_KEY must be set in production. "
                "Generate one with: python -c "
                '"from cryptography.fernet import Fernet; '
                'print(Fernet.generate_key().decode())"'
            )
        return self


settings = Settings()

if settings.jwt_secret == "change-me-in-production":
    _config_logger.warning(
        "JWT_SECRET is using the insecure default. Set JWT_SECRET env var for production."
    )
if not settings.master_encryption_key:
    _config_logger.warning("MASTER_ENCRYPTION_KEY is empty. Credential encryption will not work.")
