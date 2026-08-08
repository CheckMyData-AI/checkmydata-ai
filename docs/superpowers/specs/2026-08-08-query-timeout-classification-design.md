# Design spec — query-timeout classification, breaker, deadline, trace finalization

**Date:** 2026-08-08 · **Brief:** `2026-08-08-query-timeout-classification-brief.md`
**Carry-over:** `2026-08-08-query-timeout-classification-carryover.md`
**Decisions this spec implements:** D1–D11 (brief) · **REQ-001 … REQ-013**

## 1. Problem

A `TimeoutError` from `asyncio.wait_for` carries **no message** (`repr()` is
`TimeoutError()`, verified on Python 3.12.11). Each connector therefore synthesises
`f"Query timed out after {n:g}s"` into `QueryResult.error: str | None`. The
classifier's TIMEOUT patterns match only vendor-worded timeouts, so the app's own
string falls through to `UNKNOWN` with `is_retryable=True`
(`error_classifier.py:276-281`) and a timeout is handed to `QueryRepairer` as if it
were a defective query.

Production cost on trace `2026-08-06 11:39:24` (84 spans): 10 repair calls =
120 280 ms of LLM rewriting a correct query, 5 executes × 30 000 ms of waiting,
277 831 ms inside `sql:tool:execute_query`, request killed at
`stream_timeout_seconds = 360`, trace closed as a stub.

## 2. Contracts

### 2.1 `app/core/error_types.py` (new leaf module)

Holds `QueryErrorType` and `NON_RETRYABLE_ERRORS`, moved verbatim from
`app/core/query_validation.py`. **Imports nothing from `app`** — this is what makes
it importable by both layers. `app.core.query_validation` re-exports both names, so
every existing import site is untouched.

*Why a move and not a new enum:* `query_validation.py:8` imports `QueryResult` from
`app.connectors.base`, and connectors import nothing from `app.core`. Dependency runs
core → connectors, so a second enum would be a duplicate vocabulary, and importing
the existing one into `base.py` would be a cycle.

### 2.2 `QueryResult` gains a typed error

```python
# app/connectors/base.py
error_type: QueryErrorType | None = None
```

All-defaulted dataclass → additive, no consumer breaks. **Failure behavior:** when
`error_type is None` the classifier behaves exactly as today (regex ladder), so a
connector that never sets it is not broken, only unimproved.

### 2.3 Connectors set the type

In each existing `except TimeoutError:` handler — `mysql.py:182`, `postgres.py:235`,
`clickhouse.py:233`, `mongodb.py:311` — add `error_type=QueryErrorType.TIMEOUT`
alongside the unchanged `error=` string (kept for logs and for the user-facing
detail). **ClickHouse keeps its `await self._reset_client()`** (audit fix B2: a
cancelled coroutine leaves the HTTP worker holding the session).

### 2.4 `ErrorClassifier.classify` trusts a supplied type

```python
def classify(self, raw_error: str, db_type: str,
             error_type: QueryErrorType | None = None) -> QueryError
```

When `error_type` is given, construct the `QueryError` from it and return before the
regex ladder. **No pattern is added for the app's own string** — the goal is to stop
reading it. Vendor-worded timeouts keep flowing through the existing patterns.

**Failure behavior:** an unknown/None type falls through to today's path unchanged.

## 3. Timeout semantics (REQ-003, REQ-004)

`_TRANSIENT_RETRY_ERRORS` is **not** reused: it re-runs the same query after a
sub-second backoff, which for a 30 s timeout buys another 30 s and cannot succeed.

`ValidationLoop` counts timeouts within one `execute()`:

| Timeout # | Action |
|---|---|
| 1 | exactly **one** `QueryRepairer.repair`, whose context carries an explicit *narrow the scope* instruction |
| 2 | stop. Return `_fail(...)` with `final_error.error_type is TIMEOUT`; no repair, no further attempt |

Timeout attempts are counted **separately** from the generic `max_retries` ladder, so
a query that times out once and then fails on a column name still gets its normal
repair budget.

**`failure_kind` vocabulary is existing, not new:**
`transient | configuration | data_missing | fatal` (`stage_executor.py:54`), and
`TimeoutError` already maps to `transient` there (`:68-74`). Timeout → `transient`.

## 4. Breaker and deadline (REQ-005, REQ-006)

**Hard constraint.** `chat.py:60` builds `ConversationalAgent()` at module level; it
builds one `OrchestratorAgent` (`app/core/agent.py:40`) which builds one `SQLAgent`
(`orchestrator.py:356`), both in `__init__`. **One `SQLAgent` serves every request in
the process**, up to `max_concurrent_agent_calls = 3` concurrently.

Both new pieces of state are therefore **locals in `SQLAgent.run()`**, never on
`self`:

```python
deadline = time.monotonic() + wall_clock_remaining if wall_clock_remaining else None
consecutive_timeouts = 0          # reset to 0 by any successful query
```

- **Breaker:** a tool call that ends in a timeout increments the counter; a success
  resets it to 0. At `>= settings.sql_timeout_breaker_threshold` (default **2**) the
  loop breaks and the agent returns a transient result naming the connection.
- **Deadline:** checked at the top of each iteration of the loop at `sql_agent.py:278`.
  Exceeded → break with the same transient shape.

**Pre-existing bug fixed in the same change (K10):** `sql_agent.py:171` writes
`self._wall_clock_remaining` and `_build_validation_config` reads it back off `self`
(`:1497`), so concurrent requests overwrite each other's budget. The field becomes a
parameter: `_build_validation_config(wall_clock_remaining: float | None)`. Nothing
else on the singleton is audited — that is carry-over K11.

## 5. Trace finalization (REQ-007, REQ-008)

The SSE path is already correct and is the pattern to follow: it captures `wf_id`
from the `pipeline_start` event (`chat.py:1018-1019`), passes it to
`_finalize_on_error` (`:1083`), and uses a synthetic id **only** when none exists,
logging a warning (`:979-982`).

The REST path (`chat.py:312-341`) unconditionally passes `f"unknown-{session_id}"`,
which can never match `RequestTrace.workflow_id`, so the lookup at
`trace_persistence_service.py:228` always misses and the row is a stub.

Changes:

1. REST captures the real workflow id and passes it, falling back to a synthetic id
   only when genuinely absent — with the same warning.
2. `finalize_trace` gains `failure_kind: str | None = None` (it has **no such
   parameter today**, which is why the column is NULL on every abnormal close).
3. Router signals (`route`, `complexity`, `estimated_queries`) are stamped into the
   trace record when the router resolves, so a finalize that has no result object
   still reports them instead of the `"unknown"` defaults.

## 6. Settings (REQ-010)

| Setting | Default | Env | Meaning |
|---|---|---|---|
| `sql_timeout_breaker_threshold` | 2 | `SQL_TIMEOUT_BREAKER_THRESHOLD` | consecutive timeout-terminated tool calls on one connection before the SQL loop stops |
| `sql_agent_deadline_enabled` | on | `SQL_AGENT_DEADLINE_ENABLED` | honour the orchestrator's remaining wall clock inside the SQL tool loop |

Both validated at boot; a non-positive threshold raises rather than silently
disabling the breaker (the house rule that produced the analytics settings).
Documented in `backend/.env.example` and the flag table in `CLAUDE.md`.

## 7. User-facing behavior (REQ-009)

Design tooling is **text-only** per `docs/ux/foundation.md` — no Figma, by standing
decision. **No brand pack exists (`docs/brand/` is absent), so these strings were
written directly rather than through the `copywriting` chain; `/brand-init` is out of
this brief's scope.** Flagged rather than silently skipped.

The message must separate *environment* from *query* — the production trace proves
the system currently cannot tell the user which happened:

- **Database did not answer:** "The database didn't answer within 30 s — twice in a
  row. That points at the database rather than at your question. Try again in a few
  minutes, or check the connection."
- **Narrowed and succeeded:** the existing partial-data caveat path carries "this
  answer covers a narrower range than you asked for, because the full query timed
  out."

Logged, not shown: the SQL, the attempt count, the connection id.

Scenario **SCN-120** carries this; ids are allocated from the end of the index and
never reused (`foundation.md` → Working rules).

## 8. Testing

| REQ | Test |
|---|---|
| 001 | `test_error_classifier.py` — one case per connector string+type asserting `TIMEOUT` |
| 002 | `test_query_validation.py` — typed path never regex-matches the app's own string |
| 003 | `test_validation_loop.py` — exactly one `repair` call across a 3-attempt config; context carries the narrowing instruction |
| 004 | `test_validation_loop.py` — second timeout returns `final_error.error_type is TIMEOUT`, no repair |
| 005/006 | `test_sql_agent_timeout_breaker.py` (new) — loop exits at iteration 2 of a high `max_sql_iterations`; counter resets on success; deadline exit asserted separately |
| 007/008 | `test_trace_finalization.py` (new) — after a simulated `TimeoutError`, `failure_kind`, `route`, `complexity`, `total_duration_ms` are non-default; a synthetic-id call fails the test |
| 009 | `tests/unit/docs/test_ux_scenarios.py` green with SCN-120 |
| 010 | boot-validation test rejects a non-positive threshold |

Every new check is **probed both ways** — watched failing against a planted defect
before being trusted (stage-6 gate).

## 9. Out of scope

Process-wide breaker with Redis cooldown (K1) · auditing the rest of the singleton's
per-request state (K11) · `docs/brand/` bootstrap · the inherited m0 rows K4–K9.
