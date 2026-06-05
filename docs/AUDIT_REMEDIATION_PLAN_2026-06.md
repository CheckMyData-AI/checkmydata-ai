# Audit Remediation Plan — 2026-06

Prioritized, triaged output of the full project audit (5 business-logic modules).
Each finding below was **confirmed by reading current `main`** (file:line cited).
Status legend:

- **CONFIRMED** — real defect, reproduced against code on `main`.
- **REFUTED** — claimed in the audit roadmap but not a real defect (kept here for the record).
- **INTENDED** — works as designed; documented as a footgun / policy decision, not a bug.

Severity: **P0** = correctness / data-integrity / security · **P1** = degrades quality / reliability · **P2** = cleanup / consistency.

> Verification phase only produced this document — no code was changed. Implementation is a separate pass.

---

## Top-line verdict on the validation / replan / retry loop (the thing you asked about)

- **Complex pipeline path** has a real result-validation → correct → retry loop:
  `StageExecutor._process_one_stage` validates, then `_retry_failed_validation`
  (`max_stage_retries=2`), plus pipeline replan (`max_pipeline_replans=2`) and SQL-level
  `ValidationLoop` + `QueryRepairer` (`query_max_retries=3`). **This is solid.**
- **Unified tool-loop path** (where most simple/moderate questions go) has **no
  orchestrator-level result-quality gate**. The loop appends tool text and re-prompts
  the LLM with no "this result looks wrong → re-query" step
  ([orchestrator.py](../backend/app/agents/orchestrator.py) L1054-1088). **This is the
  iteration to add (R5-3 below).**

---

## P0 — fix first

### R1-1 · Connector pool cache key omits credentials (cross-connection leak) — CONFIRMED
- `connector_key()` keys on type/host/port/db + ssh flags only — no `db_user`,
  `db_password`, or `connection_id` ([base.py](../backend/app/connectors/base.py) L32-42).
- The pool lives on the **process-wide singleton** `SQLAgent` (`_agent = ConversationalAgent()`,
  [chat.py](../backend/app/api/routes/chat.py) L48 → `OrchestratorAgent._sql` →
  `SQLAgent._connectors`, [sql_agent.py](../backend/app/agents/sql_agent.py) L107, L1253-1273).
- **Impact:** two `Connection` rows for the same host/port/db with different users/passwords
  share one pooled connector — the second silently runs under the first's credentials.
- **Fix:** include a credential/`connection_id` discriminator in `connector_key()` (hash the
  secret, don't store it). Audit all `connector_key()` call sites (orchestrator/tool_executor
  legacy copies too).

### R2-1 · Postgres materializes the full result set before capping — CONFIRMED
- `execute_query` does `conn.fetch(query)` then slices to `MAX_RESULT_ROWS`
  ([postgres.py](../backend/app/connectors/postgres.py) L84-95). Wide/no-LIMIT tables load
  fully into memory first.
- **Fix:** stream with a server-side cursor (`conn.cursor`) and stop at `MAX_RESULT_ROWS + 1`
  to detect truncation without loading everything.

### R3-1 · Incremental graph merge keeps edges by SOURCE only → dangling edges — CONFIRMED
- `_merge_graphs` keeps an existing edge when its **source** file is unaffected, but the
  **destination** symbol may have been removed/renamed in a changed file
  ([code_graph_service.py](../backend/app/services/code_graph_service.py) L150-153).
- **Impact:** edges from unchanged callers point at deleted UIDs after an incremental run
  (regression introduced by the recently shipped incremental merge).
- **Fix:** after merge, drop edges whose `dst_uid` (and `src_uid`) is not in the merged
  symbol set; or re-validate edge endpoints before persisting.

### R3-2 · Every `save()` wipes `cluster_id`, and `save_incremental` ends in `save()` — CONFIRMED
- `save()` hardcodes `"cluster_id": None` for all symbols
  ([code_graph_service.py](../backend/app/services/code_graph_service.py) L71); `save_incremental`
  finishes by calling `save(merged)` (L121).
- **Impact:** every incremental indexing run zeroes cluster membership until M6 clustering
  re-runs successfully in the same pipeline; transient loss of cluster-driven context.
- **Fix:** preserve existing `cluster_id` on merge/save (carry it on `Symbol`), or only clear
  cluster_id for affected files.

### R4-1 · Feedback can't attribute to preloaded learnings — CONFIRMED (worse than reported)
- Compiled learnings are injected via `get_or_compile_summary`
  ([sql_agent.py](../backend/app/agents/sql_agent.py) L167-169, L1417-1424); when preloaded the
  `get_agent_learnings` tool is omitted ([sql_tools.py](../backend/app/agents/tools/sql_tools.py)
  L331-332).
- `exposed_learning_ids` **and** `times_exposed` are only set inside the tool handler
  (`_track_exposed_learnings`, [sql_agent.py](../backend/app/agents/sql_agent.py) L733, L1659-1691).
- **Impact:** on the common preloaded path, thumbs up/down has no IDs to credit/contradict —
  the entire learning-quality signal is mostly inert; `times_exposed` never bumps either.
- **Fix:** have `_load_learnings_prompt` return the learning IDs it compiled and call
  `_track_exposed_learnings` (or stash IDs on `ctx.extra`) so feedback can attribute.

### R5-1 · `StageValidator.validate_async` is dead code (LLM business rules never run) — CONFIRMED
- Defined at [stage_validator.py](../backend/app/agents/stage_validator.py) L80-94, but the
  executor only calls sync `validate()` ([stage_executor.py](../backend/app/agents/stage_executor.py)
  L226, L379, L416). No external caller of `validate_async`.
- **Impact:** `business_rules` declared on a stage are never evaluated by LLM.
- **Fix:** call `validate_async` from `_process_one_stage` (await), or fold the business-rule
  evaluation into the sync path and drop the dead method.

### R5-2 · Empty-result retry disabled by default — CONFIRMED
- `query_empty_result_retry: bool = False` ([config.py](../backend/app/config.py) L109), so
  `PostValidator` never fails on empty/likely-wrong result sets.
- **Fix:** decide the default. If empty-result is usually a wrong-query signal, default it on
  (or make it heuristic: retry once with a relaxed query). Coordinate with R5-4.

### R5-3 · Unified path has no result-check → correct → retry loop — CONFIRMED (the loop you want)
- The tool loop appends `result_text` and re-prompts with no result-quality gate
  ([orchestrator.py](../backend/app/agents/orchestrator.py) L1054-1088). Only `SQLAgent`'s
  internal `ValidationLoop` and `ToolDispatcher`'s context-free retry exist here.
- **Fix:** insert an orchestrator-level gate between `ToolDispatcher.dispatch` return and the
  message append, mirroring `StageExecutor._process_one_stage`: inspect the `SQLAgentResult`
  (empty / error / suspicious), and on failure re-dispatch with an injected error context
  (bounded by a small retry count). This is the single most impactful M5 change.

---

## P1 — high value

| ID | Finding | Status | Location | Fix sketch |
|----|---------|--------|----------|------------|
| R1-2 | SSH `known_hosts=None` everywhere (MITM exposure) | CONFIRMED (policy) | ssh_tunnel.py L50, ssh_exec.py L105, connection_service.py L252 | Pin/learn host keys; store per-connection known_hosts; opt-in TOFU |
| R1-3 | `update()` doesn't close tunnels / evict connector caches | CONFIRMED | connection_service.py L76-111 (cf. `delete()` L133-161) | On update, call `_close_ssh_tunnels` + evict pooled connector by key |
| R1-4 | 4 independent `SSHTunnelManager` instances; health UI inspects only pg+mysql | CONFIRMED | per-connector `_tunnel_mgr`; main.py L914-920 | Single shared tunnel manager; health iterates all |
| R1-5 | Postgres `execute_query` lacks `asyncio.wait_for` | CONFIRMED | postgres.py L73-105 | Wrap in `wait_for(query_timeout)` like mysql/clickhouse |
| R1-6 | `SshKeyService._find_references` omits `project_repositories` | CONFIRMED | ssh_key_service.py L125-139; repository.py L30-31 (FK SET NULL) | Add Repository check so in-use keys can't be silently un-linked |
| R2-2 | `refresh-schema` doesn't refresh stored `db_index` / BM25 | CONFIRMED | connections.py L354-416 | Trigger a (incremental) re-index, not just live introspection |
| R2-3 | No incremental schema indexing (`diff()`/`fingerprint()` unused) | CONFIRMED | base.py L86-121 (self-ref only) | Use `diff()` to re-LLM only changed tables |
| R2-4 | Sample/distinct/`schema_embed` failures swallowed | CONFIRMED | db_index_pipeline.py L331-334, L357-363, L653-655 | Record partial-evidence flag; don't mark "complete" silently |
| R2-5 | DB re-index marks code-DB sync stale but doesn't re-sync | CONFIRMED | db_index_pipeline.py L657-665; pipeline_runner.py L1545-1566 | Auto-trigger sync, or surface stale state to agent |
| R3-3 | Empty-graph incremental run strips affected-file symbols | CONFIRMED | pipeline_runner.py L1377-1394 | Skip `save_incremental` when new graph is empty due to AST failure |
| R3-4 | Diff failure silently becomes a full re-index | CONFIRMED | git_tracker.py L67-78 | Retry/raise on transient git error before full re-list |
| R3-5 | `count_commits_ahead` async but uses sync GitPython | CONFIRMED | git_tracker.py L143-154 | Wrap in `asyncio.to_thread` |
| R3-6 | BM25 rebuilt every run; "no changes" exit skips BM25 repair | CONFIRMED | pipeline_runner.py L1150-1212, L370-394 | Verify/repair `.pkl` even on no-op runs |
| R4-2 | `times_applied` only bumps on thumbs-up (no validation-time caller) | CONFIRMED | apply_learning sole caller chat.py L762 | Bump on provable use (post-validation) — depends on R4-1 |
| R4-3 | `times_exposed` absent from `_priority_score` and decay | CONFIRMED | agent_learning_service.py L724-736, L1091 | Incorporate exposure into ranking/decay or drop the column |
| R4-4 | Learning ranking inconsistent across surfaces | CONFIRMED | context_loader.py L199-203 vs `_priority_score` L735 vs chat.py L167-170 | Centralize one ranking function |
| R4-5 | `lessons_contradict` only catches negation-polarity; equal-conf tie drops incumbent | CONFIRMED | agent_learning_service.py L195-213, L402-404 | Add same-polarity conflict detection; keep incumbent on tie |
| R5-4 | ToolDispatcher SQL retry re-runs same question, no error context; zero rows = warning | CONFIRMED | tool_dispatcher.py L306-313; validation.py L60-61 | Inject `error_context` on retry; treat suspicious-empty as failure (see R5-2/R5-3) |
| R5-5 | WebSocket path omits `extra` + has no per-session lock | CONFIRMED | chat.py L2126-2137 vs HTTP L982-990, L1011-1019 | Pass `extra`; add per-session processing lock |
| R5-6 | Pipeline can exit "stuck" w/o `stage_failed`; `_resume_pipeline` one-shot; `AnswerValidator` fails open | CONFIRMED | stage_executor.py L144-149; orchestrator.py L1839-1848, L2065-2067 | Emit `stage_failed`; loop resume; fail-closed when validator errors |
| R5-7 | Investigation ("Wrong Data") agent disconnected from chat orchestration | CONFIRMED | data_investigations.py; no ref in orchestrator.py | Auto-route suspicious SQL results into investigation flow |

---

## P2 — cleanup / consistency

| ID | Finding | Status | Location |
|----|---------|--------|----------|
| R1-7 | Tunnel `stop()` uses fixed 0.1s sleep (no awaited close); `is_alive` returns cached True w/o probe; `to_config` never sets `connection_id` | CONFIRMED | ssh_tunnel.py L109-118, L131-136, L358-376 |
| R2-6 | Background index logs `tables_indexed` vs returned `tables`; schema BM25 doc id = lowercased table only (multi-schema collision); worker path skips probes/overview | CONFIRMED | connections.py L593-597; schema_retriever.py L123; worker.py L27-77 |
| R3-7 | Binary-skipped failed docs marked processed (no retry until `force_full`); `set_failed_doc_paths` errors swallowed | CONFIRMED | pipeline_runner.py L877-887, L1516-1517 |
| R4-6 | Session notes have no contradiction handling; `_COMPILE_LOCKS` grows unbounded; schema validation loose substring match | CONFIRMED | session_notes_service.py L38-99, L216-226, L638 |
| R5-8 | Parallel tool failures folded into text w/o targeted retry; `process_data` defaults to `filter_data` when planner omits op | CONFIRMED | orchestrator.py L1000-1033; stage_executor.py L717-723 |

---

## Refuted / reclassified during verification

- **Negative feedback "no cache invalidation"** — **REFUTED.** `contradict_learning` calls
  `_invalidate_summary` ([agent_learning_service.py](../backend/app/services/agent_learning_service.py)
  L499), invoked per-id by the thumbs-down route. The compiled prompt **is** invalidated.
- **`connection_string` bypasses the SSH tunnel** — **INTENDED** but a documented footgun.
  All 4 connectors skip the tunnel when a full DSN is supplied (postgres.py L46-52, etc.).
  Recommend: warn/validate when both `connection_string` and `ssh_host` are set.

---

## Production-config caveat (must verify before sizing impact)

All M3/M4 feature flags default **False** in code — `code_graph_enabled` (config.py L268),
`hybrid_retrieval_enabled` (L281), `schema_retrieval_enabled` (L288) — and the rollout flip is
tracked **pending** (BACKLOG.md L309-310, docs/ROLLOUT_M1_M6.md L362-363).
`query_empty_result_retry` defaults False (L109).

The live `checkmydata-api` Heroku config could **not** be read from this environment (it
deploys via a CI-scoped `HEROKU_API_KEY` to an account not available locally). **Action:**
the operator must confirm the live env vars. If they are at defaults, then R3-1/R3-2/R3-3/R3-6
(code-graph) and R2-3 (schema BM25) are latent (inactive in prod) and can be scheduled with
the rollout; R5-2 empty-result retry is off in prod today.

---

## Suggested order of work

1. **R5-3** (unified-path retry loop) + **R5-1** (wire `validate_async`) + **R5-4** — the
   correctness core you flagged.
2. **R1-1** (credential cache key) — security/correctness, small, high blast-radius.
3. **R4-1** (feedback attribution) — unblocks R4-2/R4-3 and the whole learning loop.
4. **R3-1/R3-2/R3-3** (graph integrity) — gate on confirming code-graph is enabled in prod.
5. **R2-1** (streaming) + remaining P1 table.
6. P2 cleanup.
