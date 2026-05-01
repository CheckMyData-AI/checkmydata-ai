# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [1.10.0] - 2026-05-01

### Changed — AI-First Refactor (T01–T32)
- **Security & tenancy (P0)**: backup router admin/owner enforcement with 403 tests, project-scoped usage stats, SSE/workflow tenancy hardening, `project_service.update` mass-assignment whitelist, fixed `insight_feed` sample-size bug and `models` route OpenRouter fallback.
- **AI-first reasoning (P1)**: replaced heuristics with LLM-driven flows in `learning_analyzer`, `data_gate`, `stage_validator`, `suggestion_engine`, `default_rule_template`, `feedback_pipeline`, `orchestrator`, `tool_dispatcher`, `viz_agent`. Added structured `span_type` to all trace producers and consolidated chart rules into `app/viz/chart_rules.py`.
- **Performance (P2)**: parallelized sequential LLM/IO via `asyncio.gather`, eliminated N+1s (delete_stale_tables, list_projects roles, ClickHouse introspect), batched GeoIP/phone lookups, shared connector-per-batch in `batch_service`. Added `TTLCache` for `SESSION_LOCKS`, health state, SSH tunnels, and workflows. Replaced `SequenceMatcher` with embedding-based similarity (`text_similarity.semantic_similarity`/`semantic_best_match`). Moved bcrypt to `asyncio.to_thread`. Migrated `IndexingCheckpoint` from JSON-rewrite to append-only `indexing_checkpoint_step` / `indexing_checkpoint_doc` tables (Alembic `b6c7d8e9f0a1`).
- **Architecture (P3)**: split `chat.py` into `cost_estimation_service` + `chat_response_builder`, split `connections.py` into `connection_learnings`, split `data_validation.py` into `data_investigations`. Centralized magic numbers in `app/config.py`. Standardized Pydantic `response_model` (`OkResponse`, `OkWithIdResponse`, `AckWithCountResponse`). LLM adapters now classify errors via structured codes/types instead of substring matching.
- **Frontend (P4)**: split `lib/api.ts` (1794 lines) into `lib/api/{_client,types,auth,projects,connections,chat,workspace,analytics,index}.ts` while preserving the `@/lib/api` import surface. Extracted helpers from `ChatPanel` (`pipeline-event-handlers.ts`) and `ConnectionSelector` (`connection-form-helpers.ts`). Added unified `usePolling` hook with visibility-aware backoff and tightened `useGlobalEvents` reconnect lifecycle. Introduced zod (`lib/schemas/workflow-event.ts`) for runtime DTO validation. Design system pass: replaced raw palette classes with semantic tokens, added `--color-error-hover` and `--color-accent-strong`.

### Added
- `app/services/text_similarity.py` — embedding-first similarity helpers with `difflib` fallback.
- `app/services/cost_estimation_service.py`, `app/services/chat_response_builder.py` — extracted chat helpers.
- `app/api/schemas/common.py` — shared Pydantic response models.
- `app/api/routes/connection_learnings.py`, `app/api/routes/data_investigations.py` — split routers.
- `app/viz/chart_rules.py` — consolidated chart-validation rules.
- Backend Alembic `b6c7d8e9f0a1_add_append_only_checkpoint_tables`.
- Frontend `hooks/usePolling.ts`, `lib/schemas/workflow-event.ts`, `components/chat/pipeline-event-handlers.ts`, `components/connections/connection-form-helpers.ts`.

## [1.9.0] - 2026-04-13

### Changed
- **Orchestrator audit & improvement plan implementation** — completed the full multi-phase improvement program covering conversation handling, error handling, SQL planning, data/knowledge layer, observability, and long-term refactors.

#### Phase 3 — Error handling parity
- Centralized LLM retry/back-off via shared `llm_call_with_retry` helper.
- Stage-error normalization (`_stage_error_message`, `_classify_stage_error`); `StageResult` now carries `error_category` (`transient | configuration | data_missing | fatal`) and a `retryable` property.
- Pipeline `AgentResponse` now correctly populates `error` and supports a `degraded` synthesis status with `degraded_reason`.
- `LLMAllProvidersFailedError.is_retryable = False` (no infinite provider thrash).
- Parallel tool-call errors are typed (`tool_call:error` events with structured `error_type`).

#### Phase 4 — Planner/executor improvements
- Removed the legacy `QueryPlanner` class (`AdaptivePlanner` is now the sole planner).
- `_MAX_REPLANS` moved to `settings.max_pipeline_replans`.
- Replan history is threaded into `build_replan_prompt` so the LLM avoids repeating failed approaches.
- Repair context (`ContextEnricher.build_repair_context`) now includes attempt error type and longer query/error excerpts.
- Stage executor implements topological scheduling with `pipeline_max_parallel_stages` for safe parallel stage execution.

#### Phase 5 — Data/knowledge layer
- **Insight expiry & dedup (D1, D2):** `InsightRecord.expires_at` is now set per severity; `_find_duplicate` uses title+description+type+severity; `expire_old_insights` reaper added.
- **Unified learning API (D12):** `AgentLearningService.get_learnings(...)` consolidates the previous getters with category/table/confidence/limit filters.
- **Unified freshness (D6):** new `KnowledgeFreshnessService` combines DB-index age, code↔DB sync status, and Git HEAD into a single `staleness_warning`.
- **Note deactivation (D5):** `SessionNote.deactivated_at` column + `decay_stale_notes` now deactivates notes whose confidence drops below `deactivate_below`. Alembic migration `a5b6c7d8e9f0_add_deactivated_at_to_session_notes` ships the column.
- **Structured tool responses (D14):** `_handle_record_learning` and `_handle_write_note` return JSON (`{"status": "ok"|"rejected", ...}`) so the LLM can parse outcomes and retry.
- **RAG pre-query (D13):** `ContextLoader.load_relevant_knowledge` injects the top-K relevant KB chunks into the orchestrator context for every question.
- **Insight reconciliation (D15):** `InsightMemoryService.reconcile_with_query_results` auto-confirms reproduced anomalies and dismisses stale ones.
- **Insight injection (D11):** `ContextLoader.load_relevant_insights` surfaces the top active insights for the orchestrator prompt.

#### Phase 6 — Quality and observability
- **Answer validator (S11):** new `AnswerValidator` LLM-based quality gate replaces the `len > 80` heuristic when step / wall-clock limits are hit. Toggle via `answer_validator_enabled`.
- **Metrics (X2):** new `MetricsCollector` records per-request route / complexity / response_type / replans / retries / SQL calls / wall clock. Exposed at `/metrics` (recent rows) and `/metrics/prometheus` (text exposition format).
- **Settings group (X1):** new `AgentSettingsView` dataclass (accessible via `settings.agent`) groups all agent-related thresholds into a single typed view.
- **End-to-end tests (X5):** added integration coverage for the question → router → complex pipeline → stage failure → replan → success path.

#### Phase 7 — Long-term
- **LLM-first learning analyzer (D10):** new `learning_analyzer_mode` setting (`heuristic | hybrid | llm_first`); the analyzer now falls back to (or leads with) the LLM extractor while keeping the legacy `_detect_*` rules as a fast pre-filter.
- **ClickHouse EXPLAIN warnings (S5):** `ExplainValidator` now parses ClickHouse plan text and warns on full MergeTree scans without `PREWHERE`/`WHERE` and on unbounded result sets.
- **Token-aware synthesis budget (S8):** `ResponseBuilder.build_synthesis_messages` now budgets data inclusion by real token estimates (`LLMRouter.estimate_tokens`) instead of a `chars / 4` heuristic.

### Added
- `pipeline_max_parallel_stages` config (default `3`).
- `answer_validator_enabled` config (default `True`).
- `learning_analyzer_mode` config (default `"hybrid"`).
- `KnowledgeFreshnessService`, `AnswerValidator`, `MetricsCollector`, `AgentSettingsView` modules.
- `/metrics/prometheus` endpoint.
- Alembic migration `a5b6c7d8e9f0_add_deactivated_at_to_session_notes`.
- New unit tests: `test_answer_validator.py`, `test_metrics_collector.py`, `test_knowledge_freshness_service.py`.

### Removed
- `QueryPlanner` class (legacy plan-decomposition path).
- Hardcoded `_MAX_REPLANS` constant in `orchestrator.py`.

## [1.8.0] - 2026-04-14

### Changed
- **LLM-driven agent architecture refactor** — eliminated hardcoded heuristics, keyword matching, and rigid decision logic across the entire agent system, empowering the LLM to make all routing, complexity, tool selection, and budget decisions based on context
- **Unified LLM router** (`router.py`) — replaces `intent_classifier.py` and `AdaptivePlanner._is_complex()` with a single LLM call that determines route, complexity, approach, estimated queries, and multi-source needs
- **Unified tool loop** — merged `_run_data_query`, `_run_knowledge_query`, `_run_mcp_query` into a single `_run_unified_agent` that provides all available tools to the LLM without intent-gated tool surface restrictions
- **Dynamic budget management** — replaced rigid synthesis deadlines (`orchestrator_synthesis_reserve_steps`, `orchestrator_synthesis_time_ratio`, `orchestrator_max_query_db_calls`) with per-iteration budget injection; the LLM self-regulates based on step/time percentages with emergency synthesis at 90% threshold
- **LLM-driven visualization** — `VizAgent` now delegates all chart type selection to the LLM, replacing `_rule_based_pick()` with a minimal `_edge_case_fallback` for degenerate cases only
- **LLM-driven SQL table/rule handling** — removed `_auto_detect_tables`, `_filter_rules`, `_extract_warning_tag` from `sql_agent.py`; the LLM receives the full table map and all custom rules directly
- **LLM-driven query repair** — `retry_strategy.py` now passes raw error details and schema context to the repair LLM instead of pre-generated hint templates per error type
- **Semantic tool deduplication** — `tool_dispatcher.py` uses word-overlap similarity (Jaccard, threshold 0.8) instead of exact string matching
- **Simplified prompts** — `orchestrator_prompt.py` and `sql_prompt.py` replaced rigid behavioral rules (TOOL CALL ECONOMY, SINGLE-QUESTION RULE, STEP BUDGET, ERROR RECOVERY, QUERY PLANNING, SELF-IMPROVEMENT PROTOCOL) with concise PRINCIPLES sections, letting the LLM decide approach
- **Removed `_parse_process_data_params` heuristics** — `stage_executor.py` no longer infers operations from description keywords; operation must be explicit in `input_context`

### Removed
- `table_resolver.py` — LLM + table map handles resolution
- `_COMPLEXITY_KEYWORDS`, `_TEMPORAL_PATTERN`, `_DIMENSION_KEYWORDS`, `_CONJUNCTION_WORDS` from `adaptive_planner.py`
- `detect_complexity`, `detect_complexity_adaptive` from `query_planner.py`
- `build_classification_prompt` from `orchestrator_prompt.py`
- `max_simple_query_steps`, `orchestrator_synthesis_reserve_steps`, `orchestrator_synthesis_time_ratio`, `orchestrator_max_query_db_calls` config settings

### Added
- `agent_emergency_synthesis_pct` config setting (default: 0.90) — budget threshold for emergency synthesis
- `router_model` config setting — optional model override for the routing LLM call

## [1.7.0] - 2026-04-14

### Changed
- **Always-deliver orchestrator (two-phase loop)** — the orchestrator tool-calling loop now operates in two phases: Phase 1 (data gathering) runs tool calls normally, and Phase 2 (mandatory synthesis) strips all tools from the LLM call, guaranteeing a text response. The system automatically enters Phase 2 when step budget (`orchestrator_synthesis_reserve_steps`, default 2) or time budget (`orchestrator_synthesis_time_ratio`, default 65%) is mostly consumed. This eliminates the "Analysis reached step limit" dead-end: even when resources are exhausted, the system always produces a complete, professional answer from whatever data was gathered
- **Time-budget propagation to sub-agents** — the orchestrator now threads `remaining_wall_seconds` through `ToolDispatcher` to the SQL agent. The SQL agent caps its per-query timeout at `min(query_timeout_seconds, remaining_wall * 0.5)` (floor: 5s), preventing a single slow query from consuming the entire time budget
- **Smarter synthesis prompt** — `ResponseBuilder.build_synthesis_messages` now includes ALL SQL query results (not just the last one), with query explanations and insights. The prompt instructs the LLM to produce a complete, professional analysis without mentioning step limits or partial results
- **Graceful response_type on budget exhaustion** — when synthesis produces a valid answer and at least one SQL result has data, the `response_type` is set to `sql_result` instead of `step_limit_reached`, giving users a normal-looking answer rather than a warning banner
- **Expanded complexity detection** — `AdaptivePlanner._is_complex` now recognizes temporal ranges ("last N months"), comparison keywords ("which performed better", "vs"), and multi-dimensional analysis patterns ("by payment method", "by region"). Revenue analysis queries that previously ran through the flat tool loop now get the more robust multi-stage pipeline
- **Continuation budget boost** — `continue_analysis` runs receive 50% more steps and wall-clock budget, reducing the chance of hitting limits again during continuation
- **Lighter repair queries on timeout** — when a SQL query times out and enters the repair loop, the repair hints now explicitly instruct the LLM to produce a lighter query (add LIMIT, remove unnecessary JOINs, narrow date ranges, use approximate aggregations)
- **Two-phase step budget prompt** — the orchestrator system prompt STEP BUDGET section updated to describe the two-phase model, instructing the LLM to maintain a running analysis so it can synthesize from partial data at any point
- **`query_database` cap raised to 3** — new `orchestrator_max_query_db_calls` setting (default 3, up from hard-coded 2) allows richer multi-query analyses

### Added
- `orchestrator_synthesis_reserve_steps` config setting (default: 2) — steps reserved for the synthesis phase
- `orchestrator_synthesis_time_ratio` config setting (default: 0.65) — fraction of wall-clock time after which synthesis begins
- `orchestrator_max_query_db_calls` config setting (default: 3) — configurable cap on `query_database` calls per request
- `wall_clock_remaining` parameter on `SQLAgent.run()` for time-aware query timeout capping

## [1.6.1] - 2026-04-08

### Fixed
- **Rule schema validation now functional** — `validate_rules_against_schema` no longer requires a `previous_tables` diff (which was never supplied). Instead it scans rule content for underscore-delimited identifiers not present in `known_tables`, detecting stale table references without needing a before/after comparison
- **Table resolution for complex queries** — `_run_data_query` now computes `table_hints` before the complexity check, so complex queries also benefit from programmatic table resolution instead of silently skipping it
- **`build_resolution_hints` logic** — fuzzy NOTEs are no longer suppressed when some tables matched exactly; unresolved-term WARNINGs are now always emitted regardless of whether other terms were resolved
- **Reasoning state cleanup on stream errors** — `handleSend` error handler, `handleStop`, and session-switch `useEffect` now finalize reasoning traces and clear `streamingMsgIdRef`, preventing orphaned traces and memory leaks
- **Reasoning store memory bounds** — traces are capped at 20 (evicting oldest on overflow), steps per trace capped at 200, and `clearAllTraces` action added for session resets. `closePanel` now also clears `activeMessageId`
- **ReasoningButton always visible** — moved out of the metadata-metrics conditional block so it appears for all assistant messages that have a reasoning trace, not only those with row_count/execution_time/token_usage
- **ReasoningButton render efficiency** — store selector narrowed from `s.traces` (entire object) to `!!s.traces[messageId]` (boolean), eliminating unnecessary re-renders when other traces update
- **`handleSend` useCallback deps** — added `reasoningInitTrace`, `reasoningFinalize`, `reasoningAddStep` to the dependency array

## [1.6.0] - 2026-04-08

### Added
- **Programmatic table resolution** — new `table_resolver.py` with `resolve_tables()` heuristic that matches user question terms against known tables via exact, plural/singular, substring, and keyword-to-description matching. Generates prompt-injectable warnings for unresolved terms. Wired into `_run_data_query` and `_run_full_pipeline` as a soft-nudge before the tool-calling loop
- **QUERY PLANNING rule 5** — orchestrator prompt now mandates `ask_user` when TABLE RESOLUTION WARNINGS are present, preventing the LLM from guessing at unknown tables
- **RULE FRESHNESS CHECK** — new prompt section (only when custom rules are loaded) instructs the orchestrator to compare query results against loaded rules and propose updates via `manage_rules` when discrepancies are detected
- **Schema-aware rule validation** — `RuleService.validate_rules_against_schema()` detects rules referencing tables that were dropped during schema refresh; wired into `POST /connections/{id}/refresh-schema` alongside existing learning validation
- **Execution plan visibility** — `plan_summary` event emitted from orchestrator (tables, strategy, rules_applied, learnings_applied, has_warnings); forwarded via SSE; rendered as a collapsible `PlanSummaryCard` in the chat thinking area
- **Agent Reasoning Panel** — new slide-out right-side panel (`ReasoningPanel.tsx`) showing full orchestrator internals: plan summary, thinking log, step-by-step timeline with icons and durations, rules and learnings applied. Brain icon on each assistant message toggles the panel
- **Reasoning store** — new `reasoning-store.ts` (Zustand) collecting per-message reasoning traces from SSE events during streaming, with trace finalization and temp-to-real message ID mapping
- **ToolCallIndicator wired into ChatPanel** — previously unused component now renders active tool calls as badges below the thinking area
- **`agent_start`/`agent_end` SSE events forwarded** — enriched with `extra` metadata and consumed by the frontend SSE parser as step events for the reasoning panel

### Changed
- Orchestrator prompt `build_orchestrator_system_prompt` now accepts optional `table_hints` parameter
- `_run_tool_loop` accepts optional `table_hints` parameter and emits `plan_summary` before the loop starts
- SSE pipeline events set extended with `plan_summary` in both backend (`chat.py`) and frontend (`api.ts`)
- `app/app/page.tsx` layout includes `ReasoningPanel` alongside `NotesPanel` in the right-side slot

## [1.5.4] - 2026-04-03

### Fixed
- **Custom rules ignored by orchestrator and SQL agent** — custom rules were never proactively injected into system prompts; they relied entirely on the LLM choosing to call optional tools (`get_custom_rules`, `get_query_context`), which was frequently skipped. Now rules are loaded via `CustomRulesEngine` and injected directly into both `build_orchestrator_system_prompt` and `build_sql_system_prompt` with budget-aware truncation (2000 chars for orchestrator, 3000 chars for SQL agent). The `ContextBudgetManager` `rules_text` slot (10% of budget) is now wired into the orchestrator's `_run_tool_loop`. An efficiency hint in the SQL prompt tells the LLM not to re-fetch rules via the tool when they're already in the prompt

## [1.5.3] - 2026-04-03

### Fixed
- **Intent classifier parse error resilience** — `_parse_classification_response` now uses a three-tier extraction strategy: (1) direct `json.loads`, (2) regex-based `{...}` extraction for JSON with trailing text, (3) plain-text intent name recovery. Previously, LLM responses with trailing text or without JSON structure caused `parse_error` fallback to `MIXED` intent, leading to unnecessary full-context loading and slower responses
- **Pipeline continuation crash protection** — `json.loads` calls on `stage_results_json` / `user_feedback_json` in `orchestrator.py` now wrapped in try/except, returning a user-friendly error instead of crashing when pipeline state is corrupted
- **Complexity classifier logging** — `query_planner.py` now logs at WARNING level when the LLM returns non-JSON for complexity classification, making parse failures visible in production logs

### Changed
- **Intent classifier logging promoted** — parse_error and invalid_intent logs elevated from DEBUG to WARNING level for production visibility on Heroku

## [1.5.2] - 2026-04-03

### Added
- **Hard step limits by query type** — simple data queries capped at 4 steps (`max_simple_query_steps`), global max reduced from 100 to 12 (`max_orchestrator_iterations`). Wrap-up injection fires 1 step before limit
- **`query_database` call cap** — after 2 `query_database` calls in a single request, a hard system message is injected and the tool is stripped from the tool list, forcing the LLM to compose a final answer
- **Multilingual complexity keywords** — `_COMPLEXITY_KEYWORDS` extended with Russian, Spanish, German, and Portuguese equivalents; conjunction words in `_is_complex` heuristic now include multilingual variants
- **Per-viz timeout** — each `viz.run()` call wrapped with `asyncio.wait_for(timeout=viz_timeout_seconds)` (default 15s); catches `TimeoutError` and `CancelledError` with graceful fallback to table visualization
- **Empty-answer guard** — all `_run_tool_loop` exit paths now check for empty `final_text`; when the LLM returns empty content but SQL results exist, `build_partial_text` is used as a fallback to guarantee a visible response
- **Viz deduplication** — `viable_sql` is deduplicated by query text before the viz loop; duplicate queries keep only the result with more rows, preventing redundant viz calls
- **`_stream_tokens` on all exit paths** — step-limit and synthesis-failure branches now always stream final text to the client, fixing silent empty responses

### Changed
- **Orchestrator prompt strengthened** — TOOL CALL ECONOMY, SINGLE-QUESTION RULE, and STEP BUDGET sections now explicitly instruct the LLM to combine sub-queries into one comprehensive SQL call; hard limit of 2 `query_database` calls stated in prompt
- **`orchestrator_wrap_up_steps` default** changed from 2 to 1 for earlier wrap-up injection
- **Config** — new settings: `max_simple_query_steps` (4), `viz_timeout_seconds` (15); `max_orchestrator_iterations` reduced from 100 to 12

## [1.5.1] - 2026-04-02

### Added
- **Agent Learning quality gates** — blocklist for SQL keywords/metadata subjects (`columns`, `tables`, `information_schema`, `pg_catalog`, etc.), minimum lesson length (15 chars), non-ASCII ratio rejection (>50%), and normalization (whitespace cleanup, capitalization, max 500 chars). Write-time validation via `validate_learning_quality()` and read-time filtering via `skip_blocklisted` flag
- **Schema cross-validation** — `validate_learnings_against_schema()` deactivates learnings whose subject no longer exists in the DB schema. Runs automatically on schema refresh and available as manual `POST /connections/{id}/learnings/validate-schema` endpoint
- **Learning confirm/contradict API** — `POST /connections/{id}/learnings/{lid}/confirm` (upvote) and `POST /connections/{id}/learnings/{lid}/contradict` (downvote) endpoints with RBAC (editor+). Votes immediately invalidate the compiled prompt cache
- **Audit script** (`scripts/audit_learnings.py`) — production database learning audit tool with dry-run and apply modes; diagnoses blocklisted subjects, short lessons, and high non-ASCII content
- **Orchestrator request summary logging** — each request now logs `request_summary` with step count, wall clock time, SQL call count, response type, and error types
- **RulesManager view mode** — viewers can now click rules to read them in a read-only modal; editors get dirty-state tracking with disabled Save button when unchanged

### Changed
- **Accelerated confidence decay** — never-applied learnings (times_applied=0) lose 0.05 per 30-day cycle vs 0.02 for applied ones, enabling faster cleanup of unproven learnings
- **Orchestrator hardened wrap-up** — time limit and step limit messages use stronger "CRITICAL" directive; hard wall-clock cutoff tightened from 1.5x to 1.2x to prevent excessive overruns
- **Table map propagation** — orchestrator now sets `context.table_map` from the loaded table map when not already set, fixing downstream stages receiving empty table maps

### Fixed
- **Vote cache invalidation** — `confirm_learning()` and `contradict_learning()` now call `_invalidate_summary()` to clear the compiled prompt cache immediately after voting
- **Blocklist filtering on read** — `get_learnings()` and `get_learnings_for_table()` now skip blocklisted subjects by default, catching legacy bad data that was stored before write-time validation

## [1.5.0] - 2026-04-01

### Added
- **AdaptivePlanner** — replaces heuristic + LLM complexity detection with a unified planner that generates quick (deterministic) plans for simple queries and LLM-driven plans for complex ones. Supports `recent_learnings` injection
- **DataGate** — intermediate data-quality validator between pipeline stages. Checks null rates, type consistency, duplicate rows, value ranges, truncation, and cross-stage consistency
- **Replan loop** — when a pipeline stage fails after retries, the orchestrator asks the `AdaptivePlanner` to generate a new plan (up to 2 replans) that avoids the failed approach and reuses completed results
- **PipelineLearningExtractor** — extracts lessons from pipeline events (replans, DataGate failures, validation failures) and stores them via `AgentLearningService` for future planning
- **ToolDispatcher** — extracted from `OrchestratorAgent`; centralizes all meta-tool dispatch logic
- **ResponseBuilder** — extracted from `OrchestratorAgent`; centralizes response assembly and synthesis
- **ContextLoader** — extracted from `OrchestratorAgent`; lazy-loads table maps, KB, learnings, staleness
- **Per-stage `max_retries`** — each `PlanStage` can define its own retry budget; `StageExecutor` respects it over the global setting
- **`replan_on_failure` flag** — per-stage control over whether a failed stage triggers replanning
- **Replan prompt** — `build_replan_prompt` in `planner_prompt.py` provides context about completed stages and the failure to guide replanning
- **Pipeline learning categories** — `pipeline_pattern`, `data_quality_hint`, `replan_recovery` added to `AgentLearningService`

### Changed
- **Orchestrator slimmed** — `orchestrator.py` reduced from 2728 to ~1760 lines by extracting `ToolDispatcher`, `ResponseBuilder`, and `ContextLoader`
- **`StageExecutor` unified validation loop** — now runs `StageValidator` then `DataGate` after each stage, with retry and replan signals
- **Complexity detection** — replaced dual `detect_complexity` + `detect_complexity_adaptive` with `AdaptivePlanner._is_complex` (single deterministic check, no extra LLM call)
- **Pipeline planning** — `_run_complex_pipeline` now uses `AdaptivePlanner._llm_plan` instead of `QueryPlanner.plan`, with learnings injected into the prompt

## [1.4.0] - 2026-04-01

### Added
- **Compound SQL responses** — when a user asks multiple questions in one message, each SQL result now gets its own chart, "View SQL Query" section, and insights card. Previously only the last SQL result was shown
- **`SQLResultBlock` dataclass** — new structured type for individual SQL results with their own viz_type, viz_config, and insights
- **`SQLResultSection` React component** — extracted reusable component for rendering per-query SQL viewer, chart toggle, visualization, data table, and insight cards
- **`sql_results` field** on `AgentResponse`, `ChatResponse`, SSE event, and `ChatMessage` — carries the array of compound results end-to-end from orchestrator to frontend
- **VizAgent runs per-result** — each SQL result in a compound response gets its own visualization recommendation instead of only the last one

## [1.3.2] - 2026-04-01

### Changed
- **Agent step limits raised** — `max_orchestrator_iterations` 25 → 100, `max_sql_iterations` 3 → 15, `agent_wall_clock_timeout_seconds` 90 → 300. Prevents premature termination on complex queries or slow LLM responses
- **Wall-clock timeout now uses distinct message** — hard timeout fallback produces "I reached the processing time limit" instead of the misleading "maximum number of analysis steps" message (via new `_build_timeout_text` method)
- **Timeout sets `response_type` correctly** — `wall_clock_timeout_hit` flag ensures `response_type = "step_limit_reached"` when the wall-clock cutoff fires (previously fell through as `"sql_result"`)

### Fixed
- **SSE stream closing before agent finishes** — `stream_timeout_seconds` 120 → 360, `stream_safety_margin_seconds` 90 → 120 (total 480s). The old SSE deadline of 210s was shorter than the new 300s agent timeout, causing premature "Request timed out" errors and agent task cancellation

## [1.3.1] - 2026-03-31

### Fixed
- **CI lint fixes** — resolve 24 ruff errors: `IntentType` migrated from `(str, Enum)` to `StrEnum` (UP042), unused `ClassifiedIntent` imports removed (F401), import blocks sorted (I001), line-length violations fixed (E501), local variable naming corrected (N806), format inconsistencies resolved

## [1.3.0] - 2026-03-31

### Fixed
- **8 bugs**: Clarification requests no longer swallowed in parallel tool execution; double `tracker.end()` eliminated from complex pipeline fallback, pipeline resume, and `_run_data_query`/`_run_full_pipeline` paths; intent classifier no longer crashes on JSON array responses; `KnowledgeAgent._collected_sources` moved from instance state to per-run local to prevent concurrency corruption; `MCPSourceAgent` adapter now restored after each `run()` call; `loop_budget` aligned with `max_context_tokens` cap (was using raw model window); `StageContext.from_persistence` now warns when resumed data is truncated

### Changed
- **Dedup extended to all data tools** — `_dedup_tool_calls` now deduplicates `search_codebase` and `query_mcp_source` in addition to `query_database`. Removed error-prone history-based substring dedup (prompt-level guidance is more reliable)
- **Viz fallback uses structured data** — `ValidationOutcome.fallback_viz_type` replaces fragile string-matching on warning text; viz type set in `validation.py` consolidated (viz_agent imports from validator)
- **Context immutability** — all intent-path methods now use `replace(context, ...)` instead of mutating `context.chat_history` in-place
- **Symmetric tool scoping** — `_run_data_query` no longer exposes MCP tools (matching `_run_mcp_query` which doesn't expose DB tools); mixed intent still exposes all
- **MCP plan validation** — `query_mcp_source` added as valid data-retrieval tool in `_validate_plan_structure`, enabling MCP-only complex plans
- **Pipeline responses include metadata** — `_build_pipeline_response` now populates `token_usage`, `tool_call_log`, `steps_used`, `steps_total`
- **MCP connection hoisted out of retry loop** — `_handle_query_mcp_source` lookups DB once, then retries only the LLM/tool calls
- **MCP source check cached** — `_has_mcp_sources` now caches results per project for 60s
- **Config defaults tuned** — `max_context_tokens` raised from 16K to 32K; `rag_relevance_threshold` lowered from 1.3 to 0.8; `"then"` keyword tightened to `" then "` to reduce false-positive complexity detection

### Added
- **`list_rules` tool** — LLM can now list existing project rules to discover IDs before update/delete (resolves `manage_rules` update/delete being unusable)
- **Intent classification tracker event** — orchestrator now emits the classified intent and reason to the workflow tracker
- **MCP result thinking event** — `_emit_tool_result_thinking` now called for MCP source results (parity with SQL and Knowledge)
- **`manage_rules` output_preview** — step data now includes output_preview for observability

### Removed
- Dead error types `AgentTimeoutError` and `AgentValidationError` (never raised/caught)
- Dead config settings `daily_token_limit`, `monthly_token_limit`, `query_cache_persist_dir`
- Aspirational prompt text: "Data Verification Protocol" tracking, "session note" references, "sanity checker" mention, "COMPLEX MULTI-STEP QUERIES" section (moved to code-level handling)
- `numeric_range` question type from `ask_user` (never implemented)

## [1.2.0] - 2026-03-31

### Added
- **Orchestrator intent classification** — The orchestrator now runs a lightweight LLM-based intent classification step (~500 tokens, ~0.5s) before loading any heavy context. User messages are classified into `direct_response`, `data_query`, `knowledge_query`, `mcp_query`, or `mixed`, and only the relevant context and tools are loaded for each intent type. A simple greeting like "What can you do?" now completes in ~1-2s with 2 LLM calls and 0 DB queries, down from ~15s / 34 spans / 174K tokens. New module: `backend/app/agents/intent_classifier.py`. New prompt builders: `build_classification_prompt()`, `build_direct_response_prompt()` in `orchestrator_prompt.py`. The orchestrator `run()` method now routes to `_run_direct_response`, `_run_data_query`, `_run_knowledge_query`, `_run_mcp_query`, or `_run_full_pipeline` based on the classified intent. Falls back to `mixed` (full pipeline) on any classification error

## [1.1.1] - 2026-03-31

### Fixed
- **402 Payment Required misclassified as retryable error** — HTTP 402 from OpenRouter (insufficient credits) was falling through to `LLMServerError` (retryable), causing 12+ seconds of futile retries before surfacing the error. Added `LLMBillingError` to the error hierarchy (non-retryable, allows fallback to other providers). Fixed the same gap in all three adapters (OpenRouter, OpenAI, Anthropic). The router now skips per-provider retries for billing errors but still tries the next configured provider in the fallback chain

## [1.1.0] - 2026-03-31

### Added
- **Welcome chat for new users** — When a user enters a project with no existing chats, a default "Welcome" session is automatically created with an agent greeting that explains capabilities (database queries, codebase analysis, visualizations, learning, data validation) and invites the user to communicate in any language. Backend endpoint `POST /chat/sessions/ensure-welcome` is idempotent. Frontend triggers it on project restore and project switch

### Improved
- **Orchestrator history-awareness refactoring** — Fixed the orchestrator re-executing SQL queries from prior conversation turns. Six changes: (1) Explicit turn separator injected between chat history and the current user message so the LLM sees history as completed, not actionable; (2) New prompt directives (CURRENT TURN FOCUS, TOOL CALL ECONOMY, SINGLE-QUESTION RULE) prevent the LLM from decomposing history+current into multiple tasks; (3) Chat history enrichment simplified — removed raw SQL text and sample data from assistant context, keeping only row count, column names, and viz type to reduce token usage and avoid "looks like active tool output" confusion; (4) Tool-call deduplication guard removes duplicate `query_database` calls in the same batch and skips calls whose questions already appear in history; (5) SQL sub-agent now receives only the last 4 history messages instead of the full conversation, reducing noise in the validation/repair loop; (6) Reduced `max_history_tokens` from 4000 to 2500
- **Orchestrator gaps audit follow-up** — Extended history scoping to the complex pipeline path and all sub-agent call sites: (1) StageExecutor now scopes chat_history to last 4 messages for both SQL and Knowledge stages; (2) `_run_complex_pipeline` and `_resume_pipeline` pass scoped context to the executor; (3) SINGLE-QUESTION RULE amended to exclude `process_data` chaining from the tool-call cap; (4) Legacy `QueryBuilder.build_query` now injects a history boundary and scopes to last 4 messages; (5) Removed dead `chat_history` parameter from `detect_complexity` and `detect_complexity_adaptive`; (6) `_handle_search_codebase` and `_handle_query_mcp_source` defensively scope context; (7) SQL agent system prompt now includes a CURRENT QUESTION FOCUS directive; (8) Cost estimate formula aligned with runtime — `max_history_tokens` is now a separate budget from static context
- **Orchestrator full flow audit** — Seven fixes from end-to-end audit: (1) CRITICAL: initialized `iteration = 0` before the main loop to prevent `UnboundLocalError` when `max_iter == 0`; (2) CRITICAL: VizAgent now receives scoped context (last 4 history messages) instead of the full unscoped context, matching all other sub-agents; (3) MCP tool `query_mcp_source` is now described in the orchestrator system prompt (capabilities + guidelines) via new `has_mcp_sources` parameter, giving the LLM proper routing guidance; (4) Parallel-tools guideline amended to explicitly exclude `process_data` from parallel recommendations ("chain sequentially"); (5) Knowledge validation failure in `_handle_search_codebase` now retries (matching `_handle_query_database` pattern) instead of returning immediately; (6) `steps_used` formula simplified to always use `iteration + 1` (1-based) regardless of how the loop ended; (7) Integration test added verifying `_run_complex_pipeline` passes scoped context to `StageExecutor`

- **Orchestrator audit round 3** — Comprehensive 32-finding audit with fixes across the entire orchestrator system: (1) HIGH: Fixed `exclude_empty="false"` truthy string bug in process_data — the string `"false"` was treated as truthy, now only `"true"/"1"/"yes"` activate; (2) HIGH: `_handle_process_data` no longer mutates shared `SQLAgentResult` in-place — uses `dataclasses.replace()` to preserve original query results for chain operations; (3) HIGH: `_run_complex_pipeline` and `_resume_pipeline` wrapped in try/except with pipeline-specific logging and tracker.end on failure; (4) HIGH: `query_mcp_source` added to planner `_VALID_TOOLS`, planner prompt, and stage executor with new `_run_mcp_stage` method — MCP data sources can now participate in multi-stage pipelines; (5) MEDIUM: `_apply_continuation_context` uses `replace()` instead of in-place mutation; (6) MEDIUM: `_create_pipeline_run` and `_persist_stage_results` wrapped in try/except; (7) MEDIUM: `RETRYABLE_LLM_ERRORS` added to SQL handler's except chain; MCP handler now validates results via `validate_mcp_result()`; (8) MEDIUM: VizAgent and MCPSourceAgent LLM calls wrapped with local try/except and graceful fallbacks; (9) MEDIUM: `_handle_ask_user` return type corrected to `NoReturn`; (10) MEDIUM: Fixed `ctx.session_id` to `ctx.extra.get("session_id")` in sql_agent.py; (11) MEDIUM: Planner now receives `project_overview` and `current_datetime`; (12) MEDIUM: `process_data` returns enriched sub-result for all operations (not just aggregate); (13) MEDIUM: `QueryRepairer` imports `EXECUTE_QUERY_TOOL` from `sql_tools` instead of deprecated `query_builder`; (14) MEDIUM: `_determine_response_type` returns `"mcp_source"` when only MCP results exist; (15) LOW: Dead constants `KNOWLEDGE_SYSTEM_PROMPT`/`VIZ_SYSTEM_PROMPT` removed; double synthesis skipped when last stage is `synthesize`; `_emit_tool_result_thinking` now logs exceptions; `AgentResponse` type annotations parameterized; history enrichment includes query, insights, followups; empty pipeline answer guarded; (16) 30 new tests covering process_data handler, wall-clock timeout, trim_loop_messages, should_wrap_up, MCP validation, and response type determination

### Fixed
- **Agent timeout hang (330s)** — Complex queries could hang for 330 seconds before timing out due to no wall-clock budget on the orchestrator loop and a double SSE timeout cascade (210s event loop + 120s wait loop). Fixed with three changes: (1) Added `AGENT_WALL_CLOCK_TIMEOUT_SECONDS` (default 90s) that forces the orchestrator to wrap up when elapsed time exceeds the limit, with a hard cutoff at 1.5x; (2) Reduced the SSE post-event grace period from `stream_timeout_seconds` (120s) to 20s, bringing worst-case total from 330s to ~230s; (3) Added `MAX_PARALLEL_TOOL_CALLS` (default 2) semaphore to cap concurrent tool executions, preventing resource exhaustion from unbounded parallel `query_database` calls
- **Trace persistence FK violation** — `_persist_workflow` was inserting into `request_traces` with empty `project_id` which violated the foreign key constraint. Now skips the initial persist when `project_id` or `user_id` is empty; `finalize_trace()` creates the trace row with correct IDs via its else branch

### Fixed
- **Favicon looked squished in browser tabs** — Regenerated `favicon.ico` as multi-size ICO (16x16, 32x32, 48x48) instead of single 32x32. Added `favicon.svg` for modern browsers. Removed unused `favicon-32.png`
- **OG image dimensions mismatch and size** — Resized `og-image.png` from 1376x768 to standard 1200x630 and compressed from 985KB to 74KB. Optimized all icons from SVG source (icon-512.png 247KB → 20KB, icon-192.png 31KB → 6KB)
- **Duplicate `<head>` tags in HTML output** — Removed manual `<link>` and `<meta>` tags from root layout `<head>` that duplicated what the Next.js `metadata` export already generates
- **Sub-page titles bypassed template** — Changed all marketing sub-pages from hardcoded `"Title | CheckMyData.ai"` to just `"Title"` so the root `template: "%s | CheckMyData.ai"` applies consistently
- **Missing Twitter cards on sub-pages** — Added `twitter` metadata to About, Contact, Support, Privacy, and Terms pages
- **`/login` in sitemap** — Removed auth page from sitemap and added `robots: { index: false }` via a login layout
- **`#main-content` skip link target missing** — Added `id="main-content"` to `<main>` in the marketing layout so the skip-to-content link actually works for keyboard users
- **`text-tertiary` failed WCAG AA** — Lightened token from `#71717a` (4.12:1) to `#84848e` (5.37:1 on surface-0, 4.79:1 on surface-1). Fixed `text-muted` usage on meaningful content (copyright, CTA notes) by switching to `text-tertiary`
- **No mobile navigation on marketing pages** — Added hamburger menu component (`MobileMenu`) with animated dropdown for About, Support, GitHub, and Log in links
- **PWA manifest missing icon purpose** — Added `"purpose": "any maskable"` to manifest.json icon entries for Android adaptive icon support

### Fixed
- **Orchestrator `steps_used` always same** — Fixed dead ternary `iteration + 1 if step_limit_hit else iteration + 1` (both branches identical); now correctly reports `iteration` when the agent finished before the step limit
- **SPAN_TYPE_MAP stale tool names** — Updated trace span classification keys to match actual knowledge agent tools (`search_knowledge` instead of `search_codebase`, `get_entity_info` instead of `get_entity_details`) and SQL agent tool (`get_sync_context` instead of `get_sync_status`); removed non-existent `list_entities` entry
- **Tautological test assertion** — Fixed `assert ... or True` in `test_persists_when_project_id_empty` that always passed regardless of actual condition
- **ARCHITECTURE.md wrong API paths** — Corrected traced request paths (`/ask` → `/api/chat/ask`, `/ws/chat` → `/api/chat/ws/{project}/{connection}`) and health endpoint path (`/health` → `/api/health`)
- **CHANGELOG duplicate entries** — Removed 5 duplicate fix entries (useRestoreState race, ProjectSelector race, Health endpoint, Graceful shutdown, seedActiveTasks race)
- **deploy.yml checkout ref** — Added `ref: ${{ github.event.workflow_run.head_sha }}` to ensure CI-validated commit is deployed, not whatever is on the default branch at deploy time
- **deploy-heroku.sh exit code** — Unknown CLI options now exit 1 instead of falling through to `usage()` which exits 0
- **`.env.example` wrong default** — Fixed `STREAM_SAFETY_MARGIN_SECONDS` comment from 30 to 90 to match actual `config.py` default
- **Clarification flow broken end-to-end** — The `ask_user` tool's structured data (question type, options, context) was lost in transit from orchestrator to frontend because `clarification_data` was stored in `viz_config` but never mapped to the API response. Added a dedicated `clarification_data` field to `AgentResponse`, `ChatResponse`, and all three response paths (REST, SSE, WebSocket). The `ClarificationCard` UI (yes/no, multiple choice, free text, numeric range) now renders correctly with structured data
- **`ask_user` unavailable without DB connection** — The `ask_user` tool was gated behind `has_connection=True` in `get_orchestrator_tools()`, preventing clarification questions for knowledge-only projects. Moved `ask_user` to be always available regardless of connected capabilities

### Improved
- **Proactive request analysis** — Added "REQUEST ANALYSIS PROTOCOL" to the orchestrator system prompt instructing the LLM to assess request ambiguity, check schema/knowledge coverage, and use `ask_user` proactively before executing tools. Previously the prompt only encouraged post-query verification

### Fixed
- **CI backend build failure** — `pyproject.toml` referenced `../README.md` which broke `pip install -e .` in CI because setuptools prohibits reading files outside the package root. Replaced with inline description text
- **29 backend lint errors** — Fixed variable naming conventions (`N806`), line-too-long violations (`E501`) in welcome message and email HTML templates, CamelCase-as-acronym import (`N817`), module-level imports not at top of file (`E402`), duplicate test method name (`F811`), and unused local variable (`F841`)
- **24 backend mypy errors** — Fixed type mismatches across 5 files: `ssh_tunnel.py` dict.pop default arg type; `email_service.py` resend `SendParams`/`Tag` type conflicts (5 call sites); `trace_persistence_service.py` missing `rowcount` attribute on `Result`; `sql_agent.py` handler dict value type inference (10 entries); `orchestrator.py` `result` variable shadowed by two incompatible types in `_resume_pipeline`
- **Frontend logs components not tracked in git** — `.gitignore` pattern `logs/` was matching `frontend/src/components/logs/` recursively; changed to `/logs/` to only ignore the root-level logs directory
- **Lost error traces** — Failed requests that crashed before `pipeline_end` was emitted now always appear in the Logs screen with full step breakdown and error details. Six root causes fixed: (1) `ConversationalAgent.run()` now wraps the orchestrator call in `try/except/finally` with a safety-net `pipeline_end` emission via `WorkflowTracker.has_ended()`; (2) Orchestrator `_resume_pipeline` early return ("pipeline not found") now calls `tracker.end()`; (3) Non-streaming `POST /ask` wraps `_agent.run()` in `try/except` to call `finalize_trace()` on crash; (4) `_persist_workflow` no longer silently drops traces with empty `project_id`/`user_id` — they are persisted with empty IDs and `finalize_trace()` updates later; (5) `_cleanup_stale_buffers` persists stale buffers as failed traces (synthetic `pipeline_end`) instead of discarding them; (6) Streaming `_finalize_on_error` uses a fallback workflow ID when the original is `None`, and the "no result" branch now surfaces the actual task exception
- **Trace persistence FK violation** — `_persist_workflow` now persists traces even when `project_id` or `user_id` are missing from the workflow context, using empty strings as placeholders. `finalize_trace()` later updates these rows with correct IDs. This replaces the earlier approach of skipping persistence entirely, which caused error traces to be lost
- **SSE stream cut off on complex queries** — Increased `stream_safety_margin_seconds` from 30 to 90 (total deadline 210s) to accommodate multi-step agent workflows that exceed 150s, preventing premature "SSE event loop exceeded safety timeout" breaks

### Improved
- **Enriched trace spans** — Trace spans in the Request Logs screen now include full step-by-step data: LLM prompt/response previews with token counts and model info, SQL query text and result summaries, RAG search inputs/outputs, sub-agent delegation details, and validation step data. Noise events (`token`, `thinking`, `orchestrator:warning`, `orchestrator:llm_retry`) are filtered out. Duplicate `execute_query` spans removed. `WorkflowTracker.step()` now accepts a `step_data` dict for capturing enrichment data inside context managers. `SPAN_TYPE_MAP` expanded with all agent step names for accurate classification. Fallback `_build_spans_from_tool_log` now handles both `args`/`result` and `arguments`/`result_preview` key formats. Initial trace creation now includes `project_id` and `user_id` from `begin()` context
- **Complete trace capture** — Fixed multiple gaps where requests bypassed trace persistence: WebSocket chat now calls `finalize_trace()` after each message; SSE streaming error/timeout/cancel paths now finalize traces with `status=failed`; MCP tools (`query_database`, `search_codebase`) switched from isolated `WorkflowTracker()` instances to the singleton tracker so events reach `TracePersistenceService`; data validation investigation agent switched to singleton tracker with `project_id` context; batch execute now includes `project_id` and `user_id` in `tracker.begin()` context; standalone LLM endpoints (`generate-title`, `explain-sql`, `summarize`) now create lightweight traces with proper pipeline names. Request list in Logs screen now shows user display names when viewing all users, and date range filter is passed to the request list API call for consistency with summary/user sidebar time windows

### Fixed
- **Markdown table rendering in chat** — Added `remark-gfm` plugin to `react-markdown` so GFM pipe tables (`| col | col |`) generated by the LLM are rendered as proper HTML tables instead of raw text. Affects `ChatMessage.tsx`, `ChatPanel.tsx` (streaming), and `SQLExplainer.tsx`
- **Streaming text markdown** — Streaming (in-progress) assistant messages now render through `ReactMarkdown` with GFM support instead of plain `<p>` tag, so tables/bold/lists display correctly while generating
- **Backend tool result formatting** — `_format_query_results` in `sql_agent.py` and `tool_executor.py` now produces proper GFM markdown tables (with header + separator rows) instead of bare pipe-separated lines, improving LLM output quality
- **Table CSS layout** — Removed `display: block` from `.chat-markdown table` in `globals.css` which broke native table column alignment; overflow scrolling is now handled by the wrapper `<div>` in `mdComponents`

### Added
- **Request Logs screen (owner-only)** — New full-panel logs screen accessible from the sidebar that shows every chat request as a structured trace. Features: KPI summary cards (total requests, success rate, failed count, LLM calls, DB queries, avg latency, cost), user filter panel, paginated request list with status/type badges, and expandable trace detail view showing the full orchestrator route with individual spans (LLM calls, DB queries, sub-agent steps, validation, RAG). Each span displays type icon, duration, token count, and error details. New `request_traces` and `trace_spans` DB tables persist orchestrator workflow events via `TracePersistenceService`. New `/api/logs/` endpoints with owner-only access control. Date range filter (7d/14d/30d/90d) and status filter (All/Completed/Failed)
- **Usage API server-side authorization** — `/api/usage/stats` now enforces owner-level access when `project_id` query param is provided (previously only frontend-gated)
- **Project creation eligibility gate** — New `can_create_projects` flag on users table (default `false`). Only eligible users can create projects on the hosted version; others see a "Request Access" modal with email/description/message form that sends a request to `contact@checkmydata.ai`. Backend enforces with 403 on `POST /api/projects`. New `POST /api/projects/access-requests` endpoint. Admin emails (configured via `ADMIN_EMAILS` env var) are seeded with `can_create_projects=true` via Alembic migration. Non-eligible users can still join projects via invite or use the self-hosted version
- **Analytics & Usage RBAC** — Analytics (`GET /chat/analytics/feedback/{pid}`, `GET /data-validation/analytics/{pid}`, `GET /data-validation/summary/{pid}`) and Usage sidebar panels are now restricted to project **owners** only. Non-owners no longer see these sections in the sidebar
- **Dashboard RBAC** — Dashboard create/edit/delete operations now require at least **editor** role. Viewers can list and view shared dashboards but cannot modify them. The "New dashboard" sidebar action and Edit button on dashboard pages are hidden for viewers. Any editor/owner can edit or delete any dashboard in their project (not just the creator)
- **`FormModal` component** (`frontend/src/components/ui/FormModal.tsx`) — Reusable modal shell with title bar, close (X) button, Escape key, backdrop click dismiss, focus trap, and scroll support
- **KnowledgeResult.sources populated** — RAG search results now correctly wire `RAGSource` objects into `KnowledgeResult.sources`, enabling citation display in chat
- **Global learning patterns** — `AgentLearningService` now identifies learnings that appear across 2+ connections and promotes them into every connection's prompt as universal patterns
- **Pre-call token estimation** — `LLMRouter.estimate_tokens()` uses tiktoken (OpenAI-accurate) with char-based fallback for pre-call context budgeting
- **Knowledge quality scoring** — `RAGFeedbackService` now computes per-source quality scores combining success rate and average retrieval distance, and identifies low-quality sources for re-indexing
- **Persistent query cache** — `QueryCache` supports optional file-based persistence via `query_cache_persist_dir` config, surviving process restarts
- **Incremental schema diff** — `SchemaInfo.fingerprint()` and `SchemaInfo.diff()` enable comparing schemas to detect only changed tables, avoiding full re-introspection
- **Token budget caps** — `UsageService.check_budget()` enforces configurable daily/monthly token limits per user with `BudgetExceededError` and remaining-budget reporting
- **Landing page and full branding** — New public landing page at `/` with hero section, feature grid (6 cards), how-it-works flow, open-source CTA, and supported databases banner. Dark theme using existing design system tokens with JSON-LD structured data for SEO
- **Marketing layout** — Shared `(marketing)` route group layout with sticky blurred header (logo, nav, Login, Get Started CTA) and 4-column footer (Product, Legal, Community links)
- **Dedicated login page** (`/login`) — Standalone authentication page with CheckMyData.ai branding replacing the inline AuthGate form. Supports email/password and Google OAuth
- **About page** (`/about`) — Product mission, technology stack overview, and open-source philosophy
- **Contact page** (`/contact`) — Email channels (contact@checkmydata.ai, support@checkmydata.ai) and GitHub community links
- **Support page** (`/support`) — FAQ with expandable details, documentation links, and support channels
- **Branding assets** — Generated favicon.ico, icon-192.png, icon-512.png, apple-touch-icon.png, og-image.png (1200x630), and reusable `Logo.tsx` SVG component (`LogoMark` + `LogoFull` variants)
- **SEO infrastructure** — robots.txt (disallows /app and /dashboard), dynamic sitemap.xml via Next.js `sitemap.ts`, `metadataBase` on root layout, canonical URLs and OG/Twitter Card metadata on all pages

### Fixed
- **Authenticated user landing redirect** — Added `AuthRedirect` client component to the landing page so authenticated users visiting `/` are automatically redirected to `/app` instead of seeing the marketing page

### Changed
- **Custom Rules editor enlarged** — Rule edit/create modal widened from `max-w-lg` (512px) to `max-w-3xl` (768px) with a taller monospaced textarea (rows=12, min-h-200px) for comfortable markdown editing
- **Agent Learnings popup** — LearningsPanel converted from an inline accordion inside the sidebar to a centered `FormModal` popup (`max-w-3xl`) with 60vh scroll area, larger text, and roomier edit textareas
- **Sidebar forms → centered modals** — All 6 sidebar create/edit forms (Project, Connection, SSH key, Rule, Schedule, Dashboard) now open as centered pop-up modals instead of rendering inline in the sidebar
- **StageValidator configurable strictness** — Min/max row count checks can now fail (not just warn) via `strict_row_bounds` flag
- **SSH tunnel idle cleanup** — `SSHTunnelManager` now tracks last-used time per tunnel and closes idle tunnels (default 30min TTL)
- **Parallel batch queries** — `BatchService.execute_batch()` now runs queries concurrently (up to 4 parallel, configurable)
- **Expanded rule-based viz** — `VizAgent` now handles more cases without LLM calls: auto-detects pie/bar/line charts for common data shapes
- **Deprecated orchestrator decoupled** — `core/orchestrator.py` is no longer imported by any production code
- **Route restructure** — Main application moved from `/` to `/app`. Unauthenticated users see the landing page at `/` instead of a login form
- **AuthGate simplified** — Reduced from 293-line login form to a 42-line redirect guard that sends unauthenticated users to `/login`
- **Legal pages moved** — `/terms` and `/privacy` migrated from `(legal)` to `(marketing)` route group to share the common header/footer
- **401 redirect** — Session-expired handler in `api.ts` now redirects to `/login` instead of `/`
- **manifest.json** — Updated `start_url` to `/app`, added enhanced description

### Added
- **Adaptive step budget system** — Replaced the hard 10-iteration orchestrator ceiling with an adaptive step budget (default 25). The LLM is now informed when it's running low on steps via a step-budget-aware wrap-up prompt (`orchestrator_wrap_up_steps`). When exhausted, a final LLM synthesis call (`orchestrator_final_synthesis`) produces a coherent summary instead of a static "maximum steps reached" message.
- **Continuation protocol** — When the step limit is reached, the response includes `response_type: "step_limit_reached"` with `steps_used`, `steps_total`, and `continuation_context`. The frontend renders a "Continue analysis" button that lets users resume the analysis from where it left off.
- **Per-project and per-request step overrides** — Added `max_orchestrator_steps` column to the `Project` model and `max_steps` field to the chat request body. Resolution order: request `max_steps` > project `max_orchestrator_steps` > global `max_orchestrator_iterations`.
- **Consistent sub-agent iteration limits** — `KnowledgeAgent` and `InvestigationAgent` now use `settings.max_knowledge_iterations` and `settings.max_investigation_iterations` instead of hardcoded class constants. `MAX_SUB_AGENT_RETRIES` in the orchestrator uses `settings.max_sub_agent_retries`.
- **Orchestrator prompt efficiency guideline** — Added a tool-usage efficiency guideline to the orchestrator system prompt encouraging the LLM to combine related questions and parallelize independent tool calls.

### Fixed
- **Email service security and reliability hardening** (`backend/app/services/email_service.py`) — Fixed HTML injection vulnerability: all user-provided values (`display_name`, `project_name`, `inviter_name`, etc.) are now HTML-escaped via `html.escape()` before interpolation into email templates. Added retry with exponential backoff (1s, 2s, 4s) for transient Resend errors (429 rate-limit, 500 server error), max 3 retries. Moved `resend.api_key` assignment from every `_send()` call to `__init__()`. Email send results now log the Resend email ID for traceability. Added category tags (`welcome`, `invite`, `invite-accepted`) for Resend dashboard analytics.
- **ARQ worker crash** — `run_db_index` and `run_code_db_sync` worker tasks referenced non-existent service methods (`set_indexing_status_standalone`, `index_connection`, `run_sync_standalone`). Rewrote both to use `DbIndexPipeline` and `CodeDbSyncPipeline` with proper session management. Fixes #128
- **ReadinessBanner stale state** — Banner showing "index outdated" from a previous project was never cleared on project switch. Now resets `staleInfo` to null when the new project is not stale. Fixes #129
- **WrongDataModal empty connection_id** — Investigation form sent `connection_id: ""` when no DB connection was selected, causing 422 errors. Now validates connection and shows user-friendly toast. Fixes #130
- **useGlobalEvents null workflow_id crash** — `toLogEntry` called `.slice()` on potentially null `workflow_id`, crashing SSE event processing. Added null-safe fallback. Fixes #131
- **Traceback logging in task callbacks** — 5 files passed exception instances to `exc_info=` in asyncio task done callbacks where `sys.exc_info()` is empty. Changed to explicit `(type, value, traceback)` tuples for reliable stack traces. Fixes #132
- **chat.py missing ConnectionConfig import** — Added `TYPE_CHECKING` import for `ConnectionConfig`, resolving ruff F821 and mypy name-defined errors. Fixes #133
- **Ruff lint violations** — Resolved all E501 (line too long) and I001 (import sorting) across `chat.py`, `task_queue.py`, `main.py`, `email_service.py`. `ruff check app/` now passes clean. Fixes #134
- **Logout state leak** — Sign-out now resets all Zustand stores (app, notes, log, task) preventing previous user's chat messages and project data from persisting in memory. Fixes #135
- **Knowledge agent raw tool fallback** — When max iterations exhausted, fallback now uses the last assistant message instead of raw tool output. Fixes #136
- **task_queue.py mypy regression** — Fixed `exc_info` tuple type by adding explicit None guard on `t.exception()`. Fixes #137
- **SSE premature connected flag** — Removed eager `setConnected(true)` after subscription setup; connected state now only set on first received event. Fixes #138
- **Orchestrator shared SQL state** — Per-request SQL results (`_last_sql_result`) scoped per `workflow_id` to prevent data leakage between concurrent requests. Fixes #139

### Added
- **Design system documentation** (`DESIGN_SYSTEM.md`) — Comprehensive visual guide covering semantic color tokens, typography scale, spacing, border-radius, shadows, icons, button variants, form inputs, cards, modals, tooltips, toasts, status indicators, animations, responsive rules, and accessibility guidelines
- **Frontend design system skill** (`.cursor/skills/frontend-design-system/SKILL.md`) — Cursor agent skill that enforces design system compliance on all future frontend work
- **Celery worker infrastructure** (`backend/app/worker.py`, `backend/app/core/task_queue.py`, `backend/app/core/cache.py`) — Redis-backed task queue with shared cache layer for background job processing

### Changed
- **Full design system migration** (68 frontend files) — Migrated all raw Tailwind palette classes (`zinc-*`, `blue-*`, `red-*`, `emerald-*`, `amber-*`, `purple-*`, etc.) to semantic design tokens (`surface-*`, `text-*`, `border-*`, `accent`, `success`, `error`, `warning`, `info`). Zero raw palette classes remain in component files
- **Typography scale enforcement** — Eliminated all off-scale font sizes: `text-[8px]`/`text-[9px]` → `text-[10px]`, `text-[11.5px]` → `text-[11px]`, `text-[12px]`/`text-[13px]` → `text-sm`, legal page h1 `text-3xl` → `text-2xl`
- **Card/panel border-radius standardization** — All card and panel containers now use `rounded-xl`; form inputs use `rounded-lg`; modals use `rounded-lg`
- **Modal accessibility** — OnboardingWizard now has `role="dialog"`, `aria-modal="true"`, `aria-labelledby`, focus trap, and Escape-to-close. WrongDataModal updated with `aria-labelledby` and correct shadow level
- **Toast styling** — Success/error/info toast variants now use semantic tokens instead of raw palette colors
- **Button focus rings** — ConfirmModal Cancel/Confirm buttons now have `focus-visible:ring` styles
- **Shadow standardization** — Eliminated `shadow-2xl` (modals → `shadow-xl`), `shadow-md` (LogPanel toggle → `shadow-lg`)
- **Batch service refactored** for Celery task queue support with improved error handling

### Fixed
- **Missing ARIA labels** — Added `aria-label` to icon-only buttons in InviteManager, LearningsPanel, ScheduleManager, NoteCard, DashboardBuilder, AccountMenu, LlmModelSelector, and OnboardingWizard
- **Missing `transition-colors`** — Added smooth color transitions to interactive elements in StageProgress, Sidebar, NotificationBell
- **ActionCard `aria-expanded`** — Expand/collapse button now correctly announces its state to screen readers
- **ConfirmModal typing input** — Added `aria-label` for the confirmation phrase input
- **SessionContinuationBanner invalid tokens** — Fixed references to non-existent tokens (`text-text-2`, `bg-border`) → valid semantic tokens
- **Test assertions updated** — VerificationBadge and ConfirmModal tests updated to match semantic token class names

### Added
- **Transactional emails via Resend** (`backend/app/services/email_service.py`) — Three email types: welcome email on registration, invite notification when a project owner invites a collaborator, and acceptance confirmation when an invite is accepted. Uses the Resend Python SDK with `asyncio.to_thread()` for async compatibility. Idempotency keys prevent duplicate sends. Gracefully no-ops when `RESEND_API_KEY` is not configured. New env vars: `RESEND_API_KEY`, `RESEND_FROM_EMAIL`, `APP_URL`
- **Session rotation** (`backend/app/services/session_summarizer.py`) — Automatic context-aware session rotation when chat history approaches the context window limit. Summarizes the old session via LLM, creates a new session with a continuation banner linking back to the original. Frontend `SessionContinuationBanner` component shows the transition. Cost estimate endpoint now includes `rotation_imminent` flag. Configurable via `SESSION_ROTATION_ENABLED`, `SESSION_ROTATION_THRESHOLD_PCT`, `SESSION_ROTATION_SUMMARY_MAX_TOKENS`
- **Context usage tracking in AgentResponse** — `context_usage_pct` field added to `AgentResponse` so the frontend can display how much of the context window has been consumed
- **Connection health auto-refresh** — `ConnectionHealth` component now auto-refreshes status periodically and shows more detailed health info
- **ChatMessage copy-all button** — New button on chat messages to copy the entire message content
- **GeoIP two-tier cache** (`backend/app/services/geoip_cache.py`) — In-memory LRU (100k entries, ~20MB) + SQLite persistent storage (`data/geoip_cache.db`, WAL mode, `WITHOUT ROWID`) for IP geolocation results. Eliminates redundant lookups across requests and survives process restarts. Handles millions of unique IPs. Batch operations deduplicate IPs and use batch SQL reads/writes. Configurable via `GEOIP_CACHE_ENABLED`, `GEOIP_CACHE_DIR`, `GEOIP_MEMORY_CACHE_SIZE` env vars
- **Data Processing meta-tool (`process_data`)** — Orchestrator tool that enriches query results with derived data between query steps. Enables multi-step analysis workflows (e.g., query DB for IPs, convert to countries, filter, aggregate). Supports chaining multiple operations sequentially
- **IP-to-country enrichment (`ip_to_country`)** — Offline GeoIP resolution using `geoip2fast` (MaxMind GeoLite2 database). Converts IP address columns to ISO country codes and country names with no external API calls
- **Phone-to-country enrichment (`phone_to_country`)** — Offline E.164 dialing code prefix resolution (~250 countries/territories) with Canadian area code disambiguation for US/CA differentiation within NANP +1 zone
- **In-memory aggregation (`aggregate_data`)** — Groups enriched data by one or more columns and computes `count`, `count_distinct`, `sum`, `avg`, `min`, `max`, `median`. **Multiple functions per column supported** (e.g., `amount:sum,amount:avg,*:count`). Optional `sort_by` / `order` params for controlling result ordering
- **Row filtering (`filter_data`)** — Post-enrichment row filtering by column value. Supports operators: `eq`, `neq`, `contains`, `not_contains`, `gt`, `gte`, `lt`, `lte`, `in`. Can exclude empty/null values with `exclude_empty`
- **`count_distinct` aggregation** — Counts unique non-null values in a column within each group (e.g., unique users per country)
- **`median` aggregation** — Computes median value for numeric columns within each group
- **GeoIPService** (`backend/app/services/geoip_service.py`) — Singleton service for offline IP geolocation lookups with graceful fallback when the library is unavailable
- **PhoneCountryService** (`backend/app/services/phone_country_service.py`) — Singleton service for offline phone number to country resolution via E.164 dialing codes, including Canadian area code disambiguation
- **DataProcessor** (`backend/app/services/data_processor.py`) — Pluggable data transformation engine that operates on `QueryResult` objects with four operations: `ip_to_country`, `phone_to_country`, `aggregate_data`, `filter_data`
- **Complex pipeline support** — `process_data` registered as a valid stage tool in `QueryPlanner` and `StageExecutor` for multi-stage queries (up to 10 stages). Stage executor parses structured JSON from `input_context` with fallback heuristics and emits fine-grained progress events
- **Sequential guard for `process_data`** — When `process_data` appears among parallel tool calls, the orchestrator forces sequential execution to prevent race conditions on shared `_last_sql_result` state
- **Aggregation visualization** — VizAgent is automatically triggered after `aggregate_data` to produce charts/tables for aggregated results
- **Cross-message enriched data persistence** — Enriched `QueryResult` survives across conversation turns for 5 minutes, enabling follow-up questions without re-running the full enrichment pipeline
- **Orchestrator iteration limit raised to 10** — Supports complex multi-enrichment workflows (e.g., dual-query call+SMS analysis with ip_to_country + phone_to_country + aggregate_data for each)

### Fixed
- **Google OAuth 403 on cross-origin** — CSRF double-submit cookie check in `/api/auth/google` now skips verification when the cookie is absent (cross-origin setup where frontend and API are on different domains). The nonce parameter already provides replay protection for the programmatic GIS callback flow
- **Heroku backup skip** — `BackupManager` now detects Heroku (`DYNO` env var) and skips `pg_dump` for managed Postgres, recommending `heroku pg:backups` instead
- **Noisy orchestrator context messages** — Replaced verbose SSE "thinking" events for context usage with quieter log-level messages to reduce UI clutter
- **LLM error formatting** — Improved error message formatting in LLM error classes
- **Registration race condition** — Concurrent duplicate email registrations now caught by DB `IntegrityError` and returned as 409 instead of 500
- **Invite accept commit on early return** — `accept_invite` now commits invite status change when user is already a project member, preventing the update from being silently rolled back
- **PATCH project response missing user_role** — `update_project` now returns a full `ProjectResponse` with `user_role` instead of the raw ORM object
- **Chat feedback learning trigger** — Negative feedback learning now triggers based on the clamped rating value instead of the raw request value, ensuring ratings like -2 or -5 still fire the learning pipeline
- **Reconnect handler connection leak** — `reconnect_connection` now always calls `connector.disconnect()` in a `finally` block, preventing connection/tunnel leaks on successful health checks
- **MCP connector TypeError on health check** — Reconnect and test-connection endpoints now gracefully handle MCP connections that don't support the `DatabaseAdapter` interface
- **Session rename title validation** — `SessionUpdate.title` now enforces `min_length=1` and `max_length=255` to prevent empty or oversized session titles
- **useRestoreState access detection** — `isAccessError` now detects permission errors by matching actual API error messages instead of just HTTP status code strings
- **Missing model imports** — Added 5 missing models (`BatchQuery`, `DataBenchmark`, `Dashboard`, `DataValidationFeedback`/`DataInvestigation`, `SessionNote`) to `models/__init__.py` for consistent mapper registration
- **Integration test auth for /health/modules** — Tests for the authenticated `GET /api/health/modules` endpoint now use `auth_client` instead of unauthenticated `client`
- **Performance smoke test limit for external API** — `test_models_list_latency` now uses a 2-second limit appropriate for the external OpenRouter API call instead of the 300ms internal-only limit
- **Mobile sidebar missing Dashboards** — Added Dashboards section to mobile sidebar drawer, matching desktop feature parity
- **DashboardBuilder JSON.parse crash** — Wrapped `visualization_json` parse in try/catch to prevent builder crash on malformed data
- **Investigation IDOR** — `get_investigation` and `confirm-fix` endpoints now verify the investigation's connection belongs to the requested project, preventing cross-project data access
- **SQL safety guard bypass** — UPDATE pattern now matches qualified table names (`schema.table`, `"schema"."table"`) and added MERGE/UPSERT DML patterns to read-only guard
- **Backend container runs as root** — Dockerfile.backend now creates a non-root `appuser` and runs the application with reduced privileges
- **Auth store localStorage consistency** — `storeAuth` now uses the safe-storage module matching the rest of the auth store, preventing partial state on Safari private mode
- **Pipeline end event not emitted** — Complex query and pipeline resume paths now emit `pipeline_end` event, preventing SSE streams from hanging indefinitely
- **SQL agent connector leak** — Connector cache now capped at 32 entries with LRU eviction and stale connector detection, preventing unbounded connection growth
- **Session title generation MissingGreenlet** — `generate_session_title` now uses explicit async query instead of triggering lazy-loaded relationship
- **Chat search LIKE injection** — Search term `%`, `_`, `\` characters now escaped before building LIKE pattern
- **WebSocket error information leak** — Error handler now sends generic message instead of raw exception string
- **SSE event regex mismatch** — Frontend SSE parser now matches hyphenated event names (e.g., `pipeline-end`)
- **ChatInput max length mismatch** — Frontend char limit raised from 4000 to 20000 to match backend
- **ChatMessage note state not reactive** — Note saved indicator now uses reactive Zustand subscription
- **Learning IDOR** — `update_learning` now verifies ownership before mutating, preventing cross-connection learning edits
- **MongoDB URI credential encoding** — Username and password now URL-encoded with `quote_plus` to handle special characters
- **SSH tunnel race condition** — Per-key asyncio locks prevent concurrent tunnel creation for the same config
- **ClickHouse password in process list** — Exec templates now pass password via environment variable instead of CLI argument
- **SSH key delete without user_id** — `delete()` now called with `user_id` for ownership verification consistency
- **Schedule pagination** — `list_schedules` and `get_history` endpoints now accept `skip`/`limit` query params
- **Alert conditions validation** — `alert_conditions` JSON validated as array with max_length; `notification_channels` capped
- **Result summary size cap** — Schedule run results truncated to 50 rows if JSON exceeds 1MB
- **Benchmark query unbounded** — `get_all_for_connection` now limited to 500 results
- **OpenRouter model fetch contention** — Double-check locking pattern reduces lock contention during cache misses
- **Connection service default limit** — `list_by_project` default reduced from 2000 to 200
- **Test connection error sanitization** — Error messages truncated to 500 chars to prevent internal detail leaks
- **Input validation hardening** — Added `max_length` to `LearningUpdate.lesson`, `SshKeyCreate.passphrase`, `mcp_env` size limits
- **Orchestrator fire-and-forget warning** — `ensure_future` callback now retrieves exceptions to suppress "Task exception was never retrieved" warnings
- **Default rules protection** — Default rules (system-generated) now return 403 on update/delete attempts, preventing accidental corruption
- **Shared notes access broken** — `get_note` and `execute_note` now use `_require_note_access` which allows project members to access shared notes (previously always returned 403)
- **NoteCard comment editing for non-owners** — Comment section now read-only for non-owners, preventing guaranteed 403 failures
- **Viz endpoint DoS** — `RenderRequest` rows capped at 10K, `ExportRequest` at 50K, columns at 500 to prevent server OOM
- **Dashboard update/delete membership check** — Both endpoints now verify project membership before checking creator ownership
- **Session notes unbounded queries** — `_find_similar` capped at 100 candidates, `get_notes_for_context` capped at 200 with 50-note default return
- **Rules rate limiting** — Added rate limits to `list_rules` (60/min) and `update_rule` (20/min)
- **Dashboard refresh parallelized** — `handleRefreshAll` now uses `Promise.allSettled` instead of sequential awaits
- **DashboardBuilder noteMap memoization** — `noteMap` wrapped in `useMemo` to prevent needless re-renders
- **Frontend input maxLength** — Added maxLength to RulesManager name/content, DashboardBuilder title inputs
- **ChartRenderer unknown type fallback** — Shows descriptive message instead of blank rectangle for unsupported chart types

### Security
- **Auth register error sanitization** — Register endpoint no longer exposes internal ValueError messages; returns static "already exists" message while logging details server-side
- **Rate limits on write endpoints** — Added rate limits to 7 previously unprotected mutation endpoints (PATCH projects, PATCH/DELETE sessions, generate-title, feedback, mark notification read, delete SSH key)
- **Probe service SQL injection hardening** — Tightened `_VALID_TABLE_RE` regex to reject quote characters; added `_quote_identifier()` with proper double-quote escaping per SQL standard
- **WebSocket input validation** — Chat WebSocket handler now validates incoming JSON with `WsChatMessage` Pydantic model (enforces message length, provider/model max_length)
- **Credentials cleanup** — Deleted local `notes.md` containing plaintext DB password and SSH private key (never committed to git history)

### Fixed
- **LLM health checks activated** — `start_health_checks()` now called on app startup; failed providers auto-marked unhealthy and skipped in fallback chain until recovered
- **Connector query result row cap** — All 4 DB connectors now cap results at 10,000 rows with `truncated` flag, preventing OOM on large result sets
- **useRestoreState race condition** — Sequence counter prevents stale restore data from overwriting user's active project selection during rapid switching
- **Misleading reconnect banner** — ChatPanel connection-down banner now says "Click Retry to reconnect" instead of the inaccurate "Attempting reconnect..."
- **Form input length limits** — Added maxLength to all text inputs in OnboardingWizard and ConnectionSelector (hosts, ports, credentials, URLs, commands)
- **Connector query timeout** — All connectors now use `settings.query_timeout_seconds` (default 30s) instead of hardcoded 120s
- **Workflow tracker synchronization** — `subscribe()` and `unsubscribe()` now async and acquire `_lock`, matching `_broadcast`'s locking discipline
- **Error boundary logging** — Both ErrorBoundary and SectionErrorBoundary now log caught errors with component stack via `componentDidCatch`
- **WebSocket token usage tracking** — WebSocket chat path now records LLM token usage via UsageService, matching HTTP `/ask` and `/ask/stream` endpoints (costs were previously untracked for WS users)
- **Toast notification cap** — Toasts limited to 5 max; oldest evicted when exceeded (prevents screen flooding during network failures)
- **Unbounded message loading** — `ChatService.get_session()` no longer eagerly loads all messages via `selectinload`; messages now fetched with DB-level LIMIT/OFFSET
- **SSH tunnel cleanup on connection delete** — `ConnectionService.delete()` now closes associated SSH tunnels across all connector types, preventing tunnel accumulation
- **localStorage Safari compatibility** — All localStorage access across 9 files wrapped in try/catch to prevent crashes in Safari private browsing mode
- **JWT expiry zombie state** — `scheduleRefresh` now triggers immediate logout with toast when token is already expired, instead of silently returning
- **WrongDataModal focus trap** — Tab key now cycles within the modal when open, preventing keyboard users from tabbing into background content
- **SSE stream deduplication** — `ConnectionHealth` components now use a shared event bus instead of each opening its own SSE stream to `/workflows/events`
- **Connector pool leak** — All 4 DB connectors (Postgres, MySQL, MongoDB, ClickHouse) now close existing pool/client in `connect()` before creating new ones, preventing connection leaks on repeated connect calls
- **Silent exceptions in sql_agent.py** — Added `logger.debug(exc_info=True)` to 13 previously silent `except` blocks in context-loading helpers, making failures diagnosable from logs
- **ConnectionHealth loading state** — Component now shows pulsing indicator during initial health check instead of immediately displaying "unknown" status
- **Accessibility** — Added `aria-label` attributes to 3 inputs in `ClarificationCard` and `MetricCatalogPanel` that only had placeholder text

### Added
- **Frontend API retry** — GET/HEAD requests automatically retry up to 2 times on network errors and 502/503/504 with exponential backoff; mutation methods (POST/PATCH/DELETE) never retry
- **TTLCache utility** — Generic TTL + LRU cache class (`app/core/ttl_cache.py`) with bounded size and time-based expiry
- **Safe storage utility** — `safe-storage.ts` module with try/catch-wrapped localStorage helpers
- **SSE event bus** — Local pub/sub (`broadcastEvent`/`onEvent`) in `sse.ts` for sharing SSE events without duplicate streams
- **Custom 404 page** — Branded `not-found.tsx` with dark theme styling and link back to home
- **Focus refresh** — `useRefreshOnFocus` hook re-fetches projects, connections, and sessions when browser tab regains focus (throttled to once per 30 seconds)

### Performance
- **Agent cache LRU eviction** — `sql_agent` and `knowledge_agent` caches now use TTLCache with max_size=128, preventing unbounded memory growth over long runtimes
- **Lazy-loaded react-markdown** — `ChatMessage.tsx` and `SQLExplainer.tsx` now use `next/dynamic` to load `react-markdown` on demand as a separate chunk

### Changed
- CI coverage threshold raised from 69% to 72%
- **Chat feedback redesign** — Removed quick-action chips, FollowupChips, DataValidationCard, and WrongDataModal from chat messages. Thumbs up/down now record data validation and thumbs down auto-triggers agent investigation in chat
- **Sidebar "+New" redesign** — Moved all "+New" buttons from section content into section header "+" icons that appear only when expanded. Applies to Projects, Connections, Chat History, Rules, Schedules, and Dashboards

### Security
- **KnowledgeAgent cache isolation** — Fixed critical cross-project data leakage where cached knowledge could bleed between projects (single-slot cache → dict keyed by project_id)
- **MCP connection IDOR** — Added project ownership check before using MCP connections in orchestrator
- **SafetyGuard on diagnostic queries** — Investigation agent `run_diagnostic_query` now validates SQL through SafetyGuard before execution
- **SafetyGuard on schedule run-now** — Manual schedule execution now applies the same safety checks as the cron scheduler
- **Rate limiting** — Added rate limits to `/visualizations/render`, `/exploration`, `/semantic-layer`, `/reconciliation`, `/temporal` endpoints

### Fixed
- **Build type error** — Fixed TypeScript build failure in ChatSessionList.tsx: added proper type assertions for metadata fields after Record<string, unknown> migration
- **Health modules auth** — /api/health/modules now requires authentication, preventing unauthenticated infrastructure reconnaissance
- **Session messages pagination** — GET /sessions/{id}/messages now supports limit/offset (default 500, max 2000) to prevent unbounded responses
- **Knowledge cache TTL** — KnowledgeAgent and SQLAgent now expire cached project knowledge after 5 minutes, preventing stale data after DB/schema updates
- **Query timeouts** — MySQL and ClickHouse connectors now enforce 120s query timeout via asyncio.wait_for, preventing pool exhaustion from long-running queries
- **Connector disconnect safety** — All 6 connectors (postgres, mysql, mongodb, clickhouse, mcp, ssh_exec) now use try/finally in disconnect() to always clear handles even when teardown throws
- **Keyboard shortcut conflict** — Removed duplicate Cmd/Ctrl+K handler from ChatInput; ChatSearch now exclusively owns the shortcut
- **Double-submit guards** — ConnectionSelector handleUpdate/handleIndexDb/handleSync and ScheduleManager toggle now prevent duplicate API calls on rapid clicks
- **useRestoreState race** — Added cancellation flag to prevent stale async restore results from overwriting store after unmount or auth change
- **ProjectSelector race** — Added sequence counter to discard out-of-order API responses when rapidly switching projects
- **Health endpoint** — /api/health now verifies DB connectivity (SELECT 1), returns 503 when database is unreachable
- **Graceful shutdown** — Indexing and sync background tasks are now cancelled during app shutdown
- **seedActiveTasks race** — useGlobalEvents checks active flag before writing to store, preventing stale seed after disconnect
- **Markdown image blocking** — ChatMessage and SQLExplainer now block markdown img tags to prevent arbitrary external image requests
- **Suggestion stale closure** — ChatPanel suggestion reset now depends on activeProject?.id, ensuring suggestions reload on project switch
- **ConnectionHealth feedback** — Reconnect failure now shows error toast instead of silently swallowing errors
- **Silent exceptions** — Added debug logging to remaining silent except blocks (WebSocket send, OpenRouter error body, tunnel introspection)
- **Input validation** — Added max_length constraints to ConnectionCreate (10+ fields) and ProjectUpdate (10 fields)
- **localStorage quota safety** — Wrapped localStorage.setItem calls in auth-store and app-store with try/catch to handle QuotaExceededError gracefully
- Recreated backend venv to fix stale shebangs from old project path
- **InsightFeedPanel** now shows "Couldn't load insights" with Retry when API fails (previously showed misleading empty state)
- **DashboardList** now shows "Couldn't load dashboards" with Retry when API fails (previously showed misleading empty state)
- **ConnectionSelector** now shows "No connections yet" empty state when no connections exist
- **VizRenderer** now shows "Visualization data unavailable" instead of rendering nothing when payload is missing
- **SSE stream completion guard** — Chat stream now fires `onError` if server ends without result/error event, preventing stuck loading state
- **DataValidationCard** — Removed premature optimistic `setVerdict` before API confirmation; UI only updates on success
- **AccountMenu** — Added Escape key handler for keyboard dismissal
- **RetryStrategy** — Fixed empty repair hints when COLUMN_NOT_FOUND has no suggested columns
- **Sidebar callbacks** — Replaced 11 inline lambdas with stable useCallback refs to prevent unnecessary child effect re-runs
- **Notes store** — `loadNotes` failure now shows toast error instead of silent empty state
- **Silent exceptions** — Added debug logging to 10+ previously silent `except: pass` blocks across chat, connectors, and agent modules
- **Accessibility** — Added dialog semantics to BatchRunner, aria-labels to icon-only buttons and form inputs across 6 components
- **Performance** — Narrowed Zustand selectors in 17+ components to prevent full-store re-renders
- **test_alembic.py** — use `sys.executable -m alembic` instead of bare `alembic` CLI to avoid picking up system Python outside venv

### Tests
- batch_service.py: 46% -> 100% coverage (9 new tests for execute_batch)
- code_db_sync_service.py: 55% -> 93% coverage (39 new tests — CRUD, status helpers, runtime enrichment, formatting)
- connection_service.py: 69% -> 99% coverage (20 new tests — test_ssh full flow, to_config error paths, update extended fields, pagination)
- project_overview_service.py: 67% -> 93% coverage (24 new tests — save_overview, _split_overview_sections, _hash_section, notes section, edge cases)
- viz/export.py: 68% -> 100% (xlsx export test), viz/utils.py: 83% -> 100% (serialize_value edge cases)
- agent_learning_service.py: 66% -> 87% (53 new tests — CRUD, fuzzy dedup, decay, compile_prompt, priority score)
- benchmark_service.py: 66% -> 100% (24 new tests — find/create/confirm/flag_stale, normalize, edge cases)
- db_index_service.py: 69% -> 100% (48 new tests — upsert, delete, index_age, is_stale, indexing_status, detail edge cases)
- Overall backend coverage: 68.78% -> 72.63%

### Added
- Open-source repository documentation (CONTRIBUTING, ARCHITECTURE, API, etc.)
- GitHub issue templates and PR template
- MIT License
- **Foundation Layer: Data Graph** — unified metrics registry with auto-discovery from DB index, relationship mapping, and graph queries (`/api/data-graph/`)
- **Foundation Layer: Insight Memory** — persistent store for discovered findings with lifecycle management (active → confirmed/dismissed/resolved), deduplication, and confidence decay (`/api/insights/`)
- **Foundation Layer: Trust Layer** — confidence scoring, provenance tracking, and freshness labels for every insight (`TrustService`, `TrustedInsight`)
- New models: `MetricDefinition`, `MetricRelationship`, `InsightRecord`, `TrustScore`
- Frontend `InsightFeedPanel` component with severity filtering, confidence badges, and insight lifecycle actions (confirm/dismiss/resolve/investigate)
- **Autonomous Insight Feed Agent** — proactive data source scanning, auto-discovers trends/outliers/patterns from DB index, LLM-powered deep analysis, stores findings in Memory Layer (`InsightFeedAgent`, `/api/feed/`)
- **Anomaly Intelligence Engine** — upgrades `DataSanityChecker` with root cause analysis, business impact scoring, severity classification, recommended actions, and confidence. Replaces basic warning text with rich `AnomalyReport` objects (`AnomalyIntelligenceEngine`, `AnomalyReportCard`)
- New API endpoints: `POST /api/data-validation/anomaly-analysis` (ad-hoc analysis), `POST /api/data-validation/anomaly-scan/{connection_id}` (table-level scan)
- SQL Agent now automatically stores critical/warning anomalies as insight records in Memory Layer
- Probe Service enriched with anomaly intelligence reports per table
- Frontend `AnomalyReportCard` component with expandable root cause, impact, and action details
- **Opportunity Detector** — finds high-performing segments, conversion gaps, undermonetized users, and growth-potential channels with impact estimates (`OpportunityDetector`, `OpportunityCard`)
- New API endpoint: `POST /api/feed/{project_id}/opportunities/{connection_id}` (opportunity scan with auto-store to insights)
- **Loss Detector** — finds revenue leaks, funnel drop-offs, spend inefficiency, declining trends, and high-churn segments with monetary quantification (`LossDetector`, `LossReportCard`)
- New API endpoint: `POST /api/feed/{project_id}/losses/{connection_id}` (loss scan with auto-store to insights)
- **Insight → Action Engine** — transforms every insight (anomaly, opportunity, loss) into a concrete recommended action with expected impact %, priority, effort, prerequisites, and risks (`ActionEngine`, `ActionRecommendation`, `ActionCard`)
- **Cross-Source Reconciliation Engine** — compares data between two connections: row counts, aggregate values, schemas, and key overlap. Detects missing records, value mismatches, schema divergence. Stores critical discrepancies as insights. (`ReconciliationEngine`, `ReconciliationCard`, `/api/reconciliation/`)
- **Semantic Layer Auto-Build** — auto-discovers metrics from DB index entries, infers aggregation (SUM/COUNT/AVG), units, and categories, normalizes across connections via canonical name mapping (70+ business metric aliases), and links equivalent metrics in the Data Graph. Browsable metric catalog with search and category filters. (`SemanticLayerService`, `MetricCatalogPanel`, `/api/semantic-layer/`)
- **Query-less Exploration** — autonomous investigation engine: user says "What's wrong?" and the system scans insights, anomalies, opportunities, losses, reconciliation discrepancies, and data health to compile a prioritized investigation report with findings sorted by severity. (`ExplorationEngine`, `ExplorationReport`, `POST /api/explore/`)
- **Temporal Intelligence Engine** — pure-Python time series analysis: linear trend detection with R² fit quality, seasonality detection via autocorrelation on detrended data (weekly/monthly/quarterly/yearly), temporal anomaly detection adjusted for trend, and cross-series lag/lead detection via cross-correlation. (`TemporalIntelligenceService`, `TemporalReport`, `/api/temporal/`)
- New API endpoint: `GET /api/insights/{project_id}/actions` (generate prioritized action recommendations from active insights)
- BACKLOG.md for iterative development tracking

### Fixed
- **Sidebar popup overflow** — NotificationBell dropdown, AccountMenu, and Tooltip now render via React portals (`PopoverPortal`) to escape sidebar `overflow-hidden`, preventing clipping on desktop collapsed/expanded states
- **Charts missing in Saved Queries** — NoteCard now renders `VizRenderer` (bar/line/pie/scatter charts) from `visualization_json` in a collapsible "Chart" section
- **Refresh-to-chat** — Clicking "Refresh" on a saved query now posts the refreshed result as a message in the currently active chat session (with `[Refreshed]` prefix)
- **Critical: Router prefix duplication** — Sprint 1 routes (reconciliation, semantic-layer, explore, temporal) had double-prefixed paths (e.g. `/api/reconciliation/reconciliation/...`) causing 404s from frontend. Removed redundant router-level prefix.
- **Security: Cross-project insight access** — confirm/dismiss/resolve insight endpoints now verify the insight belongs to the target project before mutation, preventing cross-project data manipulation.
- **Feed API empty responses** — `scan_opportunities` and `scan_losses` now return `insights_stored: 0` when no DB entries exist, matching frontend DTO expectations.
- **Next.js viewport metadata deprecation** — moved `themeColor` and `viewport` from `metadata` export to proper `viewport` export per Next.js 15 API, eliminating build warnings.
- **Float conversion safety** — added `_safe_float` utility in action_engine and exploration_engine to handle `None`, non-numeric, and string confidence values without crashing.
- **Reconciliation schema handling** — `reconcile_schemas` now handles `None` column lists gracefully with `set(schema.get(table) or [])`.
- **Feed HTTPException consistency** — replaced inline `from fastapi import HTTPException` with top-level import and keyword args for consistency.

### Changed
- Test coverage increased from 68.90% to 71.03%
- Added integration tests for Sprint 1 route path reachability (reconciliation, semantic-layer, explore, temporal)
- Added integration test for cross-project insight access prevention
- Added unit tests for `_safe_float` edge cases and `None`/non-numeric confidence handling

## [0.10.0] - 2026-03-22

### Security
- Path traversal protection via `validate_safe_id` on filesystem-facing params
- Project creation uniqueness check (owner_id + name) returns 409 on duplicates
- Audit logging on auth routes, repo mutations, and data validation
- SQL identifier quoting in probe_service to prevent injection
- Rate limiting on all mutating endpoints
- Security headers middleware (X-Content-Type-Options, X-Frame-Options, etc.)
- Command injection fix in subprocess calls
- Input validation with Pydantic Literal types across all routes

### Fixed
- VectorStore shutdown cleanup (close ChromaDB client)
- Stale git lock file cleanup on app shutdown
- Silent exception handling replaced with proper logging across 15+ locations
- Race condition in VectorStore collection access (threading.Lock)
- Invite acceptance atomicity with begin_nested transaction
- MongoDB connection timeout configuration
- N+1 queries in project_overview_service and batch_service
- Frontend unmounted setState guards on 18+ components
- Silent .catch blocks replaced with toast notifications

### Added
- Configurable timeouts: model_cache_ttl, health_degraded_latency, ssh_connect/command
- Database pool_timeout configuration
- Pagination on list_repositories endpoint
- aria-live regions for streaming chat and batch progress
- Cmd/Ctrl+K keyboard shortcut to focus chat input
- React.memo + useCallback optimization on ChatSessionList
- DataTable row cap (500) with "show all" toggle
- LearningsPanel item cap (200)
- DataValidationCard maxLength + aria-label on inputs
- Accessibility: skip-to-content, focus traps, keyboard navigation

### Changed
- Background task error logging via add_done_callback
- Moved hardcoded timeouts to centralized config

## [0.1.0] - 2026-03-15

### Added
- Initial release
- Multi-agent chat system (Orchestrator, SQL, Knowledge, Viz agents)
- Database connectors (PostgreSQL, MySQL, ClickHouse, MongoDB)
- SSH tunnel support
- Git repository indexing with ChromaDB RAG
- Natural language to SQL translation
- Automatic visualization (tables, charts)
- Batch query execution
- Dashboard creation
- Custom validation rules
- Team collaboration with invitations
- Google OAuth integration
- Onboarding wizard
- Demo project setup
