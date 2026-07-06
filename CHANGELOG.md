# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Fixed — W5 intelligence-remediation: code↔DB trust signals (2026-07-06, branch `worktree-intelligence-remediation`)

Wave 5 wave-closer (T11). All 10 prior W5 tasks committed; ruff/mypy clean; unit+integration suite green at 78% coverage (≥72% gate); retrieval-eval gate green (18/18); single alembic head `c9b8a7f6e5d4`.

- **SYNC-L3 (git freshness states AHEAD/BEHIND/DIVERGED)** — `classify_freshness()` in `git_tracker.py` uses `iter_commits` to compute exact ahead/behind counts and returns `GitFreshness(FRESH|AHEAD|BEHIND|DIVERGED)`. `KnowledgeFreshnessService.evaluate()` maps each state to a distinct warning with the commit count; DIVERGED is severity `critical`. `git_freshness_fetch_origin` flag (default `false`) gates a remote fetch for cross-machine accuracy. Env key: `GIT_FRESHNESS_FETCH_ORIGIN`.
- **SYNC-L2 (table-ref attribution)** — `EntityExtractor` tracks which SQL statement each column reference appears in; phantom cross-table attributions eliminated. Noise-only SQL tokens (literals, parameters, operators) are stripped before attribution. Confidence on attributed refs defaults to L2 rather than the weaker L1.
- **SYNC-L5 (deterministic drift set-diff)** — `CodeDbSyncPipeline._compute_column_drift()` produces a stable sorted `{code_only, db_only, matched}` diff (case-normalised). When both sides are non-empty and drift exists, `sync_status` is set to `"mismatch"` deterministically, overriding any LLM opinion. Diff persisted to `CodeDbSync.column_mismatch_json` (migration `c9b8a7f6e5d4`).
- **SYNC-L6 (schema-qualified ORM matching)** — sync loaders and `get_table_sync` now match on `(schema, table)` pair when the ORM model carries a qualified table name (e.g. `public.orders`); unqualified model names still work against the default schema.
- **SYNC-L7 (bare-suffix keying)** — all sync loaders and `get_table_sync` normalise keys to bare table name (no schema prefix) before cache lookup; eliminates duplicate and missed cache hits when some code paths pass qualified names.
- **SYNC-L8 (code-graph warning gate)** — the "code graph is empty" freshness warning is gated on `lineage_enabled OR clustering_enabled` (the actual graph consumers) rather than `code_graph_enabled` (the indexing flag); operators who index the graph but don't enable lineage/clustering no longer receive spurious empty-graph warnings.
- **SYNC-L9 (op-kind word-boundary)** — HTTP operation-kind extraction in `graph_db_bridge.py` uses word-boundary regex (`\bget\b`, `\bpost\b`, etc.) to prevent false matches (e.g. `forget` → `get`). Low-confidence name-inference now emits a debug log rather than a noisy warning.
- **Low-batch L11–L14** — `_coerce_confidence` rounds float strings before clamping (`"4.5"→4`, `"4.7"→5`) instead of silently defaulting to 3; `CallerRef.depth_estimated=True` sentinel replaces fabricated depth integers; enum-table link matching uses token word-boundary (not raw substring) so `reorder_reason` no longer spuriously links to table `order`; DB-index TTL is read from `settings.db_index_ttl_hours` (default 24, env key `DB_INDEX_TTL_HOURS`).

**Note:** SYNC-L1 was delivered in W1; SYNC-L4 (table-name inflector) was delivered in W6; the W5 set covers L2/L3/L5/L6/L7/L8/L9 + low-batch L11–L14.

### Fixed — W3 intelligence-remediation: orchestrator termination + path unification (2026-07-06, branch `worktree-intelligence-remediation`)

Wave 3 wave-closer (T14). All 13 prior W3 tasks committed; ruff/mypy clean; unit+integration suite green at 78% coverage (≥72% gate); retrieval-eval gate green (18/18).

- **ORCH-T01 (live step budget)** — `max_orchestrator_iterations` is now a live termination signal: the wrap-up phase is entered as soon as the counter is reached, not only after a post-loop check; no extra LLM call is wasted on an already-budget-exceeded loop body.
- **ORCH-T02 (wrap-up gate)** — the synthesis/wrap-up phase is only entered when at least one data retrieval has been attempted; static-prompt-only turns no longer trigger a premature "composing answer" emission.
- **ORCH-T03 (no-tool re-prompt)** — on a data route, if the model emits a planning/thinking turn with no tool calls and no data yet, the orchestrator re-prompts once to keep the loop alive; bounded to one shot (`reprompted_no_data` flag) — no infinite loop.
- **ORCH-A03 (routing metrics)** — `route`, `complexity`, and `estimated_queries` from the unified router are now recorded into `MetricsCollector` on every turn; `complexity` is no longer `"unknown"` in metrics/Prometheus.
- **ORCH-PR01 (prompt de-dup)** — duplicate reconciliation guidance removed from the orchestrator system prompt; stale self-description updated; net ~200-token reduction per request.
- **ORCH-CP01 (cue precision)** — `ContextPlanner` cue matching upgraded to word-boundary regex; over-broad single-letter cues removed; false-positive cue matches on unrelated words eliminated.
- **ORCH-P01 (validation scope)** — `StageValidator` now scopes data-quality criteria to data stages only; text/knowledge stages require a non-empty summary instead; prevents false failures on non-SQL stages.
- **ORCH-P02/P03 (planner/replan fixes)** — trivial single-step plans are bounced back for replanning; `degraded` flag is propagated across replan so downstream stages know quality was compromised; the failed tool name is stored in learnings for root-cause analysis.
- **ORCH-RP01/RP02 (cohort_window params)** — `cohort_window` params are unified across the planner and executor; both use the same type/default; no more implicit coercion mismatch.
- **ORCH-R01 / ORCH-P04 (non-DB pipeline)** — complex non-DB questions (knowledge, git, MCP) are now routed through the full multi-stage pipeline when complexity warrants it (`use_complex_pipeline`), not silently dropped to the single-loop path. Source-aware quick-plan fallback avoids a DB-specific stage appearing in a knowledge-only plan.
- **ORCH-A01 (path unification — ResultValidation on both paths)** — `ResultValidation` (DataGate + result gate + reconcile) is now wired into the pipeline SQL stage as well as the single-query path; impossible values are caught on both code paths.
- **ORCH-A02 (path unification — AnswerQualityGate on pipeline)** — `AnswerQualityGate.evaluate` is now called on the pipeline final answer, matching the single-loop path; answer quality is enforced regardless of which execution path produced the result. Pipeline answers may now surface `response_type: "step_limit_reached"` when the pipeline exhausts its budget (see API.md).
- **ORCH-P04 / pipeline reconciliation** — SQL reconciliation note injected into pipeline synthesis prompt so the LLM is aware of all prior SQL results when composing the final pipeline answer (parity with the single-loop path).
- **Low-batch fixes (A05/V02/PR03/R03/R04)** — orchestrator low-batch edge cases resolved: empty-result SQL no longer silently swallows the answer; viz-stage failure degrades gracefully; prompt refs cleaned up; router/replan boundary conditions tightened.

### Changed — W6 intelligence-remediation: code-graph correctness + flag flips (2026-07-06, branch `worktree-intelligence-remediation`)

Wave 6 wave-closer (T11). All code-graph correctness fixes (T1–T10) landed; graph-quality benchmark PASS; `code_graph_enabled` and `lineage_enabled` flipped to default-on.

- **CODEIDX-C4 (cross-file CALLS re-resolve)** — incremental re-index correctly re-resolves cross-file CALLS edges after any file in the reverse-dependency set changes; callers are no longer orphaned after incremental updates.
- **CODEIDX-C7 (UID line-drop)** — symbol UIDs use `{lang}:{file}:{kind}:{name}` format (no trailing line number); UIDs are stable across reformats and incremental rebuilds.
- **CODEIDX-C6 (EXTENDS heritage)** — multi-base Python EXTENDS edges are emitted for all explicit base classes; `Worker(Base)` produces a `Worker → Base` edge even when Base is defined in another file.
- **CODEIDX-C5 (JS/TS symbols)** — TypeScript/JavaScript arrow-function components are extracted as `kind=function`; module-level `const` exports are extracted as `kind=variable`; both produce stable UIDs.
- **CODEIDX-C8 (ORM Mapped)** — SQLAlchemy `Mapped[T]` and `mapped_column` annotations are treated as typed columns rather than class-body CALLS; no phantom call edges from ORM model definitions.
- **CODEIDX-C17 (checkpoint gate)** — pipeline stage `graph_build` is skipped (checkpoint-resume) when the graph has already been written to DB; avoids redundant CPU-heavy re-parse on resume.
- **CODEIDX-C9 (shared ignore + prune-by-degree)** — `shared_ignore.py` provides a single `is_ignored_path()` function consumed by both the pipeline and the benchmark; zero-degree symbols (no edges, private-prefixed) are pruned to reduce graph noise.
- **CODEIDX-C15 (enum-via-annotation)** — Python `StrEnum`/`IntEnum` subclass bodies are extracted as `kind=enum`; members are not emitted as spurious `variable` symbols.
- **CODEIDX-C16 (table-name inflector / SYNC-L4)** — ORM `__tablename__` or `declared_attr` is resolved first; falls back to the pluralized snake-case class name only when absent; lineage `code→DB` mapping is no longer wrong for non-default table names.
- **Graph-quality benchmark** — `app/eval/graph_benchmark.py` (`run_graph_benchmark() → GraphBenchmarkResult`) runs the fixture repo through the full AST→graph pipeline and asserts ≥7 symbols, ≥1 CALLS, ≥1 EXTENDS, ≥1 IMPORTS. Gate command: `python -m app.eval.graph_benchmark` (exit 0 = PASS). Benchmark PASS result: `symbols=7 CALLS=2 EXTENDS=1 IMPORTS=1`.
- **Flag flips (benchmark-gated)** — `code_graph_enabled` and `lineage_enabled` flipped to `True` (default-on) after the benchmark passed (spec §9, F-ARCH-6). **Deploy note:** `code_graph_enabled=true` enables CPU-heavy tree-sitter AST parsing during repo indexing; allocate ≥2 CPU cores and expect indexing time to increase on large repos (≥50k LOC).

### Added — W2 intelligence-remediation: retrieval + ContextPack wave-closer flag flips (2026-07-06, branch `worktree-intelligence-remediation`)

Wave 2 wave-closer (T15). All retrieval + ContextPack fixes (T1–T14) landed; eval gate green; flags flipped to default-on.

- **C1/C2 (tokenizer/chunk-window)** — knowledge indexer tokenizer aligned to the actual embedding model; chunk window sized correctly so oversized chunks no longer exceed the model's context window silently.
- **C3 (raw-code embedding)** — raw source code is embedded with a dedicated code-embedding path rather than being passed through the prose tokenizer; code retrieval quality improved.
- **R1/R2/R3/R8 (ContextPack hybrid+budget+provenance)** — `ContextPack` assembles a single traceable knowledge context with hybrid retrieval (BM25 + dense RRF), a token-budget cap, and per-chunk provenance metadata surfaced to the orchestrator.
- **R4 (retrieval_degraded signal)** — a `retrieval_degraded` flag is set on `ContextPack` when any retrieval stage falls back; the orchestrator prompt carries the caveat so the LLM knows context may be incomplete.
- **R5 (relevance floor)** — results above `rag_relevance_threshold` (distance > 0.45) are filtered out before entering the ContextPack; tail-noise chunks no longer dilute context.
- **R9/D7 (FK-aware schema retrieval)** — `SchemaRetriever` expands FK neighbours up to one hop so tables joined by a foreign key are co-retrieved even when only one side matches the query.
- **R10 (safety-net floor)** — `sql_agent_safety_net_min_relevance` (default 3) filters low-signal safety-net tables so retrieved + FK-expanded entries are not crowded out.
- **R14 (reranker `.rank`)** — `CrossEncoderReranker` calls `.rank()` when available (sentence-transformers ≥ 3.x) and falls back to `.predict()` for older model versions; both paths produce a sorted `List[Candidate]`.
- **Low batch** — BM25 retrieval batch size tuned to avoid memory spikes on large corpora.
- **Flag flips (gated)** — `reranker_enabled` and `context_planner_enabled` flipped to `True` (default-on) after the retrieval-eval + reranker gate passed (18/18 tests, including `test_harness_oracle_passes_thresholds` at `hit_at_k==1.0` and `test_cross_encoder_uses_rank_when_available`). Wave-gate assertion test `test_w2_flag_flips.py` added.

> ⚠️ **Deploy notes (intelligence remediation — all three apply to this release)**
>
> **1. ChromaDB full reindex required (breaking until completed)**
> The default embedding model changed from `all-MiniLM-L6-v2` (384-dim) to `BAAI/bge-base-en-v1.5` (768-dim, 512-token window) and code chunks now use a dedicated `sym:` prefix path. Existing ChromaDB collections were built with the old model and are **dimension-mismatched**; dense retrieval degrades to BM25-only (or returns empty) until the collections are rebuilt. This is graceful — the system will not crash — but retrieval quality will be degraded.
> **Operator action required after deploy:**
> ```python
> # In a management shell / Django-equivalent REPL or migration script:
> from app.services.embedding_reindex import queue_embedding_reindex
> import asyncio
> # Pass all active project IDs, or trigger a full repo re-index per project via the UI/API.
> asyncio.run(queue_embedding_reindex(<list_of_all_project_ids>))
> ```
> Alternatively: trigger "Re-index repository" for each project from the project settings UI. Until reindex completes, hybrid retrieval falls back to BM25-only (functional but lower quality).
>
> **2. `code_graph_enabled` + `lineage_enabled` now default-on (CPU-heavy)**
> Both flags flip to `True` in this release (W6). Code-graph indexing is CPU-intensive; recommend ≥2 cores on the worker dyno. Operators who want to defer the CPU cost can set `CODE_GRAPH_ENABLED=false` and `LINEAGE_ENABLED=false` in env until ready.
>
> **3. `reranker_enabled` now default-on — requires image update**
> `reranker_enabled=true` requires `sentence-transformers` + a cross-encoder model (e.g. `cross-encoder/ms-marco-MiniLM-L-6-v2`) in the production image. The flag degrades gracefully to a no-op when the library or model is absent — retrieval still works, just without reranking.

### Fixed — W1 intelligence-remediation: data-quality hardening (2026-07-05, branch `worktree-intelligence-remediation`)

Wave 1 of the intelligence-remediation audit. All 15 tasks committed; ruff/mypy clean; unit+integration suite green at ≥72% coverage.

- **DATA-01 (truncation propagation)** — `DataProcessor` additive aggregations (sum/count/count_distinct) over a row-capped input are flagged as `PARTIAL DATA`; the summary and the agent-facing output both carry the caveat; never silently presented as a complete total.
- **DATA-02/04 (dispatcher/synthesis/pipeline truncation honesty)** — `ToolDispatcher._full_data_hint` now distinguishes truncated from complete datasets; the synthesis path and pipeline result builder propagate the same caveat; LLMs downstream cannot conflate a capped sample with the whole.
- **DATA-03 (SQL-correctness prompt)** — `SQLAgent` system prompt updated with explicit instructions on GROUP BY completeness, COUNT(*) vs COUNT(DISTINCT), and NULL-handling to reduce silent miscounts at the generation step.
- **DATA-05 (phone E.164)** — `PhoneCountryService` now requires E.164 format (`+<country_code><number>`); non-E.164 inputs degrade gracefully with a warning rather than producing a silent wrong-country mapping. User-facing: phone→country enrichment now needs E.164-formatted numbers.
- **DATA-06 (DataGate on single-query path)** — `DataGate.check_query_result()` public method added; wired into `ResultValidation` so impossible values (150% conversion, negative counts) are caught on the direct single-query path, not only inside multi-stage pipelines.
- **DATA-09 (chart nulls)** — Chart-building path guards against null/missing values in series data; nulls are rendered as gaps rather than plotted as zero, preventing silent chart distortion.
- **DATA-16/17 (validator/investigation honesty)** — `AnswerValidator` and `InvestigationAgent` prompts updated: both must declare uncertainty when data is partial, and must not assert completeness when the result set is capped or the investigation is inconclusive.
- **SYNC-L1 (satisfiable required-filter guard)** — `RequiredFilterGuard` degrades gracefully when a required filter is satisfiable but cannot be applied (emits a warning + increments `filter_guard_degrade_total`) instead of blocking the query entirely.
- **DATA-14 (range-scan late rows)** — Regression test confirms `_check_value_ranges` scans the full in-memory result when `data_gate_value_range_sample=0` (default); impossible value in the last row of a 501-row result is caught. Positive-cap behaviour documented as intentional speed/correctness trade-off.
- **DATA-15 (reconciliation rounding tolerance)** — Deferred: fix belongs to `insight_memory.py` (W3-owned file). `xfail` test documents the gap.
- **DATA-18 (duplicate/null-rate false signals)** — `_check_duplicates` minimum sample raised from 3 → 10 rows to avoid false positives on legitimately-sparse tables. Null-rate warnings labelled "advisory, based on sample only" per DATA-22.
- **DATA-19 (COUNT semantics doc)** — `_compute_agg` docstring updated with explicit NULL-handling notes: `count` uses SQL COUNT(*) semantics (includes NULLs); `count_distinct` uses SQL COUNT(DISTINCT col) semantics (excludes NULLs).
- **DATA-20 (unformatted numbers)** — `ToolDispatcher._fmt_cell` static helper added; aggregation output loop now calls it instead of `str(v)`; large integers and Decimal values render with thousands separators (e.g. `1,234,567`).
- **DATA-21 (small-fan-out cartesian)** — `xfail` test documents that `_check_cross_stage_consistency` only warns above `cartesian_multiplier` (default 100×); a 2× fan-out passes silently. Known limitation, no over-engineering.
- **DATA-22 (sampled signals unmarked)** — Null-rate and duplicate-rate warnings now include "sampled" / "advisory, based on sample only" labels so the LLM knows the signal is partial.

### Added — W4 intelligence-remediation: schema-capture depth (2026-07-06, branch `worktree-intelligence-remediation`)

Wave 4 of the intelligence-remediation audit. All 18 tasks committed; ruff/mypy clean; unit+integration suite green at 77% coverage (≥72% gate).

- **DBIDX-D1/D2/D3 (MongoDB native introspection)** — `MongoDBConnector` overrides `distinct_values` and `approx_stats` using native aggregation pipelines (`$group`/`$sortByCount`/`$sample`). Field types are inferred by union-sampling nested documents; `$type` operator maps BSON types to SQL equivalents. `ProbeService` routes `distinct_count` and `sample` through connector methods so Mongo never receives a raw SQL fallback.
- **DBIDX-D4 (ClickHouse sort key)** — `ClickHouseConnector.introspect_schema` reads `system.columns.is_in_sorting_key` and sets `ColumnInfo.is_sort_key`; schema-context renderer surfaces it as `[sort-key]`.
- **DBIDX-D5 (PostgreSQL enum + CHECK constraints)** — `PostgresConnector.introspect_schema` queries `pg_type`/`pg_enum` for enum labels and `information_schema.check_constraints` for per-column CHECK expressions; both land in `ColumnInfo.enum_labels` and `ColumnInfo.check_constraints`.
- **DBIDX-D6 (views + `object_kind`)** — all four connectors (PG, MySQL, ClickHouse, MongoDB) index VIEWs and MATERIALIZED VIEWs alongside base tables; `TableInfo.object_kind` is set to `"table"`, `"view"`, or `"materialized_view"` so query generation knows not to DML a view.
- **DBIDX-D8 (comments + indexes render)** — `_format_table_context` in `DbIndexService` (the default multi-table schema context path) now renders column comments, table/column-level indexes, enum labels, and ClickHouse sort-key markers in the schema block handed to the LLM.
- **DBIDX-D9 (approx_stats persistence)** — `DbIndexService` persists `ColumnInfo.distinct_count`, `null_pct`, `numeric_format`, and `enum_labels` into `DbIndex.column_stats_json` and `DbIndex.column_distinct_values_json` (JSON columns added in W0); gated by `db_index_stats_enabled` (default on). These fields are now available to the schema-context renderer and downstream consumers (R9/D7 handoff).
- **DBIDX-D10 (completeness gate)** — `DbIndexService` emits a deterministic completeness score (0–1) per index run; runs below the threshold are logged as warnings rather than silently accepted; prevents regressions from partial connector failures.
- **DBIDX-D11 (MongoDB field inference)** — MongoDB schema inference samples `mongo_schema_sample_size` (default 100) documents per collection, unions field paths across the sample, and derives `ColumnInfo` entries for nested sub-document paths; wider schemas with optional fields get better coverage.
- **DBIDX-D12 (schema-cache bust)** — `SchemaCacheRegistry` invalidates the 300-second TTL schema cache on explicit re-index or schema-change event so a re-index is immediately visible to the next query agent turn.
- **DBIDX-D14 (reltuples < 0 fix)** — `PostgresConnector` treats `pg_class.reltuples < 0` (un-analyzed tables in PG 13+) as `None` (unknown) rather than surfacing a negative row count that confuses LLM table selection.
- **DBIDX-D15 (LLM cap)** — DB-indexing LLM analysis is capped at `db_index_max_tables_analyzed` (default 500) tables per run; tables beyond the cap receive a deterministic fallback analysis to prevent runaway cost on very wide schemas.
- **DBIDX-D16 (column prompt cap)** — the LLM analysis prompt is capped at `db_index_max_prompt_columns` (default 100) columns per table; excess columns are replaced with a `"(… N more columns)"` note.
- **DBIDX-D17 (ClickHouse freshness)** — ClickHouse connector surfaces table `last_modified` from `system.tables.metadata_modification_time` so `KnowledgeFreshnessService` can detect stale schema without a full re-index.
- **DBIDX-D18 (MongoDB freshness)** — MongoDB connector surfaces collection `last_modified` approximated from `collStats.lastModified` (if present) or `$natural` order sampling so freshness checks work on document stores.
- **Pipeline routed via connector methods** — `ProbeService` dialect-aware dispatch means `sample(n)`, `distinct_count(col)`, and `approx_stats(col)` calls go through each connector's native implementation (T6/T7); no raw SQL fallbacks for MongoDB.

**W4 handoff note (R9/D7):** `ColumnInfo.distinct_values`, `distinct_count`, `numeric_format`, and `enum_labels` are now populated by all connectors and persisted to `DbIndex.column_stats_json` / `column_distinct_values_json`; downstream waves can read these from the index without re-querying the DB.

### Removed — W4 intelligence-remediation: dead-code pruning (2026-07-06, branch `worktree-intelligence-remediation`)

- **DBIDX-D13 (dead `SchemaIndexer`)** — removed `app/knowledge/schema_indexer.py` and its unit test; schema rendering is unified in `DbIndexService` + `_format_table_context` (T13); no runtime path lost coverage.

### Added — W0 intelligence-remediation foundations (2026-07-03, branch `worktree-intelligence-remediation`)

Wave 0 of the intelligence-remediation audit (spec `docs/superpowers/specs/2026-07-03-intelligence-remediation-design.md`).
All 18 tasks committed; ruff/mypy clean; unit+integration suite green at ≥72% coverage.

- **`derive_result` helper** — pure function extracted from `SQLAgent._handle_execute_query`; converts raw connector rows + column list into a `QueryResult`; locks the data-shaping contract for downstream waves.
- **`ResultValidation` façade + `AnswerQualityGate`** — `ResultValidation(data_gate, result_gate, *, reconcile)` composes the three post-query quality checks into one callable; `AnswerQualityGate.evaluate` (async) wraps `AnswerValidator`; both wired into the agent paths.
- **DataGate Decimal/truncation fixes** — `Decimal` values are now `float()`-converted before comparison (was silently skipped → bogus pass); row-level loop `break` replaced with early `continue` so all rows are checked, not just the first suspicious one.
- **C-D schema-capture surface** — `ColumnInfo` gains `object_kind`, `sample_values`, `distinct_count`, `null_pct`; `TableInfo` gains `object_kind`; `SchemaInfo` gains `object_kind`; `DbIndex` model gains `sample_values_json`, `stats_json` columns (Alembic migration `add_dbindex_capture_columns`).
- **`RequestTrace` routing columns + migration** — `approach`, `complexity`, `route_ms` columns added to `RequestTrace` (Alembic migration `add_request_trace_routing_columns`); both migrations chain to a single Alembic head.
- **Chunk metadata + `retrieval_degraded` scaffold** — `ChunkMetadata` dataclass with `source_path`, `heading_path`, `token_count`, `embedding_model`; `retrieval_degraded` flag on `KnowledgeResult`; `KnowledgeFreshnessService` emits `retrieval_degraded_total` counter when flagged.
- **Prometheus counters** — `retrieval_degraded_total`, `datagate_block_total`, `filter_guard_degrade_total` registered in `MetricsCollector`; incremented at the gate call sites.
- **Config defaults hardened** — `max_orchestrator_iterations` default lowered 100→20; `chroma_embedding_model` defaults to `BAAI/bge-base-en-v1.5` (512-token context model); `embedder_max_tokens` default 512.
- **Hotspot decomposition** — `format_query_results`, `format_schema_overview`, `format_table_detail` extracted from `SQLAgent` → `app/agents/result_handler.py`; `_record_request_metrics` extracted from `OrchestratorAgent._run_tool_loop` (partial ORCH-A04; larger decomposition deferred to W3).
- **5 validation-lock tests** — regression tests in `tests/unit/test_validation_locks_w0.py` assert current (known-buggy) behavior for findings RET-R3, SQL-S4, ORCH-A01, VAL-V3, DATA-D2; owning waves must flip assertions when fixing.

### Added — Diagnostics capture (2026-06-30, branch `feat/diagnostics-capture-2026-06-30`)

Make failed queries fully diagnosable after the fact (motivated by the cohort/GROUP BY
incident where the failing SQL, raw DB error and repair-attempt history evaporated). Spec
`docs/superpowers/specs/2026-06-30-diagnostics-capture-design.md`, plan
`docs/superpowers/plans/2026-06-30-diagnostics-capture.md`.

- **`query_failures` table + capture** — every failed/recovered query execution persists its
  full failing SQL, full raw DB error (capped), classified `error_type`, and the complete
  repair-attempt history (`QueryFailure` model + `QueryFailureService`; captured in
  `SQLAgent._handle_execute_query` after the validation loop). Best-effort, off the request
  path, gated by `diagnostics_capture_enabled`. Composes with the GROUP BY classifier:
  `error_type` reads `group_by_violation` and `final_status` shows `recovered` vs `failed`.
- **Sync/background-job flag provenance** — `IndexingRun.meta_json["flags"]` snapshots the
  feature-flag state (git webhook/poll, auto-sync, freshness reconciler, schema-change alerts,
  incremental index) at creation, so "which flag produced this failed run?" is answerable.
- **Self-observability** — the diagnostics layer can no longer fail silently: persistence
  failures increment `diagnostics_persist_failures`, surfaced at `/api/metrics` under
  `diagnostics`.
- **Read API** — owner-gated `GET /api/logs/{project_id}/query-failures` (list + filters) and
  `/query-failures/{id}` (detail with attempts), project-scoped + tenant-isolated; frontend
  analytics client methods added.

Audit note: the existing trace stack (RequestTrace/TraceSpan/ErrorLog/IndexingRun + owner/admin
read APIs + LogsScreen) is mature; verified that SSE backpressure does NOT starve trace
persistence (persistence hooks fire for every event) — no fix needed there.

### Fixed — Orchestrator audit remediation (2026-06-27, branch `fix/orchestrator-audit-remediation-2026-06`)

Remediation of the multi-specialist orchestrator audit (intake → routing → planning →
execution → data acquisition → validation → bad-data/replan loops). TDD throughout
(failing test first); backend suite 4635 passing at 75.39% coverage; ruff/mypy clean;
new `make smoke` startup self-check (6 deterministic tests on the revenue/cohort scenario).

- **CRITICAL — DataGate semantic gate revived.** The advertised LLM-semantic column
  classifier was dead in prod and the keyword heuristic only covered percent/date, so
  impossible values in differently-named columns (e.g. `conversion` 150%) and negative
  counts reached the user. Now token-based classification (snake/camelCase aware, no
  substring false positives like `account`→count / `electric`→ctr), strict bounded-percent
  vs loose signed rates (NRR>100%, deltas, declines allowed), hard-fail on negative counts,
  and the `data_gate_llm_semantics` flag is observable when wired without a classifier.
- **Security — cross-tenant SSE/WS leak closed.** `/ask/stream` and the WS endpoint now
  subscribe to the process-global workflow tracker scoped by `user_id`+project, so a stream
  can no longer relay/latch another user's in-flight workflow events.
- **Correctness/robustness:** budget hard-stop now emits a proper terminal `pipeline_end`;
  the tool loop no longer KeyErrors (and discards the turn) on a duplicate tool-call id;
  history trimming is tool-pair-aware (no orphaned `tool_call`/`tool` → no provider 400);
  the generic error handler returns a typed code instead of raw `str(exc)` (no DSN/host
  leak); `process_data` honors its declared `depends_on` (no scavenging an unrelated
  dataset); deterministic exceptions are no longer retried as transient; replans with
  dangling deps are rejected before wasting the budget; `query_database` truncation is
  surfaced so the LLM doesn't aggregate over a silently-capped set; `row_count` semantics
  are uniform across all four connectors (returned-count + `truncated`).
- **Resource/abuse:** `POST /api/chat/ask` now acquires the `agent_limiter` slot (+timeout),
  closing the only chat entry point that bypassed concurrency/hourly caps; external MCP
  tool calls have a wall-clock timeout; auto-investigation is budget-gated + limiter-bound
  and its verdict is surfaced to the user via a Notification instead of dead-ending.
- **Validation honesty:** AnswerValidator parse failures now respect `answer_validator_fail_closed`
  (were fail-open); planner rejects stages missing `stage_id`/`description` (was an uncaught
  `KeyError` mid-planning) and reports duplicate stage ids clearly.

Remaining lower-severity findings are tracked in `docs/ORCHESTRATOR_AUDIT_2026-06.md`.

### Fixed — Orchestrator audit follow-ups (2026-06-29, branch `fix/orchestrator-audit-followups-2026-06`)

All 21 deferred follow-ups from the orchestrator audit remediated, TDD throughout (one
commit per finding); full unit suite green, ruff/mypy clean. Register:
`docs/ORCHESTRATOR_AUDIT_2026-06.md` (§ Follow-up remediation).

- **Pipeline robustness:** per-pipeline wall-clock budget (`pipeline_max_wall_seconds`) caps
  the compounded retry surface; the unified-loop wall budget is now respected by every
  expensive sub-agent (not just SQL); a `process_data` call batched with a fresh
  `query_database` is deferred so it can't transform the previous turn's stale result; a
  replan that repeats a prior plan (by semantic fingerprint) is rejected instead of burning
  the budget; resume has an in-process duplicate-run guard and sample-only restores are
  flagged `truncated` so a sample is never treated as the full dataset.
- **Query/validation:** transient DB connection errors retry (same query + backoff) rather
  than fail immediately; a clean empty result is returned as success (not a failure) and the
  repairer won't re-run an equivalent query; the dynamic per-query timeout reaches every
  connector's `execute_query` (Mongo gains one); DataGate's value-range hard check scans the
  full in-memory result by default.
- **Routing/recovery:** a question mis-routed `direct` can escape to the tool loop via a
  model-emitted sentinel (router prompt hardened); the router honors a configured
  `router_model` and `estimated_queries` now influences pipeline selection.
- **MCP:** `call_tool` returns a structured `MCPToolCallResult` so a tool-level `isError` is
  surfaced to the LLM instead of read as data.
- **Context/observability:** a hard per-result ceiling caps a fresh tool result at insertion;
  `_workflow_owners` is FIFO-bounded and `_stream_tokens` event count is capped; robust router
  JSON extraction (nested/trailing-safe) with a larger token cap.
- **Quality/correctness:** entity-info lookups are attributed as sources; auto-investigation
  gains `auto_investigate_budget_enforcement_enabled`; reconciliation rejects non-finite
  numbers; `process_data` defaults `min_rows=0`; dependency serialization into prompts is
  field-capped; cross-stage/business-rule checks documented as intentionally advisory.
- **WebSocket:** idle timeout (`ws_idle_timeout_seconds`) closes abandoned sockets; pipeline
  Continue/Modify/Retry actions are now plumbed over the WS transport.

### Fixed — R5: code↔DB sync reliability & correctness (2026-06-25 sync audit)

Closes all 22 findings of the five-specialist code↔DB synchronization audit (9 High, 9 Medium,
4 Low). Branch `fix/sync-remediation-2026-06-25`; 18 TDD tasks; combined suite 4560 passing, 75%
coverage; ruff/mypy clean. Spec `docs/superpowers/specs/2026-06-25-sync-remediation-design.md`,
plan `docs/superpowers/plans/2026-06-25-sync-remediation.md`.

- **Reliability (High):** the daily-sync parent `IndexingRun` now emits a continuous heartbeat
  (targeted `UPDATE`, no `version` lost-update) so the stale-run reaper no longer kills a healthy
  multi-minute sync (**H1**); the daily cron sub-steps **adopt-or-skip** instead of launching an
  untracked concurrent pipeline on an active-run conflict (**H9**); `RunCoordinator.start` translates
  the single-active `IntegrityError` into a clean `RunAlreadyActiveError`/409 with session rollback,
  and the partial-unique active index is mirrored onto the model for `create_all` test parity (**H8**);
  `is_indexed` now only counts `completed`/`completed_partial` (a failed-only index is no longer
  reported as indexed) (**H7**).
- **Data correctness (High):** batch table analyses are reconciled by the LLM-echoed `table_name`
  instead of tool-call position, ending silent cross-table misattribution (**H2**); a malformed
  `confidence_score` degrades only its own table instead of aborting the batch (**H3**); a degraded
  LLM run (mostly fallback) no longer overwrites previously-good sync rows, and low-confidence rows
  no longer enforce/surface required-filter guidance (**H4**).
- **Cost & privacy (High):** sync LLM calls are now metered + budget-gated against the project
  owner (manual triggers 429 on exhaustion; cron degrades gracefully; ownerless projects run
  unenforced) (**H5**); DB sample data + distinct values are scrubbed (column denylist + value
  redaction) before egress to the LLM at both the sync and db-index analyzers, with a per-connection
  `send_sample_data_to_llm` opt-out (default on) (**H6**).
- **Medium:** freshness reconciler now covers all connections, not just the first (**M1**);
  schema-qualified table identity prevents same-named cross-schema tables from collapsing (**M2**);
  the daily-sync parent run advances through manifest steps instead of 0%→100% (**M3**); the cron
  wave honors the per-project schedule hour (**M4**); daily sync regenerates the project overview
  and the worker logs the correct matched count (**M5**); investigation enrichment is routed to a
  non-enforced field and `required_filters` payloads are validated + value mappings deep-merged
  (**M6**); graph-derived `op_kind` heuristics are labelled non-authoritative (over-broad write verbs
  reclassified) (**M7**); freshness `warnings` uses a proper default + a `sync_failed` flag (**M8**);
  `get_index_age` guards a NULL `indexed_at` (**M9**).
- **Low:** the reaper logs a sweep even when the driver returns an unknown rowcount (**L1**); the
  prompt header no longer fabricates an "analyzed" date for a never-completed sync (**L2**); daily
  child-run orphaning is covered by H1+H9 (**L3**); context truncation is marked and relevance
  matching tightened (**L4**).

### Added

- **MCP protocol-polish (F5/F6/F9).** Shipped in three batched releases on top
  of the remote mount. **F6 — error contract:** actionable tool/resource failures
  now raise `ToolError` so MCP clients receive a proper `isError=true` result
  (access denied, not-found, budget-exhausted, safety block, rate-limit, internal
  error) instead of a normal result whose body is an `{"error": …}` string.
  **F5 — structured output:** `checkmydata_ping`, `checkmydata_query_database`,
  `checkmydata_search_codebase`, and `checkmydata_execute_raw_query` return typed
  Pydantic models, emitting `structuredContent` + an auto-generated `outputSchema`
  for machine-parseable results; the three `response_format` list tools stay text
  (a single schema can't cover the json+markdown switch — intentional). **F9 —
  cleanups:** `query_database` prefers an `is_active` connection when defaulting;
  the `project_schema` resource caps aggregation at 500 tables with
  `total_tables`/`truncated`; `sse` is marked deprecated in the CLI help (still
  accepted); the principal is a typed `Principal` `TypedDict`; and the benign
  userless-sync `TracePersistence` "skipping initial persist" log dropped from
  WARNING to DEBUG to quiet prod logs. Plan:
  `docs/superpowers/plans/2026-06-23-mcp-protocol-polish.md`.

- **MCP server: remote multi-tenant HTTP mount.** The MCP server can now be
  mounted into the FastAPI app as an ASGI sub-app at `/mcp` (streamable-HTTP,
  stateless), gated behind **both** `MCP_ENABLED` and the new
  `MCP_MOUNT_ENABLED` (default off — enabling the stdio surface no longer
  exposes the network endpoint). On the mounted transport, every request is
  authenticated **per request**: a pure-ASGI `McpAuthMiddleware` resolves the
  `Authorization: Bearer` token (`cmd_mcp_…` or JWT; `X-API-Key` fallback) to a
  principal carried in a `ContextVar`, so two clients with two tokens resolve to
  two different users — closing the prior gap where the network transport bound
  every caller to one env-configured user. Fails closed (`401` +
  `WWW-Authenticate: Bearer`) on missing/invalid/errored auth. New config:
  `MCP_MOUNT_ENABLED`, `MCP_MOUNT_PATH` (default `/mcp`), `MCP_ALLOWED_HOSTS`
  (opt-in DNS-rebinding Host validation; empty = permissive). Transport runs
  `stateless_http=True, json_response=True` for horizontal scaling. The stdio
  entry point (`python -m app.mcp_server`) is unchanged. New tests prove
  per-request isolation under both sequential and concurrent (`asyncio.gather`)
  load. Design/plan: `docs/superpowers/specs/2026-06-22-mcp-server-hardening-design.md`,
  `docs/superpowers/plans/2026-06-22-mcp-remote-hardening.md`.

### Changed

- **MCP agent tools enforce token budgets + concurrency.**
  `checkmydata_query_database` and `checkmydata_search_codebase` now run the
  shared token-budget gate before invoking the orchestrator (returning an
  upgrade hint when a plan's budget is exhausted), and all three agent-invoking
  tools acquire a per-user slot from the existing `agent_limiter` (concurrency +
  hourly cap, shared with chat). The budget gate logic was extracted from the
  chat route into `UsageService.check_token_budget` so both surfaces share one
  implementation (chat behaviour unchanged). MCP request traces now persist
  under the mount via a runtime trace-service holder, replacing the
  `app.main` reach-through that never resolved in the standalone process.

### Fixed

- **Pipeline checkpoint "Continue / Modify / Retry" buttons were dead.** When a
  multi-stage pipeline paused at a checkpoint (`stage_checkpoint` / `stage_failed`),
  the agent's `viz_config` — which carries `pipeline_run_id` (+ `stage_id`) — was
  built by the backend but **never serialized** into any client-facing response
  (REST `/api/chat/ask`, SSE `/api/chat/ask/stream` `result` event, or the
  WebSocket `response` payload all dropped it). The checkpoint card still rendered
  (its visibility is driven by the separate streaming `checkpoint` event), so the
  buttons appeared, but the frontend never learned `pipeline_run_id`; its resume
  handler (`sendPipelineAction`) guards `if (!pipelineRunId) return`, so every
  click silently no-op'd and the pipeline could not be resumed. Added the
  `viz_config` field to `ChatResponse` and to all three response paths (and the
  matching frontend `ChatResponse` type). New regression tests cover both the
  REST and SSE checkpoint paths.

- Pinned `mcp` to exactly `==1.27.2` (was `>=1.2.0`) for CI reproducibility,
  matching the ruff/mypy pinning convention.

## [1.14.0] - 2026-06-21 - Audit remediation, MCP tokens & sync-workflow reliability

### Added

- **MCP observability + drop-in agent skill.** Every MCP auth attempt, tool
  start/ok/crash, and key-CRUD event now emits a structured log line
  (`MCP auth: …`, `MCP tool <name> starting (user=…)`, `MCP key issued`,
  etc.) — see `docs/MCP_SERVER.md#logging--debugging` for the grep cheatsheet.
  Plaintext tokens are redacted to their 12-char display prefix in every
  log; tests pin that the secret cannot leak. New documentation:
  `docs/MCP_SERVER.md` (full integration guide), `API.md` (token CRUD
  endpoints + rate limits), `backend/.env.example` (per-user vs operator
  modes), `CLAUDE.md` (architecture note). Portable agent skill at
  `.claude/skills/checkmydata-mcp/` with `SKILL.md`,
  `references/client-configs.md` (Claude Desktop, Cursor, OpenAI Agents
  SDK), `references/tools.md` (tool schema reference), and
  `references/troubleshooting.md` (common error → root-cause table) — any
  MCP-aware agent can ingest this folder and learn the full integration
  flow.

- **Per-user MCP API tokens.** Each user can mint their own `cmd_mcp_…`
  tokens (`POST /api/auth/mcp-tokens`) and point Claude Desktop / Cursor /
  any MCP client at them via `CHECKMYDATA_API_KEY`. The MCP `authenticate()`
  flow now resolves a per-user token to the issuing user, so tool calls and
  resources are scoped to that user's project membership — no shared
  service-account binding required. Storage: new `mcp_api_keys` table
  (sha256 hash + display prefix, optional expiry, revocation, last-used
  touch). Routes (JWT/session-authenticated): list/create/revoke; plaintext
  is returned exactly once at creation. Legacy server-level
  `CHECKMYDATA_API_KEY` + `MCP_API_KEY_USER_ID` operator binding remains
  for single-tenant self-hosted setups. Frontend: `McpTokenManager` in the
  Settings panel with create/list/revoke + one-time plaintext reveal and a
  Claude Desktop config snippet. New backend tests cover issuance,
  hashed-lookup, revocation, expiry, the per-user auth path, and the route
  contract (no plaintext leak on list).

- **MCP server best-practices alignment.** All MCP tools now use the
  `checkmydata_*` service prefix to avoid collisions with other MCP servers a
  client may load in parallel. Every tool carries explicit `ToolAnnotations`
  (`readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`) so
  clients can render appropriate confirmation prompts. List tools
  (`list_projects`, `list_connections`, `get_schema`) gained pagination
  (`offset`/`limit` with `has_more`/`next_offset`) and a `response_format`
  switch between `"json"` (default) and `"markdown"`. New `checkmydata_ping`
  tool returns the resolved principal for client smoke-testing. The package
  now re-exports `create_mcp_server`. Tool/resource descriptions, titles, and
  MIME types are filled in for richer client UI. Tests cover annotations,
  pagination, markdown output, and the package export. Server name updated
  from `CheckMyData.ai` to `checkmydata-mcp` per the MCP naming convention.

- **Knowledge pipeline visibility.** New `GET /api/projects/{id}/pipeline-status`
  aggregates repo index, DB index, and code-DB sync state for all project
  members. ARQ worker workflow events are bridged to API SSE via Redis pub/sub
  (`cmd:workflow_events`). Frontend polls pipeline status and seeds
  `ActiveTasksWidget`, Sidebar, ConnectionSelector, and Knowledge Health panel.

- **Heroku worker + Redis TLS.** Production Docker image installs the `[redis]`
  extra (ARQ task queue). `heroku.yml` and CI deploy release both `web` and
  `worker` dynos. Heroku `rediss://` URLs use `ssl_cert_reqs=none` via
  `app/core/redis_tls.py` (redis-py 5.x compatibility).

- **Daily knowledge sync cron.** Opt-in nightly job (`DAILY_KNOWLEDGE_SYNC_ENABLED`)
  at 00:00 Europe/Berlin runs incremental repo index → DB index → code↔DB sync
  for every eligible project (repo + active connections). Results are persisted
  in `knowledge_sync_runs` and logged with the `Cron: daily knowledge sync`
  prefix for monitoring.

- **Sync-workflow reliability (heartbeat + reaper, durable audit, single-flight cron).**
  A set of interlocking features that make background indexing and sync jobs
  crash-proof and observable:

  - *Heartbeat + StaleRunReaper crash recovery:* every DB-index, code↔DB sync,
    and repo-index run now ticks a `heartbeat_at` timestamp on its status row
    every `HEARTBEAT_INTERVAL_SECONDS` (default 30 s). `StaleRunReaper` runs
    in both the web and worker processes every `REAPER_INTERVAL_SECONDS`
    (default 60 s); any `running` row whose heartbeat is older than
    `STALE_RUNNING_HEARTBEAT_TIMEOUT_SECONDS` (default 300 s) is reset to
    `failed`, so a hard worker crash no longer leaves the UI spinning forever.
    Controlled by `REAPER_ENABLED` (default `True`).

  - *Durable daily-sync audit + history endpoint:* the daily knowledge sync now
    records a `knowledge_sync_runs` row with full outcome (per-project status,
    counts, errors) in a crash-safe way — the audit row is written even if the
    job process dies mid-run. New `GET /api/projects/{id}/sync-history` returns
    the last N runs with per-project breakdown (see `API.md`). Frontend: a
    **Sync History** panel in Project Overview shows run timeline, duration, and
    errors.

  - *Single-flight cron via Redis advisory lock:* the daily_sync ARQ cron
    acquires a Redis `SET NX EX` lock before scheduling work so only one
    scheduler instance can trigger a given sync window, eliminating duplicate
    runs on multi-dyno deployments.

  - *Parent `daily_sync` workflow:* a durable ARQ parent task orchestrates each
    project's sync steps (repo → DB → code↔DB) as child tasks, emitting
    per-project progress SSE events and writing the audit row with final status.

  - *Stale-marking gate:* DB-index and sync stale-marking is gated on real
    status changes — a row already at `failed`/`idle` is not touched again,
    preventing spurious `updated_at` bumps and false SSE events.

  - *Unified background-tasks store:* replaced the frontend `task-store` with a
    unified `useBackgroundTasks` Zustand store that reconciles ARQ/SSE events
    and poller results using SSE-provenance precedence — a running SSE event
    cannot be overwritten by a stale poll response.

  API, agent/orchestrator, MCP, connectors/SSH, and billing:
  - *MCP resources auth (P0):* `project://{id}/schema|rules|knowledge` resources
    now resolve a principal and enforce project membership via
    `_require_project_access` — same fail-closed ownership model as MCP tools.
  - *SSH hardening (P0):* default host-key policy is now `tofu` (unknown policy
    values fail closed to `strict`); SSH pre-commands are validated against a
    strict allowlist (`app/connectors/ssh_pre_commands.py`) with metacharacter
    rejection, count/length limits, and validation at both the API layer and
    `ssh_exec`.
  - *Billing end-to-end (P0):* new `plans`/`subscriptions`/`stripe_events`
    tables (+ seeded Free/Pro/Team plans), Stripe Checkout/Customer Portal/
    webhook routes under `/api/billing/*`, `EntitlementService` (plan-derived
    token limits, connection/project quotas with HTTP 402), `BillingService`
    with idempotent webhook event handling, `/pricing` marketing page,
    `PricingTable` + `BillingPanel` UI, and 402-aware frontend API client.
    Token budget gate (`check_budget`) is now wired into all chat entry points
    (HTTP/SSE/WS) with plan-based limits.
  - *Redis-backed limits (P1):* central `app/core/redis_client.py`; slowapi
    rate limiting, `AgentLimiter` (Lua-scripted concurrency slots), and
    `WsTicketStore` (SET EX / GETDEL) all use Redis when configured, with
    in-memory fallbacks for dev.
  - *Sentry (P1):* backend `sentry-sdk[fastapi]` and frontend `@sentry/nextjs`
    initialization with shared PII/secret scrubbing (`app/core/sentry.py`,
    `frontend/src/lib/sentry-scrub.ts`) covering Bearer tokens, API keys,
    cookies, DSNs, and emails.
  - *ClickHouse streaming + health loop (P1):* `ClickHouseConnector` now streams
    row blocks and stops at the row cap instead of materializing full results;
    the background health loop iterates all registered connector pools via the
    new `app/core/connector_pools.py` registry.
  - *Orchestrator tails (P1):* stuck pipelines emit a `stage_failed` tracker
    event; `WorkflowTracker.end` reports the true terminal status;
    `AnswerValidator` fails closed on LLM errors (configurable via
    `answer_validator_fail_closed`).

### Changed

- **Frontend auth is cookie-only:** removed the legacy `localStorage`
  `auth_token` fallback from `_client.ts` / `sse.ts`; all requests rely on
  httpOnly session cookies + CSRF.
- **Next.js security headers:** `next.config.ts` now emits CSP, HSTS,
  `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`, and
  `Permissions-Policy` for the Next shell.
- **Feature flags default-on:** `orchestrator_auto_investigate_enabled`,
  `hybrid_retrieval_enabled`, and `schema_retrieval_enabled` now default to
  `True`; `code_graph_enabled` and `lineage_enabled` remain opt-in.
- **`chat.py` decomposed** (2 855 → ~1 700 lines): session CRUD moved to
  `chat_sessions.py`, feedback/learning-credit endpoints to `chat_feedback.py`,
  and estimate/search/suggestions/explain-sql/summarize to `chat_utility.py`.
  Route URLs are unchanged.

### Removed

- Deprecated legacy modules `app/core/orchestrator.py` and
  `app/core/tool_executor.py` (superseded by `app/agents/*`).

- **Knowledge Architecture roadmap — Phase 0 & Phase 1.** Foundation work toward
  a unified Knowledge Fabric (see `docs/KNOWLEDGE_CATALOG.md`).
  - *Phase 0 (Stabilize & Unify):* the plan-summary routing label now mirrors the
    actual router decision (`RouteResult.use_complex_pipeline` from planner
    signals) instead of the cosmetic table-count heuristic (BACKLOG 10.1); DB
    indexing is dispatched through a single `_dispatch_db_index` helper that uses
    `task_queue.enqueue` (ARQ) when Redis is configured and falls back to
    in-process `asyncio` otherwise, with an ARQ-aware status endpoint that no
    longer false-resets worker-managed runs to `failed`; new `task_queue.is_arq_active()`
    helper; new `docs/KNOWLEDGE_CATALOG.md` artifact-schema & `ContextPack` contract.
  - *Phase 1 (Knowledge Catalog):* new `KnowledgeCatalogService` read-facade and
    `Artifact`/`ContextPack` DTOs (`backend/app/knowledge/context_pack.py`) that
    assemble a structured, traceable bundle (tables+sync notes, lineage,
    learnings, insights, rules, RAG chunks, freshness) from the existing stores
    with per-section graceful degradation. `KnowledgeFreshnessService` now emits
    structured `FreshnessWarningDetail`s carrying a machine-readable
    `recommended_action` (reindex_db / reindex_repo / resync). New
    `GET /api/projects/{id}/knowledge-health` endpoint and a **Knowledge Health**
    UI panel in Project Overview showing artifact counts and one-click
    re-index/re-sync buttons wired to the consolidated execution path.
  - *Phase 2 (Event-Driven Smart Ingestion):* knowledge now refreshes itself
    after a `git push` without user action. All triggers ship OFF by default
    (opt-in flags). New `POST /api/repos/{id}/webhook` endpoint verifies
    GitHub-style `X-Hub-Signature-256` HMAC (and GitLab `X-Gitlab-Token`),
    debounces push bursts (`WEBHOOK_DEBOUNCE_SECONDS`), and enqueues a re-index
    via the consolidated `_spawn_repo_index` dispatcher. A new ARQ task
    `run_repo_index` runs out-of-process when Redis is configured (mirrors the
    in-process path: checkpoint/resume, docs/BM25, overview, auto-sync). A cron
    poll loop (`GIT_POLL_ENABLED` / `GIT_POLL_INTERVAL_MINUTES`) covers repos
    without webhooks by `git fetch` + HEAD comparison. The repo index→sync chain
    is automatic (`AUTO_SYNC_AFTER_INDEX`) via `maybe_autostart_sync`, closing
    the lineage-lag gap. A `FreshnessReconciler` (`FRESHNESS_RECONCILER_ENABLED`)
    in the maintenance loop evaluates `KnowledgeFreshness` per connection and
    auto-dispatches DB re-index / resync / repo re-index when stale. RAG chunks
    now carry temporal metadata (`commit_sha`, `indexed_at`, `source_path`),
    closing the retrieval temporal gap. New `_dispatch_code_db_sync` /
    `maybe_autostart_db_index` consolidate the sync/index dispatch paths.
  - *Phase 3 (Retrieval Stack):* optional cross-encoder reranker
    (`backend/app/knowledge/reranker.py`) as a second stage over fused
    hybrid/schema candidates — lazy model load, graceful no-op when
    `sentence-transformers` is absent (`RERANKER_ENABLED`, `RERANKER_MODEL`,
    `RERANKER_CANDIDATES`). Wired into `HybridRetriever`, `KnowledgeAgent`,
    `ContextLoader`, and a new async `SchemaRetriever.aquery` used by
    `SQLAgent`. New deterministic, LLM-free retrieval-eval harness
    (`backend/app/eval/`: golden set, `hit@k`/`MRR`/context precision·recall/
    `nDCG@k`, threshold gate) with a golden dataset and a CI gate
    (`.github/workflows/ci.yml`).
  - *Phase 4 (Context Planner):* `ContextPlanner`
    (`backend/app/agents/context_planner.py`) turns eager context loading into
    query-aware lazy loading — a `ContextPlan` (needs + per-category limits)
    derived from the question and router signals (`CONTEXT_PLANNER_ENABLED`,
    `CONTEXT_PLANNER_MODE` heuristic|llm, `CONTEXT_PLANNER_BUDGET_TOKENS`).
    `KnowledgeCatalogService.get_context_pack` honours the plan and enriches
    each `Artifact` with a `trust` block (confidence + freshness) via the trust
    layer; `ContextPack` gains `plan`, `all_artifacts()`, and a
    `provenance_summary()` for per-block reasoning transparency.
    `ContextLoader.build_context_pack` is the orchestrator's single entry point.
  - *Phase 5 (Proactive & Cross-Source Intelligence):* proactive
    `schema_change` insights — a DB re-index that detects added/removed/changed
    tables vs the last persisted fingerprint stores an actionable insight
    (`SchemaChangeDetector`, `SchemaChangeAlertsEnabled`), wired into
    `DbIndexPipeline` and surfaced through the existing freshness/insight loops.
    New cross-source foundations (`backend/app/knowledge/cross_source.py`):
    `CrossSourceJoinPlanner` proposes explainable join keys across *different*
    connections (multi-DB JOIN), and `CrossSourceCausalGraph` unions intra-DB
    FK edges with code↔DB lineage into one directed graph answering
    "what feeds / consumes X?" across the code/DB boundary.

- **Pipeline + Admin UX upgrade (Phases 0–4).** Redesigned live pipeline progress
  (`StageProgress`) with `ProgressBar`, icon-based `StatusBadge`, progressive
  disclosure, and `CheckpointCard` data preview. Wired `ToolCallIndicator` during
  active stages; `data_gate` is a first-class SSE event (backend frozenset +
  frontend handler with validating sub-state). Mobile reasoning opens in a bottom
  sheet. Shared UI primitives (`Button`, `Input`, `Card`, `Badge`, `ProgressBar`).
  App shell IA: Setup / Workspace / Operations sidebar groups, deep-linkable
  `?panel=` routes, Project Overview default panel, consolidated Settings, Live
  Activity vs Request History naming, Knowledge hub for Insights/Metrics.
  Custom motion easing tokens in `globals.css` (see DESIGN_SYSTEM §3.2).

Fixes a batch of correctness and lifecycle issues found in a full
business-logic audit of the orchestrator, data integration/storage, and the
self-learning/memory system.

### Fixed

- **Usage Summary "Failed to fetch" on Heroku.** slowapi rate limiting uses Redis
  when `REDIS_URL` is set; Heroku `rediss://` requires `ssl_cert_reqs="none"`
  (same as ARQ/worker). Without it, every rate-limited route (including
  `GET /api/usage/stats`) crashed with SSL verify errors → HTTP 500. Fixed by
  passing `redis_connect_kwargs()` into slowapi `storage_options`.

- **Google sign-in missing on production login page.** Frontend CSP added in
  `next.config.ts` (security headers rollout) blocked Google Identity Services
  (`accounts.google.com` / `apis.google.com` script, connect, and iframe). The
  client ID was baked into the bundle but GIS never loaded, so the login form
  showed email/password only. CSP now mirrors the backend Google OAuth
  allowlist (`script-src`, `connect-src`, `frame-src`, `img-src` for profile
  avatars).

- **Multi-stage chat crash: `WorkflowTracker.emit() got multiple values for
  argument 'status'`.** Every orchestrated request that produced a multi-stage
  execution plan failed with `An unexpected error occurred`. `StageExecutor.
  _emit_stage_result` built an `extra` dict containing a `"status"` key and ALSO
  passed `result.status` positionally to `emit(workflow_id, step, status, ...,
  **extra)`, so `**extra` collided with the positional `status` parameter
  (Python raises a `TypeError` at argument binding). Fixed by dropping the
  redundant `"status"` key from `extra` (the value is already conveyed as the
  positional `status` -> top-level `WorkflowEvent.status` and the SSE payload),
  and updating the frontend `stage_result`/`stage_complete` handler to read the
  top-level `event.status` instead of `extra.status` (value-identical). Closed
  the test gap that let it ship: the `StageExecutor` test tracker now uses
  `create_autospec(WorkflowTracker)` so the real `emit` call signature is
  enforced (plain `AsyncMock(spec=...)` does not), plus a regression test for
  `_emit_stage_result` (success + error). No backend consumer relied on
  `extra.status` (trace persistence uses the top-level `evt.status`).
- **LLM agent outage: Anthropic mid-conversation `system` 400.** Every
  multi-turn chat (and any session with an auto-welcome message) failed with
  `LLMAllProvidersFailedError` -> `400 Bad Request` from OpenRouter for
  `anthropic/*` models. The orchestrator inserted an `--- END OF CONVERSATION
  HISTORY ---` marker as a `Message(role="system", ...)` after the chat history;
  Anthropic (and Bedrock via OpenRouter) reject a `system` role that does not
  immediately follow a user message. Fixed by folding the history-framing
  guidance and the continuation summary into the final user turn instead of
  emitting mid-conversation `system` messages. Added a defensive normalizer in
  the OpenRouter adapter (`_merge_nonleading_system`) that merges any non-leading
  `system` message into the adjacent user turn, making the whole class of bug
  unreachable from any future caller.
- **Planner dict-tool `AttributeError` log spam.** `AdaptivePlanner` passed
  `_CREATE_PLAN_TOOL` (a raw OpenAI function-schema `dict`) where a `Tool`
  dataclass was expected, raising `'dict' object has no attribute 'parameters'`
  on every plan attempt (silenced by a fallback but noisy in logs). Hardened
  `_tools_to_schema`/`_tools_to_anthropic` to accept dict tool specs
  (pass-through / mapped to Anthropic shape) via a new `ToolSpec` type, emit a
  valid `items` clause for `array` parameters (and `properties` for `object`),
  added an optional `ToolParameter.items` field, set explicit array `items` on
  the `git_tools` path params, and dropped the `# type: ignore[list-item]` hacks
  in the planner.
- **Split-domain cookie auth outage (post T-SEC-3).** Browser login broke in
  production because the SPA (`checkmydata.ai`) and API (`api.checkmydata.ai`)
  run on different subdomains while `AUTH_COOKIE_DOMAIN` was empty (host-only).
  The non-httpOnly CSRF cookie set by the API was unreadable by the SPA, so the
  double-submit header was never sent and every cookie-authenticated mutation
  (notably `POST /auth/refresh` during session restore) returned 403, bouncing
  users back to `/login` after a successful Google/email login. Fixed by scoping
  the session + CSRF cookies to the shared parent domain
  (`AUTH_COOKIE_DOMAIN=.checkmydata.ai`). Added a startup guardrail that warns
  when `AUTH_COOKIE_DOMAIN` is empty while serving cross-origin HTTPS SPA
  origins, hardened `clear_session_cookies` to also expire legacy host-only
  cookies, and documented the parent-domain requirement.

### P0 security & reliability (S1/S2 launch-blockers)

Implements the first remediation sprint from the production audit
(`docs/production-plan/00-AUDIT-FINDINGS.md`): the pure-code security and
reliability fixes that unblock any public/paid launch.

- **Query result bounding / MySQL OOM fix (T-ARCH-5).** `MySQLConnector.execute_query`
  now streams via a server-side cursor (`aiomysql.SSDictCursor` + `fetchmany`)
  instead of materializing the full result with `fetchall()`. A shared byte guard
  (`cap_rows_by_bytes`, `MAX_RESULT_BYTES=50MB` in `connectors/base.py`) backstops
  the row cap for wide rows/BLOBs and is applied consistently across the MySQL,
  Postgres, and ClickHouse connectors. `truncated` is reported accurately.
- **CSP + HSTS headers (T-SEC-6).** `SecurityHeadersMiddleware` now emits a
  configurable `Content-Security-Policy` (report-only capable) and
  `Strict-Transport-Security` (HSTS, applied only over HTTPS, proxy-aware via
  `X-Forwarded-Proto`). New `SECURITY_CSP_*` / `SECURITY_HSTS_*` settings.
- **MCP authentication & tenancy (T-SEC-1).** Every MCP tool now requires an
  authenticated principal (no more `mcp-user`/`mcp-anonymous`); project/connection
  ownership is enforced via `MembershipService.can_access` / `list_accessible`,
  `list_projects` is scoped to the caller, the API key is bound to a real platform
  user (`MCP_API_KEY_USER_ID`, compared with `hmac.compare_digest`), and the server
  is off by default (`MCP_ENABLED`), refusing to start unconfigured.
- **WebSocket ticket auth (T-SEC-2).** The chat WS no longer accepts a JWT in the
  URL query string. Clients call an authenticated `POST /api/chat/ws-ticket` to
  mint a short-lived, single-use ticket (`app/core/ws_tickets.py`) and pass it via
  `Sec-WebSocket-Protocol` — credentials never appear in a URL/log.
- **httpOnly cookie session + CSRF (T-SEC-3).** Login/register/Google/refresh now
  set the JWT as an `httpOnly`/`Secure`/`SameSite` cookie plus a readable CSRF
  cookie (`app/core/auth_cookies.py`); `get_current_user` accepts the cookie and
  enforces a double-submit CSRF check on cookie-authenticated mutations. Added
  `POST /api/auth/logout`. `Authorization: Bearer` still works for API clients.
  Frontend stops persisting the token in `localStorage`, sends cookies
  (`credentials: "include"`) + the `X-CSRF-Token` header, and restores sessions
  via refresh.
- **Coverage gate aligned with reality (T-QA-1).** The CI/`pyproject` coverage
  floor is raised from `--fail-under=40` to `72` to match the documented value in
  `README.md`/`CONTRIBUTING.md` (actual combined coverage ~73%); `docs/DEPLOYMENT.md`
  updated to match. New tests cover all of the above (connector bounding + byte
  guard, security headers, MCP auth/tenancy, WS tickets, cookie/CSRF).

### Live Git access + release cohort analysis

Gives the orchestrator live, read-only access to the project's local Git clone
(commit history, diffs, blame, releases, authorship, churn, and commit-trailer
review signals) and a release→cohort bridge so it can correlate releases with
post-release retention/revenue.

- **`GitInspector` service** (`backend/app/knowledge/git_inspector.py`) — async,
  read-only GitPython wrapper: `log`, `show`, `diff`, `blame`, `list_releases`,
  `authors_stats`, `file_churn`, `commits_touching`, `review_signals`. Security
  hardened: explicit arg lists (never `shell`), path-traversal guard
  (`is_relative_to`), output/count limits, no hook execution, binary/non-UTF-8
  safe, and a typed error taxonomy (`RepoNotClonedError`, `InvalidRefError`,
  `PathOutsideRepoError`, `GitCommandFailedError`). Empty/unborn-HEAD repos and
  bad refs are handled explicitly.
- **`GitAgent` sub-agent** (`backend/app/agents/git_agent.py` + `prompts/git_prompt.py`
  + `tools/git_tools.py`) — mirrors `KnowledgeAgent`'s bounded tool-calling loop,
  with a clone-freshness warning (commits ahead of the last indexed SHA), an
  opt-in auto clone-or-pull (`git_agent_auto_pull`), a deterministic
  `get_release_timeline`, and `write_code_note`.
- **Single-loop wiring.** New orchestrator meta-tools `analyze_git`,
  `get_release_timeline`, and `write_code_note` (gated by a `has_repo` capability
  flag threaded through the router, context loader, tool definitions, and
  prompts, exactly like `has_kb`); dispatched to the `GitAgent` via
  `ToolDispatcher`. The router gains a `git` route that downgrades to `explore`
  when no clone is present.
- **Full pipeline wiring.** `analyze_git` is now a first-class planner stage tool
  (`query_planner` validation + `stage_executor._run_git_stage`), enabling the
  release→cohort recipe: `analyze_git` → `query_database` → `process_data`
  (cohort_window) → `synthesize`.
- **`cohort_window` data operation** (`backend/app/services/data_processor.py`) —
  buckets rows into each release's `[release, release+window]` and computes summed
  revenue or distinct-id retention at 7/14-day (configurable) windows. Robust
  date parsing (unparseable rows skipped and counted), empty-window safe, column
  validation. Structured params reach the single-loop `process_data` tool via a
  new `params_json` blob.
- **Code findings persisted to Insight Memory.** Added the `code_finding` insight
  type; `write_code_note` stores durable findings that the context loader already
  auto-injects into future prompts.
- **Bug fix:** `ContextLoader.has_repo` referenced `Path` without importing it,
  so the capability probe always returned `False` (caught by the new unit test).
- **Tests.** New `test_git_inspector.py` (temp-repo + edge cases),
  `test_git_agent.py`, `test_tool_dispatcher_git.py`, plus git-route/plan/stage/
  cohort_window/has_repo cases added to the router, planner, stage-executor,
  data-processor, tools, and context-loader suites.

### Marketing site — narrative, conversion & SEO refine

Repositions the landing and marketing pages around the product's real moat —
correct answers grounded in your schema *and* codebase, self-healing queries,
and institutional memory — and replaces unverifiable social proof with honest,
verifiable trust signals. The cinematic 2.5D system is unchanged; this is a
copy/structure/SEO refine.

- **Hero repositioned to correctness.** H1 now leads with "Correct answers from
  your database — on the first try"; the "Like ChatGPT, but for your database"
  hook is demoted to a small secondary line, and the subhead explains *why* the
  answers are correct (schema + codebase context).
  (`frontend/src/app/(marketing)/page.tsx`)
- **Honest trust signals.** The social-proof bar's unverifiable claims and the
  "Most loved feature" badge are replaced with true signals (MIT open source,
  read-only by default, credentials encrypted at rest, self-host or hosted,
  transparent SQL) plus an optional live GitHub star count that renders only
  when it truly resolves (server-fetched, 1h revalidate, hidden on failure/zero).
- **Moat-first features.** Codebase-aware context is promoted to first; new
  Self-healing queries and Institutional memory cards surface vision-level
  differentiators; all descriptions tightened to benefit-first.
- **New "why the answers are correct" section** (context engine: schema + code +
  rules + memory → validated, dialect-aware SQL) with an honest comparison vs. a
  plain SQL editor and vs. a generic chatbot.
- **Landing FAQ** with objection handling (safety/read-only, vs. ChatGPT, no SQL
  required, what codebase indexing sends, self-host vs. hosted), reusing the
  support accordion pattern.
- **SEO schema & metadata.** Landing JSON-LD now emits `Organization`,
  `SoftwareApplication`, and `FAQPage`; support adds `FAQPage` + `BreadcrumbList`;
  about/contact add `BreadcrumbList`. Meta/OG/Twitter descriptions across the
  landing, about, and root layout are unified around the correctness narrative
  while keeping text-to-SQL / natural-language keywords.
- **Cross-page consistency.** About hero/mission and the footer tagline are
  re-threaded around context/correctness/memory; subtle `cmd-reveal` cohesion
  added to about/support headers (each mounts `CinematicEngine` so reveals
  resolve, with the existing reduced-motion + `<noscript>` failsafes intact).

### Conversational turn isolation & response language

Makes the orchestrator behave like a normal chat partner: it acts only on the
latest user message instead of re-running tasks from earlier turns, and it
replies in the user's language.

- **History is read-only, never re-executed.** The unified tool loop now keeps
  full conversation history for reference but hard-isolates it: a strengthened
  boundary system message states that prior turns are already answered and must
  never be re-run, and a new `CURRENT TURN FOCUS` block in the orchestrator
  prompt reinforces that only the latest message is the task.
  (`backend/app/agents/orchestrator.py`,
  `backend/app/agents/prompts/orchestrator_prompt.py`)
- **Raw SQL stripped from history.** `ChatService.get_history_as_messages` no
  longer echoes the executed `query: SELECT ...` text into assistant history —
  the strongest cue for the model to re-run earlier queries. Result-shape
  metadata (viz, row count, columns, insight/follow-up counts) is preserved.
  (`backend/app/services/chat_service.py`)
- **Per-turn dedup safety net.** New `ToolDispatcher.filter_already_executed`
  skips a data-retrieval call whose question semantically matches one that
  already *succeeded* earlier in the same turn. Gate-flagged and failed calls
  are intentionally not recorded, so corrective re-queries are never blocked.
  (`backend/app/agents/tool_dispatcher.py`, `backend/app/agents/orchestrator.py`)
- **Think in English, answer in the user's language.** A language rule is
  injected at every user-facing synthesis point — orchestrator `PRINCIPLES`,
  direct-response prompt, step-limit synthesis (`build_synthesis_messages`),
  emergency synthesis, and the complex-pipeline `_synthesize` — instructing the
  model to reason internally in English but write the final answer in the same
  language as the user's most recent message. Internal/intermediate prompts
  (planner, router, SQL agent, analysis stage) stay English.

### Google sign-in button disappearing on the login/register page

- **Fixed an init race that hid the Google button.** The Google Identity
  Services init effect on `/login` ran while the page was still in its
  `restoring` state — during which the page renders only a spinner, so the
  button container (`googleBtnRef`) is not mounted. The effect would call
  `renderButton()` against a `null` ref and bail, and (since its deps did not
  include `restoring`) never retry once restore finished. With the GIS script
  already cached — e.g. landing → login warm navigation — the button silently
  vanished. The effect now waits for `!restoring` and re-runs when restore
  completes, so the button reliably renders. The build-time
  `NEXT_PUBLIC_GOOGLE_CLIENT_ID` and CSP were verified correct and were not the
  cause. (`frontend/src/app/login/page.tsx`)
- **Regression tests** cover the warm-navigation race (GIS preloaded + deferred
  restore → button renders after restore) and the no-client-id case.
  (`frontend/src/__tests__/components/LoginPage.test.tsx`)

### Marketing landing — cinematic 2.5D redesign

- **Cinematic landing motion layer (`epic-design`).** The marketing landing now
  has a dark, depth-layered "intelligence" treatment: a drifting technical
  grid, parallax glow blobs, scroll-reveal entrances with stagger, word-lighting
  shimmer on accent headings, and a rising showcase. All built from existing
  semantic design tokens — no color reskin, no image assets, no GSAP.
- **Animated "intelligence core" hero visual.** New `SchemaGraph` (pure SVG +
  CSS) shows database/codebase sources streaming data into a pulsing core that
  emits a verified, charted answer. (`components/marketing/SchemaGraph.tsx`)
- **`CinematicEngine`** client component drives reveals (IntersectionObserver)
  and depth parallax (rAF). Honors `prefers-reduced-motion` (snaps to final
  state, no listeners) and disables parallax on touch (`pointer: coarse`).
  A `<noscript>` failsafe keeps all content visible when JS is off.
- **Design system:** new `cmd-*` cinematic animation catalog documented in
  `DESIGN_SYSTEM.md` §3.2; GPU-safe properties only, all motion neutralized
  under reduced-motion. Scoped to the landing — not for app UI.

### Re-audit remediation

A meta-audit of the audit-remediation changeset surfaced a functional
regression and several correctness gaps that silently negated their own
fixes. These are now fixed, each with a regression test.

- **SSE session lock no longer leaks on normal completion.** The `/ask/stream`
  handler acquired `session_processing_lock(session_id)` but only released it
  on the client-disconnect path; a normally-completing stream left the lock
  held in its 1h-TTL cache, so the session returned `409 Busy` for up to an
  hour. The lock is now released on the normal-completion branch with a
  `finalized` guard so the disconnect and normal paths can't both
  release/persist. (`app/api/routes/chat.py`)
- **Compile-lock eviction race closed.** `_get_compile_lock` could hand out a
  lock and then have it evicted by a concurrent caller (the cap evicted
  *unheld-looking* entries), letting two `_compile_prompt_locked` run for one
  connection. Eviction now tracks an in-flight refcount and never evicts a
  recently-handed-out lock; the bounded cap is preserved.
  (`app/services/agent_learning_service.py`)
- **Binary-skip re-queue is no longer dropped (R3-7).** `state.failed_doc_paths`
  was reassigned (not unioned) late in the run, dropping the binary-skipped
  paths appended earlier; they are now unioned, and binary skips are no longer
  marked processed. (`app/knowledge/pipeline_runner.py`)
- **Stale "suspicious" workflow flag cleared (R5-3).** The result gate set
  `_wf_suspicious[wf_id]` on an over-budget result but never cleared it on a
  later good result, so a subsequent valid query stayed flagged. The flag is
  now popped when the current result is acceptable. (`app/agents/orchestrator.py`)
- **Validation learning credit is idempotent.** A successful answer credited
  exposed learnings, and a following thumbs-up credited them again
  (`apply_learning` is not idempotent), double-bumping `times_applied`; credit
  is now keyed per `message_id` and skipped for results flagged
  `suspicious_result`. (`app/api/routes/chat.py`)
- **Shared SSH tunnels are ref-counted.** Tearing down a tunnel keyed by
  transport identity closed a tunnel still in use by a sibling connection, and
  `delete()` never evicted the connector pool. Tunnels are now ref-counted
  (only torn down at zero refs, unless forced), `delete()` reuses
  `_evict_runtime_caches`, and a metadata-only update with unchanged transport
  identity preserves the tunnel. (`app/connectors/ssh_tunnel.py`,
  `app/services/connection_service.py`)
- **Postgres query timeout no longer poisons the pool.** `asyncio.wait_for`
  cancels mid-cursor; the connection could return to the asyncpg pool in an
  aborted state. On timeout/cancel the connection is now `terminate()`d so the
  pool discards it. (`app/connectors/postgres.py`)
- **Recent-learnings ranking fixed.** `context_loader` fetched the top 15 by
  confidence and *then* sorted by `priority_score`, so high-priority rows past
  the first 15 never surfaced. It now fetches an uncapped pool, sorts by
  `priority_score`, then slices the display count. (`app/agents/context_loader.py`)
- **`process_data` passthrough on the unified path (R5-8).** `_handle_process_data`
  defaulted a missing operation to `""` (→ `ValueError`) while the stage
  executor defaulted to `passthrough`; it now defaults to `passthrough` and
  the tool enum lists it. (`app/agents/tool_dispatcher.py`,
  `app/agents/tools/orchestrator_tools.py`)
- **`completed_partial` indexing is surfaced.** `db_index_service.get_status()`
  now returns `is_partial`, and the connection UI shows an `IDX*` badge plus a
  warning toast so a partial index isn't mistaken for a complete one.
  (`app/services/db_index_service.py`, `frontend/.../ConnectionSelector.tsx`)
- **Reused tables recompute `is_active` from fresh samples.** Incremental reuse
  cloned a possibly-stale `is_active`; it is now recomputed from the fresh
  sample / row count (preserving the prior value only when sampling failed),
  while the LLM analysis is preserved. (`app/knowledge/db_index_pipeline.py`)
- **Code-index incremental correctness (R3-3 / R3-4).** A partial AST parse
  failure no longer purges the failed file's existing graph symbols
  (per-file parse outcome is tracked; failed files are excluded from the merge
  purge set), and a transient-diff fallback to a full re-list now recovers
  deletions by diffing known doc paths against the current tree instead of
  silently leaving `deleted=[]`. `get_head_sha()` in the staleness check also
  runs via `to_thread` instead of blocking the loop.
  (`app/knowledge/pipeline_runner.py`, `app/core/orchestrator.py`)
- **Config hardening.** `SSH_HOST_KEY_POLICY` rejects unknown values
  (`disabled | tofu | strict`), `ORCHESTRATOR_MAX_RESULT_CORRECTIONS` must be
  `>= 0`, and `.env.example` documents the correct SSH policy values. Note:
  `QUERY_EMPTY_RESULT_RETRY` now defaults to `True` (an empty result is treated
  as suspicious and retried once within the correction budget). (`app/config.py`,
  `backend/.env.example`)
- **`cleanup_idle()` is called once.** The shared tunnel manager's idle sweep
  ran once per connector module aliasing it; `main.py` now invokes it a single
  time. (`app/main.py`)
- **Session-note conflict rules aligned with learnings (R4-5).** Note
  reconciliation now uses the strict `>` tie rule and same-polarity conflict
  detection used by learnings, so a verified incumbent can't leave a new
  contradicting note active.

### Indexing integrity

- **Incremental code-graph runs no longer wipe the graph.**
  `CodeGraphService.save()` does a full project-wide delete+reinsert; on an
  incremental run only changed files are parsed, so the graph collapsed to
  that subset and corrupted M5 lineage / M6 clustering for unchanged files.
  Added `save_incremental()` / `_merge_graphs()` that preserve unchanged
  files, replace changed ones, and drop deleted ones; the pipeline runner
  calls it on incremental runs and rehydrates the merged graph for M5/M6.
- **Partial doc-generation failures no longer leave permanent KB holes.**
  Failed paths are persisted (`project_cache.failed_doc_paths_json`, migration
  `68aa15e554e2`) and re-queued into `changed_files` on the next index run,
  then cleared once they succeed.
- **Binary-skipped docs are retried instead of silently lost (R3-7).** A doc
  the `_is_binary_content` heuristic flags is now appended to
  `failed_doc_paths` (and a failure to persist that queue logs at `warning`,
  not `debug`), so a false-positive gets one more attempt on the next run
  instead of being dropped until a forced full re-index.
- **Schema-qualified BM25 doc IDs (R2-6).** The schema-retriever keyed BM25
  docs by the bare lowercased table name, so two same-named tables in
  different schemas (`public.users` / `analytics.users`) collided and one
  became unsearchable. IDs are now `{schema}.{table}`; `metadata["table_name"]`
  stays the bare name for downstream consumers.
- **Worker DB-index path parity (R2-6).** The ARQ `run_db_index` route now
  regenerates the project overview, runs data probes, and surfaces the
  `PARTIAL` evidence status — previously only the in-process fallback did, so
  Redis-backed deployments silently diverged. Index-completion logging also
  reads the returned `tables` key (the old `tables_indexed` never existed and
  always logged `None`).

### Learning / memory lifecycle

- **Compiled-prompt cache invalidation on dedup paths.** Confidence/confirm
  bumps on the exact-hash and fuzzy-dedup paths now invalidate the
  `AgentLearningSummary` cache (previously only new inserts did), so prompt
  ranking no longer served stale order.
- **`times_applied` is live again.** A thumbs-up now credits the learnings
  exposed for that answer as applied (symmetric with the V4 thumbs-down
  contradiction), restoring the ranking and slower-decay signals that had
  degraded to confidence-only because `apply_learning` had no caller.
- **Polarity-aware conflict resolution.** `lessons_contradict()` (negation
  parity + substantive content overlap) runs *before* the fuzzy merge so
  opposite-polarity lessons aren't merged; ties deactivate the older lesson
  and an outranked new lesson is stored inactive so two contradictory lessons
  never both feed prompts.
- **Decay/TTL run on an independent schedule.** A dedicated
  `_maintenance_loop` (`MAINTENANCE_INTERVAL_HOURS`, default 24) runs learning
  + session-note decay and insight TTL/decay regardless of whether backups are
  enabled; session-note decay also runs at startup now.
- **Session-note contradiction reconciliation (R4-6).** `create_note()` now
  runs `_reconcile_contradictions`, reusing the learning-side
  `lessons_contradict` heuristic to penalize (or retire, when the new note is
  verified/stronger) an existing active note that contradicts a new one for
  the same subject+category, so the agent prompt can't carry both sides.
- **Tighter table-scoped note filtering (R4-6).** `get_notes_for_context`
  matches table names on word boundaries (`\btable\b`) instead of a naive
  substring search, so "users" no longer pulls in notes about "power_users".
- **Bounded compile-lock map (R4-6).** The per-connection `_COMPILE_LOCKS`
  dict was unbounded and leaked one `asyncio.Lock` per connection touched over
  a process's lifetime. It's now an `OrderedDict` capped at 512 that evicts the
  oldest *unheld* lock (a held lock is never evicted, so in-flight critical
  sections are safe).

### Retrieval

- **Unified hybrid retrieval.** The orchestrator's pre-loaded knowledge now
  uses the shared BM25⊕Chroma+RRF path (bounded by the previously-dead
  `HYBRID_K`) instead of a Chroma-only lookup. Low-relevance dense hits are
  filtered by `RAG_RELEVANCE_THRESHOLD` before fusion.

### Orchestrator / pipeline

- **Raised the "20" caps.** `MAX_ORCHESTRATOR_ITERATIONS` corrected from 20 to
  the documented 100 (the wall-clock timeout already bounds requests); the
  LLM result preview is no longer hardcoded to 20 rows and reads
  `LLM_RESULT_PREVIEW_ROWS` (default raised 20 → 50).
- **Case-insensitive expected-column validation** removes spurious "missing
  column" stage failures from quoted/lowercased identifiers.
- **Router multi-source signal is acted on.** `needs_multiple_data_sources`
  now also routes to the multi-stage pipeline.
- **Partial data surfaced on `stage_failed`.** The last successful stage's
  query/results are attached and the number of completed stages is noted,
  instead of discarding all progress.
- **`process_data` defaults to `passthrough` (R5-8).** When no operation is
  given the stage executor no longer silently coerces to `filter_data` (which
  could drop rows against intent); it passes data through unchanged. The
  orchestrator's `LLMError` retry check also reads the correct `is_retryable`
  attribute (was the non-existent `retryable`, so retryable LLM errors were
  never retried).
- **`connection_string` + `ssh_host` footgun documented (R1-7).** Supplying a
  raw `connection_string` bypasses SSH tunneling; the combination now warns so
  operators don't assume a tunnel is in effect.

### Knowledge freshness

- `get_head_sha()` no longer blocks the event loop (run via `to_thread`), and
  `count_commits_ahead()`'s `-1` error sentinel no longer surfaces as
  "-1 commit(s) behind".

## [1.13.1] - 2026-06-01

### CI/Deploy Restoration & Toolchain Pinning

Restores a green CI pipeline (and therefore the gated Heroku deploy, which
only runs on `workflow_run` success). CI had been red since early May: the
unpinned dev tooling (`ruff>=0.8.0`, `mypy>=1.13.0`) silently drifted to
newer releases that reformat code and add stricter type rules, so the
`Format check` step failed on commits that never touched the affected files,
and the downstream `Type check`/tests never even ran (fail-fast). Because
`deploy.yml` is triggered by CI success, every Heroku release was skipped.

- **Pinned linters/type-checkers to exact versions** (`ruff==0.15.15`,
  `mypy==2.1.0`) so formatter output and type rules can no longer drift
  between unrelated commits. Bumps are now deliberate.
  (`backend/pyproject.toml`)
- **Reformatted 16 drifted files** with the pinned `ruff` so
  `ruff format --check` passes. Purely cosmetic (line collapsing within the
  100-char limit). (`app/agents/{orchestrator,sql_agent,knowledge_agent}.py`,
  `app/knowledge/{bm25_index,code_db_sync_pipeline,code_graph,graph_db_bridge,hybrid_retriever}.py`,
  `app/models/code_graph.py`, `app/services/code_graph_service.py`, and tests)
- **Resolved 24 `mypy` errors** surfaced by the newer type checker:
  - Fixed a **real runtime bug**: `GET /investigate/{id}` referenced
    `DataInvestigation.current_step`, a column that does not exist, which
    would raise `AttributeError` on every call. The response now mirrors the
    backing `phase` field. (`app/api/routes/data_investigations.py`)
  - Supplied the missing value type-arg on `TTLCache[...]` annotations
    (`app/core/cache.py`, `app/agents/{sql_agent,knowledge_agent}.py`).
  - Switched `Model.__table__.update()` to the typed `update(Model)`
    construct (`app/services/code_graph_service.py`).
  - Added the established `# type: ignore[attr-defined]` for SQLAlchemy
    `Result.rowcount` in the two services that lacked it; disambiguated
    reused loop variables; narrowed dynamic tree-sitter node/grammar types;
    removed three now-unused `# type: ignore` comments.
- **Made the `pg_dump` backup test hermetic.** `test_pg_dump_failure`
  patched `subprocess.run`, but the code pipes `pg_dump` into `gzip` via
  `subprocess.Popen`, so the patch was a no-op and the test only passed when
  a `pg_dump` binary happened to be installed (it errored otherwise). It now
  patches `subprocess.Popen` and is deterministic.
  (`backend/tests/unit/test_backup_manager_extended.py`)
- **Bumped GitHub Actions to their Node 24-native majors**
  (`checkout@v5`, `setup-python@v6`, `setup-node@v6`, `cache@v5`,
  `upload-artifact@v7`) ahead of the June 2 2026 Node 20 deprecation.
  (`.github/workflows/ci.yml`, `.github/workflows/deploy.yml`)
- **Stabilized flaky `RulesManager` frontend tests.** The `Save` button is
  rendered inside a `FormModal` gated on `editingId`; under CI load the
  default real-timer `userEvent` typing interleaved with the modal's focus
  effects and intermittently closed the editor mid-test. Switched the
  interactive tests to the recommended `userEvent.setup({ delay: null })`
  pattern so interactions flush synchronously inside `act()`.
  (`frontend/src/__tests__/components/RulesManager.test.tsx`)

Full suite remains green (3,178 backend unit + 470 backend integration +
400 frontend); combined backend coverage 73%.

## [1.13.0] - 2026-05-19

### Vision Invariants & Correctness Restoration

This release closes four vision invariant violations and six critical
correctness bugs identified during the post-1.12.x cross-subsystem audit.
Every change is paired with focused unit tests; full suite remains green
(3,648 backend / 400 frontend, up from 3,599 / 400 baseline). The release
is single-feature in spirit: it makes the system actually behave the way
vision.md, SYSTEM_ARCHITECTURE.md, and the README have been claiming it
behaves.

### Vision invariants restored

- **V1 — Per-connection learning isolation by default.** A lesson learned
  on connection A is no longer silently injected into prompts for
  connection B. `AgentLearningService.compile_prompt()` now gates
  `_get_cross_connection_learnings()` and `promote_global_patterns()`
  behind the new `CROSS_CONNECTION_LEARNINGS_ENABLED` flag (default
  `False`). The old behavior, where two unrelated databases in the same
  project could poison each other's learnings, is now opt-in for
  homogeneous-schema customers. (`backend/app/services/agent_learning_service.py`,
  `backend/app/config.py`, `backend/.env.example`,
  `backend/tests/unit/test_agent_learning_service.py::TestCompilePromptCrossConnection`)
- **V2 — Continuous learning on every outcome, not just every retry.** The
  `len(attempts) < 2` gate that suppressed learning extraction on
  first-shot successes and first-shot failures is removed from both
  `SQLAgent._extract_learnings` and `ToolExecutor._extract_learnings`. The
  `LearningAnalyzer` cooldown is reduced from 1 h to 5 min, a lightweight
  heuristic `_extract_first_shot_success_signal` captures
  "what worked the first time" patterns (e.g., soft-delete filters, key
  joins), and lesson persistence is unified through `_persist_lessons`.
  The system now learns from every attempt, not only from messy ones.
  (`backend/app/agents/sql_agent.py`, `backend/app/core/tool_executor.py`,
  `backend/app/knowledge/learning_analyzer.py`,
  `backend/tests/unit/test_learning_analyzer_extended.py`,
  `backend/tests/unit/test_sql_agent.py`)
- **V3 — Staleness warning threaded through the complex pipeline.** The
  freshness banner used to die at the orchestrator boundary: planner LLM
  calls and stage-executor sub-agents never saw it. Both
  `AdaptivePlanner._llm_plan` / `replan` and `StageExecutor.execute` now
  accept a `staleness_warning` argument and prepend it to their own
  system / stage prompts, so every LLM call in the complex pipeline —
  initial plan, re-plan, every stage, final synthesis — sees the
  freshness block, not just `_run_tool_loop`. (`backend/app/agents/orchestrator.py`,
  `backend/app/agents/adaptive_planner.py`,
  `backend/app/agents/stage_executor.py`,
  `backend/tests/unit/test_adaptive_planner_staleness.py`,
  `backend/tests/unit/test_stage_executor.py::TestStalenessInjection`)
- **V4 — Negative feedback overrides prior learnings.** Assistant
  responses now record which learnings were exposed in their system
  prompt via `AgentResponse.exposed_learning_ids`, the chat route writes
  the list into message metadata on both the synchronous and SSE paths,
  and the `/feedback` endpoint reads it back. On a thumbs-down, the new
  helper `contradict_exposed_learnings_on_negative_feedback` calls
  `contradict_learning(...)` on each ID (capped to avoid cascades), so
  the very next turn no longer trusts the lessons that produced the bad
  answer. (`backend/app/agents/orchestrator.py`,
  `backend/app/core/agent.py`, `backend/app/api/routes/chat.py`,
  `backend/tests/unit/test_negative_feedback_contradiction.py`)

### Critical correctness fixes

- **C1 — Git rename handling.** `GitTracker.get_changed_files` switched
  from `R=True` to `M=True` on `repo.commit(...).diff()` so renames are
  detected with the correct `--find-renames` semantics; old paths are
  classified as `deleted` and new paths as `changed`, fixing a class of
  silent drift between the indexed graph and the working tree.
  (`backend/app/knowledge/git_tracker.py`,
  `backend/tests/unit/test_git_tracker.py`)
- **C2 — `generate_docs` resilience.** Per-doc LLM failures used to
  abort the indexing pipeline. `pipeline_runner.generate_docs` now uses
  `asyncio.gather(..., return_exceptions=True)` with per-doc retry, and
  only fails the whole step when the failure ratio exceeds the new
  `GENERATE_DOCS_MAX_FAILURE_RATIO` setting (default `0.3`). One bad
  file no longer takes the whole index down. (`backend/app/knowledge/pipeline_runner.py`,
  `backend/app/config.py`, `backend/.env.example`,
  `backend/tests/unit/test_generate_docs_resilience.py`)
- **C3 — Chroma failure policy.** The vector-store health check used to
  treat "Chroma collection is empty" and "Chroma is unreachable"
  identically, causing partial re-indexes on transient network blips.
  The check now distinguishes the two: an empty-but-reachable collection
  forces a full re-index, while an unreachable Chroma warns and
  preserves the previous `last_sha` so the next pipeline run resumes
  cleanly when the service comes back. (`backend/app/knowledge/pipeline_runner.py`,
  `backend/tests/unit/test_pipeline_chroma_failure_policy.py`)
- **C4 — `DataGate.fail()` path.** Out-of-range percentages and dates
  were classified as warnings, so plainly impossible numbers reached the
  final synthesis. `_check_value_ranges` now calls `outcome.fail()` on
  hard violations when `DATA_GATE_HARD_CHECKS_ENABLED` (default `True`)
  is on, blocking obviously wrong results before they're rendered.
  (`backend/app/agents/data_gate.py`, `backend/app/config.py`,
  `backend/.env.example`, `backend/tests/unit/test_data_gate.py`)
- **C5 — Read-only `get_agent_learnings`.** Loading learnings for a
  prompt used to mutate `times_applied`, conflating "the LLM saw it"
  with "the LLM used it." A new `times_exposed` column (Alembic
  migration `f0a1b2c3d4e5_add_times_exposed_to_agent_learning`) tracks
  exposure separately, `SQLAgent._track_exposed_learnings` calls the new
  `expose_learning` service method, and the exposed IDs are stashed into
  `ctx.extra["exposed_learning_ids"]` for V4 to pick up. `times_applied`
  is now reserved for confirmed application by the learning analyzer.
  (`backend/app/models/agent_learning.py`,
  `backend/app/services/agent_learning_service.py`,
  `backend/app/agents/sql_agent.py`,
  `backend/app/alembic/versions/f0a1b2c3d4e5_add_times_exposed_to_agent_learning.py`)
- **C6 — Insight expiry + decay actually run.** `InsightRecord.expires_at`
  and the `decay_stale_insights` job existed but nothing called them.
  The new `_periodic_insight_maintenance` task runs on every backup-cron
  tick (~24 h) and once on startup, calling `expire_old_insights` and
  `decay_stale_insights`. Insight TTL+confirmation semantics now
  actually happen. (`backend/app/main.py`,
  `backend/tests/unit/test_periodic_insight_maintenance.py`)

### Config additions

| Setting | Default | Purpose |
|---|---|---|
| `CROSS_CONNECTION_LEARNINGS_ENABLED` | `False` | Opt-in for cross-connection learning transfer + global pattern promotion (V1). |
| `GENERATE_DOCS_MAX_FAILURE_RATIO` | `0.3` | Per-doc LLM failure ratio at which `generate_docs` aborts (C2). |
| `DATA_GATE_HARD_CHECKS_ENABLED` | `True` | When true, out-of-range percent/date checks call `outcome.fail()` instead of `warn()` (C4). |

### Schema

- `agent_learnings.times_exposed INTEGER NOT NULL DEFAULT 0` — added via
  Alembic revision `f0a1b2c3d4e5`.

### Tests

- **Backend**: 3,648 passing (up from 3,599 baseline). 49 new tests added
  across `test_adaptive_planner_staleness.py`,
  `test_stage_executor.py::TestStalenessInjection`,
  `test_negative_feedback_contradiction.py`,
  `test_generate_docs_resilience.py`,
  `test_pipeline_chroma_failure_policy.py`, `test_data_gate.py`,
  `test_periodic_insight_maintenance.py`, plus updates to
  `test_agent_learning_service.py`, `test_sql_agent.py`,
  `test_learning_analyzer_extended.py`, `test_git_tracker.py`,
  `test_orchestrator.py`.
- **Frontend**: 400 passing (unchanged — release is backend-only).

## [1.12.3] - 2026-05-18

### Changed — Documentation actualization (no code, no schema, no flag flips)

A docs-only pass that closes every doc-vs-code gap surfaced during the
post-1.12.2 Heroku audit, plus consolidates the M1-M6 follow-ups into the
strategic backlog so they stop living only inside the rollout playbook.

**Doc-vs-code accuracy fixes**

- **`docs/SYSTEM_ARCHITECTURE.md` §2.4** rewritten — the old narrative
  pointed at `app/agents/intent_classifier.py::classify_intent()` and
  `prompts/orchestrator_prompt.py::build_classification_prompt()`, none of
  which exist. Routing now goes through the unified LLM router in
  `backend/app/agents/router.py` (`_build_router_prompt()`,
  `route_request()`, `RouteResult` dataclass with `route` + `complexity`
  in a single call). Section reflects the actual route list (`direct` /
  `query` / `knowledge` / `mcp` / `explore`) and complexity tag.
- **`ARCHITECTURE.md` Knowledge Indexing Flow** reordered to match
  `pipeline_runner.py`: `ast_parse` and `graph_build` (M1+M2) now precede
  `analyze_files` / EntityExtractor instead of being listed after. Added
  `record_index` final step, the `CodeGraphService.load_graph()`
  rehydration path that fires on M5/M6 resume, and the
  `services/indexing_artifacts.py` cleanup contract on project/connection
  delete.
- **`ARCHITECTURE.md` module table** — extended the `knowledge/` and
  `services/` rows with the modules that shipped during M1-M6
  (`pipeline_runner.py`, `db_index_pipeline.py`, `ast_parser.py`,
  `code_graph.py`, `bm25_index.py`, `hybrid_retriever.py`,
  `schema_retriever.py`, `code_db_sync_analyzer.py`,
  `code_graph_service.py`, `knowledge_freshness_service.py`,
  `indexing_artifacts.py`).
- **`docs/ROLLOUT_M1_M6.md` §2.1** — replaced an invalid + unsafe SQL
  smoke command (`xargs -I{} psql {} -c "… COUNT(*) FROM a, COUNT(*) FROM
  b …"`, which both leaked `DATABASE_URL` into `ps` and was malformed
  SQL) with `heroku pg:psql -a checkmydata-api -c "SELECT (SELECT
  COUNT(*) FROM …) …"` using subqueries.
- **`docs/ROLLOUT_M1_M6.md` §2.5** — renamed prose `has_clusters` →
  `has_code_clusters` to match the actual identifier in
  `sql_agent.py` / `sql_prompt.py` / `sql_tools.py`.
- **`docs/ROLLOUT_M1_M6.md` §4.2** — converted the brittle line-anchored
  cleanup-PR table (`pipeline_runner.py:406`, `sql_agent.py:1887`, …) to
  stable `grep -n "<predicate>"` markers so the inventory survives normal
  line drift.
- **`docs/MASTER_TEST_PLAN.md`** — fixed `POST /api/chat/stream` →
  `POST /api/chat/ask/stream` (the actual route in
  `backend/app/api/routes/chat.py`).
- **`README.md`** — `LEARNING_ANALYZER_MODE` default `hybrid` →
  `llm_first` (matches `backend/app/config.py:225`); test count `3,309
  total` → `3,999 total (3,129 backend unit + 470 backend integration +
  400 frontend)` (verified via `pytest --collect-only`); added the
  `make rollout-check` row to the Development Commands table; added a
  paragraph each on `indexing_artifacts.py`, the `staleness_warning`
  injection, and the `graph_callers` lineage rendering in the M1-M6
  summary section.
- **`CHANGELOG.md` 1.x historical entry** — corrected
  `learning_analyzer_mode` default note from `"hybrid"` to `"llm_first"`
  for consistency with code.

**New documentation (shipped behavior that previously had no docs)**

- **`docs/SYSTEM_ARCHITECTURE.md` §2.6.1 — Knowledge Freshness Warning
  Injection** — describes how `KnowledgeFreshnessService.check_staleness()`
  feeds a `KNOWLEDGE FRESHNESS WARNINGS` block into both the simple
  tool-calling loop and the multi-stage pipeline orchestrator messages,
  with the code-graph-conditional behavior gated by
  `settings.code_graph_enabled`.

**Backlog consolidation (BACKLOG.md, ROADMAP.md)**

- **`BACKLOG.md` Sprint 8 — M1-M6 rollout completion** (P0, blocked by
  2-week per-flag soak): seven tasks covering the five default flips and
  the post-soak cleanup PR (flag-gate removal + prompt-builder kwarg
  removal), with an explicit non-removal list (preserve
  `_dense_only_search`, ABC stubs, per-request flag overrides).
- **`BACKLOG.md` Sprint 9 — Test coverage gaps** (P2): eight tasks
  covering the full-pipeline E2E with a real fixture repo, incremental
  indexing, binary-file filtering, hybrid-retrieval relevance smoke,
  `KnowledgeDocs` / `WorkflowProgress` component tests, a11y matrix
  execution + fixes, and the 72% → 80% coverage threshold flip.
- **`BACKLOG.md` Sprint 10 — Documented "for now" debts** (P2/P3): seven
  tasks covering the planner-LLM table-routing replacement, optional
  Chroma extension for `SchemaRetriever`, incremental per-file
  code-graph updates, multi-language receiver-type resolution,
  multi-repo cross-repo code graph, and the
  `query_empty_result_retry` / `data_gate_llm_semantics` opt-in flags.
- **`ROADMAP.md`** — new "Architectural Debt & Rollout-Gated Cleanups"
  subsection pointing at the rollout playbook and Sprints 8/9/10 so a
  casual roadmap reader finds the M1-M6 story.

**Heroku audit snapshot (informational, no action)**

- Release **v129** (`b13f530`), web dyno up 10h+, `/api/health` = 200.
- 38h of production logs (1500 lines): **0** app-level WARNING / ERROR /
  CRITICAL / exception lines from `app[web.1]`.
- Router warnings limited to expected SSE client disconnects (`H27`) on
  `/api/workflows/events`; 1 × `H18` over 38h (single 1133s SSE backend
  interruption — not a defect).
- No production fix needed; documentation was the only out-of-sync piece.

### Notes

- **No** source edits under `backend/app/**` or `frontend/src/**`.
- **No** Alembic migrations, **no** schema changes.
- **No** `heroku config:set`, **no** flag flips, **no** dyno restart.
- The M1-M6 feature flags still default to `False` per [docs/ROLLOUT_M1_M6.md](docs/ROLLOUT_M1_M6.md); the operator drives the rollout (see Sprint 8).

## [1.12.2] - 2026-05-17

### Added — M1-M6 rollout playbook

Closes the final M1-M6 plan item (`rollout`). Every milestone has shipped
to production (v129, commit `b13f530`); all five feature flags still
default to `False`. This release ships the operator-facing artifacts to
safely flip them.

- **`docs/ROLLOUT_M1_M6.md`** — per-flag canary criteria, smoke tests,
  daily soak metrics with healthy/alarm bands, rollback commands, and a
  precise file:line inventory of the legacy branches the post-soak
  cleanup PR will delete (plus an explicit "do not delete" list for the
  load-bearing fallbacks like `_dense_only_search` and the
  `relevance_score` safety net).
- **`make rollout-check`** — one-command production health snapshot
  (flag state, dyno state, `/api/health`, and `code_graph_*` counters
  via JSON `/api/metrics`). Accepts `ADMIN_TOKEN` and `HEROKU_APP`
  overrides for staging.
- **README** — links to the playbook from the M1-M6 feature section.

The rollout itself (`code_graph_enabled` → `hybrid_retrieval_enabled` →
`schema_retrieval_enabled` → `lineage_enabled` → `clustering_enabled`,
each with a 2-week soak) is the operator's job from here. The status
table at the bottom of `ROLLOUT_M1_M6.md` is the canonical record.

## [1.12.1] - 2026-05-15

### Fixed — M1–M6 integration audit

Concrete bugs + wiring gaps surfaced by an end-to-end audit of the
M1–M6 code-intelligence pipeline against the consumer-facing surfaces
(orchestrator, SQL agent, knowledge agent, CodeDbSyncAnalyzer). Each
flag now flips cleanly to `True` without leaking artifacts or silently
serving stale data.

- **Broken `get_settings` import** in `db_index_pipeline.py` schema-embed
  step would have silently aborted M4 the moment `schema_retrieval_enabled`
  flipped to `True`. Replaced with the canonical `settings` singleton.
- **Orphan artifact lifecycle**: `ProjectService.delete`,
  `ConnectionService.delete`, and `DbIndexService.delete_all` now invoke a
  new `app/services/indexing_artifacts.py` helper to wipe the BM25 `.pkl`
  snapshots (code corpus + schema) and the ChromaDB collection that used to
  outlive their parent Postgres rows.
- **Checkpoint integrity**: `bm25_build` and `graph_clustering` now only
  call `complete_step` on actual success. A failed step no longer fools a
  later resume into thinking the artifact is fresh.
- **Code graph rehydration on resume**: when `ast_parse` collects no files
  (incremental run) or `graph_build` raises, `state.code_graph` was `None`
  and M5/M6 silently skipped. `CodeGraphService.load_graph` now reconstructs
  the in-memory `CodeGraph` from persisted rows so lineage + clustering can
  still run from existing data.
- **Staleness warning now reaches the LLM**: the orchestrator's unified
  tool loop appends a `KNOWLEDGE FRESHNESS WARNINGS` section to the system
  prompt, and the complex pipeline path now computes the same signal
  instead of passing `None`.
- **`graph_callers` rendered in `KnowledgeAgent`**: `_format_entity_detail`
  surfaces the M5 lineage block (caller name / file / endpoint kind / op
  kind / confidence) when `lineage_enabled=True`.
- **Prompts taught the new capabilities** so the model actually uses them:
  - `sql_prompt.py` documents question-aware ranking (M4), the
    `Lineage (top callers)` block (M5), and the `get_tables_in_cluster`
    tool (M6).
  - `knowledge_prompt.py` explains hybrid retrieval (BM25 ⊕ vectors fused
    via RRF) and the entity lineage section.
  - `code_db_sync_analyzer.py` system prompt instructs the LLM to derive
    `required_filters` / `column_value_mappings` from the new "Code
    callers" section.
  - `get_query_context` tool description now describes question-aware
    table ranking and the inline lineage block.
- **`MetricsCollector.snapshot_counters(prefix=...)`** + JSON `/api/metrics`
  now exposes `code_graph_*` counters without scraping Prometheus.
- **Tests**: 6 new integration assertions in `test_indexing_e2e.py` cover
  prompt rendering, entity-detail lineage, code-graph rehydrate, cleanup
  idempotency, and metrics prefix filtering. Suite total: 3,309.

## [1.12.0] - 2026-05-11

### Added — In-house code intelligence pipeline (M1–M6)

A GitNexus-inspired layer that augments (does not replace) our existing 5-pass
ORM/SQL pipeline. All milestones ship behind feature flags and degrade
gracefully to legacy behavior when disabled.

- **M1 — AST parser**: `app/knowledge/ast_parser.py` wraps `tree-sitter` +
  `tree-sitter-language-pack` to extract `Symbol` / `ImportRef` / `CallSite` /
  `ParsedFile` records for Python, JS/TS, Go, Java, Ruby, PHP, C#. File-size
  guard, binary/minified detection, parse-error ratio threshold, async
  semaphore in the pipeline. Flag: `code_graph_enabled`.
- **M2 — Code knowledge graph**: `app/knowledge/code_graph.py` two-pass
  builder produces a NetworkX `CodeGraph` (CALLS/IMPORTS/EXTENDS edges with
  confidence scores). Persisted via `app/services/code_graph_service.py` to
  new `code_graph_symbols` + `code_graph_edges` tables (Alembic
  `d8e9f0a1b2c3`).
- **M3 — Hybrid retrieval**: `app/knowledge/bm25_index.py` (rank_bm25 with
  code-aware tokenizer + atomic snapshots on disk) and
  `app/knowledge/hybrid_retriever.py` (BM25 ⊕ Chroma fused with Reciprocal
  Rank Fusion, soft timeouts, graceful single-leg degradation).
  `KnowledgeAgent._handle_search_knowledge` now uses the hybrid path when
  `hybrid_retrieval_enabled=true`. Flag: `hybrid_retrieval_enabled`.
- **M4 — Question-aware table resolution**:
  `app/knowledge/schema_retriever.py` builds a per-connection BM25 snapshot of
  LLM-enriched schema docs. `SQLAgent._build_query_context` unions retrieved
  tables with the legacy `relevance_score >= 2` safety net, bounded by
  `sql_agent_max_context_tables`. Flag: `schema_retrieval_enabled`.
- **M5 — Code→DB lineage**: `app/knowledge/graph_db_bridge.py` walks the code
  graph outward from each entity, classifies callers as
  `http`/`cli`/`migration`/`service` and ops as `read`/`write`, decays
  confidence with depth, and writes the top-N refs onto
  `EntityInfo.graph_callers`. Consumed by `CodeDbSyncAnalyzer` and rendered
  by `SQLAgent._format_table_context`. Flag: `lineage_enabled`.
- **M6 — Functional clustering**: `app/knowledge/code_clustering.py` runs
  Louvain community detection on the weighted CALLS+IMPORTS graph,
  optionally LLM-labels clusters in batches of 10, and persists to a new
  `code_clusters` table (Alembic `e9f0a1b2c3d4`). SQL agent exposes a new
  `get_tables_in_cluster` tool. Flags: `clustering_enabled`,
  `cluster_llm_label_enabled`.
- **Observability**: `KnowledgeFreshnessService` now surfaces a
  `code_graph_symbol_count` signal (warns when the graph is empty).
  `MetricsCollector` grew a generic `inc()` / `add()` API; new counters:
  `code_graph_symbols_total`, `code_graph_edges_total`,
  `code_graph_lineage_refs_total`, `code_graph_clusters_total`,
  `code_graph_builds_total`. Visible via `/api/metrics` and
  `/api/metrics/prometheus`.

### Added (files)
- `backend/app/knowledge/ast_parser.py`, `code_graph.py`, `bm25_index.py`,
  `hybrid_retriever.py`, `schema_retriever.py`, `graph_db_bridge.py`,
  `code_clustering.py`.
- `backend/app/models/code_graph.py` (extended with `CodeCluster`).
- `backend/app/services/code_graph_service.py` (extended with cluster ops).
- Alembic migrations `d8e9f0a1b2c3_add_code_graph_tables.py`,
  `e9f0a1b2c3d4_add_code_clusters_table.py`.
- Tests: `tests/unit/test_ast_parser.py`, `test_code_graph.py`,
  `test_bm25_index.py`, `test_hybrid_retriever.py`, `test_schema_retriever.py`,
  `test_graph_db_bridge.py`, `test_code_clustering.py`,
  `test_entity_info_graph_callers.py`; integration:
  `tests/integration/test_code_graph_service.py`,
  `test_schema_retriever_integration.py`,
  `test_graph_db_bridge_integration.py`, **`test_indexing_e2e.py`** (full
  M1→M6 chain).

### Changed
- `backend/pyproject.toml`: pinned `tree-sitter>=0.23.0,<0.24` +
  `tree-sitter-language-pack>=0.7.3,<1.0`, added `networkx`, `rank-bm25`.
- `backend/app/agents/knowledge_agent.py`: hybrid retrieval branch
  preserving the legacy "no relevant" / "no sufficiently relevant" message
  distinction.
- `backend/app/agents/sql_agent.py`: schema-retriever union, lineage
  formatting, cluster lookup tool wiring.
- `backend/app/agents/tools/sql_tools.py`: new
  `GET_TABLES_IN_CLUSTER_TOOL` (gated by `has_code_clusters`).
- `backend/app/knowledge/entity_extractor.py`: `EntityInfo.graph_callers`.
- `backend/app/knowledge/code_db_sync_pipeline.py`: caller groups in the
  code-context prompt.
- `backend/app/services/knowledge_freshness_service.py`: empty-graph signal.
- `backend/app/core/metrics.py`: generic `inc`/`add` API.
- `backend/.env.example` & `app/config.py`: new flags
  `code_graph_enabled`, `ast_parse_concurrency`, `ast_max_file_bytes`,
  `ast_parse_error_ratio`, `code_graph_max_symbols`,
  `code_graph_call_confidence_threshold`, `hybrid_retrieval_enabled`,
  `bm25_data_dir`, `hybrid_rrf_k`, `hybrid_min_score`, `hybrid_k`,
  `schema_retrieval_enabled`, `sql_agent_max_context_tables`,
  `lineage_enabled`, `lineage_max_depth`, `clustering_enabled`,
  `cluster_llm_label_enabled`.

### Notes
- All flags default `false` for a 2-week soak. Per-feature rollout planned;
  legacy paths will be deleted in a separate cleanup PR once the new
  pipeline holds in production.

## [1.11.0] - 2026-05-05

### Changed — AI-First Refactor: Infra & Deploy (T33–T40)
- **Multi-stage backend image (T33)**: `Dockerfile.backend` now builds deps in an isolated builder stage and ships them through a venv into a minimal runtime; added `HEALTHCHECK` against `/api/health`. `.do/app.yaml` aligned with DigitalOcean's `$PORT` convention (`http_port: 8080`) and the platform health-check schedule.
- **DB indexes (T34)**: Alembic `c7d8e9f0a1b2` adds `ix_connections_project_id` and `ix_projects_owner_id` to back the `list_by_project` / `get_accessible_projects` hot paths. SQLAlchemy models declare `index=True` for parity.
- **Config drift guard (T35)**: rewrote `backend/.env.example` to mirror every `Settings` field (commented when optional); added `TestEnvExampleSync` to fail CI if a new setting forgets a doc entry. `Settings._validate_production_secrets` now also rejects short JWTs (<32 chars), `DEBUG=true`, and `*` in `CORS_ORIGINS`. New `_validate_numeric_ranges` validator fences invalid percentages, learning-analyzer mode, and default LLM provider.
- **CI hardening (T36)**: `ci.yml` now caches HuggingFace / sentence-transformer downloads + pytest cache + Next.js build cache, runs unit and integration tests under a single `coverage append` flow, enforces a combined coverage gate (`--fail-under=40`), uploads the combined `coverage-combined.xml` as an artifact, and uses concurrency cancellation per ref.
- **Test gap closure (T37)**: added `frontend/src/__tests__/usePolling.test.tsx` (6 cases: interval, leading, disabled, max-duration cap, unmount cleanup, error swallowing) and `frontend/src/__tests__/pipeline-event-handlers.test.ts` (11 cases covering every SSE event type → state transition).
- **Regression sweep (T38)**: full backend (`3007 unit + 453 integration`) and frontend (`400 vitest`) suites green. Updated `test_edge_cases.py` and `test_routes_coverage.py` to grant admin via `monkeypatch.setattr(settings, "admin_emails", …)` for routes hardened in T01/T03.
- **Deploy (T39–T40)**: green release pushed to Heroku; production rollout guarded by combined CI coverage gate + container HEALTHCHECK.

### Added
- `backend/alembic/versions/c7d8e9f0a1b2_add_tenancy_hot_path_indexes.py`.
- `frontend/src/__tests__/usePolling.test.tsx`, `frontend/src/__tests__/pipeline-event-handlers.test.ts`.

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
- `learning_analyzer_mode` config (default `"llm_first"`).
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
