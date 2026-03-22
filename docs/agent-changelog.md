# Agent Changelog

Changes made by the continuous improvement agent.

---

## Cycle 2 — 2026-03-22

### Infrastructure

- **Recreated backend venv** — Removed stale `.venv` with shebangs pointing to `/Users/sshlg/DATA/esim-database-agent/`. Recreated with correct paths. All CLI tools (pip, ruff, mypy, pytest) now work directly without `python -m` prefix.

### Tests

- **batch_service.py: 46% -> 100%** — Added 9 unit tests for `execute_batch` covering: batch not found, connection not found, all-succeed, all-fail, partial failure, row cap (500), tracker event emission, missing SQL key fallback, connector disconnect on failure.
- **code_db_sync_service.py: 55% -> 93%** — Created new test file with 39 tests covering: upsert (create/update), get_sync, get_table_sync, delete_stale_tables, delete_all, summary CRUD, is_synced, set/get_sync_status, get_status dict, mark_stale, mark_stale_for_project, runtime enrichment (JSON merge, text append, invalid field, missing table, invalid JSON, dedup), prompt context formatting, detail formatting, response formatting.

### CI/CD

- **Coverage threshold raised** — CI `--cov-fail-under` increased from 68% to 69% in `.github/workflows/ci.yml`.

---

## Cycle 1 — 2026-03-22

### Fixed

- **Missing `google-auth` dependency in local venv** — Installed `google-auth>=2.0.0` (declared in `pyproject.toml` but absent from `.venv`). Fixes 3 failing unit tests in `TestVerifyGoogleToken`.

### Documentation

- **BACKLOG.md** — Updated Sprint 1 table: tasks 6-10 changed from `pending` to `done`. Updated header from "Sprint 1 — Active" to "Sprint 1 — Complete". Populated Completed section with all 10 tasks and completion dates.
- **ROADMAP.md** — Checked all Sprint 1 items under "AI Chief Data Brain" as complete (`[x]`). Updated section header to "Sprint 1 Complete".

### Infrastructure

- **Created `/docs/` agent tracking directory** with:
  - `agent-status.md` — cycle state and health summary
  - `agent-backlog.md` — prioritized improvement backlog
  - `agent-findings.md` — discoveries and analysis
  - `agent-changelog.md` — this file
  - `agent-test-matrix.md` — core flow verification matrix
