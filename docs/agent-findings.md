# Agent Findings

Discoveries made during continuous improvement cycles.

---

## Cycle 3 — 2026-03-22

### Project State

- **Backend coverage:** 69.42% -> 70.03% (+0.61%)
- **Total unit tests:** 2132 -> 2181 (+49 new)
- **Frontend tests:** 346/346 (unchanged, all pass)

### UX Findings

1. **Misleading empty states (FIXED):** InsightFeedPanel and DashboardList both caught API errors silently and showed "no data" empty states — indistinguishable from truly empty responses. Users would think their data is empty when it's actually a network error. Added `loadError` state tracking with Retry buttons.

2. **ConnectionSelector no empty state (FIXED):** When `connections.length === 0` and the form was closed, the list region rendered nothing. Added "No connections yet" text.

3. **VizRenderer null return (FIXED):** `if (!payload) return null` caused visualization area to disappear silently. Replaced with a fallback message.

4. **Additional UX gaps discovered (not yet fixed):**
   - Mobile notes drawer: missing Escape key, focus trap, aria-modal (P2)
   - Suggestion chips: truncated text lacks aria-label for screen readers (P3)
   - Insight cards: missing aria-expanded on toggle buttons (P3)
   - useMobileLayout: initial false default causes desktop layout flash on mobile (P3)

### Coverage Improvements

| Service | Before | After | Tests Added |
|---------|--------|-------|-------------|
| connection_service.py | 69% | 99% | 20 |
| project_overview_service.py | 67% | 93% | 24 |
| viz/export.py | 68% | 100% | 1 |
| viz/utils.py | 83% | 100% | 6 |

### Key Testing Observations

- `connection_service.test_ssh` imports `asyncssh` locally inside the method — patches must target `asyncssh.connect` directly rather than `app.services.connection_service.asyncssh`.
- `project_overview_service.save_overview` exercises incremental hashing; full integration test requires carefully sequenced mock results since it calls 6 builder methods in order.
- `project_overview_service._build_db_section` uses `:,` format specifier on `row_count` — MagicMock objects can't handle this; test stubs need concrete numeric values.

---

## Cycle 2 — 2026-03-22

### Project State

- **Backend coverage:** 68.78% -> 69.42% (+0.64%)
- **Total unit tests:** 2103 -> 2132 (+29 new)
- **Frontend tests:** 345/345 (unchanged, all pass)

### Infrastructure Fix

- **Stale venv shebangs** — The backend `.venv` was created when the project was named `esim-database-agent`. All executables in `.venv/bin/` had shebangs pointing to the old path. Recreated the entire venv under the correct project directory. All tools (pip, ruff, mypy, pytest) now work with direct invocation.

### Coverage Improvements

| Service | Before | After | Tests Added |
|---------|--------|-------|-------------|
| batch_service.py | 46% | 100% | 9 (execute_batch: all paths) |
| code_db_sync_service.py | 55% | 93% | 39 (full CRUD + formatting) |

### Key Testing Observations

- `batch_service.execute_batch` had zero test coverage despite being the core execution method. It manages its own DB session (via `async_session_factory`), requiring careful mocking.
- `code_db_sync_service` formatting methods (`sync_to_prompt_context`, `table_sync_to_detail`, `sync_to_response`) are static and don't need DB access, but test stubs must bypass SQLAlchemy instrumentation (can't use `__new__` on mapped classes).
- `add_runtime_enrichment` handles both JSON merge and text append patterns — edge cases like invalid existing JSON and duplicate text are now covered.

---

## Cycle 1 — 2026-03-22

### Project State

- **Version:** 0.10.0 (Unreleased changes pending)
- **Sprint 1:** All 10 tasks complete (Data Graph, Insight Feed, Anomaly Intelligence, Opportunity/Loss Detection, Action Engine, Reconciliation, Semantic Layer, Exploration, Temporal Intelligence)
- **Architecture:** Python/FastAPI backend + Next.js 15/React 19 frontend, SQLAlchemy + Alembic, ChromaDB for RAG vectors
- **Deployment:** Heroku (Docker containers), CI via GitHub Actions

### Health Check Results

| Area | Result |
|------|--------|
| Frontend TypeScript | Clean — 0 errors |
| Frontend ESLint | Clean — 0 warnings |
| Frontend Tests | 345/345 pass |
| Frontend Build | Compiles successfully, 221 kB first load JS on main page |
| Backend Lint (ruff) | Clean |
| Backend Format (ruff) | 411 files conformant |
| Backend Type Check (mypy) | 0 errors in 231 files (notes only, no errors) |
| Backend Unit Tests | 2103/2103 pass (after installing missing google-auth) |
| Backend Integration Tests | 410/410 pass |
| Test Coverage | 68.78% (target: 80%) |

### Issues Discovered

1. **Missing `google-auth` in venv (FIXED):** The `google-auth>=2.0.0` dependency in `pyproject.toml` was not installed in the local `.venv`. Root cause: venv was created before this dependency was added (or the project was moved from `esim-database-agent` without recreating venv). Impact: 3 Google OAuth unit tests failing locally. CI unaffected (fresh install). Fix: `python -m pip install google-auth`.

2. **Stale venv shebangs (NOT FIXED):** All scripts in `backend/.venv/bin/` (pip, mypy, ruff, etc.) have shebangs pointing to `/Users/sshlg/DATA/esim-database-agent/backend/.venv/bin/python`. Project was renamed/moved to `checkmydata-ai`. Workaround: use `python -m <tool>`. Proper fix: recreate venv.

3. **BACKLOG.md Sprint 1 table inconsistency (FIXED):** Tasks 6-10 marked `pending` in the sprint table but `done` in the detailed sections. CHANGELOG confirms all tasks complete. Fixed by updating the table.

4. **ROADMAP.md stale checkboxes (FIXED):** Sprint 1 items under "AI Chief Data Brain" shown as unchecked. Fixed by checking all completed items.

5. **PopoverPortal refactoring (ALREADY COMMITTED):** Changes to AccountMenu, NotificationBell, and Tooltip for portal-based rendering were already committed in `7dd1971`. Validated: all frontend checks pass.

6. **`notes.md` credential exposure (MITIGATED):** File contains plaintext SSH key, database password, and server IP. Already gitignored (line 46 of `.gitignore`). Never committed to git history. Recommendation: rotate credentials.

### Coverage Weak Spots

Services with coverage below 70%:
- `batch_service.py` — 46%
- `code_db_sync_service.py` — 55%
- `agent_learning_service.py` — 66%
- `benchmark_service.py` — 66%
- `project_overview_service.py` — 67%
- `connection_service.py` — 69%
- `db_index_service.py` — 69%

### Mypy Notes (Non-Blocking)

23 `annotation-unchecked` notes across:
- `app/core/retry.py`
- `app/connectors/ssh_tunnel.py`, `postgres.py`, `mysql.py`, `clickhouse.py`, `mongodb.py`
- `app/llm/router.py`
- `app/knowledge/vector_store.py`
- `app/api/routes/chat.py`
- `app/main.py`

These are informational — function bodies not checked due to missing type annotations. Not blocking CI.
