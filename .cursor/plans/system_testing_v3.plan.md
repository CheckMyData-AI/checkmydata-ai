# CheckMyData.ai — System Testing & Stabilization Plan v3

**Date:** 2026-03-22  
**Baseline:** 2,194 tests (1,616 unit + 338 integration + 240 frontend), 68% backend coverage, CI green  
**Goal:** Close critical coverage gaps, reach 72%+ backend coverage, add frontend coverage threshold, ensure all critical flows are tested

---

## STEP 1. PRODUCT UNDERSTANDING

**Product:** AI-powered database query agent that connects to databases (PostgreSQL, MySQL, MongoDB, ClickHouse) and Git repositories, enabling natural language queries with rich visualizations.

**Audience:** Data analysts, developers, and teams needing SQL-free database access.

**Key User Scenarios:**
1. **Happy path:** Register → Create project → Add connection → Index DB → Ask question → Get chart/table
2. **Team collaboration:** Owner invites member → Accept → Shared project data, isolated sessions
3. **Scheduled queries:** Create cron schedule → Auto-execute → Alert on conditions → Notification
4. **Knowledge pipeline:** Connect Git repo → Index codebase → RAG-powered Q&A
5. **Data validation:** Query result → "Wrong data" feedback → Investigation → Fix
6. **Batch queries:** Select saved notes → Execute all → Export XLSX
7. **Dashboard:** Create dashboard → Add cards from saved queries → Share/view

**User Roles:** Owner (full control), Editor (edit connections/rules), Viewer (read-only)

**Core Business Flows:**
- Chat/query execution (primary value — LLM-powered text-to-SQL)
- Multi-agent routing (Orchestrator → SQL/Knowledge/Viz/MCP agents)
- Token usage tracking and cost management
- Team sharing with RBAC
- Scheduled reports with alerting

---

## STEP 2. MODULE DECOMPOSITION (19 Modules)

### CRITICAL Modules
| # | Module | Purpose | Test Status | Gap |
|---|--------|---------|-------------|-----|
| M1 | Auth & Authorization | User auth, JWT, RBAC, Google SSO | ✅ Good | auth_service.py has no direct unit tests |
| M2 | Multi-Agent AI System | Orchestrator, SQLAgent, VizAgent, KnowledgeAgent | ✅ Good | stage_executor, query_planner, validation untested |
| M3 | Connection Management | DB connections, encryption, SSH tunnels | ✅ Good | — |
| M4 | LLM Router & Adapters | OpenAI/Anthropic/OpenRouter fallback chain | ✅ Good | — |

### HIGH Modules
| # | Module | Purpose | Test Status | Gap |
|---|--------|---------|-------------|-----|
| M5 | Chat Service | Session/message CRUD, streaming | ⚠️ Partial | No direct chat_service.py unit tests |
| M6 | Project Management | Project CRUD, membership, invites | ⚠️ Partial | No direct project_service.py unit tests |
| M7 | Knowledge/Indexing | Multi-pass pipeline, RAG, ChromaDB | ✅ Good | — |
| M8 | Scheduling & Alerts | Cron execution, alert evaluation | ⚠️ Partial | scheduler_service.py untested |
| M9 | Visualization | Chart/table/export rendering | ⚠️ Partial | viz/ module files untested directly |
| M10 | Dashboard Service | Dashboard CRUD | ✅ Recently added | — |

### MEDIUM Modules
| # | Module | Purpose | Test Status | Gap |
|---|--------|---------|-------------|-----|
| M11 | Notes & Saved Queries | Note CRUD, execution | ⚠️ Partial | note_service.py untested |
| M12 | Data Validation | Feedback, benchmarks, investigations | ⚠️ Partial | investigation_agent untested |
| M13 | Feedback Pipeline | Turns feedback into learnings | ❌ None | feedback_pipeline.py untested |
| M14 | Batch Service | Batch query execution | ✅ Recently added | — |
| M15 | Backup & Recovery | DB backup/restore | ✅ Recently added | — |
| M16 | Probe Service | Data health checks | ✅ Recently added | — |

### INFRASTRUCTURE Modules
| # | Module | Purpose | Test Status | Gap |
|---|--------|---------|-------------|-----|
| M17 | Query Cache | In-memory cache for repeated queries | ❌ None | query_cache.py untested |
| M18 | Rate Limiting | Per-user rate limits | ❌ None | rate_limit.py untested |
| M19 | Config & Dependencies | App config, auth deps injection | ❌ None | config.py, deps.py untested |

---

## STEP 3. RISKS & WEAK POINTS

### CRITICAL RISKS
| Risk | Module | Impact | Status |
|------|--------|--------|--------|
| auth_service has no unit tests | M1 | Security bypass, auth bugs | ⚠️ Gap |
| chat_service has no unit tests | M5 | Core feature regressions | ⚠️ Gap |
| Agent stage_executor untested | M2 | Agent pipeline failures | ⚠️ Gap |
| query_cache correctness | M17 | Stale data served to users | ⚠️ Gap |
| 67% of frontend components untested | Frontend | Visual regressions undetected | ⚠️ Gap |

### HIGH RISKS
| Risk | Module | Impact |
|------|--------|--------|
| scheduler_service untested | M8 | Missed scheduled queries |
| note_service untested | M11 | Lost saved queries |
| feedback_pipeline untested | M13 | Broken feedback loop |
| rate_limit untested | M18 | DoS vulnerability |
| investigation_agent untested | M12 | Data validation failures |

### DATA INTEGRITY RISKS
- Chat session isolation between users (partially tested)
- Scheduled query execution with stale connections
- Cache invalidation correctness
- Feedback pipeline state transitions

### SILENT FAILURE SCENARIOS
- Query cache serves stale data without notification
- Rate limiter fails open (allows unlimited requests)
- Feedback pipeline swallows exceptions in learning extraction
- Scheduler misses execution window due to timezone issues

---

## STEP 4. TESTING STRATEGY

### Phase 1: Critical Backend Services (Priority: CRITICAL)
Target: auth_service, chat_service, project_service, scheduler_service, note_service

| Service | Test Focus | Expected Tests |
|---------|-----------|----------------|
| auth_service.py | Register, login, Google OAuth, password change, token validation, duplicate handling | 15+ |
| chat_service.py | Session CRUD, message CRUD, user isolation, session title, generate title | 12+ |
| project_service.py | CRUD, user ownership, list for user, delete cascade | 10+ |
| scheduler_service.py | Create/update/delete schedule, run-now, execution history, cron validation | 10+ |
| note_service.py | CRUD, project scoping, execute, share toggle | 10+ |

### Phase 2: Agent Layer (Priority: HIGH)
Target: stage_executor, query_planner, validation, investigation_agent

| Module | Test Focus | Expected Tests |
|--------|-----------|----------------|
| stage_executor.py | Execute stage, handle errors, timeout, result propagation | 8+ |
| query_planner.py | Plan generation, multi-step plans, single-step, error | 6+ |
| validation.py | Validate agent output, check SQL safety, check viz format | 8+ |
| investigation_agent.py | Run investigation, generate fix, confirm fix | 6+ |

### Phase 3: Infrastructure (Priority: MEDIUM)
Target: query_cache, rate_limit, feedback_pipeline, config, deps

| Module | Test Focus | Expected Tests |
|--------|-----------|----------------|
| query_cache.py | Set/get/invalidate, TTL expiry, LRU eviction, key generation | 8+ |
| rate_limit.py | Allow/deny, sliding window, per-user limits, reset | 6+ |
| feedback_pipeline.py | Process feedback, create learning, create benchmark, error handling | 8+ |
| config.py | Env parsing, defaults, validation, missing vars | 6+ |
| deps.py | Auth dependency, project dependency, connection dependency | 6+ |

### Phase 4: Frontend Expansion (Priority: MEDIUM)
Target: 10+ new component test files

| Component | Test Focus | Expected Tests |
|-----------|-----------|----------------|
| ChartRenderer | Render bar/line/pie, empty data, config updates | 5+ |
| ChatSessionList | Loading, empty, list rendering, selection, delete | 6+ |
| OnboardingWizard | Step navigation, DB form, test connection, skip | 6+ |
| NotesPanel | Loading, empty, note list, batch button | 5+ |
| BatchRunner | Query list, execute, progress, export | 5+ |
| notes-store | Load, create, update, delete, scope filtering | 6+ |

### Phase 5: Coverage & CI
- Reach 72%+ backend coverage
- Add frontend coverage threshold to CI (50%)
- Verify all tests pass
- Update README with final metrics

---

## STEP 5. SPECIAL TEST GROUPS

### Resilience Tests
- Auth service: expired JWT, tampered token, concurrent login
- Chat service: session deleted mid-conversation
- Scheduler: cron fires during server restart
- Query cache: concurrent read/write, cache corruption
- Rate limiter: burst requests, clock skew

### Bug-Oriented Tests
- Auth: case sensitivity in emails (already handled by normalize)
- Chat: generate title with empty messages
- Project: delete project with active connections
- Scheduler: overlapping schedule executions
- Notes: execute note with deleted connection

### Error-Handling Tests
- Auth: invalid Google token, expired refresh token
- Chat: LLM failure during title generation
- Scheduler: connection timeout during scheduled execution
- Feedback pipeline: LLM failure during learning extraction
- Investigation: connection lost during investigation

---

## STEP 6. GLOBAL PLAN

### Module Map (Risk × Impact Priority)
```
CRITICAL:  M1(Auth) → M2(Agent) → M5(Chat) → M3(Connections)
HIGH:      M6(Project) → M8(Scheduler) → M9(Viz) → M4(LLM)
MEDIUM:    M11(Notes) → M12(Validation) → M13(Feedback) → M17(Cache)
LOW:       M18(RateLimit) → M19(Config) → M14(Batch) → M15(Backup)
```

### Key User Flows to Test
1. Register → Login → Create project → Add connection → Query → Visualize
2. Create schedule → Auto-execute → Alert → Notification → Read
3. Save query → Batch execute → Export XLSX
4. Invite member → Accept → Query in shared project
5. Wrong data feedback → Investigation → Confirm fix

### Highest-Risk Areas
1. **Security:** auth_service business logic (register/login/token)
2. **Data:** chat_service session isolation, note execution safety
3. **Reliability:** scheduler execution, feedback pipeline
4. **Infrastructure:** query cache correctness, rate limiting
5. **Frontend:** 46 untested components

---

## STEP 7. EXECUTION & CI LOOP

### Iteration Protocol
1. **Code:** Write tests for Phase N, fix any bugs found
2. **Lint:** `ruff check app/ tests/`, `ruff format`, `mypy`, `tsc`, `eslint`
3. **Test:** `pytest tests/unit/`, `pytest tests/integration/`, `npm test`
4. **Commit & Push:** One commit per phase
5. **CI:** `gh run list` → monitor GitHub Actions
6. **Fix:** If CI fails → read logs → fix → re-push
7. **Repeat:** Until consistently green

### Success Criteria
- [ ] auth_service, chat_service, project_service unit tested
- [ ] Agent layer (stage_executor, query_planner, validation) tested
- [ ] Infrastructure (query_cache, rate_limit, feedback_pipeline) tested
- [ ] 10+ new frontend component tests
- [ ] Backend coverage ≥ 72%
- [ ] Frontend coverage threshold in CI
- [ ] CI consistently green
- [ ] Zero flaky tests
- [ ] README updated
