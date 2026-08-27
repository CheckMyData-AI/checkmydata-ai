import base64
import logging
from dataclasses import dataclass
from urllib.parse import urlparse

from pydantic import Field, model_validator
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
    pipeline_max_wall_seconds: int
    llm_result_preview_rows: int
    answer_validator_enabled: bool
    learning_weight_confidence: float
    learning_weight_confirmed: float
    learning_weight_applied: float
    insight_ttl_days_low: int
    insight_ttl_days_warning: int
    insight_ttl_days_critical: int


_config_logger = logging.getLogger(__name__)

# Environments treated as non-production. The production secret guard fails *closed*
# (F-AUTH-11): any environment NOT in this allow-list — including unset/empty, a typo,
# "staging" used as prod, "live", "prod-eu" — is treated as production and must pass
# the secret checks. Only these explicit dev/test names relax them.
_SAFE_ENVIRONMENTS = frozenset({"development", "dev", "test", "testing", "local", "ci"})


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "CheckMyData.ai"
    # Fail closed (F-AUTH-11 / S-04): the default is "production" so an unset,
    # empty, or mistyped ENVIRONMENT keeps the production secret guards active
    # (see _validate_production_secrets). Local dev/test must opt in explicitly
    # (ENVIRONMENT=development — set in .env.example, copied by `make setup`).
    environment: str = "production"
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
    #: Comma-separated retired Fernet keys, kept for READING only (F-CONN-05).
    #: Rotation: put the new key in ``master_encryption_key``, move the previous one
    #: here, deploy. `app.ops.credential_rotation` then sweeps stored rows onto the
    #: new key; once its pending count reaches zero the old key can be dropped.
    master_encryption_keys_old: str = ""

    chroma_persist_dir: str = "./data/chroma"
    chroma_server_url: str = ""
    chroma_embedding_model: str = Field(
        default="BAAI/bge-base-en-v1.5",
        description=(
            "Embedding model for ChromaDB (768-d). Requires the optional "
            "`sentence-transformers` extra: `pip install -e '.[ml]'`. Without it "
            "this value is silently ignored and Chroma embeds at 384-d with its "
            "built-in all-MiniLM-L6-v2. The two are NOT comparable -- switching "
            "requires a full re-index."
        ),
    )
    # Real tokenizer context window of ``chroma_embedding_model`` (tokens). Chunking
    # sizes to this, not chars/4. Changing the model requires a full re-embed (W2).
    embedder_max_tokens: int = 512

    # AUD-0819-01: how many documents reach one `collection.upsert` call. This is
    # the knob that decides peak worker memory, and it is not obvious why.
    # ChromaDB's bundled ONNX MiniLM pads EVERY document to 256 tokens and runs
    # its own inner batch of 32, so the transformer's intermediate activations are
    # sized by the batch and nothing else — content length does not matter.
    # Measured through `VectorStore.add_documents` itself, 960 chunks, macOS
    # (`chromadb` 1.x, ONNXMiniLM_L6_V2, base RSS 290 MiB):
    #
    #     batch=200 -> peak 967.1 MiB,  9.27 s
    #     batch=8   -> peak 414.5 MiB, 10.86 s
    #
    # So 8 costs about 17% more wall clock and saves ~552 MiB — the difference
    # between finishing and being SIGKILLed. This is what killed the production
    # worker at `code_symbol_embed` (R15, 1053 MiB against a 512 MiB quota) with
    # no run ever reaching `pipeline_end`. Raise it only on a dyno with headroom.
    # (A raw-chroma probe made the small batch look *faster*; that was warm-up
    # noise in the probe, not a property of the batch size.)
    embedding_upsert_batch_size: int = 8

    default_llm_provider: str = "openai"

    # F-LLM-01. The router falls back to another vendor when the chosen one fails, and
    # the messages it retries with are the user's question, their schema and their query
    # results — so a transient 503 at Anthropic sends that content to OpenAI. Fallback
    # stays ON by default: turning it off for everyone would trade every deployment's
    # resilience for a guarantee most never asked for, and a control that breaks the
    # normal case gets switched off and then protects nobody. Set False where the choice
    # of processor is a promise made to customers; crossing the boundary is logged at
    # WARNING naming both vendors either way.
    llm_allow_provider_fallback: bool = True
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

    # Default lifetime (days) for newly minted MCP tokens when the caller doesn't
    # specify one (F-AUTH-12). 0 = never expire (opt-out). Bounds long-lived bearer
    # credentials by default; an explicit per-token expiry still overrides this.
    mcp_token_default_expiry_days: int = 90

    google_client_id: str = ""

    # Password reset (SCN-013): how long an emailed reset link stays valid, in hours.
    # Kept short so a leaked link has a small window; the token is single-use anyway.
    password_reset_expiry_hours: int = 1

    # Resend transactional email
    resend_api_key: str = ""
    resend_from_email: str = "CheckMyData <noreply@checkmydata.ai>"
    app_url: str = "http://localhost:3000"

    custom_rules_dir: str = "./rules"

    # F-RULE-03. Rule text goes straight into an LLM prompt and its size is bounded by
    # nothing the code controls — files an operator drops in `rules/` plus rows a user adds
    # through `manage_custom_rules`. The cap lives in `rules_to_context` so no caller can
    # forget it; two of five used to carry their own unrelated numbers (2000 and 3000) and
    # three had none. Whole rules are dropped rather than cut, and the notice says how many,
    # so the agent can tell the user its answer may not reflect all of them.
    rules_context_max_chars: int = 3000

    repo_clone_base_dir: str = "./data/repos"

    # Where the demo project's sample SQLite lives (F-EXP-01). A file, not `:memory:`:
    # an in-memory database is empty on every fresh connection, so seeding it in one
    # says nothing to the next — which is why "Try demo instead" showed a new user an
    # empty database while SCN-003 promised sample data. On an ephemeral filesystem the
    # file disappears with the dyno, and `demo_setup` re-seeds when it is missing rather
    # than assuming it survived.
    demo_db_dir: str = "./data/demo"

    # FA-004 SSRF guard for user-supplied git repository URLs. By default
    # ``validate_repo_url`` DNS-resolves the repo host and rejects
    # loopback/private/link-local/reserved targets so `git ls-remote`/`clone`
    # can't be turned into an internal network probe or a cloud-metadata
    # (169.254.169.254) fetch. Set True ONLY for self-hosted deployments whose
    # git server lives inside a trusted private network (e.g. GitLab on RFC1918).
    repo_allow_private_hosts: bool = False

    # F-CONN-04 SSRF guard for user-supplied connection hosts (db_host, ssh_host, and a
    # DSN's host). Unlike ``repo_allow_private_hosts`` this defaults to **True**, and the
    # asymmetry is deliberate: a public git remote is the normal case, while a database
    # on 10.x / 192.168.x / 127.0.0.1 is the normal case, so refusing private addresses
    # by default would break the product for most deployments. Cloud metadata endpoints
    # (169.254.169.254 and friends) are refused either way — no database lives there and
    # what does hands out credentials for the whole account. Set this False when running
    # multi-tenant, where a tenant reaching 127.0.0.1 reaches *your* infrastructure.
    connection_allow_private_hosts: bool = True

    # Live Git access (GitInspector / GitAgent). All operations are read-only.
    # ``git_agent_auto_pull`` lets the GitAgent refresh the local clone before
    # answering when it has fallen behind the indexed HEAD; off by default
    # because a pull costs network IO + can block on auth.
    #
    # F-GIT-02: it also **moves the working tree mid-conversation**, so two answers in
    # one session can come from different trees and a follow-up question can contradict
    # the answer it follows up on. The transport risk the row worried about does not
    # apply — `RepoAnalyzer.clone_or_pull` validates the URL and branch and pins
    # `GIT_ALLOW_PROTOCOL` itself, so this caller inherits the guard — but the
    # consistency cost is real and is the reason to leave this off unless a deployment
    # specifically wants live answers over stable ones.
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
    # When true, ``classify_freshness`` compares the indexed SHA against
    # ``origin/<branch>`` (after an offline ``repo.remotes.origin.fetch``)
    # instead of the local ref, catching a clone that is behind the remote.
    # Off by default — a fetch is network I/O and can hang; enable only where
    # the clone auto-pulls.
    git_freshness_fetch_origin: bool = False

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
    # DBIDX-D11: number of documents sampled per collection during MongoDB schema
    # inference. Larger values improve field coverage for sparse/optional fields at
    # the cost of a slightly slower introspect_schema call. 100 is a good balance
    # for most collections; raise for very sparse schemas.
    mongo_schema_sample_size: int = 100

    # --- R5 sync remediation -------------------------------------------------
    # H6: scrub PII / secrets from DB samples + distinct values before LLM egress.
    sync_pii_scrubbing_enabled: bool = True
    # H4: per-table analyses below this confidence never enforce hard SQL filters.
    sync_min_confidence_to_enforce_filters: int = 2
    # H4: if the fraction of non-fallback analyses is below this, keep prior rows
    # instead of overwriting with a degraded run. 0.0 disables the guard.
    sync_min_success_ratio_to_persist: float = 0.5
    # H5: gate sync LLM spend on the project owner's token budget.
    sync_budget_enforcement_enabled: bool = True

    auto_index_db_on_test: bool = False
    # R2-3: reuse prior LLM table analysis for tables whose schema signature
    # is unchanged since the last successful index, instead of re-LLM-ing every
    # table on each run. Samples/row-counts still refresh; only the expensive
    # business-description generation is skipped for unchanged tables.
    db_index_incremental_enabled: bool = True
    # DBIDX-D9: collect per-column approximate stats (distinct count, null rate,
    # min/max) during db-indexing via connector.approx_stats().  Gated so the
    # extra per-column queries can be disabled if they add unacceptable latency
    # against very wide or large tables.
    db_index_stats_enabled: bool = True
    # DBIDX-D9: maximum number of columns per table for which approx_stats is
    # called.  Caps cost on wide tables (e.g. 200-column staging tables).
    # Only the first N enum-candidate / low-cardinality columns are sampled.
    db_index_stats_max_columns: int = 20
    # DBIDX-D9: row-sample cap passed to connectors that support approximate
    # counting (MongoDB $sample, ClickHouse SAMPLE).  SQL connectors ignore
    # this value (COUNT(DISTINCT …) already scans the full column efficiently).
    db_index_stats_sample_cap: int = 100_000
    # DBIDX-D15: cap on the number of tables that receive a full LLM analysis
    # call during db-indexing.  Tables beyond the cap (sorted by row_count desc,
    # then alphabetically) receive the deterministic _fallback_analysis instead
    # of an LLM call, preventing runaway cost on schemas with 500+ tables.
    db_index_max_tables_analyzed: int = 500
    # DBIDX-D16: maximum number of columns listed per-table in the LLM analysis
    # prompt.  When a table has more columns than this cap, the excess columns
    # are replaced with a "(… N more columns)" note so the prompt stays bounded
    # while still conveying that extra columns exist.
    db_index_max_prompt_columns: int = 100
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
    # When True (default), auto-investigation enforces the project owner's token
    # budget before spawning: it skips if the owner is over budget AND skips when
    # the owner cannot be resolved (no unbilled, unattributed background spend).
    # Set False to allow auto-investigation regardless of budget/owner resolution.
    auto_investigate_budget_enforcement_enabled: bool = True

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
    # Hard per-result ceiling applied when a FRESH tool result is appended to
    # the loop context (B6). Much larger than tool_result_max_chars (which
    # condenses OLD results during trim) so the model keeps enough of the
    # just-produced data to reason over, while a single pathologically large
    # result can't dominate/blow the context before the next trim.
    tool_result_insert_max_chars: int = 16000
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
    # ceiling just prevents a pathological infinite loop. Reduced from 100 to 20
    # (ORCH-T01: the step lever was inert at 100; 20 is the control target).
    max_orchestrator_iterations: int = 20
    orchestrator_final_synthesis: bool = True
    agent_wall_clock_timeout_seconds: int = 180
    max_parallel_tool_calls: int = 2
    max_sub_agent_retries: int = 2
    max_sql_iterations: int = 10
    #: Consecutive timeout-terminated `execute_query` calls, on one connection and
    #: within one request, before the SQL tool loop stops. A timeout means the
    #: database is not executing; retrying a different query against it costs another
    #: full `query_timeout_seconds` and cannot succeed. Reset by any successful query.
    #: Non-positive is rejected at boot — "0" would read as configured and behave as
    #: absent. Env: SQL_TIMEOUT_BREAKER_THRESHOLD.
    sql_timeout_breaker_threshold: int = 2
    #: Honour the orchestrator's remaining wall clock *inside* the SQL tool loop.
    #: Without it the loop is bounded only by `max_sql_iterations`: the orchestrator
    #: checks its own budget between its iterations, and the entire SQL agent runs
    #: within one of them. Env: SQL_AGENT_DEADLINE_ENABLED.
    sql_agent_deadline_enabled: bool = True
    max_mcp_iterations: int = 5
    # Per-call wall-clock timeout (seconds) for an external MCP tool invocation.
    # External MCP servers are untrusted and may hang; without this a single
    # call can stall the whole orchestrator turn indefinitely.
    mcp_call_timeout_s: float = 30.0
    max_knowledge_iterations: int = 2
    max_investigation_iterations: int = 12
    # cosine distance ≤ 0.45 ⟺ cosine similarity ≥ 0.55 (RET-R5)
    rag_relevance_threshold: float = 0.45
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

    # Auto-chain code↔DB sync after a successful repo index completes.
    #
    # DEFAULT ON, and moved out of the ingestion-automation group above (2026-08-27).
    # It sat there under the house rule "nothing calls out on a schedule unasked", and
    # that rule has no claim on it: measured against `code_db_sync_pipeline.py`, the sync
    # has zero references to `adapter`, `connector`, `execute_query`, `introspect`,
    # `httpx` or `aiohttp`. It opens no connection to anything. Its inputs are the stored
    # `DbIndex` and the code knowledge — both already local — and its output is the
    # code↔DB map, which is *what a repo index produces*, not a separate ingestion.
    #
    # The grouping had a consequence. Unset in production on 2026-08-25 with eight
    # genuine ingestion flags, it meant a full re-index on 2026-08-27 rebuilt the graph
    # (25 491 symbols, 2 134 edges) and left the map carrying the previous night's
    # `updated_at`. For a product whose value is that map's freshness, "the index ran and
    # the map did not" is the wrong default.
    #
    # The flag stays, because a switch does earn its place — for a reason the old grouping
    # never named. The sync runs an LLM (`CodeDbSyncAnalyzer.analyze_table`,
    # `analyze_table_batch`, `generate_summary`), so it costs TOKENS per run. An operator
    # who wants that off now turns off a cost, not a phantom outward call.
    auto_sync_after_index: bool = True

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

    # ----- Analytics sources (GA4 / App Store / Google Play), spec §4 ---------
    # Hourly collection wave for analytics connections. OFF by default: it calls
    # third-party APIs on a schedule, which must be an explicit opt-in, and the
    # per-connection ``collection_hour`` decides which hour a connection runs in
    # (local to ``daily_knowledge_sync_timezone``, shared so both crons agree on
    # what "3 a.m." means).
    analytics_collect_enabled: bool = False
    # How far back a fresh connection backfills, in periods of the report's
    # grain, ending yesterday — today is always partial at the vendor. Overridden
    # per connection by ``source_config_json.backfill_days``.
    analytics_backfill_days: int = 30
    # How many of the most recent periods are refetched even when already
    # collected. Vendors revise recent data (GA4 settles within ~48 h), so a
    # period that is merely "done" is not necessarily final.
    analytics_refetch_tail_periods: int = 2
    # Wall-clock budget for one connection's collection job. Registered on the
    # ARQ function (arq has no per-enqueue timeout) and passed to the in-process
    # fallback for parity.
    # AUD-0819-20: the repo index is the longest job in the system and was the only
    # one without a configurable ceiling — it inherited ARQ's class-level
    # `job_timeout = 1800` while its two newer siblings read their own settings.
    # Production hit exactly that on 2026-08-19: `1800.09s ! run_repo_index failed,
    # TimeoutError` with `code_symbol_embed` still running after 29 minutes over
    # 8,552 files. It got a knob and the default was left at 1800 — the value that
    # had just been measured as too small.
    #
    # Raised to 3600 on 2026-08-27, because leaving it produced the same failure
    # eight days later and the reason to withhold the raise had gone. Two
    # measurements, both from `indexing_runs` on the one real customer repository:
    #
    #     08-25 22:00  completed      42.4 min   nightly cron, ceiling 7200 s
    #     08-27 09:30  TimeoutError   30.0 min   manual re-index, ceiling 1800 s
    #
    # The same pipeline, the same 2 544 s of work, two ceilings — because the cron
    # runs it *inside* `run_daily_project_knowledge_sync`, which carries
    # `daily_knowledge_sync_job_timeout_seconds`. So the repository rebuilt
    # unattended at 3 a.m. and could never rebuild when a person pressed
    # "Re-index repository", which is the path an operator reaches for after a fix.
    #
    # The old note said raising this only helps when the worker is not swapping.
    # That precondition is now met and measured: the dyno is Standard-2X and a full
    # rebuild logged zero R14 and zero R15 (CB-OPS1, 2026-08-27). What is left of
    # that caution is the opposite lesson — the same day's memory fix cut
    # `EMBEDDING_UPSERT_BATCH_SIZE` from 200 to 8 and bought ~552 MiB with ~17 % more
    # wall clock, spent inside the very step this ceiling was cutting off.
    #
    # Invariant, asserted in `tests/unit/services/test_repo_index_ceiling.py`: this
    # stays below `daily_knowledge_sync_job_timeout_seconds`, which contains it plus
    # a DB index plus a code↔DB sync.
    repo_index_job_timeout_seconds: int = 3600

    # F-SCHED-07: how long a `running` batch may sit before another attempt may take
    # its claim. `run_batch` inherits ARQ's class-level `job_timeout` (1800 s), so past
    # that the previous attempt is provably dead — arq cancelled it. Matching the two
    # is the point: a shorter value could double-run a live batch, and a longer one
    # strands a crashed one, because the stale-run reaper covers IndexingRun and does
    # not know about `batch_queries`.
    batch_stale_claim_seconds: int = 1800

    # F-PROJ-04: how long a project invitation stays acceptable. An invite used to be
    # `pending` forever, so `auto_accept_for_user` would take it whenever that address
    # eventually registered — years later, after the person left. Email verification
    # (F-PROJ-01) does not cover this: a re-registered address verifies perfectly well,
    # because verification proves control of the mailbox today, not that the invitation
    # was meant for whoever controls it now. Two weeks is long enough for a colleague
    # on holiday and short enough that a forgotten invite dies.
    invite_expiry_days: int = 14
    analytics_collect_job_timeout_seconds: int = 1800
    # Attempts per vendor HTTP call before it is reported as transient. Only
    # transient/quota failures are retried — auth and permission never are.
    analytics_http_attempts: int = 3
    # Retention for the ``analytics_imports`` journal (REQ-015). A little over a
    # year so year-over-year backfills still see their own history.
    analytics_journal_retention_days: int = 400

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

    # Diagnostics capture — persist failed/recovered query executions (full SQL,
    # raw DB error, classified type, repair-attempt history) to query_failures for
    # post-hoc diagnosis. Best-effort, off the request path; set False to disable.
    diagnostics_capture_enabled: bool = True
    diagnostics_attempt_history_max: int = 20
    diagnostics_raw_error_max_chars: int = 8000

    # Pipeline settings
    pipeline_run_ttl_days: int = 7
    max_stage_retries: int = 2
    max_pipeline_replans: int = 2
    # Maximum stages run concurrently in one DAG level. Set to 1 to disable
    # parallel stage execution.
    pipeline_max_parallel_stages: int = 3
    # Per-pipeline wall-clock budget (seconds) for one StageExecutor.execute
    # run. Bounds the compounded retry surface (per-stage × validation ×
    # data-gate) by stopping the DAG scheduler before dispatching a new batch
    # once the budget is spent. 0 → fall back to agent_wall_clock_timeout_seconds.
    pipeline_max_wall_seconds: int = 0

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
    code_graph_enabled: bool = True  # W6: flipped ON after graph-quality benchmark passed (spec §9)
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
    # above rank-30 RRF contribution (1/90 ≈ 0.011); filters tail noise (RET-R5)
    hybrid_min_score: float = 0.03
    hybrid_k: int = 20

    # Phase 3: cross-encoder reranking (second stage over fused RRF hits).
    #
    # OFF by default since 2026-08-10, and the change is a correction rather than a
    # regression: `sentence-transformers` has never been in any dependency list, so
    # this defaulted to True while degrading to a no-op in every deployment that has
    # ever run. A flag that advertises a capability the image does not carry is worse
    # than one that is off -- it is read as configuration and behaves as absence.
    #
    # To turn it on for real: `pip install -e '.[ml]'` (see optional-dependencies),
    # which also unlocks the 768-d embedder named by `chroma_embedding_model`.
    reranker_enabled: bool = False
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    reranker_candidates: int = 30

    # M4: question-aware schema retrieval (BM25 + embeddings over DbIndex).
    # Default ON: retrieved tables are unioned with the legacy relevance-score
    # safety net and any retriever failure degrades to the old behaviour.
    schema_retrieval_enabled: bool = True
    sql_agent_max_context_tables: int = 15
    # RET-R10: minimum relevance_score for safety-net tables to be included in
    # context.  Tables below this floor are omitted so retrieved/FK-expanded
    # tables are not crowded out by low-signal entries.  Raise to 4 to be more
    # aggressive; lower to 2 to restore legacy behaviour.
    sql_agent_safety_net_min_relevance: int = 3

    # M5: graph-driven code→DB lineage (replaces regex `used_in_files`).
    # ON by default — requires code_graph_enabled (see F-ARCH-6 note above).
    lineage_enabled: bool = True  # W6: flipped ON with code_graph (benchmark-gated, spec §9)
    lineage_max_depth: int = 5

    # M6: functional clustering (Louvain) + LLM-labeled cluster names.
    clustering_enabled: bool = False
    cluster_llm_label_enabled: bool = True

    # Phase 4: orchestrator Context Planner. When enabled, the orchestrator
    # plans which knowledge categories to load (query-aware lazy loading) and
    # assembles a single traceable ContextPack instead of 6+ eager loads.
    # ON by default as of W2 (gated on retrieval-eval + reranker tests).
    # mode: "heuristic" (zero-cost) or "llm".
    context_planner_enabled: bool = True
    context_planner_mode: str = "heuristic"
    context_planner_budget_tokens: int = 8000

    # Phase 5: proactive schema-drift alerts. When enabled, a DB re-index that
    # detects added/removed/changed tables vs the last fingerprint stores a
    # `schema_change` insight (surfaced + actionable). OFF by default.
    schema_change_alerts_enabled: bool = False

    # Streaming settings
    stream_timeout_seconds: int = 360
    stream_safety_margin_seconds: int = 120
    # Idle timeout (seconds) for a chat WebSocket waiting on the next client
    # message; the connection is closed when exceeded so abandoned sockets don't
    # hold server resources. 0 disables the idle timeout.
    ws_idle_timeout_seconds: int = 300

    # F-CHAT-03. The WebSocket event relay used a hardcoded `timeout=60` and **exited**
    # when it expired, so a step that legitimately takes longer than a minute — a large
    # `ast_parse`, a slow warehouse query — ended the event stream while the run carried
    # on. An unnamed number, five times tighter than the `ws_idle_timeout_seconds`
    # beside it. The relay now polls and continues, exactly as the SSE relay in the same
    # file already did; `ws_event_relay_poll_seconds` is how often it wakes to check the
    # deadline, and `ws_event_relay_timeout_seconds` is the overall ceiling on a run that
    # never reaches `pipeline_end`.
    ws_event_relay_poll_seconds: float = 0.5
    ws_event_relay_timeout_seconds: int = 900

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
    # protection (TransportSecuritySettings.allowed_hosts). Empty = protection
    # disabled (permissive, backwards-compatible default).
    #
    # F-MCP-04. This MUST name the host the API is *served on* — the value of the
    # `Host` header an MCP client sends, e.g. `api.checkmydata.ai`. It is deliberately
    # NOT derived from `cors_origins`: those are browser origins for the SPA, and on
    # this deployment they are `checkmydata.ai` and the web dyno's herokuapp domain —
    # neither of which is the API host. Deriving from them would switch protection ON
    # with a list that excludes the real host and reject every legitimate MCP call.
    # A guess that breaks the endpoint is worse than a documented gap.
    #
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
    # Max rows the value-range hard check scans for impossible values (negative
    # counts, >100% bounded percentages, impossible dates). The per-cell numeric
    # comparison is cheap and short-circuits per column on the first hit, and
    # missing even one impossible value defeats the gate — so 0 (default) scans
    # the FULL in-memory result. Set a positive value only to bound the scan.
    data_gate_value_range_sample: int = 0
    # Floor for "bounded percent" columns — the only place this is read. F-DG-05: the
    # interval was tightened on one side only. The upper bound got its own setting
    # (`data_gate_percent_bounded_max = 100.5`, a rounding tolerance) while this stayed
    # at -1.0, so a `conversion_pct` of -0.9 passed a check whose whole premise is that
    # the column is a 0..100 share. A negative share is exactly as impossible as 150%,
    # so the tolerance is now symmetric: 0.5 below zero, 0.5 above one hundred.
    data_gate_percent_min: float = -0.5
    # Loose upper bound for "rate"-kind columns (rate/ratio/growth) which can
    # legitimately exceed 100% (e.g. 150% YoY growth).
    data_gate_percent_max: float = 200.0
    # Strict upper bound for "bounded percent" columns whose name implies a
    # 0..100 share (conversion, completion, ctr, occupancy, retention, churn,
    # *_pct, *percentage*). 100.5 leaves a small tolerance for rounding while
    # still flagging impossible values like 150%. (F-DG hard-check domain.)
    data_gate_percent_bounded_max: float = 100.5
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
    #                 (a *changed* key is then rejected)
    #   "strict"    — verify against ``ssh_known_hosts_path`` only; reject unknown hosts
    #   "disabled"  — known_hosts=None (no verification; MITM-exposed; explicit,
    #                 logged, non-production-only override)
    # Use the ``SSH_HOST_KEY_POLICY`` env var to override.
    #
    # AUD-0819-06 — the guarantee above is only as durable as the store. "tofu"
    # rejects a changed key only while the pin from the previous connect still
    # exists; on a host whose ``ssh_known_hosts_path`` is emptied between
    # restarts, first use runs again every boot and no rejection can occur. That
    # is the case on Heroku with the default path below, so ``tofu`` is NOT a
    # secure default there — it degrades to "verified within one dyno lifetime".
    # ``connect_with_policy`` says so once per process; a durable store is
    # docs/adr/0002-ssh-host-key-store.md.
    ssh_host_key_policy: str = "tofu"
    # Where TOFU/strict host keys are stored (writable path). ``/tmp`` is chosen
    # because it is the only reliably writable location on the deploy target —
    # not because it is durable. Point this at real storage where one exists.
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
            pipeline_max_wall_seconds=self.pipeline_max_wall_seconds,
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
    def _validate_sql_loop_bounds(self) -> "Settings":
        """A bound that silently means "never" is worse than no bound at all."""
        if self.sql_timeout_breaker_threshold < 1:
            raise ValueError(
                "SQL_TIMEOUT_BREAKER_THRESHOLD must be >= 1 "
                f"(got {self.sql_timeout_breaker_threshold}). A non-positive value "
                "would disable the breaker while still reading as configured."
            )
        return self

    @model_validator(mode="after")
    def _validate_production_secrets(self) -> "Settings":
        """Prevent insecure defaults from being used in production.

        Fail closed (F-AUTH-11): treat *any* environment as production unless it is
        an explicit dev/test name, so a missing/mistyped ENVIRONMENT can't silently
        boot with the default JWT secret.
        """
        is_prod = self.environment.strip().lower() not in _SAFE_ENVIRONMENTS
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
        # F-AUTH-08: browsers reject SameSite=None cookies that aren't also Secure,
        # which silently drops the session/CSRF cookies and breaks login. Fail closed.
        if self.auth_cookie_samesite.strip().lower() == "none" and not self.auth_cookie_secure:
            raise ValueError(
                "AUTH_COOKIE_SAMESITE=none requires AUTH_COOKIE_SECURE=true "
                "(browsers drop non-Secure SameSite=None cookies)."
            )
        if self.mcp_token_default_expiry_days < 0:
            raise ValueError("MCP_TOKEN_DEFAULT_EXPIRY_DAYS must be >= 0 (0 = never).")
        # Analytics collection: a zero/negative window would make the collector
        # silently idle (nothing "expected", so nothing ever pending) instead of
        # failing — the exact silent-no-data mode this module exists to prevent.
        if self.analytics_backfill_days <= 0:
            raise ValueError("ANALYTICS_BACKFILL_DAYS must be positive.")
        if self.analytics_refetch_tail_periods < 0:
            raise ValueError("ANALYTICS_REFETCH_TAIL_PERIODS must be >= 0 (0 = no tail).")
        if self.analytics_collect_job_timeout_seconds <= 0:
            raise ValueError("ANALYTICS_COLLECT_JOB_TIMEOUT_SECONDS must be positive.")
        if self.analytics_http_attempts < 1:
            raise ValueError("ANALYTICS_HTTP_ATTEMPTS must be >= 1.")
        if self.analytics_journal_retention_days < 1:
            raise ValueError("ANALYTICS_JOURNAL_RETENTION_DAYS must be >= 1.")
        if self.embedding_upsert_batch_size < 1:
            raise ValueError("EMBEDDING_UPSERT_BATCH_SIZE must be >= 1.")
        if self.repo_index_job_timeout_seconds <= 0:
            raise ValueError("REPO_INDEX_JOB_TIMEOUT_SECONDS must be positive.")
        if self.batch_stale_claim_seconds <= 0:
            raise ValueError("BATCH_STALE_CLAIM_SECONDS must be positive.")
        if self.invite_expiry_days <= 0:
            raise ValueError("INVITE_EXPIRY_DAYS must be positive.")
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
