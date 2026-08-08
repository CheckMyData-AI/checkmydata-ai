# Task brief — query-timeout classification, circuit breaker, deadline, trace finalization

**Date:** 2026-08-08
**Pipeline:** task-pipeline 1.10.0
**Model (confirmed at preflight):** Opus 5 (1M context) — top tier available, all stages
**Origin:** production trace analysis, `request_traces` row `2026-08-06 11:39:24.804818+00`
(84 spans, `status=failed`, `response_type=error`), Heroku `checkmydata-api` release v199.

## The incident, in numbers

A user asked *«дай динамику выручки за последние 3 месяца по когортам»*. The
orchestrator planned 5 stages (span 0, 17 407 ms). The SQL agent then made 6 LLM
calls and 5 `execute_query` tool calls. **Every execute timed out at exactly
30 000 ms**, while `explain_check` in the same attempts completed in 72–466 ms —
the database planned instantly and executed never.

| Measure | Value | Source |
|---|---|---|
| Spans persisted | 84 | `trace_spans` join on the trace |
| `error_classify` spans, all reading `unknown` | 10 | spans 7, 11, 23, 27, 39, 43, 55, 59, 71, 75 |
| `query_repair` spans | 10 | spans 8, 12, 24, 28, 40, 44, 56, 60, 72, 76 |
| Time spent in LLM repair of a correct query | 120 280 ms | sum of the 10 repair span durations |
| Executes that hit the 30 s ceiling | 5 | spans 17, 33, 49, 65, 81 |
| Total inside `sql:tool:execute_query` | 277 831 ms | 61 255 + 51 911 + 53 567 + 58 098 + 53 000 |
| Request killed at | 360 s | `stream_timeout_seconds` (`config.py:595`) |

The agent itself diagnosed the environment at span 68 — *"even `MIN/MAX(id)` times
out, which is unusual for an indexed PK"* — after five minutes. Nothing in the
system reached that conclusion.

## Knowledge sources (phase-1 harvest — this is stage 9's work list)

| Source | What it says about this task | Fresh? | Authority |
|---|---|---|---|
| `app/core/query_validation.py:19,27-35` | `QueryErrorType.TIMEOUT` already exists; `NON_RETRYABLE_ERRORS` = `{PERMISSION_DENIED}` only; comment records the intent that `CONNECTION_ERROR` is retried by re-running the query **without LLM repair** | current | code |
| `app/core/validation_loop.py:31-36,417-436` | `_TRANSIENT_RETRY_ERRORS = {CONNECTION_ERROR}` — the existing seam that bypasses repairer and identity guard; TIMEOUT is not in it | current | code |
| `app/core/error_classifier.py:64,122,170,198,276-281` | TIMEOUT patterns are server-side only; fallback → `UNKNOWN` with `is_retryable=True` | current | code |
| `app/connectors/{mysql:182,postgres:235,clickhouse:233,mongodb:311}.py` | each synthesises the client-side string `f"Query timed out after {timeout_s:g}s"` — the error the classifier cannot read | current | code |
| `app/connectors/base.py:299-306` | `QueryResult` is an all-defaulted dataclass — a new optional field is backwards-compatible | current | code |
| `app/core/query_validation.py:8` | imports `QueryResult` from `app.connectors.base`; connectors import nothing from `app.core` → dependency runs **core → connectors**, so putting `QueryErrorType` in `QueryResult` as-is is a cycle | current | code |
| `app/agents/sql_agent.py:277-278,1493-1509` | tool loop bounded by `max_sql_iterations=10` only; `_wall_clock_remaining` merely shrinks a single query's timeout and is read once at config build | current | code |
| `app/agents/orchestrator.py:1381,1580,1644` | the 180 s budget is checked between **orchestrator** iterations; the whole SQL agent runs inside one dispatch and cannot be interrupted | current | code |
| `app/api/routes/chat.py:312-341` | route wraps the agent in `asyncio.wait_for(stream_timeout_seconds)`; on `TimeoutError` calls `finalize_trace` with synthetic id `f"unknown-{session_id}"` | current | code |
| `app/services/trace_persistence_service.py:195-219,228` | `finalize_trace` looks up by `workflow_id`; the synthetic id cannot match. **`failure_kind` is not a parameter at all** | current | code |
| `docs/SYSTEM_ARCHITECTURE.md:895` | claims `ErrorClassifier` categorises `timeout` — false for the app's own string | **stale** | doc → stage 9 |
| `CLAUDE.md` (W0 landmarks) | promises `RequestTrace` columns `approach`, `complexity`, `route_ms`; only `complexity` exists (`grep -rln "approach" alembic/versions/` is empty) | **stale** | doc → stage 9 |
| `docs/INTELLIGENCE_AUDIT_2026-07.md:195` (DATA-10) | repair prompt permits semantically-lossy "fixes"; only a textual identity guard | 2026-07 | audit |
| `docs/ux/scenarios.md` | 119 scenarios, highest `SCN-119`; SCN-046 is "mid-stream error + retry". No scenario covers a database that does not answer | 2026-07-19 | UX SSOT |
| `2026-08-01-analytics-sources-carryover.md` | **C13 open (security)**: `ssh_key_id` lacks an ownership check — named "the next piece of work". C7, C14, C19 also open | 2026-08-01 | ledger |
| `docs/superpowers/retro.md` | **absent** — no standing instructions exist yet; this run creates the file | — | — |
| `graphify-out/` | cache only, `graph.json` not built — graph not queried, recorded as a gap | — | — |
| wiki `~/.obsidian-wiki/config` | vault `sshlg-projects-vault` resolves; sync at stage 9 | current | — |

## Locked decisions

| id | Decision | Rationale |
|---|---|---|
| **D1** | **Timeout = one narrowing repair, then transient.** A timeout gets exactly one LLM repair, explicitly prompted to reduce scope. If the narrowed query also times out, the stage ends as `transient` with an honest message. | The trace proves narrowing sometimes cannot help (`MIN/MAX(id)` on an indexed PK timed out), but a genuinely heavy query is repairable. One attempt separates the two cases at a cost of ~60 s instead of ~278 s. |
| **D2** | **Circuit breaker lives in the SQL agent's tool loop, memory scoped to one run.** Counter of consecutive timeout-terminated tool calls per `connection_id`, threshold **2** → break the loop, return transient. Reset by any successful query. | No shared state, so it is deterministically testable. A process-wide breaker needs Redis, half-open states and tenant care — its own brief (→ carry-over). |
| **D3** | **Connectors return a typed error, the classifier stops parsing strings.** `QueryErrorType` moves to a leaf module imported by both layers; `QueryResult` gains an optional typed field; the classifier honours it when present and keeps the regexes as fallback for genuine vendor strings. | The operator's stated preference, and it removes the root absurdity — the app parsing text it generated itself. The leaf module avoids the `core → connectors` cycle. |
| **D4** | **Branch policy: worktree + `fix/query-timeout-classification` → merge to `main`.** Direct commits to `main` are forbidden (C18 recorded that violation in m0). | Isolation for parallel subagents and a rollback point. |
| **D5** | **Deploy: standing go.** Push to `main` → auto-deploy to `checkmydata-api`, **only** with `ruff format --check` + `ruff check` + `mypy` clean, full backend suite green and coverage ≥ 72%. Any red gate stops and asks. | Specific target + specific preconditions, per the doctrine's hard floor. |
| **D6** | **Stage-8 verification reads production.** A `Bash(heroku pg:psql:*)` permission rule is added so trace fields are verified against the running system rather than asserted. | A REQ about what production writes cannot be closed by a local test alone. |

## Stage 1 — docs study (grounded on the runtime, 2026-08-08)

No third-party contract is in play; the only external surface is stdlib `asyncio`,
verified by execution rather than by memory on `backend/.venv` (Python **3.12.11**):

- `asyncio.TimeoutError is TimeoutError` → `True` (aliased since 3.11)
- `asyncio.wait_for(...)` on expiry raises the builtin `TimeoutError`, and its
  `repr()` is **`TimeoutError()`** — the exception carries **no message at all**.

This reframes the root defect. The connectors did not gratuitously invent a string:
with a textless exception they had nothing else to hand upward through a
`QueryResult.error: str | None`. The fix is therefore to carry the **type**, not to
improve the text — and the regex patterns stay, because genuine vendor-worded
timeouts (`canceling statement due to statement timeout`) still arrive as text.

All four connectors wrap execution in `asyncio.wait_for` and share one identical
`except TimeoutError` handler shape, so the change is uniform:
`mysql.py:156`, `postgres.py:208`, `clickhouse.py:207`, `mongodb.py:260,265,269`
(three call sites, one handler). ClickHouse additionally calls `_reset_client()`
in that handler (audit fix B2 — a cancelled coroutine leaves the HTTP worker
thread holding the session) and must keep doing so.

## Stage 2 — approved design (2026-08-08)

### D7 — `QueryErrorType` moves to a leaf module

`app/core/error_types.py` holds `QueryErrorType` and `NON_RETRYABLE_ERRORS` and
imports nothing from `app`. `app.core.query_validation` re-exports both, so every
existing import keeps working. `app/connectors/base.py` imports the leaf, and
`QueryResult` gains `error_type: QueryErrorType | None = None` — an all-defaulted
dataclass, so no consumer breaks.

*Rejected:* a plain string discriminator on `QueryResult`. It dodges the import
question but re-creates the original defect one layer up — a value the classifier
must interpret rather than trust.

### D8 — the classifier trusts a supplied type instead of re-deriving it

`ErrorClassifier.classify(raw_error, db_type, error_type=None)`. When the caller
supplies a type, build the `QueryError` from it and return; the regex ladder is
untouched and still serves genuine vendor-worded timeouts. **No pattern is added for
the app's own string** — the point is to stop reading it, not to read it better.

### D9 — timeout is neither "repair it" nor "retry it": one narrowing attempt

`_TRANSIENT_RETRY_ERRORS` is deliberately *not* reused. It re-runs the **same**
query after a sub-second backoff, which for a 30 s timeout buys another 30 s of
waiting and cannot succeed. Instead the loop counts timeouts within itself: the
first gets one repair carrying an explicit narrowing instruction; the second ends
the loop with `final_error.error_type is TIMEOUT` and no further repair.

`failure_kind` uses the vocabulary already in the codebase —
`transient | configuration | data_missing | fatal` (`stage_executor.py:54`) — and
timeout maps to `transient`, which `stage_executor.py:68-74` already does for
`TimeoutError`. No new vocabulary.

### D10 — breaker and deadline are call-frame locals, never instance state

**Load-bearing constraint discovered at this stage.** `chat.py:60` builds
`ConversationalAgent()` at **module level**; it builds one `OrchestratorAgent` in
`__init__` (`app/core/agent.py:40`), which builds one `SQLAgent` in `__init__`
(`orchestrator.py:356`). **One `SQLAgent` instance serves every request in the
process**, with `max_concurrent_agent_calls = 3` concurrent.

Therefore the consecutive-timeout counter and the deadline live as locals inside
`SQLAgent.run()`. Anything on `self` would let one tenant's dead connection break
another tenant's loop.

**Pre-existing bug this uncovers, fixed in the same change:** `sql_agent.py:171`
already writes `self._wall_clock_remaining = wall_clock_remaining`, and
`_build_validation_config` reads it back off `self` (`:1497`). Two concurrent
requests overwrite each other's budget. The deadline work crosses exactly this
boundary, so the field becomes a parameter rather than instance state. Scope is
targeted — no unrelated refactor.

The deadline itself needs no new plumbing: `orchestrator.py:1644` already computes
`_dispatch_wall` and passes it as `remaining_wall_seconds` through the dispatcher
into `SQLAgent.run(wall_clock_remaining=…)`. It is simply never consulted by the
loop at `:278`. The design converts it to an absolute monotonic deadline checked at
the top of each iteration.

### D11 — the REST path adopts the SSE path's finalization, which already works

The stream path solves this correctly today: it captures `wf_id` from the
`pipeline_start` event (`chat.py:1018-1019`), passes it to `_finalize_on_error`
(`:1083`), and falls back to a synthetic id **only** when none exists — logging a
warning when it does (`:979-982`). The REST path (`:312-341`) unconditionally
passes `f"unknown-{session_id}"`, which can never match a persisted trace, so
`finalize_trace`'s lookup at `trace_persistence_service.py:228` always misses.

The fix is to follow the pattern already in the file, plus: `finalize_trace` gains
a `failure_kind` parameter (it has none today, which is why the column is NULL on
every abnormal close), and the router signals are stamped into the trace buffer
when the router resolves rather than being read off a result object that a timeout
destroys.

### UI verdict — **yes**

No new screens, but the failure message changes, and `docs/ux/scenarios.md` is this
project's source of truth for user-facing behaviour.

- **Path:** user asks a data question in chat → the database does not answer →
  today they wait ~6 minutes and receive an error with no explanation; after this
  change they wait ~2 and are told what happened and what to do.
- **States:** running · answered · **answered-with-caveat** (narrowed query
  succeeded — the answer covers less than asked) · **stopped-transient** (database
  did not answer) · stopped-budget (existing `step_limit_reached`).
- **Error path:** the message must separate environment from query — *"the database
  did not answer within 30 s, twice"* is a different fact from *"your question was
  too broad"*, and the trace proves the system currently cannot tell the user which
  one happened. What is said out loud: which of the two, and the next action.
  What stays in the log: the SQL, the attempt count, the connection id.

Scenario ids are **not** drafted here — that is the stage-3 chain's job.

### Every REQ answered

REQ-001/002 → D7+D8 · REQ-003/004 → D9 · REQ-005/006 → D10 · REQ-007/008 → D11 ·
REQ-009 → UI verdict · REQ-010 → two settings added under D9/D10 · REQ-011 → stage 9 ·
REQ-012/013 → stages 6–8. Nothing dropped.

## REQ table — frozen (adding is free, removing needs the operator)

| ID | Requirement | How it's verified | Status |
|---|---|---|---|
| REQ-001 | A connector timeout is classified as `QueryErrorType.TIMEOUT`, never `UNKNOWN`, for all four connectors | `tests/unit/test_error_classifier.py` — a case per connector asserting `error_type is TIMEOUT`; probed by reverting the fix and watching it fail | open |
| REQ-002 | Connectors emit a typed timeout on `QueryResult`; the classifier reads the type without regex-matching the app's own string | `tests/unit/test_query_validation.py` + a test asserting the classifier never sees `"Query timed out after"` as raw input on the typed path | open |
| REQ-003 | A timeout triggers **at most one** LLM repair, and that repair is prompted to narrow scope | `tests/unit/test_validation_loop.py` — assert exactly 1 `QueryRepairer.repair` call across a 3-attempt config, and the repair context carries the narrowing instruction | open |
| REQ-004 | A second consecutive timeout ends the loop as `transient`, not as a query defect | `tests/unit/test_validation_loop.py` — `ValidationLoopResult.final_error.error_type is TIMEOUT` and no further repair; `failure_kind == "transient"` | open |
| REQ-005 | Two consecutive timeout-terminated tool calls on one connection break the SQL agent loop before `max_sql_iterations` | `tests/unit/test_sql_agent_timeout_breaker.py` (new) — assert the loop exits at iteration 2 of 10; counter resets on success | open |
| REQ-006 | The SQL agent's tool loop honours a wall-clock deadline, not only an iteration count | `tests/unit/test_sql_agent_timeout_breaker.py` — assert the loop exits when the injected deadline passes, with `max_sql_iterations` deliberately high | open |
| REQ-007 | A run killed by the route-level timeout writes a trace with `failure_kind` populated and the router signals carried, not a stub | `tests/integration/test_trace_finalization.py` (new) — assert `failure_kind`, `route`, `complexity`, `total_duration_ms` are non-default after a simulated `TimeoutError` | open |
| REQ-008 | `finalize_trace` can no longer be called with an id that cannot match a persisted trace | `tests/unit/` — assert the route passes the real workflow id; a synthetic-id call is a test failure | open |
| REQ-009 | The user-visible message on a database that does not answer is honest and distinguishes environment from query | `docs/ux/scenarios.md` gains a scenario (next free id `SCN-120`); `tests/unit/docs/test_ux_scenarios.py` stays green | open |
| REQ-010 | Breaker threshold and deadline are configurable settings with docstrings, present in `.env.example` | `grep` in `app/config.py` + `backend/.env.example`; a test asserting non-positive values are rejected at boot | open |
| REQ-011 | Stale docs corrected: `SYSTEM_ARCHITECTURE.md:895` and the `CLAUDE.md` W0 `approach`/`route_ms` claim | stage-9 diff; each claim resolvable against code | open |
| REQ-012 | Full backend suite green, coverage ≥ 72% combined | `make test-all` + `coverage report --fail-under=72` | open |
| REQ-013 | Deployed to `checkmydata-api` and verified against the running system | health 200, migration revision in boot logs, and a production `request_traces` read showing the new fields on a real run | open |

**REQ-005 and REQ-006 are additions made during the grill**, not in the original
three-defect request — the harvest proved the loop has no deadline at any level,
which is why 30 s of database slowness became 360 s of wall clock. Named out loud
rather than folded in silently; the operator may defer either.

## Autonomy sweep

| Stage | Settled |
|---|---|
| run-wide | Opus 5 (1M), all stages. Decide alone inside the repo and reversible; escalate anything outward beyond D5 |
| 1 Docs | context7 for `asyncio.wait_for`, aiomysql / asyncpg / clickhouse-connect / motor timeout surfaces |
| 2 Decompose | one module, not a platform |
| 3 UI | text-only; no Figma. User-facing surface is the failure message → `docs/ux/scenarios.md` updated in the same change |
| 4–5 Dev | worktree; branch `fix/query-timeout-classification`; conventional commits; `main` off-limits for direct commits |
| 6 Tests | `make test-all`; green = full backend suite; coverage gate 72% combined; no known-red baseline (the m0 heartbeat flake was fixed in `c5c6460`) |
| 7 Lint+deploy | `ruff format --check app/ tests/`, `ruff check app/ tests/`, `mypy app/ --ignore-missing-imports`; deploy per D5 |
| 8 Post-deploy | `heroku logs -a checkmydata-api`; `heroku pg:psql` per D6 |
| 9 Docs | `CLAUDE.md`, `docs/SYSTEM_ARCHITECTURE.md`, `CHANGELOG.md`, `docs/ux/scenarios.md`, `BACKLOG.md`; wiki sync **yes**; graph refresh **no** (not built — carry-over) |
| 10 Acceptance | operator signs off; deferred REQs → `BACKLOG.md`; retro created at `docs/superpowers/retro.md` (does not exist yet) |
