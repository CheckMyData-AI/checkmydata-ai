# PRJ-01 — production hotfix wave (task-pipeline run, 2026-09-14)

**Standard:** Proof of Done. Every claim below carries the command, file or test that proves it.

## Source ledger (stage 0 harvest)

| Source | Found | What it contributed |
|---|---|---|
| `docs/audits/2026-09-13-connections-sync-orchestrator-audit.md` | yes | the four defects, their `file:line`, and PRJ-01's acceptance gate |
| `docs/adr/0005-…-request-kernel.md` | yes | wave 0 is these four fixes; PRJ-03 later deletes the `_wf_*` dicts (constrains fix 4) |
| `docs/adr/0006-buy-before-build…` | yes | wave 0 unchanged; the pgvector fix is needed until CBM lands |
| `CLAUDE.md` (project) | yes | conventional commits, branch prefixes, CI green, coverage ≥80%, one-PR-at-a-time changelog rule |
| `~/CLAUDE.md` (machine) | yes | ops steps are mine to run; production-mutating actions confirmed once |
| `graphify-out/graph.json` | yes | present; refreshed at stage 9 |
| obsidian wiki | configured | updated at stage 9 |
| `docs/evidence/{retro,backlog,verification}.md` | **none found** | seeded by this run |
| production DB (Supabase) | yes | the four failing runs and their exact error text |

## Grill — decisions taken, with rationale

| # | Question | Decision | Why |
|---|---|---|---|
| G1 | Fix (4): mutate `context.extra` in place, or drain via `_wf_*`/`pop_*` like routing? | **Mutate in place** at the two sites that rebuild it (`orchestrator.py:835`, `:2399`), plus a guard test that fails if anyone rebuilds it again | `replace()` without `extra=` copies the *reference*, so one dict identity is shared by every copy and every sub-agent write reaches `core/agent.py:92`. The `_wf_*` route would add a dict ADR-0005 PRJ-03 deletes. Two lines instead of a new drain. |
| G2 | Fix (1): coerce the two broken fields, all string fields of that analyzer, or codebase-wide? | **All string-declared fields of `code_db_sync_analyzer`**, via one helper that also validates a JSON round-trip for the `_json` ones | Six fields there are declared `type="string"` and land in `Text` columns; only two have been observed failing, and a fix that covers the observed two leaves four loaded. Codebase-wide is PRJ-14's AST guard, a separate project. |
| G3 | Fix (3): pass `None`, or make `execution_time_ms` `None`-able? | **Pass `None` at the three call sites** | `QueryResult.execution_time_ms: float = 0.0` is read by connectors and tests as a number; making it optional is a contract change across six connectors for a caller bug. |
| G4 | Deploy and the production rebuild | **Authorized** — the operator answered "вперёд" to a message naming "CI, деплой, пересборка, измерения" | Standing authorization in `~/CLAUDE.md` covers commit/push; the rebuild was named explicitly in the request it answered. |
| G5 | Merge route | **Branch → PR → CI green → merge**, changelog entry on the branch | Project CLAUDE.md; only one PR in flight, so the `## [Unreleased]` conflict rule does not bite. |

## REQ table (frozen; adding is free, removing needs the operator)

| REQ | Requirement | Verified by |
|---|---|---|
| R1 | A tool-call argument declared `string` that arrives as a dict/list is stored as a JSON string, never handed to asyncpg | `tests/unit/knowledge/test_code_db_sync_analyzer.py` — new case: LLM stub returns objects for `required_filters` / `column_value_mappings` / `column_sync_notes`; asserts every field of `TableSyncAnalysis` is `str` and round-trips through `json.loads` |
| R2 | `PgVectorStore.delete_by_source_path(kind=…)` produces SQL psycopg3 accepts, for both `kind` branches | new `tests/unit/knowledge/test_pgvector_sql_is_valid.py` — the composed SQL is parsed by `psycopg.sql`/the client-side placeholder scanner; red on `main` |
| R3 | A completed SQL answer's `request_traces.total_duration_ms` is the request's duration, not the last query's | `tests/unit/test_trace_meta_duration.py` — finalize with a result carrying `execution_time_ms=12.0` leaves the flush-written duration intact |
| R4 | `AgentResponse.exposed_learning_ids` carries what sub-agents exposed | `tests/unit/test_agent.py` — new case: a stub orchestrator writes into the ctx it received after `replace()`; assert the response carries the ids |
| R5 | No future change may rebuild `AgentContext.extra` and re-break R4 | guard test in the same file: `grep`-free AST check that `orchestrator.py` contains no `replace(context, extra=…)` |
| R6 | Production: the code↔DB map updates again | `indexing_runs` shows a `code_db_sync` `completed` after the deploy |
| R7 | Production: a full repository rebuild reaches `pipeline_end` | `indexing_runs` shows `index_repo` `completed` with `current_step='record_index'` for a `force_full` run |
| R8 | The four fixes ship with the suite green and coverage ≥ 80% | `make check` + CI on the PR |

## Carry-over ledger

| Item | Status | Home |
|---|---|---|
| Codebase-wide AST guard for tool-call argument types | deferred | PRJ-14 (ADR-0005 wave 0) |
| `_wf_*` dicts → `RequestState` | deferred | PRJ-03 (wave 1) |
| The other 56 audit findings | deferred | `docs/audits/2026-09-13-…` §3, sequenced by ADR-0005/0006/0007 |
