# Acceptance — query-timeout classification, breaker, deadline, trace finalization

**Date:** 2026-08-08 · **Branch:** `fix/query-timeout-classification` → `main`
**Deployed:** Heroku release **v202** from commit `278b043` (docs follow-up `b4a6ca0`)
**Suite:** 6043 passed / 5 skipped / 1 xfailed · **coverage 79%** (gate 72%, exit 0)

## REQ coverage — every row with evidence from a check seen failing

| ID | Requirement | Evidence | State |
|---|---|---|---|
| 001 | Connector timeout classifies as `TIMEOUT`, not `UNKNOWN` | `test_error_classifier.py::TestSuppliedErrorType` — a case per connector; probed by reverting the short-circuit | **met** |
| 002 | Connectors emit a typed error; the classifier stops reading the app's own string | `test_connector_timeout_type.py` (6 tests); seen red first as `ModuleNotFoundError: app.core.error_types`. A test pins that the untyped string is still `UNKNOWN` — no regex was added for it | **met** |
| 003 | At most one LLM repair per timeout, prompted to narrow | `test_validation_loop.py::TestTimeoutBudget` + `TestTimeoutRepairHint`; probed by disabling the budget (repair count 1 → 2, red) | **met** |
| 004 | Second consecutive timeout ends the loop as `TIMEOUT`/transient | same class, asserting `final_error.error_type is TIMEOUT` and no further repair | **met** |
| 005 | Two consecutive timeout-terminated tool calls break the SQL loop | `test_sql_agent_timeout_breaker.py`; breaker + threshold validated at boot | **met** |
| 006 | The SQL loop honours a wall-clock deadline, not only an iteration count | deadline built in `run()`'s frame from the budget the orchestrator already passed and the loop ignored | **met** |
| 007 | An abnormally-ended run records `failure_kind` and keeps its routing signals | `test_trace_finalization_failure_kind.py` — asserts on the **emitted UPDATE**, after the first version (source-text assertions) was caught passing against a planted defect | **met** |
| 008 | `finalize_trace` is never called with an id that cannot match | both abnormal REST paths go through one logged fallback helper | **met** |
| 009 | Honest user-facing message distinguishing environment from query | `SCN-120` in `docs/ux/scenarios.md`; `tests/unit/docs/` green, probed with a bad `Coverage:` path | **met** |
| 010 | Breaker + deadline are documented settings, invalid values rejected at boot | `config.py` docstrings, `.env.example`, `CLAUDE.md` flag table; boot test for non-positive threshold | **met** |
| 011 | Stale docs corrected | `SYSTEM_ARCHITECTURE.md` timeout claim; `CLAUDE.md` `approach`/`route_ms` claim — the correction carries its own disproving command | **met** |
| 012 | Suite green, coverage ≥ 72% | 6043 passed, 79%, gate exit 0 | **met** |
| 013 | Deployed and verified against the running system | v202; health 200; `Database schema is up to date (revision=a7b8c9d0e1f2)`; `Application startup complete`; zero ERROR/Traceback since boot; CI, deploy and both repos all on `278b043` | **met — with the limit below** |

## The limit, stated rather than glossed

**REQ-013 proves a clean boot of the right commit, not the fixed behaviour.** Exercising
the timeout path needs a real question against a database that accepts EXPLAIN and never
returns rows. Production has had **no chat traffic** since the 2026-08-07 04:44 restart —
verified twice: zero `api/chat` entries across the log window, and the `health_check`
workflow (which only fires once a connector pool is registered) has not run since.
Carry-over **K14** names the check for the next real timeout.

## Ladder walk — absences found, not just rows compared

Three gaps surfaced by walking each REQ down to its artefact rather than reading the table:

1. **The branch had no scenario.** Code was built in a worktree, `SCN-120` was authored in
   the main checkout. `git show <branch>:docs/ux/scenarios.md | grep -c SCN-120` → `0`,
   caught before the merge. Isolation that protects code separates everything else too.
2. **A test passed against its own defect.** The first `finalize_trace` check asserted on
   source text; a planted blanket-overwrite kept the text it looked for. Rewritten to
   assert on the emitted statement, then re-probed red→green.
3. **The stated root cause was wrong twice, and reading the code fixed it both times.**
   The plan named three classifier call sites (two exist — one classifies `str(exc)`),
   and K12 was recorded as "signals not stamped" when the defect was `finalize_trace`
   *erasing* values already written. Implementing the ledger entry as written would have
   produced a green test and no production change.

## Carry-over ledger

14 rows. **9 open**, and one of them is security: **K4** — `ssh_key_id` has no ownership
check, inherited from m0, still the recommended next piece of work. All are in
`BACKLOG.md` with evidence.

## Not done, by decision

Wiki sync and the code-graph refresh (K2 — the graph has never been built in this
project). Both are recommendations, neither gates; doing them properly is a next
session's work rather than a rushed line in this one.
