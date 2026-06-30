# Plan — Diagnostics capture (TDD + subagent-driven)

Spec: `docs/superpowers/specs/2026-06-30-diagnostics-capture-design.md`. Branch:
`feat/diagnostics-capture-2026-06-30`. Every task: failing test → confirm fail → minimal
impl → confirm pass → conventional commit. Status protocol: DONE / DONE_WITH_CONCERNS /
BLOCKED.

## Dependency graph / groups

- **G0 (sequential, contracts-first):** T1 model+migration, T2 config flags. Lock shared
  contracts before any parallel work.
- **G1 (parallel after G0, non-overlapping files):**
  - T3 `QueryFailureService` + `maybe_record_query_failure` (services/query_failure_service.py)
  - T4 RunCoordinator flag snapshot (services/run_coordinator.py)
  - T5 metrics counter `diagnostics_persist_failures` (core/metrics.py)
- **G2 (sequential glue, depends on G1):**
  - T6 SQLAgent capture hook (agents/sql_agent.py) — depends T3
  - T7 read API + analytics client (api/routes/logs.py + frontend analytics.ts) — depends T1/T3
- **G3 (integration):** T8 full suite + smoke + ruff/mypy + manual-verification notes.

No two parallel tasks write the same file (T3/T4/T5 distinct).

---

### T1 — QueryFailure model + migration  [G0]
- Create `app/models/query_failure.py` per spec §3.2. Register in models package `__init__` if the repo imports models there (check `app/models/__init__.py`).
- `cd backend && PYTHONPATH=. .venv/bin/alembic revision --autogenerate -m "query_failures table"`; review the generated migration — **Postgres-safe** server defaults (no `sa.text("1")` for booleans/ints that break PG; follow existing migrations' patterns).
- Tests: `tests/unit/test_query_failure_model.py` — instantiate, default fields, `to_dict()` if added. Migration round-trips on the test DB (a model-create smoke).
- DoD: `alembic upgrade head` clean on SQLite **and** the migration uses PG-safe defaults; model imports.

### T2 — config flags  [G0]
- Add `diagnostics_capture_enabled=True`, `diagnostics_attempt_history_max=20`,
  `diagnostics_raw_error_max_chars=8000` to `app/config.py` (+ `.env.example`).
- Test: `tests/unit/test_config_settings.py` env-sync gate already enforces docs; add an assertion the defaults exist.
- DoD: config-sync test green.

### T3 — QueryFailureService  [G1, dep T1/T2]
- `app/services/query_failure_service.py` per spec §3.3: `record(...)` builds the row from
  `attempts: list[QueryAttempt]` (from `app.core.query_validation`), serializes ≤
  `diagnostics_attempt_history_max`, caps `raw_error`, sets `failed_sql`/`error_type` from the
  last errored attempt. Best-effort try/except → on failure increment
  `MetricsCollector.diagnostics_persist_failures` (T5) + `logger.error`. `maybe_record_query_failure`
  no-ops when disabled or no errored attempts.
- Tests `tests/unit/test_query_failure_service.py`: records a row from attempts (failed +
  recovered); truncates attempts/raw_error to caps; no-op when flag off; no-op when zero
  errored attempts; a DB error inside record does not raise + bumps the counter.
- DoD: tests green; never raises.

### T4 — RunCoordinator flag snapshot  [G1, dep none beyond G0]
- In `services/run_coordinator.py` where an `IndexingRun` is created, write
  `meta_json["flags"]` = snapshot of the spec §3.5 flag set from `settings`.
- Tests `tests/unit/test_run_coordinator_flag_snapshot.py` (or extend existing): a created run's
  `meta_json` contains `flags` with the expected keys/values.
- DoD: tests green; existing run_coordinator tests still pass.

### T5 — diagnostics metric  [G1]
- `core/metrics.py`: add `diagnostics_persist_failures` counter + increment method; surface in
  the `/api/metrics` JSON dict.
- Tests `tests/unit/test_metrics*.py`: increment + snapshot exposes it.
- DoD: tests green; `/api/metrics` includes the field.

### T6 — SQLAgent capture hook  [G2, dep T3]
- In `agents/sql_agent.py::_handle_execute_query` after `validation_loop.execute(...)`, when
  `loop_result.attempts` has any errored attempt, fire `maybe_record_query_failure` as a
  non-blocking best-effort task with ids from `AgentContext`. Gate via `diagnostics_capture_enabled`.
- Tests `tests/unit/test_sql_agent_failure_capture.py`: a failing validation loop triggers a
  record call (mock the service) with the right ids + attempts; a clean success does not.
- DoD: tests green; sql_agent suite still green; capture never blocks/raises.

### T7 — read API + client  [G2, dep T1/T3]
- `api/routes/logs.py`: `GET /{project_id}/query-failures` (list, owner-only, filters) +
  `/{id}` (detail). Mirror the existing `/requests` owner gate + pagination.
- `frontend/src/lib/api/analytics.ts`: add `logs.queryFailures()` + `logs.queryFailureDetail()`.
- Tests `tests/unit/test_logs_query_failures_api.py`: owner can list/detail; non-owner 403;
  filters work; tenant isolation (other project's rows not returned).
- DoD: tests green.

### T8 — integration  [G3]
- Full `tests/unit tests/integration` + `make smoke` + `ruff format --check` + `ruff check` +
  `mypy app/`. Update `CHANGELOG.md [Unreleased]`. Manual-verification notes from spec §5.
- DoD: all gates green; CHANGELOG updated.

---

## Human steps (end)
- None required to ship; post-deploy verification (spec §5) is operator-run but optional.
