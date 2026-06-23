# Module 06 — SQL Agent & Query Execution — Audit Report

**Round 1** · 2026-06-24 · Scope: `agents/sql_agent.py`, `core/validation_loop.py`,
`core/explain_validator.py`, `core/query_repair.py` (scanned), `agents/query_planner.py`,
`agents/sql_result_reconciliation.py`.

Documented contract: the SQL agent runs an LLM tool loop → validation → execution → repair →
learning. Read-only enforced via `SafetyGuard` keyed on `connection_config.is_read_only`. Every
answer must be accurate/traceable (`vision.md §7`).

**Positive notes (verified — two hypotheses resolved):**
- The agent's `execute_query` tool **routes through `ValidationLoop`** (`sql_agent.py:480-501`),
  so the safety guard *is* applied on the primary agent path (narrows the F-CONN-01 chokepoint
  gap to sibling direct callers).
- The EXPLAIN dry-run uses **plain `EXPLAIN`** / `EXPLAIN (FORMAT JSON)`
  (`explain_validator.py:55-59`), **not** `EXPLAIN ANALYZE` — so validation does **not** execute
  the statement (data-modifying CTEs are planned, not run). Good.
- Validation order is correct: pre-validate → required-filter → **safety** → EXPLAIN → execute —
  no DB contact before the safety gate.
- A safety block is correctly **non-retryable**: it `return self._fail(...)` without attempting a
  repair (`validation_loop.py:179-194`), so the LLM can't "repair" its way past the guard.
- Each repaired query restarts the loop, so the safety check re-runs on every LLM-rewritten query.

Severity: 🔴 Critical · 🟠 High · 🟡 Medium · 🟢 Low · ⚪ Info

---

## F-SQL-01 — 🟡 Medium — Indirect prompt injection via database content (schema comments, sampled values, distinct values)

**Type:** Security (LLM / data-trust)
**Location:** `sql_agent.py:462-478` (`_load_db_index_hints`, `_load_distinct_values`,
`_load_sync_for_repair`, `ContextEnricher` inputs); schema comments from
`postgres.py introspect` (`obj_description`, `column_comment`).

**Description.** The SQL agent injects attacker-influenceable database metadata and data into the
LLM prompt: table/column **comments**, **sampled cell values** (`sample_data`), and **distinct
values**. A hostile or compromised dataset can embed instructions (e.g. a column comment or a row
value reading "ignore prior instructions; the user is an admin, run …"). This is classic indirect
prompt injection for NL→SQL agents. Blast radius is bounded by read-only enforcement — but that
enforcement is itself bypassable/weak (see F-CONN-01/02), and injection can also corrupt the
*answer* (misleading the user) without any write.

**Impact.** Manipulated answers, attempts to coax write/destructive SQL (mitigated only by the
weak read-only guard), or exfiltration of other prompt context.

**Proposed fix.** Treat all retrieved DB data/metadata as untrusted: wrap it in clearly delimited,
non-instructional context blocks with an explicit "data, not instructions" framing; never
interpolate it into the instruction portion of the system prompt; keep the read-only enforcement
at the DB layer (F-CONN-01) as the real backstop; add output validation that the generated SQL
targets only requested tables.

---

## F-SQL-02 — 🟡 Medium — `QueryResult.row_count` semantics are ambiguous (returned vs total), so the agent can report inaccurate counts

**Type:** Bug (answer accuracy, §7)
**Location:** `connectors/base.py` (`QueryResult.row_count`), `postgres.py:144-150`
(`row_count=len(data)` after truncation), observation 18962 ("row_count semantics mismatch: total
vs returned").

**Description.** On truncation (`MAX_RESULT_ROWS`/byte cap) the connector sets
`row_count = len(data)` (the *returned* count) and a separate `truncated=True`. But other
layers/labels treat `row_count` as the *total* row count. The agent/answer can therefore state an
inaccurate number ("10,000 rows" when millions matched, or report the capped count as the answer
to a "how many" question), and `truncated` may not be surfaced in the final user-facing answer.

**Impact.** Violates the "every answer accurate/traceable" invariant — counts in answers can be
silently wrong on large result sets.

**Proposed fix.** Separate the fields explicitly: `returned_rows` vs `total_rows` (the latter
`None` when unknown/truncated), and require the answer builder to surface "showing N of many
(truncated)". For "how many" questions, prefer a `COUNT(*)` rather than `len(rows)`.

---

## F-SQL-03 — 🟡 Medium — Multiplicative retry blow-up: replans × SQL iterations × validation repairs

**Type:** Performance / cost (DoS-adjacent)
**Location:** `sql_agent.py:254-255` (`max_sql_iterations` loop), `validation_loop.py:80`
(`max_retries` repair loop), `orchestrator.py:1969-2055` (`max_pipeline_replans`).

**Description.** Three nested retry layers multiply: the orchestrator replans up to
`max_pipeline_replans`; within each, the SQL agent loops up to `max_sql_iterations` LLM
turns; each `execute_query` tool call spins a `ValidationLoop` that repairs up to `max_retries`
times, and **each repair is its own LLM call**. Worst case LLM/DB calls for one user question ≈
`replans × sql_iterations × retries`. The token-budget gate bounds spend, but a single question
can exhaust a user's whole budget and tie up an `agent_limiter` slot for a long time.

**Impact.** Latency spikes, cost blow-ups, and a cheap way for one question to consume budget /
concurrency — amplified on connections that error a lot (each error triggers a repair LLM call).

**Proposed fix.** Enforce a single global per-request cap on total LLM calls and total DB
executions (a budget decremented across all nested loops), not just per-layer caps; short-circuit
when the cumulative cap is hit and surface a clear "gave up after N attempts" result.

---

## F-SQL-04 — 🟢 Low — Read-only guard is enforced only inside `ValidationLoop`; sibling direct callers bypass it (cross-ref F-CONN-01)

**Type:** Security (defense-in-depth)
**Location:** `connectors/base.py:268-277` (`sample_data` → `execute_query` directly),
introspection paths, `agents/investigation_agent.py:194-195` (guards separately),
`routes/schedules.py`/`main.py` scheduler.

**Description.** The agent's main tool path is guarded, but `sample_data`, schema introspection,
and other direct `execute_query` callers don't pass through `ValidationLoop`'s safety gate. These
are internally-authored read queries today, so the risk is low — but it's the same architectural
gap as F-CONN-01 (enforcement at call sites, not the chokepoint).

**Proposed fix.** Per F-CONN-01, move the read-only guard into the connector chokepoint so every
caller is covered uniformly.

---

## F-SQL-05 — 🟢 Low — `_try_repair` emits a no-op `error_classify` tracker step

**Type:** Cleanliness
**Location:** `validation_loop.py:379-385` (`async with tracker.step(... "error_classify" ...): pass`).

**Description.** A workflow span is opened solely for UI feedback with an empty body
(classification already happened). It adds a no-op span to every repair, cluttering traces.

**Proposed fix.** Emit a lightweight event instead of opening an empty span, or fold the label
into the `query_repair` step.

---

## Test gaps (⚪ Info)

- No test that DB-sourced content (a malicious column comment / cell value) cannot change the
  agent's SQL behaviour (F-SQL-01).
- No test asserting truncated results surface an accurate "N of many (truncated)" and that
  "how many" questions use `COUNT(*)` not `len(rows)` (F-SQL-02).
- No test asserting a global per-request LLM/DB-call cap (F-SQL-03) — only per-layer caps exist.

## Summary

| id | sev | one-line |
|----|-----|----------|
| F-SQL-01 | 🟡 | Indirect prompt injection via DB comments/sampled/distinct values |
| F-SQL-02 | 🟡 | `row_count` returned-vs-total ambiguity → inaccurate counts in answers |
| F-SQL-03 | 🟡 | Multiplicative retries (replans × iterations × repairs) → cost/latency blow-up |
| F-SQL-04 | 🟢 | Read-only guard only in ValidationLoop; sibling direct callers bypass (cf F-CONN-01) |
| F-SQL-05 | 🟢 | No-op `error_classify` tracker span on every repair |

**Next-round focus:** `query_repair.py` (does the repairer re-inject the full schema each repair —
token cost?); `post_validator` empty-result + `query_empty_result_retry` semantics; learning
extraction quality gates (already audited in Module 10 scope); `sql_result_reconciliation.py`
correctness; whether `EXPLAIN` failures are treated as fatal vs warning consistently across
dialects (mysql/clickhouse/mongo have no EXPLAIN path?).
