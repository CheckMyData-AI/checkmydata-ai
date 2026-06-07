# CheckMyData.ai

[![CI](https://github.com/CheckMyData-AI/checkmydata-ai/actions/workflows/ci.yml/badge.svg)](https://github.com/CheckMyData-AI/checkmydata-ai/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

AI-powered database query agent that analyzes Git repositories, understands database schemas, and lets you query databases through natural language chat with rich data visualization.

**Supported databases**: PostgreSQL, MySQL, ClickHouse, MongoDB
**LLM providers**: OpenAI, Anthropic, OpenRouter
**Project tracking**: [Linear — CheckMyData.ai](https://linear.app/sshlg/project/checkmydataai-b7670b0dd990) (single source of truth for tasks, backlog, and bugs)

### What's new in v1.13.0 — Vision Invariants & Correctness Restoration

Closes four vision invariant violations and six correctness bugs from the
post-1.12.x audit. Test count climbs from 3,599 → 3,648 backend (400
frontend unchanged). See [`CHANGELOG.md`](CHANGELOG.md#1130---2026-05-19)
for the full list.

- **Learnings are per-connection by default** — cross-connection transfer
  and global-pattern promotion are now opt-in via
  `CROSS_CONNECTION_LEARNINGS_ENABLED` (default `False`).
- **The system learns from every outcome**, not just from retries —
  first-shot successes and first-shot failures now produce lessons.
- **Knowledge-freshness banners thread through the whole pipeline** —
  the planner, every stage sub-agent, and final synthesis all see the
  staleness warning when the index is behind code.
- **Negative feedback contradicts the exact learnings that produced it**
  — assistant messages now record `exposed_learning_ids` and a
  thumbs-down rolls those lessons back.
- **`times_exposed` separates "the LLM saw it" from "the LLM used it"**
  (new column, Alembic `f0a1b2c3d4e5`).
- **Insight TTL + decay actually run** on a 24 h cron tick.
- **Indexing pipeline survives partial failures**: per-doc retry +
  failure-ratio threshold (`GENERATE_DOCS_MAX_FAILURE_RATIO=0.3`); Chroma
  empty ≠ Chroma unreachable; Git renames are tracked correctly.
- **`DataGate` blocks impossible numbers** (out-of-range percentages and
  dates) instead of merely warning, gated by `DATA_GATE_HARD_CHECKS_ENABLED`
  (default `True`).

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
| [docs/GIT_ACCESS_AUDIT_AND_ROADMAP.md](docs/GIT_ACCESS_AUDIT_AND_ROADMAP.md) | Live Git access architecture audit + Phase 1–4 roadmap |
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
│  │  OrchestratorAgent → LLM-driven loop (gather → synthesize)    │   │
│  │    SQLAgent:       schema + SQL gen + validation + execution   │   │
│  │    VizAgent:       chart type + config (LLM-driven)           │   │
│  │    KnowledgeAgent: RAG search + entity info + codebase Q&A    │   │
│  │    GitAgent:       live read-only Git history + releases      │   │
│  │  AdaptivePlanner:  quick/full plan generation + replan        │   │
│  │  DataGate:         intermediate data-quality validation       │   │
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
3. **Chat** -- Ask questions in natural language across independent chat sessions. Each project supports multiple parallel chats per user — each session maintains its own message history, database connection binding, and isolated state. Sessions are created eagerly on "New Chat", messages are cached per-session for instant switching, and in-flight streams are aborted cleanly on session change. When a user switches chats or reloads the page during an active query, the backend continues processing in the background and persists the result; the frontend detects in-progress sessions (via a `status` field) and polls for completion, showing a "Processing in background" indicator until the response appears. The OrchestratorAgent routes to SQLAgent (DB queries), KnowledgeAgent (codebase Q&A), or responds directly. Results include rich visualizations, follow-up suggestions, and data insights.
4. **Knowledge** -- Git repos are analyzed via multi-pass pipeline (profiling, entity extraction, cross-file analysis, LLM doc generation) and stored in ChromaDB for RAG retrieval.
5. **Sharing** -- Invite collaborators by email with role-based access (owner/editor/viewer). Owners can change member roles on the fly and remove members. Each user gets isolated chat sessions while sharing project data.

## Key Features

- **Natural language to SQL** with self-healing validation loop (retry, repair, explain), dialect-aware error classification (column/table not found, syntax, collation mismatch, timeout, permission denied, etc.), and targeted repair hints
- **Multi-agent orchestration** with LLM-driven routing and complexity assessment (replacing hardcoded intent classification and keyword heuristics), adaptive planning, per-stage validation + DataGate quality checks, automatic replanning on failure (configurable via `max_pipeline_replans`, default 2; replan history is threaded into the prompt so the LLM avoids repeating failed approaches), context-aware routing, hardened history-aware turn isolation (conversation history is read-only reference — prior turns are never re-executed, raw SQL is stripped from history, and a per-turn dedup safety net skips queries already answered in the same turn), semantic tool-call deduplication, continuation-aware analysis resumption, and structured clarification questions (yes/no, multiple choice, free text) when user intent is ambiguous. A unified router performs a single LLM call to determine route, complexity, approach, and estimated queries. Per-viz timeouts (15s with table fallback) and empty-answer guards ensure queries always produce a visible response. Dynamic budget injection per iteration replaces rigid step/time cutoffs — the LLM self-regulates tool usage based on budget status. **Parallel stage execution** (`pipeline_max_parallel_stages`, default 3) runs independent stages concurrently via topological scheduling. Stage failures are classified (`transient | configuration | data_missing | fatal`) so non-retryable errors short-circuit the retry loop. When analysis hits the budget limit, an LLM-based **Answer Validator** decides whether the partial answer addresses the question — only then is the "Continue analysis" button shown, preserving executed SQL queries, intermediate results, and partial findings.
- **Agent Learning Memory** -- automatically learns from query outcomes, pipeline replans, and DataGate failures; accumulated learnings are injected into planning prompts for future queries. Quality gates enforce minimum lesson length, subject validation (blocklist for SQL keywords/metadata), and non-ASCII ratio checks to prevent polluted learnings. Read-time blocklist filtering also catches legacy bad data. Users can confirm (upvote) or contradict (downvote) individual learnings via the UI; votes invalidate the compiled prompt cache immediately. Confidence decay is accelerated for never-applied learnings (-0.05 vs -0.02 per 30-day cycle). Schema cross-validation runs automatically on schema refresh and is available as a manual API endpoint (`POST /connections/{id}/learnings/validate-schema`) to deactivate learnings referencing dropped tables. Nine learning categories are supported: Table Preferences, Column Usage, Data Formats, Query Patterns, Schema Gotchas, Performance Hints, Pipeline Patterns, Data Quality Hints, and Replan Recoveries
- **Custom rules & business logic** -- user-defined rules (metric formulas, naming conventions, data handling guidelines) are proactively injected into both orchestrator and SQL agent system prompts with budget-aware truncation, ensuring every query respects domain knowledge without relying on optional tool calls. **Rule Freshness Check**: after receiving query results, the orchestrator compares them against loaded custom rules and proposes updates when discrepancies are detected (e.g., a new enum value appears in data that isn't covered by a rule). **Schema-aware rule validation** runs automatically on schema refresh to flag rules referencing dropped tables.
- **Multilingual responses** -- the agent reasons internally in English but writes its final answer in the same language as the user's most recent message (e.g. a Russian question gets a Russian answer). The rule is injected at every user-facing synthesis point (orchestrator, direct response, step-limit/emergency synthesis, and the complex-pipeline synthesizer).
- **LLM-driven table resolution** -- the SQL agent resolves relevant tables using the full table map and schema context provided in its prompt, letting the LLM reason about which tables are relevant rather than relying on keyword heuristics.
- **Execution plan visibility** -- a `plan_summary` event is emitted before query execution, showing the user which tables, rules, and learnings the orchestrator will use, streamed as a compact card in the chat UI that auto-collapses when the answer starts streaming.
- **Agent Reasoning Panel** -- a slide-out side panel (brain icon on each assistant message) displays the full orchestrator reasoning trace: plan summary, thinking log, step-by-step timeline with icons and durations, rules and learnings applied. Data is collected in real-time via SSE during streaming and persisted per-message in a dedicated Zustand store.
- **Data validation feedback loop** -- wrong data investigation, benchmarks, proactive sanity checks
- **Rich visualizations** -- bar, line, pie, scatter charts with on-the-fly type switching and XLSX/CSV/JSON export; compound queries produce multiple independent charts per answer
- **Database indexing** -- AI-powered schema analysis with business descriptions, data patterns, and query hints
- **Code-DB sync** -- cross-references codebase with database to discover data formats, enums, conversion rules
- **SSH tunnel & exec mode** -- connect through jump servers via port forwarding or CLI execution
- **Scheduled queries & alerts** -- cron-based recurring queries with threshold-based notifications
- **Team dashboards** -- compose saved queries into grid layouts for monitoring
- **Batch query execution** -- run multiple queries, export results as multi-sheet XLSX
- **MCP server & client** -- expose the agent as MCP tools and consume external MCP servers; MCP sources are fully integrated into the multi-stage pipeline planner
- **Multi-chat sessions** -- independent parallel chats per project with per-session message caching, connection binding, abort-on-switch safety, and background completion of in-progress queries (results persist even after navigating away or reloading)
- **Session rotation** -- automatic context-preserving session continuation near token limits
- **Data enrichment pipeline** -- IP-to-country, phone-to-country, aggregation, filtering, and release `cohort_window` (7/14-day retention/revenue) between query steps with immutable result handling
- **Live Git access** -- read-only Git history specialist (`GitAgent` + `GitInspector`) the orchestrator can call to inspect commits, diffs, blame, releases/tags, authorship, file churn, and commit-trailer review signals on the project's local clone. Available both as single-loop meta-tools (`analyze_git`, `get_release_timeline`, `write_code_note`) and as a first-class `analyze_git` planner stage. Gated by a fast `has_repo` capability probe, security-hardened (read-only, explicit arg lists, path-traversal guard, output/count caps, no hooks), with a clone-freshness warning and opt-in auto-pull. Code findings are persisted as `code_finding` insights and recalled in future questions. Enables the release→cohort recipe: `analyze_git` → `query_database` → `process_data (cohort_window)` → `synthesize`.
- **Robust error handling** -- try/except wrapping for pipeline execution, DB persistence, sub-agent LLM calls, and MCP adapter calls with graceful fallbacks. Centralized `llm_call_with_retry` helper provides exponential backoff for all LLM calls; `LLMAllProvidersFailedError` is non-retryable to prevent provider thrash.
- **Unified knowledge freshness** -- `KnowledgeFreshnessService` combines DB-index age, code↔DB sync status, and Git HEAD vs indexed SHA into a single freshness warning surfaced in the orchestrator prompt.
- **Insight memory & reconciliation** -- discovered anomalies are persisted with TTL-based expiry per severity; new query results auto-confirm reproduced insights and dismiss stale ones. Active insights are injected into the orchestrator context.
- **RAG-augmented orchestration** -- relevant knowledge-base chunks for the user's question are pre-fetched and injected into the orchestrator prompt (not only during query repair).
- **Structured tool responses** -- `record_learning` and `write_note` return JSON outcomes (`status: ok|rejected`) so the LLM can parse rejection reasons and retry with corrections.
- **LLM-first learning analyzer** -- `learning_analyzer_mode` (`heuristic | hybrid | llm_first`) controls how lessons are extracted from query attempts; the legacy `_detect_*` rules remain as a fast pre-filter.
- **ClickHouse EXPLAIN warnings** -- the EXPLAIN validator now flags unbounded MergeTree scans without `PREWHERE`/`WHERE`.
- **Per-request observability** -- `MetricsCollector` records route, complexity, response_type, replans, retries, SQL calls, and wall-clock time per request. Exposed via `/metrics` (recent rows) and `/metrics/prometheus` (text exposition format). Also surfaces M2/M5/M6 code-graph counters (`code_graph_symbols_total`, `code_graph_edges_total`, `code_graph_lineage_refs_total`, `code_graph_clusters_total`).
- **Code intelligence pipeline (M1–M6, feature-flagged)** — an in-house GitNexus-inspired layer that augments the existing 5-pass ORM/SQL pipeline:
  - **AST parsing** (`code_graph_enabled`): tree-sitter-based extraction of symbols/imports/calls for Python, JS/TS, Go, Java, Ruby, PHP, C#.
  - **Code knowledge graph**: NetworkX graph (CALLS/IMPORTS/EXTENDS) persisted to `code_graph_symbols` + `code_graph_edges` with confidence scores.
  - **Hybrid retrieval** (`hybrid_retrieval_enabled`): BM25 (rank_bm25) ⊕ ChromaDB merged via Reciprocal Rank Fusion in `KnowledgeAgent`; soft timeouts and single-leg degradation.
  - **Question-aware schema retrieval** (`schema_retrieval_enabled`): BM25 over LLM-enriched schema docs picks the right tables for the SQL agent instead of the legacy top-12-by-`relevance_score`.
  - **Code→DB lineage** (`lineage_enabled`): walks the call graph from each ORM entity to discover HTTP endpoints / CLI commands / migrations that read or write the table; the SQL agent gets a "Lineage (top callers)" section per table.
  - **Functional clustering** (`clustering_enabled`): Louvain communities on the graph; optional LLM labeling (`cluster_llm_label_enabled`) powers the new `get_tables_in_cluster` SQL agent tool ("show me the auth tables" → one call).
  - **Resume safety + cleanup**: on pipeline resume, `state.code_graph` is rehydrated from Postgres via `CodeGraphService.load_graph()` before M5/M6 run (no silent skips). On project / connection delete, `backend/app/services/indexing_artifacts.py` performs best-effort, non-throwing cleanup of the on-disk BM25 snapshots and the project's ChromaDB collection (Postgres FK cascades handle the structured rows).
  - **Knowledge freshness warning**: `KnowledgeFreshnessService.check_staleness()` is injected as a `KNOWLEDGE FRESHNESS WARNINGS` block into both the simple tool-calling loop and the multi-stage pipeline orchestrator messages, so the LLM is told *why* answers may be stale.
  - **Code lineage rendering**: `KnowledgeAgent._format_entity_detail()` renders the top callers from `EntityInfo.graph_callers` as a "Code lineage (top callers)" section in entity detail responses when `lineage_enabled` is on.
  - **Rollout playbook**: per-flag canary criteria, smoke tests, soak duration, rollback, and the exact scope of the post-soak cleanup PR are documented in [docs/ROLLOUT_M1_M6.md](docs/ROLLOUT_M1_M6.md). The operator drives the rollout with `make rollout-check`.
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

**Optional:** `GOOGLE_CLIENT_ID` (Google OAuth), `RESEND_API_KEY` (transactional emails), `REDIS_URL` (shared cache + task queue), `DATABASE_URL` (PostgreSQL for production), `AGENT_WALL_CLOCK_TIMEOUT_SECONDS` (orchestrator time limit, default 180s), `MAX_PARALLEL_TOOL_CALLS` (concurrent tool cap, default 2), `PIPELINE_MAX_PARALLEL_STAGES` (concurrent pipeline stages, default 3), `MAX_PIPELINE_REPLANS` (replan attempts, default 2), `ANSWER_VALIDATOR_ENABLED` (LLM quality gate on partial answers, default true), `LEARNING_ANALYZER_MODE` (`heuristic | hybrid | llm_first`, default `llm_first`), `MAX_ORCHESTRATOR_ITERATIONS` (tool-loop ceiling, default 100), `LLM_RESULT_PREVIEW_ROWS` (result rows shown to the LLM, default 50), `MAINTENANCE_INTERVAL_HOURS` (learning/insight decay cadence, default 24), `SSH_HOST_KEY_POLICY` (`disabled | tofu | strict`, default `disabled`; with `SSH_KNOWN_HOSTS_PATH` for `tofu`/`strict`), `QUERY_EMPTY_RESULT_RETRY` (treat an empty result as suspicious and retry once within the correction budget, default `true`), `ORCHESTRATOR_MAX_RESULT_CORRECTIONS` (result-gate correction budget, `>= 0`, default 2), `AUTH_COOKIE_SECURE` / `AUTH_COOKIE_SAMESITE` (browser session is delivered as an httpOnly cookie + CSRF; set `AUTH_COOKIE_SECURE=false` only for local http), `SECURITY_CSP` / `SECURITY_HSTS_ENABLED` (CSP + HSTS response headers), `MCP_ENABLED` / `MCP_API_KEY_USER_ID` (the MCP tool server is off by default and binds its API key to a real user). See `backend/.env.example` for all options.

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
| `make rollout-check` | Heroku health snapshot for the M1–M6 flag rollout (config, dyno, `/api/health`, `code_graph_*` metrics) |

## Deployment

The project supports multiple deployment targets:

- **Heroku** (primary) -- `Procfile`, `heroku.yml`, and Dockerfiles included. CI auto-deploys via GitHub Actions. See [INSTALLATION.md](INSTALLATION.md#production-deployment) for setup.
- **Docker Compose** -- `docker compose up --build` runs backend, frontend, and Redis with health checks.
- **DigitalOcean App Platform** -- App spec at `.do/app.yaml` with secret management.

## Testing

- **4,246 total tests** (3,366 backend unit + 478 backend integration + 402 frontend)
- **72%+ backend coverage** (CI-enforced minimum; target 80%, tracked in [BACKLOG.md](BACKLOG.md) Sprint 9)
- Zero flaky tests, zero skipped tests

```bash
make check           # Backend lint + all tests
make test-frontend   # Frontend vitest
```

## Contributing

We welcome contributions! Please read [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines on setting up the development environment, branch naming, commit conventions, and the pull request process.

## License

This project is licensed under the [MIT License](LICENSE).
