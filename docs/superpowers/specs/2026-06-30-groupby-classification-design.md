# Spec — GROUP BY error classification + self-heal repair hint (and replan dangling-dep feedback)

- **Date:** 2026-06-30
- **Author:** orchestrator audit follow-up (post-incident)
- **Incident:** prod workflow `9ce03f80` (project `38856e63`, MySQL `esim_analytics`) — cohort-analysis request failed; `pipeline_end: failed` at 2026-06-30T09:00:38Z.
- **Skills applied:** senior-architect (impact/ADR/coupling), senior-ml-engineer (LLM self-healing pipeline + observability/recall), senior-prompt-engineer (repair-hint = structured-output / format-enforcement design).

---

## 1. Problem statement (precise)

A cohort-analysis chat request produced SQL that violated **GROUP BY** rules. The self-healing
SQL repair loop could not recover and the pipeline failed. Three distinct defects, ranked:

### P1 — Classifier recall gates the self-healing loop (PRIMARY)
`app/core/error_classifier.py` is a per-dialect **allow-list of regexes**. An unmatched error →
`QueryErrorType.UNKNOWN`. `RetryStrategy.get_repair_hints` only schema-enriches
`COLUMN_NOT_FOUND` / `TABLE_NOT_FOUND`; UNKNOWN yields the raw error text but **no actionable
rewrite guidance**. The **GROUP BY violation** — one of the most common analytics SQL errors —
is **absent from all three SQL dialects**:

| Dialect | Error | Canonical message (grounded) | Present? |
|---|---|---|---|
| MySQL | 1055 `ONLY_FULL_GROUP_BY` | `Expression #N of SELECT list is not in GROUP BY clause and contains nonaggregated column '…' which is not functionally dependent …; this is incompatible with sql_mode=only_full_group_by` (verbatim from prod log `9ce03f80`) | ❌ |
| PostgreSQL | SQLSTATE 42803 | `column "…" must appear in the GROUP BY clause or be used in an aggregate function` (PostgreSQL error reference) | ❌ |
| ClickHouse | `NOT_AN_AGGREGATE` (215) | `Column … is not under aggregate function and not in GROUP BY` (ClickHouse issue tracker) | ❌ |

**Consequence:** UNKNOWN → repair retries with no targeted hint → the LLM regenerates the same
GROUP-BY-violating shape across all attempts → `Query failed after 3 attempts`. ML-eng lens: a
self-correction pipeline's recovery rate is **bounded by the recall of its error-signal layer**;
the repeated `WARNING app.core.error_classifier: Unclassified DB error (mysql): (1055, …)` is the
system reporting its own recall gap (memory obs 23709/23710).

### P2 — Replan cannot recover from a dangling stage reference (SECONDARY)
On resume, only **successful** stages seed the replan context. The planner replanned with a
dependency on `cohort_signups` (the dropped first stage) → dangling dep → the orchestrator guard
**correctly rejected** both attempts (prior-audit fix, no crash) → `Replan failed after 2
attempts`. Root: the replan prompt does **not** constrain the planner to the allowed stage-id set,
nor feed the specific dangling-dep validation error back for self-correction → it repeats the
mistake and gives up.

### P3 — MySQL connection down (OPERATIONAL, out of scope)
At 09:23:52Z health check → `(2003, "Can't connect to MySQL server on '127.0.0.1'")` — SSH tunnel
dropped (was healthy 09:18:52Z). Distinct from the 09:00 failure (DB was up, returning 1055).
Infra remediation only; no code change. Note: the A3 follow-up (CONNECTION_ERROR retryable) means
a persistently-down tunnel degrades cleanly after bounded backoff retries.

**Not introduced by the 2026-06-29 follow-ups deploy (v189).** P1 predates them. The A2
empty-result identity guard interacts (see §5) but did not cause the failure.

---

## 2. Scope

- **In scope (this spec):** P1 — GROUP BY classification + targeted repair hint, all three SQL
  dialects. P2 — replan dangling-dep feedback (smaller, same spec, separable commit).
- **Out of scope:** P3 (infra); disabling `only_full_group_by` (see §6 rejected alternatives);
  Mongo (no GROUP BY analogue — aggregation pipeline `$group` errors differently).

---

## 3. Locked contracts

### 3.1 New error type — `app/core/query_validation.py`
```python
class QueryErrorType(StrEnum):
    ...
    GROUP_BY_VIOLATION = "group_by_violation"   # NEW
```
- `NON_RETRYABLE_ERRORS` — **unchanged** (GROUP_BY_VIOLATION is retryable; it is mechanically
  fixable by rewriting the query).

### 3.2 Classifier patterns — `app/core/error_classifier.py`
Add one `_Pattern` (entity_group `None`) per dialect, ordered **before** the generic
`SYNTAX_ERROR` pattern of that dialect (a GROUP BY error must not be mis-bucketed as syntax):

```python
# POSTGRES_PATTERNS
_Pattern(re.compile(r"must appear in the GROUP BY clause", re.I),
         QueryErrorType.GROUP_BY_VIOLATION, None),
# MYSQL_PATTERNS
_Pattern(re.compile(r"not in GROUP BY clause|only_full_group_by", re.I),
         QueryErrorType.GROUP_BY_VIOLATION, None),
# CLICKHOUSE_PATTERNS
_Pattern(re.compile(r"not under aggregate function and not in GROUP BY|NOT_AN_AGGREGATE", re.I),
         QueryErrorType.GROUP_BY_VIOLATION, None),
```
The existing cross-dialect fallback (lines ~234–258) then also catches a dialect mislabel.
`_build_message(GROUP_BY_VIOLATION, None)` → `"GROUP BY violation"`.

### 3.3 Repair hint — `app/core/retry_strategy.py::get_repair_hints`
Add a branch (prompt-eng: explicit, actionable, format-enforcing — not just the raw error):

```python
elif et == QueryErrorType.GROUP_BY_VIOLATION:
    parts.append(
        "GROUP BY fix required. Every column in the SELECT list must EITHER appear in the "
        "GROUP BY clause OR be wrapped in an aggregate (SUM/COUNT/MIN/MAX/AVG/COUNT(DISTINCT …)). "
        "Rewrite by one of: (a) add the offending non-aggregated column(s) to GROUP BY; "
        "(b) wrap them in an aggregate. For cohort / time-bucket analysis, GROUP BY the bucket "
        "expression (e.g. DATE_FORMAT(created_at,'%Y-%m') in MySQL, date_trunc('month', created_at) "
        "in Postgres) and aggregate the per-row measures — do NOT select raw per-row timestamps "
        "alongside aggregates. Do not change the question's intent."
    )
```
This reaches the LLM via the existing `context_enricher.build_repair_context` →
`get_repair_hints(...)` section (confirmed path: `app/core/context_enricher.py:69`). No
`schema_hint` plumbing change needed; `error.raw_error` (full) is already included.

### 3.4 P2 — replan feedback (`app/agents/adaptive_planner.py` + `prompts/planner_prompt.py`)
- `replan(...)` already receives `completed_stages`. Compute
  `allowed_dep_ids = {successful completed stage ids}` and pass into the replan prompt: an
  explicit "you may only set `depends_on` to one of: [ids]" constraint.
- When the orchestrator's dangling-dep guard rejects a replan, thread the specific error
  (`Stage 'X' depends on unknown stage 'Y'`) back into the next replan attempt's `replan_history`
  so the planner self-corrects rather than repeating. (The guard in `orchestrator._run_pipeline_replans`
  stays as the backstop.)

---

## 4. Test plan (TDD, RED→GREEN)

| File | Cases |
|---|---|
| `tests/unit/test_query_validation.py` | `GROUP_BY_VIOLATION not in NON_RETRYABLE_ERRORS` |
| `tests/unit/test_error_classifier.py` | MySQL 1055 string → GROUP_BY_VIOLATION + `is_retryable`; PG 42803 string → same; ClickHouse string → same; cross-dialect fallback (PG string under `mysql` dialect) → GROUP_BY_VIOLATION; a GROUP BY string is NOT mis-classified as SYNTAX_ERROR |
| `tests/unit/test_retry_strategy.py` | `get_repair_hints(GROUP_BY_VIOLATION, schema)` contains "GROUP BY" + "aggregate" |
| `tests/unit/test_pipeline.py` (P2) | replan prompt receives `allowed_dep_ids`; a dangling-dep replan error is fed into the next attempt |

No new migration, no config flag (pure correctness improvement, safe-by-default).

---

## 5. Whole-system impact (architect lens)

**Touch set (files):** `core/query_validation.py`, `core/error_classifier.py`,
`core/retry_strategy.py` (+ P2: `agents/adaptive_planner.py`, `agents/prompts/planner_prompt.py`)
+ 4 test files. **No** DB schema, **no** API surface, **no** config, **no** connector change.

**Coupling / blast-radius (verified, not assumed):**

1. **Exhaustive `match` on `QueryErrorType`?** None. `grep` shows only isolated `==` checks:
   `validation_loop` (EMPTY_RESULT), `context_enricher` (TABLE_NOT_FOUND), `learning_analyzer`
   (SYNTAX_ERROR, TIMEOUT). A new enum value breaks no exhaustive handling. ✅
2. **`RetryStrategy.should_retry`** — consults `NON_RETRYABLE_ERRORS`; GROUP_BY_VIOLATION absent →
   retryable. The repaired query now **differs** (adds GROUP BY / aggregates). ✅
3. **Composes with A2 (empty-result identity guard, 2026-06-29):** before the fix, the LLM
   regenerated near-identical broken SQL, so A2's `_normalize_sql` guard could short-circuit the
   repair (treat repeated-identical as terminal) — failing *faster*. With a real hint the repaired
   query diverges, so A2 no longer misfires. **Net positive interaction.** ✅
4. **Composes with A3 (transient-conn retry):** unrelated path (GROUP_BY_VIOLATION is not in
   `_TRANSIENT_RETRY_ERRORS`) → goes through the normal LLM-repair branch, not the same-query
   backoff. ✅
5. **`learning_analyzer`** keys on SYNTAX_ERROR/TIMEOUT only — GROUP_BY_VIOLATION will not feed
   the learning heuristic. Optional future: add it so the system *learns* GROUP BY corrections
   per-connection. Not required for the fix.
6. **Retrieval-eval CI gate** (`test_retrieval_eval.py`, `test_reranker.py`) — unaffected (no
   retrieval/embedding change).
7. **Multi-dialect:** the gap and fix span MySQL + Postgres + ClickHouse. Mongo excluded.
8. **Coverage gate (72%):** net new code is small + fully tested → coverage non-decreasing.

**Observability (ML-eng lens):** keep the `Unclassified DB error` WARNING as the **recall canary**
— after this fix it should stop firing for GROUP BY errors. Recommended follow-up (not blocking):
a `MetricsCollector` counter for `error_type=unknown` so a future recall gap is alertable rather
than discovered post-incident.

**Failure-mode after fix:** if the LLM still cannot satisfy GROUP BY within `max_retries`, the
loop exhausts and surfaces an honest error with the GROUP BY reason now classified (not "unknown")
— strictly better diagnosability. No new infinite-loop risk (retry ceiling + A2 identity guard +
B3 replan fingerprint + B4 pipeline wall-budget all bound it).

---

## 6. Rejected alternatives

- **Disable `only_full_group_by` via session `sql_mode`** (MySQL) / loosen PG/CH — hides genuine
  aggregation ambiguity → arbitrary per-group row values → **wrong numbers**. Violates vision §7
  ("every answer traceable / no impossible numbers"). Rejected. Fix the SQL, not the mode.
- **Reuse `SYNTAX_ERROR`** for GROUP BY — routes through the syntax repair path with no targeted
  aggregate guidance, and pollutes `learning_analyzer`'s syntax signal. Rejected for a dedicated
  type.
- **Generic "unknown → ask LLM to fix" hint** — too vague; prompt-eng evidence (the 3 failed
  attempts) shows the LLM needs the explicit GROUP-BY/aggregate rewrite rule.

---

## 7. Rollout

- TDD per fix; one commit P1, one commit P2; full unit+integration + ruff/mypy gates.
- No migration / flag → deploy is a straight push (auto-deploy). Safe-by-default.
- Post-deploy verification: re-run the cohort query against `esim_analytics` (once the MySQL
  tunnel/P3 is restored) and confirm `error_classify: group_by_violation` + successful repair in
  logs, and the absence of `Unclassified DB error (… GROUP BY …)`.

## Sources (grounded error strings)
- PostgreSQL 42803: https://www.bytebase.com/reference/postgres/error/42803-column-must-appear-in-group-by-clause/
- ClickHouse NOT_AN_AGGREGATE: https://github.com/ClickHouse/ClickHouse/issues/32744
- MySQL 1055: verbatim from prod log (workflow `9ce03f80`, 2026-06-30).
