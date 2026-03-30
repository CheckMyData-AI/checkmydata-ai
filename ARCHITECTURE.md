# Architecture

## Overview

CheckMyData.ai is a full-stack application with a Python/FastAPI backend and a
Next.js/React frontend. It uses a multi-agent AI system to translate natural
language questions into database queries with rich visualizations.

```
┌─────────────────────────────────────────────────────────┐
│                   Frontend (Next.js)                     │
│  React + TypeScript + Tailwind + Zustand                │
└────────────────────────┬────────────────────────────────┘
                         │ REST + SSE
┌────────────────────────▼────────────────────────────────┐
│                 Backend (FastAPI)                         │
│                                                          │
│  ┌──────────┐  ┌──────────────┐  ┌───────────────────┐  │
│  │ API Layer│  │ Multi-Agent  │  │ Knowledge Layer   │  │
│  │ (Routes) │──│ System       │──│ (RAG + ChromaDB)  │  │
│  └──────────┘  └──────┬───────┘  └───────────────────┘  │
│                        │                                 │
│  ┌─────────┐  ┌───────▼──────┐  ┌───────────────────┐  │
│  │LLM      │  │ Database     │  │ Services           │  │
│  │Router   │  │ Connectors   │  │ (Auth, Projects,   │  │
│  │(OpenAI, │  │ (PG, MySQL,  │  │  Batch, Schedule)  │  │
│  │Anthropic│  │  Mongo, CH)  │  │                    │  │
│  │OpenR.)  │  └──────────────┘  └───────────────────┘  │
│                                                          │
│  Storage: SQLite/PostgreSQL (app) + ChromaDB (vectors)   │
└──────────────────────────────────────────────────────────┘
```

## Module Decomposition

### Backend (`backend/app/`)

| Module | Purpose | Key Files |
|--------|---------|-----------|
| `api/routes/` | REST API endpoints (31 routers) | `auth.py`, `chat.py`, `connections.py`, `projects.py`, `logs.py`, `batch.py`, `dashboards.py`, `schedules.py`, `notifications.py`, `insights.py`, `feed.py`, `data_graph.py`, `reconciliation.py`, `semantic_layer.py`, `exploration.py`, `temporal.py`, ... |
| `agents/` | Multi-agent orchestration | `orchestrator.py`, `sql_agent.py`, `knowledge_agent.py`, `viz_agent.py`, `mcp_source_agent.py`, `query_planner.py`, `stage_executor.py`, `stage_validator.py` |
| `llm/` | LLM provider abstraction | `router.py`, `base.py`, `openai_adapter.py`, `anthropic_adapter.py`, `openrouter_adapter.py` |
| `connectors/` | Database connectivity | `postgres.py`, `mysql.py`, `mongodb.py`, `clickhouse.py`, `ssh_tunnel.py`, `mcp_client.py` |
| `knowledge/` | RAG pipeline & code analysis | `vector_store.py`, `repo_analyzer.py`, `entity_extractor.py`, `learning_analyzer.py` |
| `services/` | Business logic | `auth_service.py`, `batch_service.py`, `probe_service.py`, `trace_persistence_service.py`, `logs_service.py`, `schedule_service.py`, `notification_service.py`, `insight_memory_service.py`, `action_engine.py`, ... |
| `models/` | SQLAlchemy ORM models | `user.py`, `project.py`, `connection.py`, `chat_session.py`, `request_trace.py`, `insight.py`, `schedule.py`, `notification.py`, `agent_learning.py`, ... |
| `core/` | Cross-cutting concerns | `agent.py`, `context_budget.py`, `history_trimmer.py`, `insight_memory.py`, `validation_loop.py`, `workflow_tracker.py`, `health_monitor.py`, `rate_limit.py`, `audit.py` |
| `pipelines/` | Long-running workflows | `mcp_pipeline.py` |
| `mcp_server/` | MCP protocol server | `server.py`, `tools.py`, `resources.py`, `auth.py` |

### Frontend (`frontend/src/`)

| Module | Purpose |
|--------|---------|
| `components/chat/` | Chat panel, input, message rendering, streaming, result cards |
| `components/connections/` | Database connection management, health monitoring |
| `components/viz/` | Data tables, charts, visualizations, export (CSV/JSON/XLSX) |
| `components/batch/` | Batch query execution and results |
| `components/dashboards/` | Dashboard builder and list |
| `components/logs/` | Request Logs screen (owner-only trace viewer) |
| `components/projects/` | Project selector, invite manager, access requests |
| `components/onboarding/` | 5-step onboarding wizard |
| `components/schedules/` | Scheduled queries and alert conditions |
| `components/insights/` | Insight feed panel, metric catalog |
| `components/learnings/` | Agent learning management |
| `components/notes/` | Saved queries panel |
| `components/knowledge/` | Knowledge docs browser |
| `components/rules/` | Custom rules manager |
| `components/ssh/` | SSH key manager |
| `components/auth/` | AuthGate, AuthRedirect, AccountMenu |
| `components/workflow/` | Workflow and investigation progress |
| `components/usage/` | Usage statistics panel |
| `components/analytics/` | Feedback analytics panel |
| `components/tasks/` | Active tasks widget |
| `components/invites/` | Pending invites |
| `components/ui/` | Shared UI components (modals, buttons, icons, tooltips) |
| `stores/` | Zustand state management (app, auth, notes, toast, task, log) |
| `hooks/` | Custom hooks (permissions, mobile layout, global events) |
| `lib/` | API client, SSE, utilities, polling |

## Data Flow

### Chat Query Flow

```
User types question
  → ChatPanel → POST /api/chat/ask (or SSE stream)
    → OrchestratorAgent routes to sub-agent
      → SQLAgent: schema lookup → SQL generation → validation → execution
      → KnowledgeAgent: RAG search → context retrieval
    → VizAgent: picks chart type for SQL results
  → Response with query, results, visualization config
  → Frontend renders DataTable + Chart
```

### Knowledge Indexing Flow

```
User connects Git repo
  → POST /api/repos/{project_id}/index
    → RepoAnalyzer clones/pulls repo
      → ProjectProfiler: high-level project scan
      → EntityExtractor: function/class extraction
      → LLM doc generation: enriched documentation
    → Chunks stored in ChromaDB
  → Available for RAG retrieval in chat
```

### Trace Persistence Flow

```
Chat request arrives (any path)
  → WorkflowTracker.begin() creates workflow_id (with project_id, user_id)
    → Each step emits events via WorkflowTracker.step(step_data={...})
      → step_data carries input_preview, output_preview, token_usage
      → Noise events (token, thinking, warning) are filtered out
    → TracePersistenceService hooks into _broadcast, accumulates spans
  → WorkflowTracker.end() fires pipeline_end
    → TracePersistenceService batch-inserts RequestTrace + TraceSpan rows
      → TraceSpan.input_preview  — LLM prompt / SQL query / tool args
      → TraceSpan.output_preview — LLM response / query results / tool output
      → TraceSpan.token_usage_json — model, prompt/completion/total tokens
  → finalize_trace() enriches with message IDs and metadata
  → Owner opens Logs screen → GET /api/logs/ queries request_traces + trace_spans

Error trace guarantees:
  → ConversationalAgent.run() wraps orchestrator in try/except/finally
    → If orchestrator raises without calling end(), safety net emits pipeline_end
    → WorkflowTracker.has_ended(wf_id) prevents duplicate pipeline_end events
  → _persist_workflow no longer skips traces with empty project_id/user_id
    → Traces are persisted with empty IDs; finalize_trace() updates them later
  → Stale buffers (pipeline_end never received) are persisted as failed traces
    → _cleanup_stale_buffers creates synthetic pipeline_end event
  → Non-streaming /ask wraps _agent.run() in try/except to finalize on crash
  → Streaming _finalize_on_error uses fallback wf_id when original is None

Traced request paths:
  POST /api/chat/ask              — non-streaming chat (finalize on success/error/crash)
  POST /api/chat/ask/stream       — SSE streaming (finalize on success + error/timeout)
  WebSocket /api/chat/ws/{project}/{connection} — WebSocket chat (finalize after each message)
  MCP tools              — query_database, search_codebase (singleton tracker)
  Data validation        — investigation agent (singleton tracker)
  Batch execute          — batch queries (project_id in context)
  POST /generate-title   — lightweight LLM call (generate_title pipeline)
  POST /explain-sql      — lightweight LLM call (explain_sql pipeline)
  POST /summarize        — lightweight LLM call (summarize pipeline)
```

## Key Dependencies

### Backend
- **FastAPI** — async web framework
- **SQLAlchemy 2.0** — async ORM (asyncpg/aiosqlite)
- **Alembic** — database migrations
- **ChromaDB** — vector store for RAG
- **httpx** — async HTTP client (LLM APIs)
- **Pydantic** — data validation and settings

### Frontend
- **Next.js 15** — React framework (App Router)
- **Zustand** — lightweight state management
- **Tailwind CSS** — utility-first styling

## Database Schema

The application uses SQLite in development and PostgreSQL in production.
Key models:

- `User` — authentication, profile
- `Project` — workspace container
- `ProjectMember` — multi-tenant access control (owner/editor/viewer)
- `Connection` — encrypted database credentials
- `ChatSession` / `ChatMessage` — conversation history
- `SavedNote` — bookmarked queries
- `Dashboard` — saved visualizations
- `Repository` — linked Git repos
- `KnowledgeDoc` — indexed documentation chunks
- `RequestTrace` / `TraceSpan` — persisted orchestrator execution traces
- `AgentLearning` — per-connection learned patterns and knowledge
- `Schedule` / `ScheduleResult` — recurring query schedules and results
- `Notification` — in-app notification delivery
- `InsightRecord` / `TrustScore` — proactive insights with confidence scores
- `MetricDefinition` / `MetricRelationship` — semantic layer metric catalog
- `CodeDbSync` — code-database sync results

## Security Boundaries

- All routes require JWT authentication (except `/api/auth/*` and `/api/health`)
- Project access enforced via `ProjectMember` role checks
- Database credentials encrypted with Fernet (MASTER_ENCRYPTION_KEY)
- SSH tunnels for remote database access
- Rate limiting on all mutating endpoints
- Input validation on all Pydantic models
- Path traversal protection on filesystem-facing parameters

---

For the full deep-dive into orchestrator internals, memory system, LLM routing, and data flow diagrams, see [docs/SYSTEM_ARCHITECTURE.md](docs/SYSTEM_ARCHITECTURE.md).
