# CheckMyData.ai

[![CI](https://github.com/CheckMyData-AI/checkmydata-ai/actions/workflows/ci.yml/badge.svg)](https://github.com/CheckMyData-AI/checkmydata-ai/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

AI-powered database query agent that analyzes Git repositories, understands database schemas, and lets you query databases through natural language chat with rich data visualization.

**Supported databases**: PostgreSQL, MySQL, ClickHouse, MongoDB
**LLM providers**: OpenAI, Anthropic, OpenRouter

## Quick Start

```bash
git clone https://github.com/CheckMyData-AI/checkmydata-ai.git
cd checkmydata-ai
make setup    # Install deps, create .env, run migrations
make dev      # Backend on :8000, frontend on :3100
```

Open `http://localhost:3100` to see the landing page, then click **Get Started** to register. See [INSTALLATION.md](INSTALLATION.md) for detailed setup instructions.

## Documentation

| Document | Description |
|----------|-------------|
| [vision.md](vision.md) | Product vision and guiding principles |
| [INSTALLATION.md](INSTALLATION.md) | Setup, deployment, and configuration |
| [USAGE.md](USAGE.md) | Step-by-step user guide for all features |
| [API.md](API.md) | REST API reference |
| [ARCHITECTURE.md](ARCHITECTURE.md) | System design and module overview |
| [docs/SYSTEM_ARCHITECTURE.md](docs/SYSTEM_ARCHITECTURE.md) | Deep-dive: orchestrator, memory, LLM routing, feedback loops |
| [DESIGN_SYSTEM.md](DESIGN_SYSTEM.md) | UI design system, tokens, and component guidelines |
| [CONTRIBUTING.md](CONTRIBUTING.md) | How to contribute |
| [CHANGELOG.md](CHANGELOG.md) | Release history |
| [ROADMAP.md](ROADMAP.md) | Future plans and priorities |
| [SECURITY.md](SECURITY.md) | Vulnerability reporting and security measures |
| [FAQ.md](FAQ.md) | Common questions and troubleshooting |

## How It Works

```
┌───────────────────────────────────────────────────────────────────────┐
│                        User  (Browser)                               │
│  ┌─────────┐  ┌──────────────┐  ┌──────────┐  ┌────────────┐  ┌──────┐│
│  │  Auth    │  │  Sidebar     │  │  Chat    │  │ Visualiz.  │  │Notes ││
│  │  Gate    │  │  (Projects,  │  │  Panel   │  │ (Table/    │  │Panel ││
│  │         │  │  Connections, │  │          │  │  Chart/    │  │(Saved││
│  │         │  │  SSH Keys,   │  │          │  │  Export)   │  │Quer.)││
│  │         │  │  Rules, Docs)│  │          │  │            │  │      ││
│  └────┬────┘  └──────┬───────┘  └────┬─────┘  └─────┬──────┘  └──┬───┘│
│       │              │               │              │            │    │
└───────┼──────────────┼───────────────┼──────────────┼────────────┼────┘
        │              │               │              │            │
        ▼              ▼               ▼              ▼            ▼
┌───────────────────────────────────────────────────────────────────────┐
│                    FastAPI  Backend  (Python)                         │
│                                                                       │
│  ┌────────────────────────────────────────────────────────────────┐   │
│  │  API Layer  (/api/...)                                        │   │
│  │  auth · projects · connections · ssh-keys · chat · notes      │   │
│  │  repos · rules · visualizations · workflows · data-validation │   │
│  │  batch · dashboards · usage · data-graph · insights · demo    │   │
│  └──────────────────────────┬─────────────────────────────────────┘   │
│                             │                                         │
│  ┌──────────────────────────▼─────────────────────────────────────┐   │
│  │  Multi-Agent System                                            │   │
│  │  OrchestratorAgent → routes to specialised sub-agents:        │   │
│  │    SQLAgent:       schema + SQL gen + validation + execution   │   │
│  │    VizAgent:       chart type + config (rule-based / LLM)     │   │
│  │    KnowledgeAgent: RAG search + entity info + codebase Q&A    │   │
│  │  AgentResultValidator: validates before returning to user     │   │
│  └──┬────────┬───────────┬────────────┬───────────────────────────┘   │
│     │        │           │            │                               │
│     ▼        ▼           ▼            ▼                               │
│  ┌──────┐ ┌──────────┐ ┌──────────┐ ┌────────────────────────────┐   │
│  │ LLM  │ │Knowledge │ │Connectors│ │ Workflow Tracker            │   │
│  │Router│ │  Layer   │ │(PG,MySQL,│ │ (SSE events, structured    │   │
│  │      │ │          │ │ Mongo,CH)│ │  logging, step-by-step     │   │
│  │OpenAI│ │ Git repo │ │          │ │  progress)                 │   │
│  │Anthro│ │ ChromaDB │ │SSH tunnel│ │                            │   │
│  │OpenR.│ │ Doc gen  │ │support   │ │                            │   │
│  └──────┘ └──────────┘ └──────────┘ └────────────────────────────┘   │
│                                                                       │
│  Internal Storage: SQLite (agent.db) + ChromaDB (vectors)             │
└───────────────────────────────────────────────────────────────────────┘
```

**Five main flows:**

1. **Onboarding** -- Guided 5-step wizard: connect database, test, index schema, connect code repo, ask first question. A welcome chat with an agent greeting is created automatically for new users. Or try a demo project with sample data.
2. **Setup** -- Register/login, add SSH keys, create project (with Git repo), create database connections (with optional SSH tunnels).
3. **Chat** -- Ask questions in natural language. The OrchestratorAgent routes to SQLAgent (DB queries), KnowledgeAgent (codebase Q&A), or responds directly. Results include rich visualizations, follow-up suggestions, and data insights.
4. **Knowledge** -- Git repos are analyzed via multi-pass pipeline (profiling, entity extraction, cross-file analysis, LLM doc generation) and stored in ChromaDB for RAG retrieval.
5. **Sharing** -- Invite collaborators by email with role-based access (owner/editor/viewer). Owners can change member roles on the fly and remove members. Each user gets isolated chat sessions while sharing project data.

## Key Features

- **Natural language to SQL** with self-healing validation loop (retry, repair, explain)
- **Multi-agent orchestration** with adaptive step budgets, context-aware routing, history-aware turn isolation, tool-call deduplication, and structured clarification questions (yes/no, multiple choice, free text) when user intent is ambiguous
- **Agent Learning Memory** -- automatically learns from query outcomes and accumulates per-connection knowledge
- **Data validation feedback loop** -- wrong data investigation, benchmarks, proactive sanity checks
- **Rich visualizations** -- bar, line, pie, scatter charts with on-the-fly type switching and XLSX/CSV/JSON export
- **Database indexing** -- AI-powered schema analysis with business descriptions, data patterns, and query hints
- **Code-DB sync** -- cross-references codebase with database to discover data formats, enums, conversion rules
- **SSH tunnel & exec mode** -- connect through jump servers via port forwarding or CLI execution
- **Scheduled queries & alerts** -- cron-based recurring queries with threshold-based notifications
- **Team dashboards** -- compose saved queries into grid layouts for monitoring
- **Batch query execution** -- run multiple queries, export results as multi-sheet XLSX
- **MCP server & client** -- expose the agent as MCP tools and consume external MCP servers; MCP sources are fully integrated into the multi-stage pipeline planner
- **Session rotation** -- automatic context-preserving session continuation near token limits
- **Data enrichment pipeline** -- IP-to-country, phone-to-country, aggregation, filtering between query steps with immutable result handling
- **Robust error handling** -- try/except wrapping for pipeline execution, DB persistence, sub-agent LLM calls, and MCP adapter calls with graceful fallbacks
- **Progressive Web App** -- installable, responsive design with mobile sidebar drawer

## Website Structure

| Route | Description |
|-------|-------------|
| `/` | Public landing page with product overview |
| `/login` | Login / registration page |
| `/app` | Main application (requires authentication) |
| `/about` | About page -- mission, tech stack |
| `/contact` | Contact information and channels |
| `/support` | FAQ, documentation links, support channels |
| `/terms` | Terms of Service |
| `/privacy` | Privacy Policy |
| `/dashboard/[id]` | Shared dashboard viewer |

## Configuration

Copy `backend/.env.example` to `backend/.env` and set the required values. See [INSTALLATION.md](INSTALLATION.md) for the full environment variable reference.

**Required:**

| Variable | Description |
|----------|-------------|
| `MASTER_ENCRYPTION_KEY` | Fernet key for encrypting stored credentials. Generate: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `JWT_SECRET` | Secret for signing JWT tokens (change from default in production) |
| One LLM API key | `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, or `OPENROUTER_API_KEY` |

**Optional:** `GOOGLE_CLIENT_ID` (Google OAuth), `RESEND_API_KEY` (transactional emails), `REDIS_URL` (shared cache + task queue), `DATABASE_URL` (PostgreSQL for production), `AGENT_WALL_CLOCK_TIMEOUT_SECONDS` (orchestrator time limit, default 90s), `MAX_PARALLEL_TOOL_CALLS` (concurrent tool cap, default 2). See `backend/.env.example` for all options.

## Development Commands

| Command | Description |
|---------|-------------|
| `make setup` | Full setup: venv, deps, .env, encryption key, migrations |
| `make dev` | Start backend (:8000) + frontend (:3100) |
| `make test` | Backend unit tests |
| `make test-frontend` | Frontend vitest |
| `make test-all` | All backend tests (unit + integration) |
| `make lint` | Run ruff linter |
| `make check` | Lint + all tests |
| `make docker-up` | Build and start Docker containers |

## Deployment

The project supports multiple deployment targets:

- **Heroku** (primary) -- `Procfile`, `heroku.yml`, and Dockerfiles included. CI auto-deploys via GitHub Actions. See [INSTALLATION.md](INSTALLATION.md#production-deployment) for setup.
- **Docker Compose** -- `docker compose up --build` runs backend, frontend, and Redis with health checks.
- **DigitalOcean App Platform** -- App spec at `.do/app.yaml` with secret management.

## Testing

- **3,252 total tests** (2,487 backend unit + 410 integration + 346 frontend + 9 performance smoke)
- **72%+ backend coverage** (CI-enforced minimum)
- Zero flaky tests, zero skipped tests

```bash
make check           # Backend lint + all tests
make test-frontend   # Frontend vitest
```

## Contributing

We welcome contributions! Please read [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines on setting up the development environment, branch naming, commit conventions, and the pull request process.

## License

This project is licensed under the [MIT License](LICENSE).
