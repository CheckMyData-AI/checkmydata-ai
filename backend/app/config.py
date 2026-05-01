import base64
import logging
from dataclasses import dataclass

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


@dataclass(frozen=True)
class AgentSettingsView:
    """Immutable, typed grouping of agent-related thresholds.

    Provides a single named-tuple-like surface so consumers can pass
    ``settings.agent`` around instead of importing the full ``Settings``
    object. The fields are populated lazily via :pyattr:`Settings.agent`.
    """

    max_orchestrator_iterations: int
    agent_wall_clock_timeout_seconds: int
    max_parallel_tool_calls: int
    max_sub_agent_retries: int
    max_sql_iterations: int
    max_mcp_iterations: int
    max_knowledge_iterations: int
    max_investigation_iterations: int
    agent_emergency_synthesis_pct: float
    history_tail_messages: int
    history_db_load_limit: int
    synthesis_data_token_budget_pct: float
    min_synthesis_length: int
    slow_query_warning_ms: int
    pipeline_run_ttl_days: int
    max_stage_retries: int
    max_pipeline_replans: int
    pipeline_max_parallel_stages: int
    llm_result_preview_rows: int
    answer_validator_enabled: bool
    learning_weight_confidence: float
    learning_weight_confirmed: float
    learning_weight_applied: float
    insight_ttl_days_low: int
    insight_ttl_days_warning: int
    insight_ttl_days_critical: int


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

    # Resend transactional email
    resend_api_key: str = ""
    resend_from_email: str = "CheckMyData <noreply@checkmydata.ai>"
    app_url: str = "http://localhost:3000"

    custom_rules_dir: str = "./rules"

    repo_clone_base_dir: str = "./data/repos"

    include_sample_data: bool = False

    # Query validation loop settings
    query_max_retries: int = 3
    query_enable_explain: bool = True
    query_enable_schema_validation: bool = True
    query_empty_result_retry: bool = False  # Set QUERY_EMPTY_RESULT_RETRY=true to enable
    query_explain_row_warning_threshold: int = 100_000
    query_timeout_seconds: int = 30

    max_history_tokens: int = 2500
    history_summary_model: str = ""

    # Database index settings
    db_index_ttl_hours: int = 24
    db_index_batch_size: int = 5
    auto_index_db_on_test: bool = False

    # Batch query execution (T19). ``batch_max_concurrency`` caps the
    # number of concurrent queries inside one batch; ``batch_result_row_cap``
    # is the per-query soft row cap we persist as part of the batch result.
    batch_max_concurrency: int = 4
    batch_result_row_cap: int = 500

    # Chat router knobs (T25). ``chat_raw_result_row_cap`` bounds the raw
    # tabular payload we serialise back to the client when a SQL block is
    # attached to a chat response. ``chat_sql_explain_cache_max`` caps the
    # in-process LRU cache for ``/explain-sql`` responses.
    chat_raw_result_row_cap: int = 500
    chat_sql_explain_cache_max: int = 100

    # Miscellaneous magic-number knobs lifted from scattered modules (T25).
    tool_preview_max_chars: int = 500
    tool_result_max_chars: int = 500
    max_lesson_length: int = 500
    health_check_interval_seconds: int = 300

    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://localhost:3100",
        "https://checkmydata.ai",
    ]

    # Agent settings
    max_orchestrator_iterations: int = 20
    orchestrator_final_synthesis: bool = True
    agent_wall_clock_timeout_seconds: int = 180
    max_parallel_tool_calls: int = 2
    max_sub_agent_retries: int = 2
    max_sql_iterations: int = 10
    max_mcp_iterations: int = 5
    max_knowledge_iterations: int = 2
    max_investigation_iterations: int = 12
    rag_relevance_threshold: float = 0.8
    schema_cache_ttl_seconds: int = 300
    max_pie_categories: int = 20
    viz_timeout_seconds: int = 15

    # Emergency synthesis threshold (fraction of budget used before forced synthesis)
    agent_emergency_synthesis_pct: float = 0.90
    router_model: str = ""  # optional fast model for the router LLM call

    # History tail / load limits (centralized, used across orchestrator + sub-agents)
    history_tail_messages: int = 4
    history_db_load_limit: int = 20

    # Synthesis budget (fraction of context window used to pack data into final synthesis)
    synthesis_data_token_budget_pct: float = 0.4
    # Minimum length the synthesis answer must reach before we treat it as a real answer
    # (rather than falling back to the static "step_limit_reached" message). 0 disables.
    min_synthesis_length: int = 0

    # Slow query warning threshold (post-validator)
    slow_query_warning_ms: int = 30_000

    # Pipeline settings
    pipeline_run_ttl_days: int = 7
    max_stage_retries: int = 2
    max_pipeline_replans: int = 2
    # Maximum stages run concurrently in one DAG level. Set to 1 to disable
    # parallel stage execution.
    pipeline_max_parallel_stages: int = 3

    # SQL agent
    llm_result_preview_rows: int = 20

    # Answer quality validator (LLM-based, optional). Falls back to length
    # heuristic when disabled or when the validator call fails.
    answer_validator_enabled: bool = True
    # Minimum length for the legacy length-based fallback used when the
    # LLM validator is disabled or errors (T12). Deliberately small — this
    # is a *fallback*, not the primary signal.
    answer_validator_min_chars: int = 80
    # Threshold for auto-selecting pipeline vs. single_query strategy (T12).
    # Kept as a tunable knob so environments with very wide schemas can
    # adjust without code changes; future work will route this through the
    # planner LLM instead of table count alone.
    orchestrator_pipeline_table_threshold: int = 3

    # Tool-call deduplication (T13). ``semantic_dedup_threshold`` is the
    # cosine-similarity cutoff used by the embedding-based dedup path when a
    # sentence-transformer model is available. ``semantic_dedup_word_overlap``
    # is the Jaccard fallback when embeddings are unavailable.
    tool_dedup_semantic_threshold: float = 0.85
    tool_dedup_word_overlap_threshold: float = 0.8
    # If empty, dedup falls back to word-overlap. Reuse of the ChromaDB
    # embedding model is encouraged; keep this as a separate knob so it can
    # be tuned (e.g. to a smaller model) without affecting RAG quality.
    tool_dedup_embedding_model: str = ""

    # Knowledge / learnings
    learning_weight_confidence: float = 0.4
    learning_weight_confirmed: float = 0.4
    learning_weight_applied: float = 0.2

    # Learning analyzer mode (D10):
    #   "heuristic"  — only the legacy `_detect_*` rules (kept as fast fallback)
    #   "hybrid"     — run heuristics first; fall back to LLMAnalyzer when empty
    #   "llm_first"  — always run LLMAnalyzer first; heuristics fill any gaps
    # Default is "llm_first" (T06): the product is AI-first by policy; the
    # legacy `_detect_*` regex rules remain only as a zero-cost fallback when
    # the LLM is unavailable or in cooldown.
    learning_analyzer_mode: str = "llm_first"

    # Insight memory TTL (days). 0 = never expire.
    insight_ttl_days_low: int = 7
    insight_ttl_days_warning: int = 30
    insight_ttl_days_critical: int = 0  # never expire

    # Subject blocklist (extends built-in list)
    learning_subject_blocklist_extra: list[str] = []

    # Streaming settings
    stream_timeout_seconds: int = 360
    stream_safety_margin_seconds: int = 120

    # Backup settings
    backup_enabled: bool = True
    backup_hour: int = 0
    backup_retention_days: int = 7
    backup_dir: str = "./data/backups"

    # Context window budget
    max_context_tokens: int = 32000

    # Session rotation (auto-summarize and start new session near context limit)
    session_rotation_enabled: bool = True
    session_rotation_threshold_pct: int = 95
    session_rotation_summary_max_tokens: int = 500

    # Request limits
    max_request_body_bytes: int = 10 * 1024 * 1024  # 10 MB
    max_concurrent_agent_calls: int = 3
    max_agent_calls_per_hour: int = 100

    # Redis (enables shared cache + ARQ task queue; empty = in-process fallback)
    redis_url: str = ""

    # GeoIP cache settings
    geoip_cache_enabled: bool = True
    geoip_cache_dir: str = "./data"
    geoip_memory_cache_size: int = 100_000

    # DataGate — data-quality gate thresholds (T07). Previously hard-coded
    # in :mod:`app.agents.data_gate`; now centrally tunable.
    data_gate_max_sample: int = 200
    data_gate_high_null_ratio: float = 0.5
    data_gate_high_duplicate_ratio: float = 0.9
    data_gate_value_range_sample: int = 50
    data_gate_percent_min: float = -1.0
    data_gate_percent_max: float = 200.0
    data_gate_year_min: int = 1900
    data_gate_year_max: int = 2100
    data_gate_common_limits: list[int] = [100, 500, 1000, 5000, 10000, 50000]
    data_gate_cartesian_multiplier: int = 100
    # When True, DataGate asks the LLM to classify column semantic type
    # (percentage / date / amount / id) instead of the legacy keyword
    # heuristic. Off by default to keep the gate cheap & predictable.
    data_gate_llm_semantics: bool = False

    # External service settings
    model_cache_ttl_seconds: int = 3600
    health_degraded_latency_ms: int = 3000
    ssh_connect_timeout: int = 30
    ssh_command_timeout: int = 60

    # Admin emails — users with these emails get access to admin-only endpoints
    # (manual backup trigger, cluster-wide metrics, etc.). Use the
    # ``ADMIN_EMAILS`` env var (JSON list, e.g. ``["alice@x.com","bob@x.com"]``).
    admin_emails: list[str] = []

    def is_admin_email(self, email: str | None) -> bool:
        """Return True when the given email is configured as admin."""
        if not email:
            return False
        target = email.strip().lower()
        return any(e.strip().lower() == target for e in self.admin_emails if e)

    @property
    def agent(self) -> AgentSettingsView:
        """Typed view over agent-related thresholds (X1)."""
        return AgentSettingsView(
            max_orchestrator_iterations=self.max_orchestrator_iterations,
            agent_wall_clock_timeout_seconds=self.agent_wall_clock_timeout_seconds,
            max_parallel_tool_calls=self.max_parallel_tool_calls,
            max_sub_agent_retries=self.max_sub_agent_retries,
            max_sql_iterations=self.max_sql_iterations,
            max_mcp_iterations=self.max_mcp_iterations,
            max_knowledge_iterations=self.max_knowledge_iterations,
            max_investigation_iterations=self.max_investigation_iterations,
            agent_emergency_synthesis_pct=self.agent_emergency_synthesis_pct,
            history_tail_messages=self.history_tail_messages,
            history_db_load_limit=self.history_db_load_limit,
            synthesis_data_token_budget_pct=self.synthesis_data_token_budget_pct,
            min_synthesis_length=self.min_synthesis_length,
            slow_query_warning_ms=self.slow_query_warning_ms,
            pipeline_run_ttl_days=self.pipeline_run_ttl_days,
            max_stage_retries=self.max_stage_retries,
            max_pipeline_replans=self.max_pipeline_replans,
            pipeline_max_parallel_stages=self.pipeline_max_parallel_stages,
            llm_result_preview_rows=self.llm_result_preview_rows,
            answer_validator_enabled=self.answer_validator_enabled,
            learning_weight_confidence=self.learning_weight_confidence,
            learning_weight_confirmed=self.learning_weight_confirmed,
            learning_weight_applied=self.learning_weight_applied,
            insight_ttl_days_low=self.insight_ttl_days_low,
            insight_ttl_days_warning=self.insight_ttl_days_warning,
            insight_ttl_days_critical=self.insight_ttl_days_critical,
        )

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
elif settings.master_encryption_key:
    try:
        _raw = base64.urlsafe_b64decode(settings.master_encryption_key)
        if len(_raw) != 32:
            raise ValueError(f"decoded key is {len(_raw)} bytes, expected 32")
    except Exception as _e:
        _config_logger.error(
            "MASTER_ENCRYPTION_KEY is not a valid Fernet key (%s). "
            'Generate one with: python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"',
            _e,
        )
        raise SystemExit(1) from _e
if not settings.resend_api_key:
    _config_logger.warning("RESEND_API_KEY is empty. Transactional emails will be skipped.")
