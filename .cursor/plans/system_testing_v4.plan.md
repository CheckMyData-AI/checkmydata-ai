# CheckMyData.ai — System Testing & Stabilization Plan v4

**Date:** 2026-03-22
**Baseline (v3):** 2,422 tests, 67% backend coverage, CI green
**Result (v4):** 2,606 tests, 70% backend coverage, CI green
**Delta:** +184 tests, +3% coverage

---

## STEP 1. PRODUCT UNDERSTANDING (Confirmed)

**Product:** AI-powered database query agent. Connects to databases (PostgreSQL, MySQL, MongoDB, ClickHouse) and Git repositories. Users ask natural language questions → multi-agent system generates SQL → returns visualized results.

**Target Audience:** Data analysts, developers, product managers needing SQL-free database access.

**Key User Scenarios:**
1. Register → Create project → Add DB connection → Ask natural language question → Get chart/table
2. Team: Owner invites collaborator → shared project data, isolated sessions
3. Scheduled: Create cron schedule → auto-execute → alert on conditions → notification
4. Knowledge: Connect Git repo → index codebase → RAG Q&A
5. Validation: Flag wrong data → investigation agent → corrected query → learning
6. Batch: Select saved notes → execute all → export XLSX
7. Dashboard: Create dashboard → add cards → share/view

**User Roles:** Owner (full control), Editor (edit connections/rules), Viewer (read-only)

**Core Business Flows:**
- Chat/query execution (primary value — LLM text-to-SQL)
- Multi-agent routing (Orchestrator → SQL/Knowledge/Viz/MCP)
- Token usage tracking and cost management
- Team sharing with RBAC
- Scheduled reports with alerting

---

## STEP 2. MODULE DECOMPOSITION (19 Modules)

### CRITICAL Modules
| # | Module | Test Status v4 |
|---|--------|---------------|
| M1 | Auth & Authorization | ✅ Unit (28) + Integration (29) |
| M2 | Multi-Agent AI System | ✅ Unit (orchestrator 12, sql_agent 20, viz 15, knowledge 12, mcp 10, investigation 39) |
| M3 | Connection Management | ✅ Unit (25) + Integration (23) |
| M4 | LLM Router & Adapters | ✅ Unit (14 + 24 adapters) |

### HIGH Modules
| # | Module | Test Status v4 |
|---|--------|---------------|
| M5 | Chat Service | ✅ Unit (18) + Integration (18) |
| M6 | Project Management | ✅ Unit (15) + Integration (9) |
| M7 | Knowledge/Indexing | ✅ Unit (70+) |
| M8 | Scheduling & Alerts | ✅ Unit (25) + Integration (22) |
| M9 | Visualization | ✅ Unit (19) |
| M10 | Dashboard Service | ✅ Unit (10) + Integration (8) |

### MEDIUM Modules
| # | Module | Test Status v4 |
|---|--------|---------------|
| M11 | Notes & Saved Queries | ✅ Unit (18) + Integration (22) |
| M12 | Data Validation | ✅ Unit (7 + investigation 39) |
| M13 | Feedback Pipeline | ✅ Unit (30) |
| M14 | Batch Service | ✅ Unit (12) + Integration (9) |
| M15 | Backup & Recovery | ✅ Unit (21) + Integration (4) |
| M16 | Probe Service | ✅ Unit (8) |

### INFRASTRUCTURE
| # | Module | Test Status v4 |
|---|--------|---------------|
| M17 | Query Cache | ✅ Unit (18) |
| M18 | Rate Limiting | ❌ No direct tests |
| M19 | Config & Dependencies | ✅ Unit (9) |

---

## STEP 3. RISK MAP (Updated)

### CRITICAL RISKS → Now Mitigated
| Risk | Status v3 | Status v4 |
|------|-----------|-----------|
| auth_service no unit tests | ⚠️ Gap | ✅ Fixed (28 tests) |
| chat_service no unit tests | ⚠️ Gap | ✅ Fixed (18 tests) |
| stage_executor untested | ⚠️ Gap | ✅ Fixed (20 tests) |
| query_cache correctness | ⚠️ Gap | ✅ Fixed (18 tests) |
| investigation_agent 0% | ⚠️ Gap | ✅ Fixed (39 tests) |
| 67% frontend untested | ⚠️ Gap | ⬆️ Reduced to 52% untested |

### REMAINING HIGH RISKS
| Risk | Module | Impact |
|------|--------|--------|
| rate_limit untested | M18 | DoS vulnerability |
| chat.py routes 26% coverage | M5 | Untested streaming endpoints |
| sql_agent.py 42% coverage | M2 | Core query generation gaps |
| main.py 25% coverage | Infra | Startup/middleware untested |
| orchestrator.py 59% coverage | M2 | Complex routing untested |

### DATA INTEGRITY RISKS (Monitored)
- Chat session isolation ✅ Integration tested
- Scheduled execution with stale connections ✅ Run-now tested
- Cache invalidation ✅ Unit tested
- Feedback pipeline state transitions ✅ Unit tested
- Batch service sequential execution — needs real DB integration

### SILENT FAILURE SCENARIOS
- Rate limiter fails open → untested (P1 for v5)
- SSH tunnel timeout → partially tested
- LLM streaming SSE drops → needs resilience test

---

## STEP 4. TESTING STRATEGY (Executed)

### Phase 1: Quick-Win Backend Services ✅
| Service | Tests Added | Coverage Before → After |
|---------|------------|------------------------|
| investigation_agent.py | 39 | 0% → ~70% |
| batch_service.py | 12 | 23% → ~80% |
| checkpoint_service.py | 33 | 35% → ~90% |
| usage_service.py | 13 | 27% → 100% |

### Phase 2: Integration Route Tests ✅
| Route Area | Tests Added | Coverage |
|-----------|------------|---------|
| Auth extended (change-password, refresh, me, onboarding, delete) | 18 | Filled 45% → ~70% |
| Schedule & Notes CRUD + auth guards | 22 | Filled schedule 48% → ~70%, notes 50% → ~70% |

### Phase 3: Frontend Expansion ✅
| Component | Tests Added |
|-----------|------------|
| toast-store | 12 |
| ConfirmModal (store + component) | 17 |
| DataTable | 9 |
| OnboardingWizard | 10 |
| BatchRunner | 11 |
| ScheduleManager | 8 |

### Phase 4: Lint, Verify, CI ✅
- ruff check: clean
- ruff format: clean
- tsc --noEmit: clean
- eslint: clean
- All 2,606 tests pass
- Backend coverage: 70%
- CI green

---

## STEP 5. SPECIAL TEST GROUPS (v4 Additions)

### Resilience Tests Added
- InvestigationAgent: LLM failure mid-investigation, connector disconnect
- BatchService: connection not found during execution
- CheckpointService: stale checkpoint cleanup
- Auth: expired token, invalid token, deleted user

### Bug-Oriented Tests Added
- InvestigationAgent: unknown tool handling, empty investigation_id
- CheckpointService: duplicate step names, batch doc deduplication
- Auth: short password validation, invalid email format
- ConfirmModal: previous dialog auto-resolution on new open

### Error-Handling Tests Added
- InvestigationAgent: all tool handlers with missing connections
- BatchService: note_ids referencing non-existent notes
- UsageService: zero data periods, change_percent edge cases
- Auth: wrong old password, cascading delete with projects

---

## STEP 6. GLOBAL PLAN

### Module Map (Risk × Impact Priority)
```
CRITICAL ✅: M1(Auth) → M2(Agent) → M5(Chat) → M3(Connections)
HIGH ✅:     M6(Project) → M8(Scheduler) → M9(Viz) → M4(LLM)
MEDIUM ✅:   M11(Notes) → M12(Validation) → M13(Feedback) → M17(Cache)
REMAINING:   M18(RateLimit) → main.py → chat.py routes → sql_agent.py gaps
```

### Coverage Progression
| Metric | v1 Baseline | v3 | v4 |
|--------|------------|-----|-----|
| Backend unit | 1,616 | 1,808 | 1,890 |
| Backend integration | 338 | 338 | 371 |
| Frontend | 240 | 276 | 345 |
| **Total** | **2,194** | **2,422** | **2,606** |
| Backend coverage | 68% | 67% | 70% |
| Tested frontend components | ~25 | ~28 | ~34 |

### Highest-Risk Areas for v5
1. **chat.py routes** — 561 uncovered lines, core streaming endpoints
2. **sql_agent.py** — 560 uncovered lines, query generation paths
3. **main.py** — 323 uncovered lines, startup/middleware
4. **orchestrator.py** — 292 uncovered lines, complex routing
5. **rate_limit.py** — 0% coverage, security-critical

---

## STEP 7. EXECUTION & CI LOOP

### v4 Iteration Results
1. Code: 7 new test files (4 backend unit, 2 integration, 6 frontend)
2. Lint: Fixed E501 (line length) and E741 (ambiguous variable) errors
3. Format: 4 files reformatted
4. Tests: All 2,606 pass locally
5. CI: Pushed → GitHub Actions verified green

### Next Iteration Targets (v5)
If continuing, the optimal strategy to reach 75%+ coverage:
1. Add unit tests for `rate_limit.py` (quick win, security-critical)
2. Add tests for `health_monitor.py` (core + routes = 63 missed lines)
3. Mock-based tests for `chat.py` route handlers (561 missed lines)
4. Agent-layer expansion: orchestrator decision paths, sql_agent query gen
5. Frontend: 11 chat sub-components (StageProgress, SQLExplainer, etc.)
