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
    # R5-2: enabled by default — an empty result set is usually a
    # wrong-query signal (bad table/column/filter), so the ValidationLoop
    # retries once with schema hints (bounded by ``query_max_retries``).
    # Set QUERY_EMPTY_RESULT_RETRY=false to restore "empty is always valid".
    query_empty_result_retry: bool = True
    query_explain_row_warning_threshold: int = 100_000
    query_timeout_seconds: int = 30

    # Orchestrator unified-path result-quality gate (R5-3). On the unified
    # tool loop (used by simple/moderate queries) a failing query_database
    # result was previously fed straight back to the LLM with no signal.
    # When enabled, the orchestrator appends a correction directive to the
    # tool message (hard failure: validation error / no query / exec error;
    # soft: suspicious empty result, only when ``query_empty_result_retry``
    # is on) so the LLM re-queries. Bounded per workflow to avoid loops.
    orchestrator_result_gate_enabled: bool = True
    orchestrator_max_result_corrections: int = 2

    max_history_tokens: int = 2500
    history_summary_model: str = ""

    # Database index settings
    db_index_ttl_hours: int = 24
    db_index_batch_size: int = 5
    auto_index_db_on_test: bool = False
    # R2-3: reuse prior LLM table analysis for tables whose schema signature
    # is unchanged since the last successful index, instead of re-LLM-ing every
    # table on each run. Samples/row-counts still refresh; only the expensive
    # business-description generation is skipped for unchanged tables.
    db_index_incremental_enabled: bool = True
    # R4-2: credit exposed learnings as "applied" when a result passes
    # validation (not only on a rare thumbs-up), so times_applied / the decay
    # and ranking signals derived from it stay live in production.
    learning_apply_on_validation_enabled: bool = True
    # R5-6: when the post-timeout answer validator errors, treat the answer as
    # unverified (frame it as a continuable partial result with the "Continue
    # analysis" CTA) rather than silently presenting it as a verified final
    # answer. Set False to restore the lenient length-heuristic fallback.
    answer_validator_fail_closed: bool = True

    # R5-7: auto-route suspicious SQL results to the investigation ("Wrong
    # Data") agent. When the orchestrator's result gate spends its full
    # correction budget and the result still looks wrong (failed validation or
    # an unexplained empty set), the response is flagged ``suspicious_result``.
    # With this enabled, the chat layer kicks off a background investigation on
    # that flagged result automatically instead of waiting for a manual user
    # thumbs-down. Default off: auto-investigations cost LLM calls, so it is
    # opt-in per deployment.
    orchestrator_auto_investigate_enabled: bool = False

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
    # Tool-calling loop safety ceiling. The wall-clock timeout
    # (agent_wall_clock_timeout_seconds) is the real bound on a request; this
    # ceiling just prevents a pathological infinite loop, so it is set
    # generously (matches the documented default) rather than throttling
    # legitimate multi-step analysis.
    max_orchestrator_iterations: int = 100
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

    # Knowledge-lifecycle maintenance loop interval (hours). Drives learning /
    # session-note confidence decay and insight TTL/decay on a fixed cadence,
    # decoupled from the backup cron so decay runs even when backups are off.
    maintenance_interval_hours: int = 24

    # Pipeline settings
    pipeline_run_ttl_days: int = 7
    max_stage_retries: int = 2
    max_pipeline_replans: int = 2
    # Maximum stages run concurrently in one DAG level. Set to 1 to disable
    # parallel stage execution.
    pipeline_max_parallel_stages: int = 3

    # SQL agent
    # Number of result rows surfaced to the LLM when summarizing a query
    # result. Too small and the model reasons over a truncated view of the
    # data; the value is configurable so wide/large results can be tuned
    # without code changes.
    llm_result_preview_rows: int = 50

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

    # C2 (v1.13.0) — generate_docs failure tolerance. When ``generate_docs``
    # is processing many files per indexing run, a single transient LLM error
    # should not abort the entire run. We tolerate up to this ratio of failed
    # docs per run (default 30%); above that the step fails so an operator
    # sees the problem before it becomes silent KB drift.
    generate_docs_max_failure_ratio: float = 0.3

    # Cross-connection learning injection (V1, vision §7 #4).
    # When False (default), `compile_prompt` skips sibling-connection and
    # promoted-global-pattern sections — every connection's prompt contains only
    # its own learnings. This restores vision invariant "learning is per-connection,
    # not global; knowledge about one database never leaks into or corrupts
    # queries against another." Opt-in to `True` only if you explicitly want
    # cross-pollination across sibling connections in the same project.
    cross_connection_learnings_enabled: bool = False

    # ----- Code intelligence pipeline (M1–M6) ---------------------------------
    # Master flag: enables tree-sitter AST parsing + code knowledge graph.
    # When False, the legacy regex-based entity_extractor path runs.
    code_graph_enabled: bool = False
    # Concurrency for AST parsing (CPU-bound, bounded by semaphore).
    ast_parse_concurrency: int = 4
    # Files larger than this are skipped (binary/minified/generated).
    ast_max_file_bytes: int = 2_097_152  # 2 MB
    # Tolerated ratio of ERROR nodes per file before we drop the parse result.
    ast_parse_error_ratio: float = 0.3
    # Hard cap on graph size; above this, private/underscore symbols are pruned.
    code_graph_max_symbols: int = 50_000
    # Minimum confidence for keeping a CALLS edge in the graph.
    code_graph_call_confidence_threshold: float = 0.3

    # M3: hybrid retrieval (BM25 + Chroma fused via RRF).
    hybrid_retrieval_enabled: bool = False
    bm25_data_dir: str = "./data/bm25"
    hybrid_rrf_k: int = 60
    hybrid_min_score: float = 0.01
    hybrid_k: int = 20

    # M4: question-aware schema retrieval (BM25 + embeddings over DbIndex).
    schema_retrieval_enabled: bool = False
    sql_agent_max_context_tables: int = 15

    # M5: graph-driven code→DB lineage (replaces regex `used_in_files`).
    lineage_enabled: bool = False
    lineage_max_depth: int = 5

    # M6: functional clustering (Louvain) + LLM-labeled cluster names.
    clustering_enabled: bool = False
    cluster_llm_label_enabled: bool = True

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
    # C4 (v1.13.0). When True (default), the gate's unambiguous "data is
    # wrong" checks (out-of-range percent, out-of-range date) call
    # ``outcome.fail()`` instead of ``warn()``. This triggers a stage retry
    # via ``StageExecutor._retry_failed_data_gate`` so the LLM has a chance
    # to fix the query before returning bogus values to the user. Set to
    # False to revert to the v1.12.x warn-only behavior.
    data_gate_hard_checks_enabled: bool = True
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

    # R1-2: SSH host-key verification policy.
    #   "disabled" — known_hosts=None (no verification; legacy default, MITM-exposed)
    #   "tofu"      — trust-on-first-use: pin the host key on first connect into
    #                 ``ssh_known_hosts_path`` and verify against it thereafter
    #   "strict"    — verify against ``ssh_known_hosts_path`` only; reject unknown hosts
    # Use the ``SSH_HOST_KEY_POLICY`` env var to opt into verification.
    ssh_host_key_policy: str = "disabled"
    # Where TOFU/strict host keys are stored (writable path).
    ssh_known_hosts_path: str = "/tmp/checkmydata_known_hosts"

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
        if len(self.jwt_secret) < 32:
            raise ValueError(
                "JWT_SECRET must be at least 32 chars in production. "
                'Generate one with: python -c "import secrets; '
                'print(secrets.token_urlsafe(32))"'
            )
        if not self.master_encryption_key:
            raise ValueError(
                "MASTER_ENCRYPTION_KEY must be set in production. "
                "Generate one with: python -c "
                '"from cryptography.fernet import Fernet; '
                'print(Fernet.generate_key().decode())"'
            )
        if self.debug:
            raise ValueError("DEBUG must be false in production.")
        if "*" in self.cors_origins:
            raise ValueError(
                "CORS_ORIGINS may not contain '*' in production. List concrete origins instead."
            )
        return self

    @model_validator(mode="after")
    def _validate_numeric_ranges(self) -> "Settings":
        """Catch obvious mis-configurations early, regardless of environment."""
        if self.jwt_expire_minutes <= 0:
            raise ValueError("JWT_EXPIRE_MINUTES must be positive.")
        if self.max_orchestrator_iterations <= 0:
            raise ValueError("MAX_ORCHESTRATOR_ITERATIONS must be positive.")
        if not 0.0 < self.agent_emergency_synthesis_pct <= 1.0:
            raise ValueError("AGENT_EMERGENCY_SYNTHESIS_PCT must be in (0, 1].")
        if not 0.0 < self.synthesis_data_token_budget_pct <= 1.0:
            raise ValueError("SYNTHESIS_DATA_TOKEN_BUDGET_PCT must be in (0, 1].")
        if self.session_rotation_threshold_pct <= 0 or self.session_rotation_threshold_pct > 100:
            raise ValueError("SESSION_ROTATION_THRESHOLD_PCT must be in (0, 100].")
        if not 0.0 <= self.tool_dedup_semantic_threshold <= 1.0:
            raise ValueError("TOOL_DEDUP_SEMANTIC_THRESHOLD must be in [0, 1].")
        if not 0.0 <= self.tool_dedup_word_overlap_threshold <= 1.0:
            raise ValueError("TOOL_DEDUP_WORD_OVERLAP_THRESHOLD must be in [0, 1].")
        if self.learning_analyzer_mode not in {"heuristic", "hybrid", "llm_first"}:
            raise ValueError("LEARNING_ANALYZER_MODE must be one of: heuristic, hybrid, llm_first")
        if self.default_llm_provider not in {"openai", "anthropic", "openrouter"}:
            raise ValueError("DEFAULT_LLM_PROVIDER must be one of: openai, anthropic, openrouter")
        # R1-2: reject unknown SSH host-key policies early so a typo can't
        # silently fall back to the insecure "disabled" behavior at runtime.
        if self.ssh_host_key_policy not in {"disabled", "tofu", "strict"}:
            raise ValueError("SSH_HOST_KEY_POLICY must be one of: disabled, tofu, strict")
        # R5-3: the result-gate correction budget must be non-negative (0 = gate
        # validates but never issues a correction directive).
        if self.orchestrator_max_result_corrections < 0:
            raise ValueError("ORCHESTRATOR_MAX_RESULT_CORRECTIONS must be >= 0.")
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
