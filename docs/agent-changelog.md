# Agent Changelog

Changes made by the continuous improvement agent.

---

## Cycle 3 — Quality & Reliability — 2026-03-22

### UX Fixes
- **InsightFeedPanel**: Added `loadError` state tracking. API failure now shows "Couldn't load insights" + Retry button instead of misleading "No insights yet" empty state.
- **DashboardList**: Added `loadError` state tracking. API failure now shows "Couldn't load dashboards" + Retry button instead of misleading "No dashboards yet" empty state.
- **ConnectionSelector**: Added empty state rendering ("No connections yet") when `connections.length === 0` and form is closed.
- **VizRenderer**: Returns helpful "Visualization data unavailable" message instead of `null` when payload is missing.

### Backend Test Coverage
| Service | Before | After | Tests Added |
|---------|--------|-------|-------------|
| connection_service.py | 69% | 99% | 20 (test_ssh, to_config errors, update extended, pagination) |
| project_overview_service.py | 67% | 93% | 24 (save_overview, split sections, hash, notes, edge cases) |
| viz/export.py | 68% | 100% | 1 (xlsx export) |
| viz/utils.py | 83% | 100% | 6 (serialize_value: Decimal, bytes, fallback) |

### CI/CD
- Coverage threshold raised from 69% to 70%.
- Total backend unit tests: 2132 → 2181 (+49).
- Overall coverage: 69.42% → 70.03%.

---

## UI Redesign — 2026-03-22

### Chat Message Feedback

- **Removed 4 UI blocks** from `ChatMessage.tsx`: quick-action chips ("Top 10", "Group by", "Sort desc"), FollowupChips (AI-generated suggestions), DataValidationCard ("Do these numbers look right?"), WrongDataModal ("Report Incorrect Data" dialog), and the "Report wrong data" icon button.
- **Enhanced `handleFeedback`** — Thumbs up on SQL results now records `verdict: "confirmed"` via `api.dataValidation.validateData`. Thumbs down records `verdict: "rejected"` and auto-sends an investigation prompt to the agent in chat.
- **Removed imports** for `DataValidationCard`, `FollowupChips`, `WrongDataModal`, and the `wrongDataOpen` state.

### Sidebar "+New" Pattern

- **`SidebarSection.tsx`** — Added `open &&` guard so the "+" action button only renders when the section is expanded.
- **6 child components** (`ProjectSelector`, `ConnectionSelector`, `ChatSessionList`, `RulesManager`, `ScheduleManager`, `DashboardList`) — Added `createRequested` / `onCreateHandled` props and removed their internal "+New" buttons.
- **`Sidebar.tsx`** — Added create-request state and `action` prop for all 6 sections (Projects, Connections, Chat History, Custom Rules, Schedules, Dashboards) in both mobile and desktop views.

### Tests

- **ChatMessage.test.tsx** — Removed 2 FollowupChips tests, removed FollowupChips mock, added `dataValidation.validateData` to API mock, added `sessionId` to render helper, added 3 new tests (thumbs down auto-sends, thumbs up confirms, thumbs down on non-SQL doesn't send).
- **6 component test files updated** — `ChatSessionList`, `ConnectionSelector`, `ProjectSelector`, `RulesManager`, `ScheduleManager`, `DashboardList` tests updated to use `createRequested` prop instead of clicking removed "+New" buttons.
- All 39 test files pass (346 tests).

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
