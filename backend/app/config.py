import base64
import logging
from dataclasses import dataclass
from urllib.parse import urlparse

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
    router_last_turn_char_limit: int
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

    # Browser session cookies (T-SEC-3). The JWT is delivered to browsers as an
    # httpOnly/Secure/SameSite cookie so it is never readable from JS/storage,
    # paired with a non-httpOnly CSRF cookie (double-submit) for mutations.
    # ``Authorization: Bearer`` still works for non-browser API clients.
    auth_cookie_enabled: bool = True
    auth_cookie_secure: bool = True  # set False only for local http dev
    auth_cookie_samesite: str = "lax"  # lax | strict | none
    auth_cookie_domain: str = ""  # empty = host-only cookie

    google_client_id: str = ""

    # Resend transactional email
    resend_api_key: str = ""
    resend_from_email: str = "CheckMyData <noreply@checkmydata.ai>"
    app_url: str = "http://localhost:3000"

    custom_rules_dir: str = "./rules"

    repo_clone_base_dir: str = "./data/repos"

    # Live Git access (GitInspector / GitAgent). All operations are read-only.
    # ``git_agent_auto_pull`` lets the GitAgent refresh the local clone before
    # answering when it has fallen behind the indexed HEAD; off by default
    # because a pull costs network IO + can block on auth.
    git_agent_auto_pull: bool = False
    git_clone_pull_timeout_s: int = 60
    # Bounded iterations for the GitAgent tool-calling loop.
    max_git_iterations: int = 6
    # Output guards so a single huge file/diff cannot blow up memory or the
    # LLM context window.
    git_max_output_bytes: int = 100_000
    git_max_log_count: int = 200
    # Freshness: warn the agent when the local clone is this many commits (or
    # more) behind the indexed HEAD.
    git_staleness_warn_commits: int = 5

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
    # thumbs-down. Default ON (F-ARCH-6 decision, 2026-06): the LLM cost is
    # now bounded by per-user token budgets (entitlements / USER_*_TOKEN_LIMIT)
    # and the AgentLimiter, and the quality win on suspicious results outweighs
    # the marginal spend. Set False to make investigations manual-only.
    orchestrator_auto_investigate_enabled: bool = True

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
    # Char limit applied to the *latest* user turn sent to the routing LLM. The
    # older history tail stays clipped to ~200 chars; the latest message gets a
    # wider window so long follow-ups ("same cohorts but for Q2 …") are not
    # truncated before the router classifies them (I5).
    router_last_turn_char_limit: int = 800
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

    # --- Phase 2: Event-driven smart ingestion ---------------------------------
    # All triggers are OFF by default so existing deployments keep their manual
    # POST /index behaviour; flip individually to opt into automation.
    #
    # Git push webhook (POST /api/repos/{id}/webhook). When enabled, a verified
    # push event enqueues a (debounced) repo re-index. ``git_webhook_secret`` is
    # the shared HMAC secret used to verify GitHub-style ``X-Hub-Signature-256``
    # (and GitLab ``X-Gitlab-Token``) headers; an empty secret rejects all calls.
    git_webhook_enabled: bool = False
    git_webhook_secret: str = ""
    # Collapse a burst of pushes into a single re-index: a new trigger within this
    # window after the last one is ignored (the running/queued index already
    # covers it).
    webhook_debounce_seconds: int = 30

    # Cron poll fallback for repos without a webhook: the periodic loop runs
    # ``git fetch`` for each project's repo and enqueues a re-index when the
    # remote HEAD has advanced. ``0`` disables.
    git_poll_enabled: bool = False
    git_poll_interval_minutes: int = 15

    # Auto-chain code↔DB sync after a successful repo index completes (closes the
    # index→sync gap so lineage never silently lags the freshly indexed code).
    auto_sync_after_index: bool = False

    # FreshnessReconciler: when stale knowledge crosses the staleness threshold,
    # enqueue a background re-index instead of waiting for a user. Runs inside the
    # maintenance loop. ``0`` disables.
    freshness_reconciler_enabled: bool = False

    # DailyKnowledgeSync: forced nightly repo index → DB index → code↔DB sync for
    # every eligible project. Runs at ``daily_knowledge_sync_hour`` in
    # ``daily_knowledge_sync_timezone`` (default Europe/Berlin = 00:00 CET/CEST).
    daily_knowledge_sync_enabled: bool = False
    daily_knowledge_sync_hour: int = 0
    daily_knowledge_sync_timezone: str = "Europe/Berlin"
    daily_knowledge_sync_job_timeout_seconds: int = 7200

    # Stale-run reaper (P0): heartbeat-based recovery of stuck 'running' statuses
    # after a hard worker crash (OOM/SIGKILL/dyno cycle) where the job's finally
    # block never ran. Reaper runs in both web and worker; idempotent.
    reaper_enabled: bool = True
    heartbeat_interval_seconds: int = 30
    reaper_interval_seconds: int = 60
    stale_running_heartbeat_timeout_seconds: int = 300

    # Telemetry retention (run-event journal + error catalog). Swept by the
    # maintenance cron.
    indexing_run_events_ttl_days: int = 30
    indexing_run_events_max_per_run: int = 500
    error_log_ttl_days: int = 90

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
    # F-ARCH-6 rollout decision (2026-06):
    #   * Read-path retrieval flags (hybrid_retrieval, schema_retrieval) are ON
    #     by default — they are fail-safe (dense-only / safety-net fallbacks)
    #     and need no extra dependencies.
    #   * Index-path flags (code_graph, lineage, clustering) stay OFF by
    #     default — they add significant CPU cost to repo indexing and lineage
    #     depends on the graph; enable per-deployment once indexing cost is
    #     validated on production-sized repos.
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

    # M3: hybrid retrieval (BM25 + Chroma fused via RRF). Default ON: falls
    # back to dense-only when a project has no BM25 snapshot yet, so it is
    # safe across projects indexed before the feature existed.
    hybrid_retrieval_enabled: bool = True
    bm25_data_dir: str = "./data/bm25"
    hybrid_rrf_k: int = 60
    hybrid_min_score: float = 0.01
    hybrid_k: int = 20

    # Phase 3: cross-encoder reranking (second stage over fused RRF hits).
    # OFF by default — requires `sentence-transformers` + a model download.
    # Degrades to a no-op when the library/model is unavailable at runtime.
    reranker_enabled: bool = False
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    reranker_candidates: int = 30

    # M4: question-aware schema retrieval (BM25 + embeddings over DbIndex).
    # Default ON: retrieved tables are unioned with the legacy relevance-score
    # safety net and any retriever failure degrades to the old behaviour.
    schema_retrieval_enabled: bool = True
    sql_agent_max_context_tables: int = 15

    # M5: graph-driven code→DB lineage (replaces regex `used_in_files`).
    # OFF by default — requires code_graph_enabled (see F-ARCH-6 note above).
    lineage_enabled: bool = False
    lineage_max_depth: int = 5

    # M6: functional clustering (Louvain) + LLM-labeled cluster names.
    clustering_enabled: bool = False
    cluster_llm_label_enabled: bool = True

    # Phase 4: orchestrator Context Planner. When enabled, the orchestrator
    # plans which knowledge categories to load (query-aware lazy loading) and
    # assembles a single traceable ContextPack instead of 6+ eager loads.
    # OFF by default — opt-in. mode: "heuristic" (zero-cost) or "llm".
    context_planner_enabled: bool = False
    context_planner_mode: str = "heuristic"
    context_planner_budget_tokens: int = 8000

    # Phase 5: proactive schema-drift alerts. When enabled, a DB re-index that
    # detects added/removed/changed tables vs the last fingerprint stores a
    # `schema_change` insight (surfaced + actionable). OFF by default.
    schema_change_alerts_enabled: bool = False

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

    # Security headers (T-SEC-6). CSP is configurable so the frontend's inline
    # scripts, analytics, Google Identity, and the Swagger UI CDN can be
    # allowlisted without code changes. Report-only mode lets the policy be
    # rolled out and observed before it is enforced.
    security_csp_enabled: bool = True
    security_csp_report_only: bool = False
    security_csp: str = (
        "default-src 'self'; "
        "base-uri 'self'; "
        "frame-ancestors 'none'; "
        "object-src 'none'; "
        "img-src 'self' data: https:; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "script-src 'self' https://accounts.google.com https://apis.google.com "
        "https://cdn.jsdelivr.net; "
        "connect-src 'self' https://accounts.google.com; "
        "frame-src https://accounts.google.com; "
        "worker-src 'self' blob:; "
        "form-action 'self'"
    )
    # HSTS — only emitted over HTTPS; max-age in seconds (default 1 year).
    security_hsts_enabled: bool = True
    security_hsts_max_age: int = 31_536_000
    security_hsts_include_subdomains: bool = True
    security_hsts_preload: bool = False

    # Redis (enables shared cache + ARQ task queue; empty = in-process fallback)
    redis_url: str = ""

    # ------------------------------------------------------------------
    # Sentry error tracking (T-OBS-1). Off unless ``SENTRY_DSN`` is set.
    # PII is scrubbed before send (no request bodies/headers/cookies, no
    # default PII); only user *id* is attached for correlation.
    # ------------------------------------------------------------------
    sentry_dsn: str = ""
    sentry_environment: str = ""  # defaults to ``environment`` when empty
    sentry_traces_sample_rate: float = 0.0  # performance tracing off by default
    sentry_profiles_sample_rate: float = 0.0

    # MCP server (T-SEC-1). Off by default: the network-exposed MCP surface
    # must not run until a credential is configured. ``mcp_api_key_user_id``
    # binds the server's API key to a real platform user so MCP tool calls are
    # scoped/authorized exactly like that user's HTTP requests.
    mcp_enabled: bool = False
    mcp_api_key_user_id: str = ""

    # MCP HTTP mount (remote multi-tenant). Gated SEPARATELY from mcp_enabled so
    # turning on the stdio MCP surface does not auto-expose the remote HTTP
    # endpoint. The mount requires BOTH mcp_enabled and mcp_mount_enabled.
    mcp_mount_enabled: bool = False
    mcp_mount_path: str = "/mcp"

    # Host allow-list for the mounted MCP HTTP endpoint's DNS-rebinding
    # protection (TransportSecuritySettings.allowed_hosts).  Empty list =
    # protection disabled (permissive / backwards-compatible default).
    # Example: ["api.checkmydata.ai", "localhost:8000"]
    mcp_allowed_hosts: list[str] = []

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

    # F-FIN-1: per-user LLM token budgets enforced at the chat entry points
    # (/ask, /ask/stream, WS). 0 = unlimited. Use the
    # ``USER_DAILY_TOKEN_LIMIT`` / ``USER_MONTHLY_TOKEN_LIMIT`` env vars to
    # cap runaway LLM spend per user until plan-based entitlements land.
    user_daily_token_limit: int = 0
    user_monthly_token_limit: int = 0

    # ------------------------------------------------------------------
    # Billing / Stripe (T-BILL-1..9). Disabled by default: with
    # ``billing_enabled=False`` all billing routes 404 and entitlements
    # fall back to the global token limits above.
    # ------------------------------------------------------------------
    billing_enabled: bool = False
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_publishable_key: str = ""
    # Map of plan slug -> Stripe price id; set via env, e.g.
    # STRIPE_PRICE_PRO=price_xxx, STRIPE_PRICE_TEAM=price_yyy
    stripe_price_pro: str = ""
    stripe_price_team: str = ""
    # Where Stripe redirects after Checkout / Portal (frontend URLs).
    billing_success_path: str = "/dashboard?billing=success"
    billing_cancel_path: str = "/pricing?billing=canceled"

    # External service settings
    model_cache_ttl_seconds: int = 3600
    health_degraded_latency_ms: int = 3000
    ssh_connect_timeout: int = 30
    ssh_command_timeout: int = 60

    # R1-2 / F-SEC-4: SSH host-key verification policy.
    #   "tofu"      — trust-on-first-use: pin the host key on first connect into
    #                 ``ssh_known_hosts_path`` and verify against it thereafter
    #                 (secure default; a *changed* key is rejected)
    #   "strict"    — verify against ``ssh_known_hosts_path`` only; reject unknown hosts
    #   "disabled"  — known_hosts=None (no verification; MITM-exposed; explicit,
    #                 logged, non-production-only override)
    # Use the ``SSH_HOST_KEY_POLICY`` env var to override.
    ssh_host_key_policy: str = "tofu"
    # Where TOFU/strict host keys are stored (writable path).
    ssh_known_hosts_path: str = "/tmp/checkmydata_known_hosts"
    # F-SEC-5: restrict ssh_pre_commands to a safe allowlist (export/source/cd)
    # and reject shell metacharacters. Disable only as an emergency escape hatch.
    ssh_pre_command_allowlist_enabled: bool = True

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
            router_last_turn_char_limit=self.router_last_turn_char_limit,
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
    def _warn_split_domain_cookie(self) -> "Settings":
        """Warn when the CSRF cookie will be unreadable across subdomains.

        The double-submit CSRF token (T-SEC-3) requires the SPA's JavaScript to
        read the ``cmd_csrf`` cookie and echo it in a header. A host-only cookie
        (empty ``auth_cookie_domain``) set by, e.g., ``api.example.com`` cannot
        be read by a SPA on ``example.com``, which silently breaks every
        cookie-authenticated mutation. This guardrail surfaces that exact
        misconfiguration (the cause of the split-domain login outage) at startup
        without affecting single-host local dev.
        """
        if not (self.auth_cookie_enabled and self.auth_cookie_secure):
            return self
        if self.auth_cookie_domain:
            return self
        remote_hosts = []
        for origin in self.cors_origins:
            parsed = urlparse(origin)
            host = (parsed.hostname or "").lower()
            if parsed.scheme != "https" or not host:
                continue
            if host in ("localhost", "127.0.0.1", "::1") or host.endswith(".localhost"):
                continue
            remote_hosts.append(host)
        if remote_hosts:
            _config_logger.warning(
                "AUTH_COOKIE_DOMAIN is empty while serving cross-origin SPA origins %s. "
                "The CSRF cookie will be host-only and unreadable by a SPA on a different "
                "subdomain, breaking cookie-authenticated mutations. Set AUTH_COOKIE_DOMAIN "
                "to the shared parent domain (e.g. '.example.com').",
                remote_hosts,
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
