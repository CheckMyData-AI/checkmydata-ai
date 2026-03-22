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
| `api/routes/` | REST API endpoints | `auth.py`, `chat.py`, `connections.py`, `projects.py`, ... |
| `agents/` | Multi-agent orchestration | `orchestrator.py`, `sql_agent.py`, `knowledge_agent.py` |
| `llm/` | LLM provider abstraction | `router.py`, `base.py` (OpenAI, Anthropic, OpenRouter) |
| `connectors/` | Database connectivity | `postgres.py`, `mysql.py`, `mongodb.py`, `clickhouse.py` |
| `knowledge/` | RAG pipeline & code analysis | `vector_store.py`, `repo_analyzer.py`, `entity_extractor.py` |
| `services/` | Business logic | `auth_service.py`, `batch_service.py`, `probe_service.py` |
| `models/` | SQLAlchemy ORM models | `user.py`, `project.py`, `connection.py`, `chat_session.py` |
| `core/` | Cross-cutting concerns | `rate_limit.py`, `audit.py`, `health_monitor.py` |
| `pipelines/` | Long-running workflows | `mcp_pipeline.py` |

### Frontend (`frontend/src/`)

| Module | Purpose |
|--------|---------|
| `components/chat/` | Chat panel, input, message rendering, streaming |
| `components/connections/` | Database connection management |
| `components/viz/` | Data tables, charts, visualizations |
| `components/batch/` | Batch query execution |
| `components/learnings/` | Agent learning management |
| `components/ui/` | Shared UI components (modals, buttons, icons) |
| `stores/` | Zustand state management |
| `lib/` | API client, utilities |

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
- `ProjectMember` — multi-tenant access control
- `Connection` — encrypted database credentials
- `ChatSession` / `ChatMessage` — conversation history
- `SavedNote` — bookmarked queries
- `Dashboard` — saved visualizations
- `Repository` — linked Git repos
- `KnowledgeDoc` — indexed documentation chunks

## Security Boundaries

- All routes require JWT authentication (except `/auth/*` and `/health`)
- Project access enforced via `ProjectMember` role checks
- Database credentials encrypted with Fernet (MASTER_ENCRYPTION_KEY)
- SSH tunnels for remote database access
- Rate limiting on all mutating endpoints
- Input validation on all Pydantic models
- Path traversal protection on filesystem-facing parameters
