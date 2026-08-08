# Build plan — query-timeout classification, breaker, deadline, trace finalization

**Spec:** `docs/superpowers/specs/2026-08-08-query-timeout-classification-design.md`
**Brief:** `…-brief.md` · **Carry-over:** `…-carryover.md`
**Branch:** `fix/query-timeout-classification` in a git worktree · **`main` is off-limits for direct commits**

Written zero-context: an implementer needs this file and the repo, nothing else.

## Ground rules for every task

- **TDD is not optional.** Write the failing test first, watch it fail for the right
  reason, then the minimal implementation, then refactor. A test that has never been
  seen red is not evidence.
- Line length 100 · `ruff` rules `E F I N W UP` · async everywhere, no sync I/O on the
  request path · new env vars get a docstring in `app/config.py` **and** a line in
  `backend/.env.example`.
- Run from `backend/`: `.venv/bin/pytest <path> -q`, `.venv/bin/ruff check app/ tests/`,
  `.venv/bin/ruff format --check app/ tests/`, `.venv/bin/mypy app/ --ignore-missing-imports`.
- Conventional commits (`fix:`, `feat:`, `test:`, `refactor:`).
- **Never widen scope.** Anything noticed but out of plan goes to the carry-over
  ledger, not into the diff.

## Execution order

`B1 → B2 → B3 → B4` is a **contract chain** — each task changes the interface the next
one consumes, so they land in order, one implementer. **B5 is genuinely independent**
(different files: `chat.py`, `trace_persistence_service.py`, `orchestrator.py`) and runs
concurrently with the whole chain in a second worktree.

Stating this plainly rather than inventing a five-way fan-out: the parallelism here is
two lanes, not five, and pretending otherwise would just produce merge conflicts.

| Lane | Tasks | Files |
|---|---|---|
| **1** | B1 → B2 → B3 → B4 | `core/error_types.py`, `core/query_validation.py`, `connectors/*`, `core/error_classifier.py`, `core/validation_loop.py`, `core/post_validator.py`, `core/explain_validator.py`, `agents/sql_agent.py`, `config.py` |
| **2** | B5 | `api/routes/chat.py`, `services/trace_persistence_service.py`, `agents/orchestrator.py` |

---

## B1 — Typed error contract (REQ-002)

**Do:**
1. Create `app/core/error_types.py` containing `QueryErrorType` and
   `NON_RETRYABLE_ERRORS`, moved verbatim from `app/core/query_validation.py:11-35`
   (keep the explanatory comment about `CONNECTION_ERROR`). **This module imports
   nothing from `app`** — that is the whole point of it existing.
2. In `app/core/query_validation.py`, replace the moved definitions with
   `from app.core.error_types import NON_RETRYABLE_ERRORS, QueryErrorType` and keep
   both names exported so every existing import site is untouched.
3. In `app/connectors/base.py`, import `QueryErrorType` from the leaf module and add
   to `QueryResult` (currently `:299-306`):
   `error_type: QueryErrorType | None = None`.
4. In each connector's existing `except TimeoutError:` handler, add
   `error_type=QueryErrorType.TIMEOUT` beside the unchanged `error=` string:
   `mysql.py:182`, `postgres.py:235`, `clickhouse.py:233`, `mongodb.py:311`.
   **ClickHouse keeps its `await self._reset_client()` call** — audit fix B2; removing
   it poisons the driver session for every later query.

**Do not:** change the `error=` strings; they still carry the human-readable detail.

**DoD:** a new `tests/unit/test_connector_timeout_type.py` asserts, per connector, that
a timed-out execution returns `error_type is QueryErrorType.TIMEOUT` and a non-empty
`error`. `import app.core.error_types` pulls in no `app.*` module (assert on
`sys.modules` or inspect the file's imports). Full unit suite still green — this task
must break nothing, since it only adds a defaulted field.

---

## B2 — The classifier trusts a supplied type (REQ-001)

**Do:**
1. `ErrorClassifier.classify` (`app/core/error_classifier.py:222`) gains a third
   parameter `error_type: QueryErrorType | None = None`. When it is not `None`,
   build and return the `QueryError` from it **before** the regex ladder, with
   `is_retryable = error_type not in NON_RETRYABLE_ERRORS` and the message built by
   the existing `_build_message`.
2. Pass `result.error_type` at **all three** call sites that hold a `QueryResult` —
   missing one leaves the typed path half-wired:
   - `app/core/post_validator.py:28`
   - `app/core/explain_validator.py:45` (the `:41` site classifies `str(exc)`, not a
     `QueryResult` — leave it alone)

   **Correction made during B2:** this list originally named
   `app/core/validation_loop.py:284` as a third site. It is not one — it classifies
   `str(exc)` inside an `except Exception`, where no `QueryResult` exists. A timeout
   never raises; `execute_query` *returns* a result with `error` set. **Two sites,
   not three.**

**Do not:** add a regex pattern for `"Query timed out after …"`. The goal is to stop
reading the app's own string, not to read it better. Vendor-worded timeouts
(`canceling statement due to statement timeout` etc.) keep flowing through the
existing patterns and their tests must stay green.

**DoD:** `tests/unit/test_error_classifier.py` gains (a) a case per connector proving
the connector's own timeout now classifies as `TIMEOUT` rather than `UNKNOWN`, and
(b) a regression case proving a vendor-worded timeout still classifies via regex when
no type is supplied. Probe: revert the short-circuit and watch (a) fail.

---

## B3 — Timeout semantics in the validation loop (REQ-003, REQ-004)

**Do:** in `app/core/validation_loop.py`, count timeouts **within one `execute()`**,
separately from the generic `max_retries` ladder:

- **First** timeout → exactly one `QueryRepairer.repair`, whose repair context carries
  an explicit instruction to narrow the scope (smaller range / fewer rows / an
  aggregate instead of a scan).
- **Second** timeout → stop. Return via `_fail(...)` with
  `final_error.error_type is TIMEOUT`, no repair call, no further attempt.

Keep the counter separate so a query that times out once and then fails on a column
name still gets its normal repair budget.

**Do not:** add `TIMEOUT` to `_TRANSIENT_RETRY_ERRORS` (`:34`). That path re-runs the
**same** query after a sub-second backoff — for a 30 s timeout it buys another 30 s and
cannot succeed. `CONNECTION_ERROR` stays the only member.

**DoD:** `tests/unit/test_validation_loop.py` gains: exactly one `repair` call across a
3-attempt config when every execute times out; the repair context contains the
narrowing instruction; the second timeout returns `final_error.error_type is TIMEOUT`;
and a mixed case (timeout → column error) still gets its normal repairs. Probe each by
planting the opposite behaviour.

---

## B4 — Breaker, deadline, and the shared-state fix (REQ-005, REQ-006, REQ-010)

**Context an implementer must not get wrong:** `chat.py:60` builds
`ConversationalAgent()` at **module level**; it builds one `OrchestratorAgent`
(`app/core/agent.py:40`) which builds one `SQLAgent` (`orchestrator.py:356`), both in
`__init__`. **One `SQLAgent` instance serves every request in the process**, up to
`max_concurrent_agent_calls = 3` concurrently. Anything stored on `self` leaks between
tenants.

**Do:**
1. Two settings in `app/config.py`, each with a docstring, a line in
   `backend/.env.example`, and boot validation in the existing
   `@model_validator(mode="after")` style (`config.py:78`, `:811`):
   - `sql_timeout_breaker_threshold: int = 2` (`SQL_TIMEOUT_BREAKER_THRESHOLD`) —
     **non-positive must raise**, not silently disable the breaker.
   - `sql_agent_deadline_enabled: bool = True` (`SQL_AGENT_DEADLINE_ENABLED`).
2. In `SQLAgent.run()`, as **locals** (never attributes):
   `deadline = time.monotonic() + wall_clock_remaining` when a budget was passed and
   the flag is on; `consecutive_timeouts = 0`.
3. In the loop at `sql_agent.py:278`: check the deadline at the top of each iteration;
   increment `consecutive_timeouts` when a tool call ended in a timeout and reset it to
   `0` on any successful query; at `>= threshold`, break and return a transient result
   naming the connection.
4. **Fix the pre-existing leak (carry-over K10):** `sql_agent.py:171` assigns
   `self._wall_clock_remaining`, and `_build_validation_config` reads it back off
   `self` (`:1497`). Make it a parameter:
   `_build_validation_config(wall_clock_remaining: float | None)`. Delete the attribute.

**Do not:** audit or refactor other `self.`-assignments on the agent chain — that is
carry-over K11, deliberately out of scope.

**DoD:** new `tests/unit/test_sql_agent_timeout_breaker.py`: the loop exits after 2
timeout-terminated tool calls with `max_sql_iterations` set high; the counter resets on
a success in between; an expired deadline exits the loop independently of the counter;
a non-positive threshold raises at boot. Plus a test that two concurrent `run()` calls
with different budgets do not observe each other's value (the K10 regression).

---

## B5 — Trace finalization (REQ-007, REQ-008) · runs in parallel

**The pattern already exists in the same file — copy it, do not invent.** The SSE path
captures `wf_id` from the `pipeline_start` event (`chat.py:1018-1019`), passes it to
`_finalize_on_error` (`:1083`), and uses a synthetic id **only** when none exists,
logging a warning (`:979-982`).

**Do:**
1. The REST timeout handler (`chat.py:312-341`) currently passes
   `f"unknown-{session_id}"` unconditionally, which can never match
   `RequestTrace.workflow_id`, so the lookup at
   `trace_persistence_service.py:228` always misses and writes a stub. Capture the real
   workflow id and pass it; fall back to a synthetic id only when genuinely absent, with
   the same warning.
2. `finalize_trace` (`trace_persistence_service.py:195-219`) gains
   `failure_kind: str | None = None` — it has **no such parameter today**, which is why
   the column is NULL on every abnormal close. Use the existing vocabulary
   `transient | configuration | data_missing | fatal` (`stage_executor.py:54`);
   a request killed by the outer timeout is `transient`.
3. Stamp the router signals (`route`, `complexity`, `estimated_queries`) into the trace
   record when the router resolves — `orchestrator.py:738-749` already writes them to
   `context.extra` — so a finalize with no result object reports them instead of the
   `"unknown"` defaults.

**DoD:** new `tests/integration/test_trace_finalization.py`: after a simulated
`TimeoutError` on the REST path, the persisted trace has non-default `failure_kind`,
`route`, `complexity` and `total_duration_ms`, and exactly one row exists for the run
(not a stub beside a real one). A test asserting the route never passes an id that
cannot match. Probe by reverting each of the three changes.

---

## REQ coverage of this plan (stage-4 gate evidence)

Mechanical set-comparison against the brief's REQ table, not an eyeball:

| REQ | Where |
|---|---|
| 001 | B2 | 
| 002 | B1 |
| 003, 004 | B3 |
| 005, 006, 010 | B4 |
| 007, 008 | B5 |
| **009** | **already closed at stage 3** — `SCN-120` is in `docs/ux/scenarios.md` and `tests/unit/docs/` is green, having been watched failing against a planted bad `Coverage:` path |
| 011 | stage 9 (docs) |
| 012 | stage 6 (suite + coverage gate) |
| 013 | stages 7–8 (deploy + production verification) |

Nothing in the brief is unassigned; nothing in the plan is unrequested.

## Integration

Lane 1 and lane 2 merge into `fix/query-timeout-classification`; lane 2 touches no file
lane 1 touches, so the merge is mechanical. Then: full backend suite, `ruff format
--check`, `ruff check`, `mypy`, and the combined coverage gate at **72%** — the stage-6
and stage-7 gates. Docs (`CLAUDE.md` flag table, `SYSTEM_ARCHITECTURE.md:895`,
`CHANGELOG.md`, `.env.example`) are **stage 9**, not this plan.

---

## Progress

| Task | State | Evidence |
|---|---|---|
| **B1** | **done** | `tests/unit/test_connector_timeout_type.py` — 6 pass (seen red first: `ModuleNotFoundError: app.core.error_types`). 202 tests in the 7 adjacent files still pass. `ruff check app/ tests/` clean, `ruff format --check` clean on 833 files, `mypy` clean. Worktree module resolution verified empirically before any code was written — `PathFinder` beats the editable finder, so the worktree's own `app/` is what runs. |
| **B2** | **done** (`b97c38a`) | `test_error_classifier.py` — 31 pass. Both QueryResult call sites wired; the explain one probed by reverting it and watching it fail. 100 tests across 7 classification-related files green. |
| **B3** | **done** (`b92be3f`) | `test_validation_loop.py` — 18 pass incl. 3 new budget cases + 1 hint case; probed by disabling the budget (repair count went 1 → 2, test red). **Full unit suite: 5397 passed, 5 skipped, 1 xfailed.** ruff/format/mypy clean. |
| **B4** | **done** | breaker + deadline as call-frame locals; K10 shared-state leak fixed and regression-tested; settings validated at boot. 5 new tests; **full unit suite 5402 passed**. |
| **B5** | **done** | REQ-008 done + failure_kind through both abnormal REST paths (2 tests). REQ-007 closed too: the real defect was `finalize_trace` clobbering the buffer's real values with its parameter defaults; the UPDATE is now additive. Full unit suite 5405 passed. |
