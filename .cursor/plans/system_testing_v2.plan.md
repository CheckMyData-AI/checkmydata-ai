# CheckMyData.ai — System Testing & Stabilization Plan v2

**Date:** 2026-03-22  
**Baseline:** 1,922 tests (1,402 unit + 309 integration + 211 frontend), 65% backend coverage, CI green  
**Goal:** Close remaining coverage gaps, harden security, test untested services/routes/components, reach 70%+ backend coverage, add frontend coverage threshold

---

## STEP 1. PRODUCT UNDERSTANDING

**What:** AI-powered database query agent. Users connect databases (PostgreSQL, MySQL, MongoDB, ClickHouse) + Git repos, then ask questions in natural language. A multi-agent system (Orchestrator → SQL/Knowledge/Viz/MCP agents) generates SQL, executes it safely (read-only), and renders visualizations.

**Who for:** Data analysts, developers, and teams who need to query databases without writing SQL.

**Key user scenarios:**
1. **Happy path:** Register → Create project → Add SSH key → Add connection → Index DB → Ask question → Get chart/table
2. **Team collaboration:** Owner invites member → Member joins → Shares project data with isolated sessions
3. **Scheduled queries:** Create cron schedule → Automatic execution → Alert on conditions → Notification
4. **Knowledge pipeline:** Connect Git repo → Index codebase → RAG-powered codebase Q&A
5. **Data validation:** Query result → "Wrong data" feedback → Investigation → Fix confirmation

**User roles:** Owner (full control), Editor (edit connections/rules), Viewer (read-only queries)

**Core business flows:**
- Chat/query execution (primary value)
- LLM token usage and cost tracking
- Team sharing and access control
- Automated scheduled reports with alerts

---

## STEP 2. MODULE DECOMPOSITION

### M1: Authentication & Authorization (CRITICAL)
- **Entities:** User, JWT, Google OAuth
- **Scenarios:** Register, login, Google SSO, token refresh, account delete
- **Dependencies:** bcrypt, python-jose, Google Identity Services
- **Tested:** ✓ Comprehensive (auth, RBAC, JWT edge cases)

### M2: Project & Team Management (HIGH)
- **Entities:** Project, ProjectMember, ProjectInvite
- **Scenarios:** CRUD, invite/accept, role-based access
- **Dependencies:** M1 (auth), MembershipService
- **Tested:** ✓ Good coverage

### M3: Connection Management (CRITICAL)
- **Entities:** Connection, ConnectionConfig, SSH tunnel
- **Scenarios:** Create with encryption, test, delete, 4 DB types + SSH + MCP
- **Dependencies:** M1, M2 (membership), encryption service
- **Tested:** ✓ Good coverage

### M4: Multi-Agent AI System (CRITICAL)
- **Entities:** OrchestratorAgent, SQLAgent, VizAgent, KnowledgeAgent, MCPSourceAgent
- **Scenarios:** Query routing, SQL generation, visualization, codebase Q&A, tool execution
- **Dependencies:** LLMRouter, connectors, VectorStore, history trimmer
- **Tested:** ✓ Good but LLM integration paths are mocked

### M5: Knowledge/Indexing Pipeline (HIGH)
- **Entities:** IndexingPipeline, VectorStore, KnowledgeDoc, Checkpoint
- **Scenarios:** 5-pass pipeline, chunking, RAG retrieval, incremental updates
- **Dependencies:** ChromaDB, Git, LLM for doc generation
- **Tested:** ✓ Good coverage

### M6: Data Validation & Benchmarking (MEDIUM)
- **Entities:** DataValidationFeedback, DataBenchmark, DataInvestigation
- **Scenarios:** Validation feedback, benchmarks, investigations
- **Dependencies:** M4 (agent), M3 (connection)
- **Tested:** ✓ Basic coverage

### M7: Scheduling & Notifications (MEDIUM)
- **Entities:** ScheduledQuery, ScheduleRun, Notification
- **Scenarios:** Cron scheduling, auto-execution, alerts, notifications
- **Dependencies:** M3, croniter, AlertEvaluator
- **Tested:** ✓ Basic coverage

### M8: Dashboard Service (HIGH) — ❌ UNTESTED
- **Entities:** Dashboard
- **Scenarios:** CRUD, project-scoped listing
- **Dependencies:** M2 (membership)
- **Tested:** ❌ No unit tests; only basic integration via test_business_logic

### M9: Backup & Recovery (HIGH) — ❌ UNTESTED
- **Entities:** BackupRecord, BackupManager
- **Scenarios:** Create backup, restore, list history, cron backup
- **Dependencies:** File system, SQLite DB
- **Tested:** ❌ Route tests missing (unit test exists for BackupManager)

### M10: Demo Setup (MEDIUM) — ❌ UNTESTED
- **Entities:** Demo project with sample data
- **Scenarios:** POST /api/demo/setup creates demo project
- **Dependencies:** M2, M3
- **Tested:** ❌ No tests

### M11: Metrics & Monitoring (MEDIUM) — ❌ UNTESTED
- **Entities:** Request metrics (latency, status codes)
- **Scenarios:** GET /api/metrics returns Prometheus-style metrics
- **Dependencies:** MetricsMiddleware
- **Tested:** ❌ No tests

### M12: Probe Service (MEDIUM) — ❌ UNTESTED
- **Entities:** Probes for data quality checks
- **Scenarios:** run_probes
- **Dependencies:** M3 (connection)
- **Tested:** ❌ No tests

### M13: Health Monitor Routes (MEDIUM) — ⚠️ UNDER-TESTED
- **Entities:** Connection health checks, reconnect
- **Scenarios:** Per-connection health, all-connections health, reconnect
- **Dependencies:** M3
- **Tested:** ⚠️ Only basic health endpoint tested

### M14: Frontend — Visualization Components (HIGH) — ❌ UNTESTED
- **Components:** VizRenderer, ChartRenderer, DataTable, VizToolbar
- **Scenarios:** Render chart types, table pagination, export
- **Tested:** ❌ No tests

### M15: Frontend — Feature Components (MEDIUM) — ❌ UNTESTED
- **Components:** OnboardingWizard, DashboardBuilder, ScheduleManager, BatchRunner, NotesPanel, AccountMenu, ChatSearch, ChatSessionList, SuggestionChips, NotificationBell, UsageStatsPanel
- **Tested:** ❌ No tests

### M16: Security (CRITICAL)
- **Areas:** SQL injection, RBAC, JWT, encryption, secrets in repo
- **Tested:** ✓ Good but `notes.md` contains real credentials in the repo

---

## STEP 3. RISKS & WEAK POINTS

### CRITICAL RISKS

| Risk | Module | Impact | Likelihood |
|------|--------|--------|------------|
| **Credentials in repo** (`notes.md`) | Security | Credential leak, server compromise | CONFIRMED |
| Dashboard service untested | M8 | Silent data corruption | Medium |
| Backup routes untested | M9 | Failed restores in production | Medium |
| No frontend coverage threshold | M14-15 | Frontend regressions undetected | High |
| Probe service untested | M12 | Silent data quality failures | Medium |

### HIGH RISKS

| Risk | Module | Impact |
|------|--------|--------|
| Demo endpoint could create orphaned data | M10 | DB pollution |
| Metrics endpoint exposes internal state | M11 | Information leakage |
| Health monitor reconnect not tested | M13 | Failed reconnects in prod |
| Viz components untested | M14 | Broken charts shipped silently |

### DATA INTEGRITY RISKS

- Dashboard CRUD: no tests verify project scoping or concurrent access
- Backup restore: untested data integrity after restore
- Scheduled query: alert evaluation edge cases (empty results, null values)

### SILENT FAILURE SCENARIOS

- Probe service fails silently (21% coverage, mostly uncovered lines)
- Backup cron loop catches all exceptions — failures may go unnoticed
- Health monitor loop: errors logged but no notification mechanism

---

## STEP 4. TESTING STRATEGY

### Phase 1: Security — Remove Credentials from Repo
- Remove `notes.md` from tracking
- Add to `.gitignore`
- Rotate compromised credentials

### Phase 2: Untested Backend Services & Routes
- `dashboard_service.py` — full CRUD unit tests
- `probe_service.py` — probe execution unit tests
- `backup` routes — integration tests (trigger, list, history)
- `demo` routes — integration test for POST /api/demo/setup
- `metrics` route — integration test for GET /api/metrics
- `health_monitor` routes — integration tests (per-connection health, reconnect)
- `notifications` routes — expand integration tests (count, read-all)

### Phase 3: Frontend Coverage Expansion
- Add vitest coverage to CI with threshold
- VizRenderer, ChartRenderer, DataTable tests
- OnboardingWizard tests
- DashboardBuilder/DashboardList tests
- ScheduleManager, BatchRunner tests
- NotesPanel, ChatSearch, ChatSessionList tests
- SuggestionChips, AccountMenu tests
- NotificationBell, UsageStatsPanel tests

### Phase 4: Edge Cases & Hardening
- Concurrent dashboard operations
- Backup with corrupted DB file
- Demo setup with existing demo project
- Metrics with high request volume
- Alert evaluation edge cases (null, empty, type mismatch)
- WebSocket disconnect during agent execution

### Phase 5: Coverage Target & CI Enhancement
- Reach 70%+ backend coverage
- Add frontend coverage threshold (e.g., 50%)
- Verify full CI pipeline green
- Update README with final metrics

---

## STEP 5. SPECIAL TEST GROUPS

### Resilience Tests
- Backup with disk full / permission denied
- ChromaDB unavailable during indexing
- LLM provider all-down scenario (already tested)
- Database connection timeout during scheduled query
- WebSocket disconnect mid-stream

### Bug-Oriented Tests
- Dashboard duplicate names in same project
- Notification read-all with no notifications
- Demo setup called twice by same user
- Metrics counter overflow
- Schedule with invalid cron expression (already tested via validator)

### Error-Handling Tests
- Backup restore with wrong format
- Probe service with disconnected connection
- Health monitor reconnect with invalid credentials
- Demo setup with missing dependencies
- Metrics endpoint when middleware disabled

---

## STEP 6. GLOBAL PLAN

### Module Map (Priority Order)
1. 🔴 Security: credentials removal
2. 🔴 M8: Dashboard service tests
3. 🔴 M9: Backup route tests
4. 🟡 M10: Demo route tests
5. 🟡 M11: Metrics route tests
6. 🟡 M12: Probe service tests
7. 🟡 M13: Health monitor route tests
8. 🟡 M14: Frontend viz components
9. 🟢 M15: Frontend feature components
10. 🟢 Coverage targets & CI

### Key User Flows to Test
1. Full onboarding → demo setup → first query (E2E)
2. Scheduled query → alert → notification → read
3. Dashboard CRUD → widget configuration
4. Backup → restore → verify data
5. Team invite → accept → shared query

### Highest-Risk Areas
1. **Security:** Credentials in `notes.md`
2. **Data:** Dashboard/backup service integrity
3. **Reliability:** Probe/health monitor silent failures
4. **Frontend:** Visualization rendering correctness

---

## STEP 7. EXECUTION & CI LOOP

### Iteration Protocol
1. **Code:** Write tests, fix issues found
2. **Lint:** `ruff check`, `ruff format`, `mypy`, `tsc`, `eslint`
3. **Test:** `pytest tests/`, `npm test`
4. **Commit & Push:** Single commit per phase
5. **CI:** Monitor GitHub Actions
6. **Fix:** If CI fails → identify → fix → re-push
7. **Repeat:** Until all green

### Success Criteria
- [ ] `notes.md` removed from repo
- [ ] All untested services have tests
- [ ] All untested routes have tests
- [ ] Frontend coverage threshold in CI
- [ ] Backend coverage ≥ 70%
- [ ] Frontend coverage ≥ 50%
- [ ] CI consistently green
- [ ] Zero flaky tests
- [ ] README updated
