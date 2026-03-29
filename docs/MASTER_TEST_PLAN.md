# CheckMyData.ai — Master Test Plan

Comprehensive testing plan covering every module, expected behavior, and verification criteria.

**Last Updated:** 2026-03-29
**Backend Tests:** 2487 unit + 410 integration = 2897 total
**Frontend Tests:** 346 total
**Backend Coverage:** 72.03% (target: 80%)

> Live metrics are tracked in [docs/agent-status.md](agent-status.md).

---

## Table of Contents

1. [Authentication & Authorization](#1-authentication--authorization)
2. [Projects](#2-projects)
3. [Connections](#3-connections)
4. [Chat & Orchestration](#4-chat--orchestration)
5. [AI Agents](#5-ai-agents)
6. [Knowledge & Indexing](#6-knowledge--indexing)
7. [Data Validation & Investigations](#7-data-validation--investigations)
8. [Insights & Analytics](#8-insights--analytics)
9. [Dashboards](#9-dashboards)
10. [Schedules & Automation](#10-schedules--automation)
11. [Rules](#11-rules)
12. [Notes](#12-notes)
13. [Invites & RBAC](#13-invites--rbac)
14. [Notifications](#14-notifications)
15. [Batch Queries](#15-batch-queries)
16. [SSH Keys](#16-ssh-keys)
17. [Visualization](#17-visualization)
18. [LLM Providers](#18-llm-providers)
19. [Database Connectors](#19-database-connectors)
20. [Data Graph & Semantic Layer](#20-data-graph--semantic-layer)
21. [Reconciliation](#21-reconciliation)
22. [Temporal Intelligence](#22-temporal-intelligence)
23. [Exploration Engine](#23-exploration-engine)
24. [Infrastructure & Core](#24-infrastructure--core)
25. [Frontend: Stores & State](#25-frontend-stores--state)
26. [Frontend: Components](#26-frontend-components)
27. [Frontend: API Client](#27-frontend-api-client)
28. [E2E User Flows](#28-e2e-user-flows)
29. [Performance & Load](#29-performance--load)
30. [Security](#30-security)

---

## 1. Authentication & Authorization

### Backend: `app/services/auth_service.py`, `app/api/routes/auth.py`

| Module | Expected Behavior | Tests | Coverage |
|--------|-------------------|-------|----------|
| `AuthService.register` | Creates user with hashed password, returns JWT. Rejects duplicate email. Validates password length ≥8 | Unit: 28, Int: 29 | 92% |
| `AuthService.authenticate` | Verifies email+password, returns JWT. Rejects wrong password. Rejects nonexistent user | ✅ Covered | |
| `AuthService.create_token` / `decode_token` | JWT creation with user_id claim, expiry. Decode validates signature/expiry | ✅ Covered | |
| `AuthService.verify_google_token` | Validates Google ID token, extracts email/name. Rejects invalid/expired tokens | ✅ Covered (3 tests) | |
| `AuthService.find_or_create_google_user` | Finds existing user by google_id or email; creates new user if neither found | ✅ Covered | |
| **Route: POST /api/auth/register** | 201 + token on success. 409 on duplicate. 422 on invalid body | Int: ✅ | |
| **Route: POST /api/auth/login** | 200 + token on success. 401 on wrong creds | Int: ✅ | |
| **Route: POST /api/auth/google** | 200 + token on valid Google token. 401 on invalid | Int: ✅ | |
| **Route: POST /api/auth/change-password** | 200 on success. 401 on wrong current password. 401 if unauthenticated | Int: ✅ | |
| **Route: POST /api/auth/refresh** | 200 + new token. 401 on expired/invalid | Int: ✅ | |
| **Route: GET /api/auth/me** | 200 + user profile. 401 if unauthenticated | Int: ✅ | |
| **Route: POST /api/auth/onboarding** | Marks onboarding complete | Int: ✅ | |
| **Route: DELETE /api/auth/account** | Deletes user, sessions, projects. 401 if unauthenticated | Int: ✅ | |

### Frontend: `AuthGate`, `AccountMenu`, `auth-store`

| Component | Expected Behavior | Tests |
|-----------|-------------------|-------|
| `AuthGate` | Shows login form when unauthenticated. Shows register form on toggle. Renders children when authenticated. Handles Google GIS button. Shows loading spinner during auth restore | 8 tests ✅ |
| `AccountMenu` | Shows user email. Change password flow. Logout clears state. Delete account with confirm | 5 tests ✅ |
| `useAuthStore` | `login` → sets token/user, stores in localStorage. `logout` → clears all. `restore` → reads localStorage, refreshes if needed. `error` state on failure | 9 tests ✅ |

### Gaps & Needed Tests

- [ ] Token expiry edge case: request mid-refresh
- [ ] Google OAuth flow in browser (E2E)
- [ ] Rate limiting on /auth/login (brute force protection)
- [ ] Password validation rules in frontend form

---

## 2. Projects

### Backend: `app/services/project_service.py`, `app/api/routes/projects.py`

| Module | Expected Behavior | Tests | Coverage |
|--------|-------------------|-------|----------|
| `ProjectService.create` | Creates project with name, optional LLM config. Returns project with generated ID | Unit: 15, Int: 12 | 90% |
| `ProjectService.get` | Returns project by ID. Returns None for nonexistent | ✅ | |
| `ProjectService.list_all` | Returns all projects (for current user via route) | ✅ | |
| `ProjectService.update` | Updates name, LLM fields. Returns None for nonexistent | ✅ | |
| `ProjectService.delete` | Deletes project and cascades. Returns False for nonexistent | ✅ | |
| **Route: POST /api/projects** | 201 + project. 401 if unauthenticated | Int: ✅ | |
| **Route: GET /api/projects** | 200 + list (filtered by membership) | Int: ✅ | |
| **Route: GET /api/projects/{id}** | 200 + project. 404 not found. 403 no access | Int: ✅ | |
| **Route: PUT /api/projects/{id}** | 200 + updated. 404 not found. 403 no editor access | Int: ✅ | |
| **Route: DELETE /api/projects/{id}** | 200 on success. 404 not found. 403 not owner | Int: ✅ | |
| **Route: GET /api/projects/{id}/readiness** | Returns readiness checks (schema, index, sync) | Int: ✅ | |

### Frontend: `ProjectSelector`, `app-store`

| Component | Expected Behavior | Tests |
|-----------|-------------------|-------|
| `ProjectSelector` | Lists projects. Create new with name/LLM config. Edit existing. Delete with confirm. Select switches active project | 8 tests ✅ |
| `useAppStore` (project state) | `activeProject` persisted to localStorage. Switching project clears connection/session. Loading projects from API | 13 tests ✅ |

### Gaps

- [ ] Project LLM field update (provider/model selection)
- [ ] Project deletion cascading UI (connections, sessions gone)

---

## 3. Connections

### Backend: `app/services/connection_service.py`, `app/api/routes/connections.py`

| Module | Expected Behavior | Tests | Coverage |
|--------|-------------------|-------|----------|
| `ConnectionService.create` | Creates connection, encrypts password/connection_string/mcp_env, serializes JSON arrays, sanitizes strings | Unit: 44, Int: 18 | 99% |
| `ConnectionService.update` | Updates only _UPDATABLE_FIELDS. Encrypts/clears password, connection_string, mcp_env. Serializes ssh_pre_commands, mcp_server_args | ✅ (7 update tests) | |
| `ConnectionService.get` | Returns by ID or None | ✅ | |
| `ConnectionService.list_by_project` | Returns connections for project, ordered by created_at desc, supports skip/limit | ✅ (pagination tests) | |
| `ConnectionService.delete` | Deletes or returns False | ✅ | |
| `ConnectionService.test_connection` | Loads config, connects via retry, runs test_connection(), disconnects. Returns {success, error} | ✅ (4 tests) | |
| `ConnectionService.test_ssh` | Tests SSH independently: loads key, connects asyncssh, runs echo+hostname, parses output | ✅ (6 tests) | |
| `ConnectionService.to_config` | Decrypts credentials, loads SSH key, parses JSON fields (ssh_pre_commands, mcp_server_args, mcp_env). Raises ValueError on decrypt failure | ✅ (7 tests) | |
| **Route: POST /api/connections** | Creates connection with RBAC. 403 for viewer | Int: ✅ | |
| **Route: PUT /api/connections/{id}** | Updates connection. 404 not found | Int: ✅ | |
| **Route: POST /api/connections/{id}/test** | Tests connection. Returns success/error | Int: ✅ | |
| **Route: POST /api/connections/{id}/test-ssh** | Tests SSH. Returns success/hostname | Int: ✅ | |
| **Route: POST /api/connections/{id}/index** | Triggers DB index pipeline | Int: ✅ | |
| **Route: POST /api/connections/{id}/sync** | Triggers code-DB sync pipeline | Int: ✅ | |

### Frontend: `ConnectionSelector`, `ConnectionHealth`, `SyncStatusIndicator`

| Component | Expected Behavior | Tests |
|-----------|-------------------|-------|
| `ConnectionSelector` | Lists connections for active project. Create form with all DB types (PG, MySQL, ClickHouse, Mongo, MCP). SSH/MCP fields shown conditionally. Test button. Index/sync controls. Learnings panel. Empty state when no connections | 10 tests ✅ |
| `ConnectionHealth` | Shows connection health status. Reconnect button | Not unit tested |
| `SyncStatusIndicator` | Shows sync status with polling | Not unit tested |

### Gaps

- [ ] Connection types: verify all 5 types create correctly (PG, MySQL, ClickHouse, Mongo, MCP)
- [ ] MCP connection: transport types (stdio, sse), env vars, server args
- [ ] Schema refresh pipeline status polling
- [ ] Connection health monitor integration

---

## 4. Chat & Orchestration

### Backend: `app/core/orchestrator.py`, `app/agents/orchestrator.py`, `app/api/routes/chat.py`

| Module | Expected Behavior | Tests | Coverage |
|--------|-------------------|-------|----------|
| `ConversationalAgent.run` | Receives question + history, calls OrchestratorAgent, handles tool calls iteratively, accumulates token usage, emits workflow events | Unit: 31 | ~70% |
| `OrchestratorAgent.run` | Plans execution (detect complexity), dispatches to SQL/Knowledge/Viz/MCP agents, handles clarification, returns structured AgentResponse | Unit: 8 | 60% |
| `Orchestrator.process_question` | Connects to DB if needed, refreshes schema if stale, builds context (knowledge, rules, learnings, notes), calls agent, records usage, processes feedback | Unit: 8 | ~60% |
| `ChatService.create_session` | Creates session for project | Unit: 18 | 100% |
| `ChatService.add_message` | Adds message with role/content/metadata | ✅ | |
| `ChatService.get_history_as_messages` | Returns messages formatted for LLM context | ✅ | |
| **Route: POST /api/chat/sessions** | Creates chat session | Int: ✅ | |
| **Route: POST /api/chat/ask** | Synchronous ask (returns full response) | Int: ✅ | |
| **Route: POST /api/chat/stream** | SSE streaming response with chunks | Int: ✅ | |
| **Route: POST /api/chat/feedback** | Records thumbs up/down | Int: ✅ | |
| **Route: GET /api/chat/search** | Searches across messages | Int: ✅ | |
| **Route: POST /api/chat/explain-sql** | SQL explanation | Int: ✅ | |

### Frontend: `ChatPanel`, `ChatInput`, `ChatMessage`, `ChatSessionList`

| Component | Expected Behavior | Tests |
|-----------|-------------------|-------|
| `ChatPanel` | Shows restoring state during load. Shows "no project" when no project selected. Renders message history. Handles streaming (thinking log, tool calls, stage progress). Cost estimator. Readiness gate. Error messages with retry | 10 tests ✅ |
| `ChatInput` | Controlled text input. Submit on Enter. Disabled when streaming. aria-label for accessibility | 7 tests ✅ |
| `ChatMessage` | Renders markdown. Shows SQL with copy button. Viz toolbar with type switching. Thumbs up/down feedback (records validation, auto-sends investigation on thumbs down). Shows RAG sources. Shows insights. Retry on error. Save to notes | 20 tests ✅ |
| `ChatSessionList` | Lists sessions. Create via createRequested prop. Rename inline. Delete with confirm. Switch session | 9 tests ✅ |

### Gaps

- [ ] Streaming interruption (user cancels mid-stream)
- [ ] Multi-stage pipeline visualization during stream
- [ ] Clarification flow: agent asks question → user picks option → continues
- [ ] WebSocket chat route (`/api/chat/ws`)
- [ ] Chat history trimming (token budget exceeded)
- [ ] Cost estimator accuracy
- [ ] Session title auto-generation

---

## 5. AI Agents

### Backend: `app/agents/`

| Agent | Expected Behavior | Tests | Coverage |
|-------|-------------------|-------|----------|
| `SQLAgent` | Receives question + schema context. Uses tools: execute_query, get_table_detail, get_similar_tables, etc. Returns SQL query + result. Handles self-repair on error. Respects dialect (PG/MySQL/ClickHouse/Mongo) | Unit: 24 | ~65% |
| `KnowledgeAgent` | Searches vector store for relevant code/docs. Returns knowledge snippets with sources. RAG pipeline | Unit: 12 | ~60% |
| `VizAgent` | Recommends visualization type from query result. Returns chart config or table format | Unit: 21 | ~70% |
| `InvestigationAgent` | Investigates flagged wrong data. Runs diagnostic queries, compares with benchmarks, produces findings | Unit: 39 | ~80% |
| `MCPSourceAgent` | Queries external MCP data sources. Calls MCP tools | Unit: 10 | ~65% |
| `InsightFeedAgent` | Scans data for opportunities, losses, anomalies. Generates insights | Unit: 9 | ~60% |
| `QueryPlanner` | Detects query complexity (simple/moderate/complex/multi_stage). Plans execution stages | Unit: 25 | ~75% |
| `StageExecutor` | Executes planned stages sequentially. Handles retries, resume from failure | Unit: 20 | ~70% |
| `StageValidator` | Validates stage results against criteria | Unit: in test_pipeline (36) | ~73% |
| **Agent Tools** | `sql_tools`, `orchestrator_tools`, `knowledge_tools`, `investigation_tools`, `mcp_tools` — tool definitions and dispatch | Unit: 50 (tool_executor) | ~75% |
| **Agent Prompts** | System prompts for each agent. Include datetime, dialect hints, context sections | Unit: 26 | ~80% |
| **Error Handling** | `AgentError`, `AgentTimeoutError`, `AgentRetryableError`, `AgentFatalError`. Retry strategy with backoff | Unit: 16 (llm_resilience) + 5 (retry) + 16 (retry_strategy) | ✅ |

### Gaps

- [ ] SQLAgent: test all 4 SQL dialects (PG, MySQL, ClickHouse, Mongo)
- [ ] SQLAgent: self-repair loop (error → classify → repair → retry)
- [ ] Multi-agent pipeline: orchestrator → planner → SQL → viz
- [ ] Agent token budget management (history trimming mid-conversation)
- [ ] MCP agent with real MCP server mock

---

## 6. Knowledge & Indexing

### Backend: `app/knowledge/`

| Module | Expected Behavior | Tests | Coverage |
|--------|-------------------|-------|----------|
| `IndexingPipelineRunner.run` | 4-pass pipeline: (1) profile project, (2-3) extract knowledge, (4) enrich with code analysis. Tracks via checkpoints. Incremental on re-run | Unit: 15 + 11 + 10 | ~65% |
| `DbIndexPipeline.run` | Introspects DB schema, samples data, analyzes tables with LLM, stores index | Unit: 36 + 8 | ~70% |
| `CodeDbSyncPipeline.run` | Matches code entities to DB tables, analyzes conventions, stores sync data | Unit: 11 + 15 | ~70% |
| `VectorStore` | ChromaDB operations: create collection, add/query/delete documents | Unit: 21 | ~75% |
| `SchemaIndexer` | Introspects schema, samples data, builds markdown context | Unit: 4 | ~60% |
| `RepoAnalyzer` | Clones git repo, analyzes file structure, extracts entities | Unit: 20 | ~70% |
| `DocStore` | CRUD for knowledge documents in DB | Unit: via test_services | ~80% |
| `EntityExtractor` | Extracts columns, tables, models, enums from code | Unit: 24 + 12 | ~75% |
| `GitTracker` | Tracks commit SHAs, detects changed files for incremental indexing | Unit: 16 | ~80% |
| `CheckpointService` | Manages indexing checkpoints: create, complete steps, mark failures, cleanup stale | Unit: 33 | ~85% |
| `ProjectProfiler` | Detects language, frameworks, ORMs, key directories | Unit: 10 | ~70% |
| `LearningAnalyzer` | Extracts learnings from query feedback | Unit: 10 + 15 | ~75% |

### Frontend: `KnowledgeDocs`, Sidebar index controls

| Component | Expected Behavior | Tests |
|-----------|-------------------|-------|
| Sidebar: Index Repo button | Triggers indexing pipeline. Shows workflow progress | Sidebar: 8 tests |
| `KnowledgeDocs` | Lists indexed docs. Shows doc content in markdown | Not unit tested |
| `WorkflowProgress` | Shows live SSE progress for indexing pipelines | Not unit tested |

### Gaps

- [ ] Full pipeline E2E: clone repo → extract → index → query knowledge
- [ ] Incremental indexing: only changed files reprocessed
- [ ] Binary file filtering in pipeline
- [ ] Vector store query relevance quality
- [ ] KnowledgeDocs component rendering

---

## 7. Data Validation & Investigations

### Backend: `app/services/data_validation_service.py`, `app/services/investigation_service.py`, `app/agents/investigation_agent.py`

| Module | Expected Behavior | Tests | Coverage |
|--------|-------------------|-------|----------|
| `DataValidationService.record_validation` | Records user verdict (confirmed/rejected/approximate) for a query result | Unit: 10 | 100% |
| `DataValidationService.get_accuracy_stats` | Returns accuracy statistics per connection | ✅ | |
| `InvestigationService.create_investigation` | Creates investigation from validation feedback | Unit: 13 | 94% |
| `InvestigationService.update_phase` | Updates investigation phase (analyzing, diagnosing, fixing) | ✅ | |
| `InvestigationAgent.run` | Runs multi-tool investigation: profile data, check schema, compare benchmarks, diagnose issues, suggest fixes | Unit: 39 | ~80% |
| `FeedbackPipeline.process` | Processes feedback verdict → creates learnings, benchmarks, notes | Unit: 30 + 6 | 100% |
| `BenchmarkService` | Stores and confirms data benchmarks for known good values | Unit: 4, Int: 12 | 66% |

### Frontend: `DataValidationCard`, `WrongDataModal`, `InvestigationProgress`

| Component | Expected Behavior | Tests |
|-----------|-------------------|-------|
| `DataValidationCard` | Shows validation UI for query results. Buttons: confirm/reject/approximate. Calls API | 4 tests ✅ |
| `WrongDataModal` | Modal for reporting wrong data (note: now handled via thumbs-down in chat) | Legacy, may not render |
| `InvestigationProgress` | Shows investigation pipeline progress | Not unit tested |

### Gaps

- [ ] `BenchmarkService`: increase coverage from 66% to 80%
- [ ] Investigation flow: validation → investigation → findings → fix → confirm
- [ ] Anomaly analysis integration
- [ ] Data sanity checker edge cases

---

## 8. Insights & Analytics

### Backend: `app/core/insight_memory.py`, `app/core/insight_generator.py`, `app/core/action_engine.py`, `app/core/anomaly_intelligence.py`, `app/core/opportunity_detector.py`, `app/core/loss_detector.py`

| Module | Expected Behavior | Tests | Coverage |
|--------|-------------------|-------|----------|
| `InsightMemoryService` | Store/retrieve/confirm/dismiss/resolve insights. Confidence decay over time. Deduplication | Unit: 27 (foundation) | ~70% |
| `InsightGenerator.analyze` | Analyzes query results for trends, outliers, concentration patterns | Unit: 13 | ~70% |
| `ActionEngine` | Generates action recommendations from insights | Unit: 20 | ~75% |
| `AnomalyIntelligenceEngine` | Detects data anomalies: nulls, zeros, duplicates, outliers | Unit: 10 | ~70% |
| `OpportunityDetector` | Finds growth opportunities in data | Unit: 11 | ~70% |
| `LossDetector` | Finds revenue/data losses | Unit: 11 | ~70% |
| `DataSanityChecker` | Checks for data quality issues, compares against benchmarks | Unit: 5 | ~70% |
| **Route: GET /api/insights** | List insights with filters | Int: 19 | |
| **Route: POST /api/feed/scan** | Triggers feed scan | Int: in test_insights_api | |

### Frontend: `InsightFeedPanel`, `MetricCatalogPanel`, insight cards

| Component | Expected Behavior | Tests |
|-----------|-------------------|-------|
| `InsightFeedPanel` | Lists insights with severity filter. Scan actions (quick/full/opportunities/losses). Confirm/dismiss/resolve actions. Error state with Retry. Empty state when no insights. Loading spinner | Not unit tested |
| `MetricCatalogPanel` | Lists metrics from semantic layer. Build/normalize catalog | Not unit tested |
| `InsightCards` | Renders insight cards with drill-down | Not unit tested |
| `AnomalyReportCard` | Displays anomaly report | Not unit tested |
| `OpportunityCard` | Displays opportunity findings | Not unit tested |
| `LossReportCard` | Displays loss findings | Not unit tested |

### Gaps

- [ ] InsightFeedPanel component tests
- [ ] Feed scan pipeline end-to-end
- [ ] Insight lifecycle: create → confirm → resolve
- [ ] Confidence decay over time
- [ ] Anomaly detection accuracy on real-like data

---

## 9. Dashboards

### Backend: `app/services/dashboard_service.py`, `app/api/routes/dashboards.py`

| Module | Expected Behavior | Tests | Coverage |
|--------|-------------------|-------|----------|
| `DashboardService` CRUD | Create, get, list, update, delete dashboards | Unit: 10, Int: 6 | 100% |
| **Route: POST /api/dashboards** | Creates dashboard. 403 for viewer | Int: ✅ | |
| **Route: GET /api/dashboards** | Lists for project | Int: ✅ | |

### Frontend: `DashboardList`, `DashboardBuilder`, `DashboardPage`

| Component | Expected Behavior | Tests |
|-----------|-------------------|-------|
| `DashboardList` | Lists dashboards. Create via createRequested prop. Navigate to dashboard page. Loading/error/empty states | 4 tests ✅ |
| `DashboardBuilder` | Card grid editor. Add/remove cards. Save layout | Not unit tested |
| `DashboardPage` | Full page: load dashboard, display cards, auto-refresh, edit mode | Not unit tested |

### Gaps

- [ ] DashboardBuilder component tests
- [ ] Dashboard card rendering with different viz types
- [ ] Auto-refresh interval behavior
- [ ] Dashboard sharing/permissions

---

## 10. Schedules & Automation

### Backend: `app/services/scheduler_service.py`, `app/api/routes/schedules.py`

| Module | Expected Behavior | Tests | Coverage |
|--------|-------------------|-------|----------|
| `SchedulerService.validate_cron` | Validates cron expression syntax | Unit: 25 | 100% |
| `SchedulerService.compute_next_run` | Computes next run time from cron expression | ✅ | |
| `SchedulerService` CRUD | Create, get, list, update, delete schedules | ✅ | |
| `SchedulerService.get_due_schedules` | Returns schedules past their next_run time | ✅ | |
| `SchedulerService.record_run` | Records execution result (success/failure, row count, error) | ✅ | |
| **Scheduler loop** (main.py lifespan) | Background loop checks due schedules, executes queries, records results | Not directly tested | |

### Frontend: `ScheduleManager`

| Component | Expected Behavior | Tests |
|-----------|-------------------|-------|
| `ScheduleManager` | CRUD schedules with cron, connection, SQL. Run now. View history. createRequested prop pattern | 9 tests ✅ |

### Gaps

- [ ] Scheduler background loop execution
- [ ] Schedule execution with real connector
- [ ] Failure notification on schedule failure
- [ ] Cron expression edge cases (timezone handling)

---

## 11. Rules

### Backend: `app/services/rule_service.py`, `app/knowledge/custom_rules.py`

| Module | Expected Behavior | Tests | Coverage |
|--------|-------------------|-------|----------|
| `RuleService` CRUD | Create, get, list, update, delete custom rules | Unit: 17, Int: 9 | 100% |
| `RuleService.ensure_default_rule` | Creates default rule for project if none exists | ✅ | |
| `CustomRulesEngine` | Loads rules, formats for prompt context | Unit: 16 | ~80% |

### Frontend: `RulesManager`

| Component | Expected Behavior | Tests |
|-----------|-------------------|-------|
| `RulesManager` | CRUD rules with name/content. Create via createRequested prop. canEdit permission gating | 8 tests ✅ |

### Gaps

- [ ] Rule impact on query generation (verify rule content appears in SQL agent prompt)
- [ ] Global rules (project_id=None) behavior

---

## 12. Notes

### Backend: `app/services/note_service.py`, `app/services/session_notes_service.py`

| Module | Expected Behavior | Tests | Coverage |
|--------|-------------------|-------|----------|
| `NoteService` CRUD | Saved SQL notes: create, get, list, update, delete | Unit: 18, Int: 15 | 100% |
| `NoteService.update_result` | Updates cached query result on note | ✅ | |
| `SessionNotesService` | Agent learning notes per session: create, dedup, compile prompt, verify, deactivate, decay | Unit: 13 | 90% |

### Frontend: `NotesPanel`, `NoteCard`, `notes-store`

| Component | Expected Behavior | Tests |
|-----------|-------------------|-------|
| `useNotesStore` | Loads notes for project. Scope filter (mine/shared/all). isOpen persistence | 18 tests ✅ |
| `NotesPanel` | Lists notes by scope. Execute note (replay SQL) | Not unit tested |
| `NoteCard` | Individual note display with actions | Not unit tested |

### Gaps

- [ ] Note execution (execute saved SQL) end-to-end
- [ ] Note sharing between project members
- [ ] Session notes compile into prompt context

---

## 13. Invites & RBAC

### Backend: `app/services/invite_service.py`, `app/services/membership_service.py`

| Module | Expected Behavior | Tests | Coverage |
|--------|-------------------|-------|----------|
| `InviteService` | Create invite with role, list, revoke, accept | Unit: 11, Int: 9 | 90% |
| `MembershipService` | Get role, require role (403 on insufficient), add/remove member, list members | Unit: 12, Int: 31 | 100% |
| **RBAC roles** | owner: full access. editor: CRUD except delete project/remove members. viewer: read only | Int: 31 (test_security_rbac) | |

### Frontend: `InviteManager`, `PendingInvites`

| Component | Expected Behavior | Tests |
|-----------|-------------------|-------|
| `InviteManager` | Invite by email + role. List sent invites. Revoke | 6 tests ✅ |
| `PendingInvites` | Lists pending invites for current user. Accept invite | Not unit tested |

### Gaps

- [ ] Multi-user RBAC scenario (viewer tries to edit → 403)
- [ ] Invite acceptance flow (new user registers → auto-accept pending invites)
- [ ] PendingInvites component tests

---

## 14. Notifications

### Backend: `app/api/routes/notifications.py`

| Module | Expected Behavior | Tests |
|--------|-------------------|-------|
| **GET /api/notifications** | Lists notifications for user | Int: 4 |
| **GET /api/notifications/unread-count** | Returns unread count | Int: ✅ |
| **POST /api/notifications/{id}/read** | Marks notification as read | Int: ✅ |
| **POST /api/notifications/read-all** | Marks all as read | Int: ✅ |

### Frontend: `NotificationBell`

| Component | Expected Behavior | Tests |
|-----------|-------------------|-------|
| `NotificationBell` | Shows unread count. Dropdown with notifications. Mark read. Mark all read | 5 tests ✅ |

### Gaps

- [ ] Notification creation triggers (schedule failure, invite, etc.)
- [ ] Notification polling/SSE updates

---

## 15. Batch Queries

### Backend: `app/services/batch_service.py`, `app/api/routes/batch.py`

| Module | Expected Behavior | Tests | Coverage |
|--------|-------------------|-------|----------|
| `BatchService` CRUD | Create, get, list, delete batches | Unit: 21, Int: 9 | 100% |
| `BatchService.execute_batch` | Executes multiple SQL queries, stores results per query | ✅ | |
| **Route: POST /api/batch/execute** | Creates and executes batch | Int: ✅ | |
| **Route: GET /api/batch/{id}/export** | Exports batch results (CSV/XLSX) | Int: ✅ | |

### Frontend: `BatchRunner`, `BatchResults`

| Component | Expected Behavior | Tests |
|-----------|-------------------|-------|
| `BatchRunner` | Build batch from notes/SQL. Submit. Link to results | 11 tests ✅ |
| `BatchResults` | Shows batch status. Per-query results. Export | Not unit tested |

### Gaps

- [ ] Batch export file format validation
- [ ] Large batch (50+ queries) behavior
- [ ] Batch cancellation

---

## 16. SSH Keys

### Backend: `app/services/ssh_key_service.py`

| Module | Expected Behavior | Tests | Coverage |
|--------|-------------------|-------|----------|
| `SshKeyService` CRUD | Create (encrypt), list, get, get_decrypted, delete | Unit: 10, Int: 3 | 78% |
| `SshKeyInUseError` | Raised when deleting key that's in use by a connection | ✅ | |

### Frontend: `SshKeyManager`

| Component | Expected Behavior | Tests |
|-----------|-------------------|-------|
| `SshKeyManager` | List keys. Add with paste. Delete with confirm. In-use protection | 6 tests ✅ |

### Gaps

- [ ] SSH key validation (PEM format check)
- [ ] Passphrase-protected keys
- [ ] Key rotation flow

---

## 17. Visualization

### Backend: `app/viz/`

| Module | Expected Behavior | Tests | Coverage |
|--------|-------------------|-------|----------|
| `render(result, config)` | Routes to table/chart/text based on type and data | Unit: 54 | 88-100% |
| `format_table` | Formats QueryResult as table dict | ✅ | 100% |
| `format_text` | Handles empty, single number, key_value, text | ✅ | 91% |
| `generate_bar_chart/line_chart/pie_chart/scatter` | Chart.js config generation from QueryResult | ✅ | 88% |
| `export_csv/json/xlsx` | Export data in multiple formats | ✅ | 100% |
| `serialize_value` | Handles None, primitives, Decimal, bytes, fallback str | ✅ | 100% |

### Frontend: `VizRenderer`, `ChartRenderer`, `DataTable`, `VizToolbar`

| Component | Expected Behavior | Tests |
|-----------|-------------------|-------|
| `VizRenderer` | Routes to ChartRenderer/DataTable/TextViz based on type. Shows fallback for missing payload | 7 tests ✅ |
| `ChartRenderer` | Renders Chart.js chart from config. Dynamic import with loading skeleton | 9 tests ✅ |
| `DataTable` | Renders tabular data with scroll. "No data" empty state | 9 tests ✅ |
| `VizToolbar` | Buttons to switch viz type (table/bar/line/pie/scatter) | Not unit tested |

### Gaps

- [ ] Chart type switching in ChatMessage (re-render via API)
- [ ] Large dataset rendering (1000+ rows)
- [ ] Export from frontend (CSV/XLSX download)

---

## 18. LLM Providers

### Backend: `app/llm/`

| Module | Expected Behavior | Tests | Coverage |
|--------|-------------------|-------|----------|
| `LLMRouter` | Routes to healthy provider. Fallback chain on failure. Health checks. Context window limits | Unit: 23 | ~70% |
| `OpenAIAdapter` | Complete/stream via OpenAI API. Tool calls. Error handling | Unit: 30 | ~75% |
| `AnthropicAdapter` | Complete/stream via Anthropic API. Tool calls | ✅ (in test_llm_adapters) | |
| `OpenRouterAdapter` | Complete/stream via OpenRouter. Model routing | ✅ | |
| **Resilience** | Fallback chain, retry behavior, error hierarchy, health marking | Unit: 16 | ~80% |

### Gaps

- [ ] Provider failover: primary fails → fallback succeeds
- [ ] Streaming with tool calls
- [ ] Token usage tracking accuracy
- [ ] Rate limit handling per provider
- [ ] Context window enforcement (message trimming)

---

## 19. Database Connectors

### Backend: `app/connectors/`

| Module | Expected Behavior | Tests | Coverage |
|--------|-------------------|-------|----------|
| `PostgresConnector` | Connect, execute_query, introspect_schema, test_connection. SSH tunnel support | Unit: 50 (test_connectors_extended) | ~70% |
| `MySQLConnector` | Same interface for MySQL | ✅ | |
| `ClickHouseConnector` | Same interface for ClickHouse | ✅ | |
| `MongoDBConnector` | Connect, execute (aggregate), introspect, sample_data | ✅ | |
| `SSHExecConnector` | Executes DB commands over SSH exec channel | Unit: 15 | ~65% |
| `MCPClientAdapter` | Connects to MCP servers, lists entities, queries data, calls tools | Unit: 19 | ~70% |
| `SSHTunnel` / `SSHTunnelManager` | Creates/manages SSH tunnels for DB connections | Unit: 9 | ~60% |
| `CLIOutputParser` | Parses TSV/CSV/psql output from CLI connectors | Unit: 20 | ~85% |
| `get_connector` / `get_adapter` | Registry for connector types | Unit: 11 | ~80% |

### Gaps

- [ ] Real database integration tests (PostgreSQL, MySQL)
- [ ] Connection timeout behavior
- [ ] Large result set handling (memory)
- [ ] SSH tunnel reconnection after disconnect

---

## 20. Data Graph & Semantic Layer

### Backend: `app/core/data_graph.py`, `app/core/semantic_layer.py`

| Module | Expected Behavior | Tests | Coverage |
|--------|-------------------|-------|----------|
| `DataGraphService` | CRUD metrics, relationships. Auto-discover from DB index. Graph queries | Unit: 27 (foundation) | ~65% |
| `SemanticLayerService` | Discover metrics from schema. Normalize naming. Build catalog | Unit: 17 | ~60% |
| **Route: GET /api/data-graph/summary** | Returns graph overview | Int: 19 | |
| **Route: POST /api/semantic-layer/build** | Builds metric catalog | Int: in test_insights_api | |

### Gaps

- [ ] Data graph visualization in frontend
- [ ] Metric relationship discovery accuracy
- [ ] Semantic layer normalization edge cases

---

## 21. Reconciliation

### Backend: `app/core/reconciliation_engine.py`

| Module | Expected Behavior | Tests | Coverage |
|--------|-------------------|-------|----------|
| `ReconciliationEngine` | Reconcile row counts, values, schemas across connections. Build discrepancy report | Unit: 19 | ~60% |
| **Route: POST /api/reconciliation/full** | Full cross-source reconciliation | Int: in test_insights_api | |

### Frontend: `ReconciliationCard`

| Component | Expected Behavior | Tests |
|-----------|-------------------|-------|
| `ReconciliationCard` | Displays discrepancies with drill-down | Not unit tested |

### Gaps

- [ ] Multi-connection reconciliation end-to-end
- [ ] ReconciliationCard component tests
- [ ] Large schema comparison performance

---

## 22. Temporal Intelligence

### Backend: `app/core/temporal_intelligence.py`

| Module | Expected Behavior | Tests | Coverage |
|--------|-------------------|-------|----------|
| `TemporalIntelligenceService` | Analyze time series: trends, seasonality, anomalies, lag detection | Unit: 23 | ~70% |
| **Route: POST /api/temporal/analyze** | Analyze series | Int: in test_insights_api | |
| **Route: POST /api/temporal/detect-lag** | Detect data lag | Int: ✅ | |

### Frontend: `TemporalReport`

| Component | Expected Behavior | Tests |
|-----------|-------------------|-------|
| `TemporalReport` | Displays trend/seasonality/anomaly data | Not unit tested |

### Gaps

- [ ] TemporalReport component tests
- [ ] Edge cases: insufficient data points, all-null series

---

## 23. Exploration Engine

### Backend: `app/core/exploration_engine.py`

| Module | Expected Behavior | Tests | Coverage |
|--------|-------------------|-------|----------|
| `ExplorationEngine.investigate` | Multi-step data investigation: profile, sample, correlate, summarize findings | Unit: 18 | ~65% |
| **Route: POST /api/explore** | Run exploration | Int: in test_insights_api | |

### Frontend: `ExplorationReport`

| Component | Expected Behavior | Tests |
|-----------|-------------------|-------|
| `ExplorationReport` | Shows investigation findings with drill-down | Not unit tested |

---

## 24. Infrastructure & Core

### Backend: Various `app/core/` and `app/main.py`

| Module | Expected Behavior | Tests | Coverage |
|--------|-------------------|-------|----------|
| **Health endpoint** | `GET /api/health` returns 200 with status | Int: 2 + perf smoke | ✅ |
| **Module health** | `GET /api/health/modules` returns component statuses | Unit: via test_api_routes | |
| **Rate limiting** | SlowAPI rate limits on sensitive routes | Unit: 3 | |
| **Encryption** | Fernet encrypt/decrypt for credentials | Unit: 3 | 80% |
| **Retry decorator** | Retries with backoff on specified exceptions | Unit: 5 | ✅ |
| **Audit logging** | Logs security events | Unit: 5 | ✅ |
| **Backup manager** | SQLite/Chroma backups, pruning old backups | Unit: 5 + 20 | ~75% |
| **Workflow tracker** | SSE event tracking for long-running operations | Unit: 18 | ~80% |
| **Query cache** | In-memory cache with schema invalidation | Unit: 18 | ~85% |
| **Safety guard** | SQL injection detection, DML blocking, Mongo safety | Unit: 17 + 41 | ~90% |
| **Context budget** | Token budget allocation across context sources | Unit: 23 | ~80% |
| **History trimmer** | Token-aware history trimming for LLM context | Unit: 15 | ~75% |
| **Error classifier** | Classifies DB/LLM errors for retry/repair decisions | Unit: 18 | ~80% |
| **SQL parser** | Extracts tables, columns, subqueries, aggregations from SQL | Unit: 18 | ~85% |
| **Schema hints** | Find similar tables/columns, table detail | Unit: 14 | ~80% |
| **Logging config** | JSON/readable formatters, correlation filter | Unit: 7 | ~70% |
| **Middleware** (main.py) | Security headers, request size limit, request ID, metrics | Unit: via test_api_routes | |
| **Alembic migrations** | Run on startup, idempotent | Unit: 2 | |

### Gaps

- [ ] Middleware isolation tests (security headers, size limit, metrics)
- [ ] Backup restore flow
- [ ] Query cache eviction under memory pressure
- [ ] Alembic migration upgrade/downgrade sequence

---

## 25. Frontend: Stores & State

| Store | Expected Behavior | Tests |
|-------|-------------------|-------|
| `useAppStore` | Project/connection/session management. Message history. Loading/thinking states. Readiness cache. Persists active IDs to localStorage | 13 tests ✅ |
| `useAuthStore` | Login/register/logout/restore/refresh. Token management. Error state | 9 tests ✅ |
| `useLogStore` | Ring buffer of workflow events. SSE connection status. Unread count | 9 tests ✅ |
| `useNotesStore` | Notes per project. Scope filter. Panel open/close persistence | 18 tests ✅ |
| `useTaskStore` | Background task tracking. SSE merge. Auto-dismiss timers | 13 tests ✅ |
| `useToastStore` | Toast queue. Auto-dismiss by type. `toast()` helper | 12 tests ✅ |
| `useConfirmStore` | Promise-based confirm dialog | 18 tests ✅ |

### Gaps

- [ ] Store interaction: switching project should clear connection/session
- [ ] Store persistence: localStorage read/write correctness
- [ ] Store: concurrent updates (multiple tabs)

---

## 26. Frontend: Components (Additional)

| Component | Expected Behavior | Tests |
|-----------|-------------------|-------|
| `Sidebar` | Desktop/mobile layouts. Section collapse (persisted). All 6+ sections. Mobile drawer with focus trap | 8 tests ✅ |
| `OnboardingWizard` | Multi-step wizard: welcome → create project → connect DB → index → done | 10 tests ✅ |
| `ReadinessGate` | Blocks chat until readiness checks pass. Bypass with confirm | 8 tests ✅ |
| `ClarificationCard` | Renders clarification options. Submits selected answer | 9 tests ✅ |
| `ErrorBoundary` | Catches React errors. Shows reload button | 3 tests ✅ |
| `SuggestionChips` | Renders clickable query suggestions | 8 tests ✅ |
| `VerificationBadge` | Shows verified/unverified/flagged status | 5 tests ✅ |
| `StatusDot` | Colored dot for connection status | 10 tests ✅ |
| `Spinner` | Loading spinner | 3 tests ✅ |
| `ToastContainer` | Renders toasts from store | 5 tests ✅ |
| `SidebarSection` | Collapsible section with persisted state | Tested via Sidebar |
| `FeedbackAnalyticsPanel` | Shows feedback metrics per project | Not unit tested |
| `UsageStatsPanel` | Shows token usage statistics | Not unit tested |
| `ChatSearch` | Searches chat history | Not unit tested |
| `LearningsPanel` | Agent learnings CRUD | Not unit tested |
| `ActiveTasksWidget` | Shows background tasks | Not unit tested |
| `LogPanel` | Workflow event log | Not unit tested |

---

## 27. Frontend: API Client

### `lib/api.ts`

| Namespace | Methods | Tests |
|-----------|---------|-------|
| `api.auth` | login, register, googleLogin, refresh, me, changePassword, deleteAccount, onboarding | Via auth-store tests |
| `api.projects` | create, list, get, update, delete, readiness | 18 tests ✅ (api.test.ts) |
| `api.connections` | create, list, get, update, delete, test, testSsh, index, sync, health, learnings... | Partial (sync-api.test.ts: 5) |
| `api.chat` | createSession, listSessions, ask, askStream, feedback, search, explainSql, summarize | Partial (via component tests) |
| `api.notes` | create, list, get, update, delete, execute | ✅ (api.test.ts) |
| `api.dashboards` | create, list, get, update, delete | ✅ (api.test.ts) |
| `api.batch` | execute, get, list, delete, export | ✅ (api.test.ts) |
| `api.rules` | create, list, get, update, delete | Via component tests |
| `api.schedules` | create, list, get, update, delete, runNow, history | Via component tests |
| `api.sshKeys` | create, list, get, delete | Via component tests |
| `api.invites` | create, list, revoke, accept, pending, members | Via component tests |
| `api.notifications` | list, unreadCount, markRead, markAllRead | Via component tests |
| `api.viz` | render, export | Via component tests |
| `api.dataValidation` | validateData, stats, benchmarks, investigate, confirmFix | Partial |
| `api.usage` | getStats | Not tested |
| `api.dataGraph` | summary, metrics, upsertMetric, relationships, discover, deleteMetric | Not tested |
| `api.insights` | list, summary, create, confirm, dismiss, resolve, actions | Not tested |
| `api.feed` | scan, fullScan, opportunities, losses | Not tested |
| `api.temporal` | analyze, detectLag | Not tested |
| `api.explore` | explore | Not tested |
| `api.semanticLayer` | buildCatalog, normalize, getCatalog | Not tested |
| `api.reconciliation` | rowCounts, values, schemas, full | Not tested |

### Gaps

- [ ] API client tests for: dataGraph, insights, feed, temporal, explore, semanticLayer, reconciliation, usage
- [ ] 401 handling (session expired → redirect to login)
- [ ] Network timeout behavior
- [ ] Streaming response parsing (SSE chunks)

---

## 28. E2E User Flows

These are full user journeys that span backend + frontend and should be tested via browser automation.

| Flow | Steps | Status |
|------|-------|--------|
| **Onboarding** | Register → Wizard → Create project → Connect DB → Index → First chat | NOT TESTED |
| **Chat conversation** | Select project → Select connection → Ask question → Get SQL + results → Follow-up → Viz switch | NOT TESTED |
| **Data validation** | Get result → Thumbs down → Agent investigates → Suggests fix → Confirm | NOT TESTED |
| **Insight discovery** | Trigger feed scan → View insights → Drill down → Resolve | NOT TESTED |
| **Dashboard creation** | Save query → Create dashboard → Add cards → View dashboard → Auto-refresh | NOT TESTED |
| **Schedule setup** | Create schedule → Cron expression → Wait for run → View history | NOT TESTED |
| **Multi-user RBAC** | Owner invites editor → Editor joins → Editor creates connection → Viewer cannot edit | NOT TESTED |
| **Knowledge indexing** | Add repo → Index → View docs → Chat uses knowledge | NOT TESTED |
| **Connection management** | Create PG connection → Test → Index schema → Sync with code → View learnings | NOT TESTED |
| **Mobile experience** | All core flows on mobile viewport (sidebar drawer, chat, notes panel) | NOT TESTED |
| **Error recovery** | Network error during chat → Retry → Reconnect | NOT TESTED |
| **Session restore** | Login → Create session → Refresh page → Session restored | NOT TESTED |

---

## 29. Performance & Load

| Test | Expected Behavior | Status |
|------|-------------------|--------|
| Health endpoint latency | < 50ms | Smoke test exists (Int) |
| Auth endpoint latency | < 200ms | Smoke test exists |
| CRUD endpoint latency | < 300ms | Smoke test exists |
| List endpoint latency | < 500ms for 100 items | Smoke test exists |
| Chat response time | First token < 3s | NOT TESTED |
| Frontend bundle size | Main page < 250kB gzipped | Build output shows 221kB |
| DB query performance | Complex queries < 5s | NOT TESTED |
| Concurrent users | 10 simultaneous chat sessions | NOT TESTED |
| Memory usage | Backend < 512MB under load | NOT TESTED |
| SSE connection stability | Reconnects within 5s of disconnect | NOT TESTED |

---

## 30. Security

| Test | Expected Behavior | Tests |
|------|-------------------|-------|
| SQL injection prevention | Safety guard blocks all injection patterns | Unit: 41 ✅ |
| Mongo injection prevention | Blocks $where, $eval, etc. | Unit: ✅ |
| DML blocking (read-only) | Blocks INSERT/UPDATE/DELETE unless explicitly allowed | Unit: ✅ |
| JWT validation | Rejects expired/tampered tokens | Unit + Int: ✅ |
| RBAC enforcement | Viewer cannot edit, editor cannot delete project | Int: 31 ✅ |
| Credential encryption | Passwords/keys encrypted at rest with Fernet | Unit: 3 ✅ |
| XSS prevention | Security headers middleware | Middleware exists |
| CORS configuration | Restricted origins | Configured in main.py |
| Rate limiting | Brute force protection on auth endpoints | Configured, Unit: 3 |
| Request size limit | Rejects oversized requests | Middleware exists |
| Unauthenticated access | All protected routes return 401 | Int: ✅ |
| Credential exposure | notes.md gitignored, never in API responses | ✅ Verified |

---

## Coverage Summary by Module

| Module | Unit Tests | Int Tests | Coverage | Target | Gap |
|--------|-----------|-----------|----------|--------|-----|
| auth_service | 28 | 29 | 92% | 95% | -3% |
| project_service | 15 | 12 | 90% | 95% | -5% |
| connection_service | 44 | 18 | 99% | — | Done |
| chat_service | 18 | 21 | ~85% | 90% | -5% |
| batch_service | 21 | 9 | 100% | — | Done |
| code_db_sync_service | 39 | — | 93% | — | Done |
| project_overview_service | 38 | — | 93% | — | Done |
| agent_learning_service | 24 | 11 | 66% | 80% | -14% |
| benchmark_service | 4 | 12 | 66% | 80% | -14% |
| db_index_service | 25 | — | 69% | 80% | -11% |
| scheduler_service | 25 | — | 100% | — | Done |
| rule_service | 17 | 9 | 100% | — | Done |
| note_service | 18 | 15 | 100% | — | Done |
| dashboard_service | 10 | 6 | 100% | — | Done |
| invite_service | 11 | 9 | 90% | 95% | -5% |
| membership_service | 12 | 31 | 100% | — | Done |
| investigation_service | 13 | — | 94% | — | Done |
| data_validation_service | 10 | — | 100% | — | Done |
| ssh_key_service | 10 | 3 | 78% | 85% | -7% |
| encryption | 3 | — | 80% | 90% | -10% |
| orchestrator (agents) | 8 | 12 | 60% | 75% | -15% |
| sql_agent | 24 | — | ~65% | 80% | -15% |
| viz (all) | 54 | 8 | 88-100% | — | Done |
| connectors | 50+15+19 | — | ~70% | 80% | -10% |
| llm_router | 23+30+16 | — | ~70% | 80% | -10% |
| safety_guard | 17+41 | — | ~90% | — | Done |
| **Frontend components** | 346 | — | N/A | — | See gaps |

---

## Priority Ranking (Next Actions)

### P0 — Critical Coverage Gaps
1. `agent_learning_service` — 66% → 80% (+14%)
2. `benchmark_service` — 66% → 80% (+14%)
3. `orchestrator/agents` — 60% → 75% (+15%)

### P1 — High Impact
4. `db_index_service` — 69% → 80% (+11%)
5. `sql_agent` — 65% → 80% (+15%)
6. `ssh_key_service` — 78% → 85% (+7%)
7. Frontend: `InsightFeedPanel` tests
8. Frontend: `DashboardBuilder` tests

### P2 — Medium Impact
9. `connectors` — 70% → 80%
10. `llm_router` — 70% → 80%
11. Frontend: API client tests for Sprint 1 namespaces
12. Frontend: `LearningsPanel`, `ChatSearch`, `UsageStatsPanel` tests

### P3 — Polish
13. Frontend: accessibility audit (aria-labels, focus management)
14. E2E flow tests (browser automation)
15. Performance profiling
16. Mobile responsiveness verification
