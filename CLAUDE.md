# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Product snapshot

- **What it is**: AI-powered database query agent — natural language → SQL, codebase Q&A, visualizations, team workspaces.
- **Supported databases**: PostgreSQL, MySQL, ClickHouse, MongoDB (via `backend/app/connectors/`).
- **LLM providers**: OpenAI, Anthropic, OpenRouter (`backend/app/llm/router.py`).
- **Task tracking**: [Linear — CheckMyData.ai](https://linear.app/sshlg/project/checkmydataai-b7670b0dd990).
- **Tests**: ~4,246 total (backend unit + integration + frontend Vitest); **72% backend coverage** enforced in CI.
- **Recent work**: see `[Unreleased]` in `CHANGELOG.md` (June 2026 audit remediation: billing, cookie auth, MCP/SSH hardening, Redis limits, Sentry).

## Prerequisites

| Tool | Version |
|------|---------|
| Python | 3.12+ |
| Node.js | 20+ |
| npm | 10+ |
| Git | 2.30+ |

## Quick start

```bash
make setup    # venv, deps, backend/.env, migrations
make dev      # backend :8000, frontend :3100
```

Open `http://localhost:3100`. Required env in `backend/.env`: `MASTER_ENCRYPTION_KEY`, `JWT_SECRET`, and at least one of `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `OPENROUTER_API_KEY`. Full reference: `INSTALLATION.md`, `backend/.env.example`.

## Repo layout

Monorepo with two top-level apps and shared infrastructure:

- `backend/` — Python 3.12 + FastAPI + SQLAlchemy 2.0 async + Alembic. Source in `backend/app/`; tests in `backend/tests/{unit,integration}`. Packaged via `pyproject.toml` (editable install with `[dev]` extras). Eval harness in `backend/app/eval/`.
- `frontend/` — Next.js 15 (App Router) + React 19 + TypeScript + Tailwind v4 + Zustand. Source in `frontend/src/`. PWA-capable.
- `rules/` — user-supplied custom rule files (Markdown/YAML); consumed by the rule engine at runtime, **not** code.
- `scripts/` — `dev-up.sh` / `dev-down.sh` (Docker), `deploy-heroku.sh`, `audit_learnings.py`.
- `docs/` — deep-dive architecture, rollout playbooks, audit plans. Root docs: `ARCHITECTURE.md`, `vision.md`, `DESIGN_SYSTEM.md`, `BACKLOG.md`, `CHANGELOG.md`.
- `backend/alembic/` — DB migrations. The `Procfile` runs `alembic upgrade head` before the web dyno boots.

## Commands

All routine commands are driven through the root `Makefile`. It bootstraps a venv at `backend/.venv` and uses `$(VENV)/<tool>` invocations everywhere.

### Setup / dev

| Command | What it does |
|---|---|
| `make setup` | Full bootstrap: venv, `pip install -e ".[dev]"`, `npm install`, copies `backend/.env.example` → **`backend/.env`**, generates a Fernet `MASTER_ENCRYPTION_KEY` if blank, runs `alembic upgrade head`. |
| `make setup-backend` / `setup-frontend` / `setup-env` / `migrate` | Granular setup steps. |
| `make dev` | Backend on `:8000`, frontend on `:3100`. PIDs in `.pids/`, logs in `logs/`. |
| `make dev-backend` / `make dev-frontend` | Start one side only. |
| `make stop` | Kill PIDs in `.pids/`. |
| `make logs` | Tail both logs. |
| `make clean` | Stop processes, remove logs/PIDs, `__pycache__`, `frontend/.next`. |
| `make docker-up` / `make docker-down` | OrbStack/Docker Compose: redis + backend + worker + frontend (`scripts/dev-up.sh`). |
| `make docker-clean` / `make docker-logs` | Tear down with volumes / follow compose logs. |
| `cd backend && PYTHONPATH=. .venv/bin/alembic revision --autogenerate -m "..."` | Generate a new migration. |
| `cd backend && PYTHONPATH=. .venv/bin/alembic upgrade head` | Apply migrations (also `make migrate`). |

### Tests / lint

| Command | Scope |
|---|---|
| `make test` | Backend unit tests (`backend/tests/unit/`). |
| `make test-integration` | Backend integration tests. |
| `make test-all` | Everything under `backend/tests/`. |
| `make test-frontend` | Vitest (`vitest run`). |
| `make lint` | `ruff check app/ tests/`. |
| `make check` | `make lint` + `make test-all` (backend only — no frontend lint/tsc). |

**CI parity** (`.github/workflows/ci.yml`):

```bash
cd backend && .venv/bin/ruff format --check app/ tests/
cd backend && .venv/bin/ruff check app/ tests/
cd backend && .venv/bin/mypy app/ --ignore-missing-imports
cd frontend && npx tsc --noEmit && npx eslint . --max-warnings=0 && npm test
```

CI also runs a **coverage gate of 72%** on the *combined* unit+integration run (matches `fail_under` in `backend/pyproject.toml`). Per-step pytest passes `--cov-fail-under=0` deliberately — the single authoritative gate is the combined `coverage report --fail-under=72` step. Don't add a per-step floor. A retrieval eval gate runs `test_retrieval_eval.py` + `test_reranker.py`.

### Running a single test

```bash
cd backend
.venv/bin/pytest tests/unit/path/to/test_file.py::test_name -v
.venv/bin/pytest -k "substring_match" -v
.venv/bin/pytest -m unit      # or -m integration
```

`asyncio_mode = "auto"` is set globally; no `@pytest.mark.asyncio` needed.

Frontend: `cd frontend && npx vitest run path/to/foo.test.tsx` (watch: `npm run test:watch`).

### Production / rollout

- `make rollout-check` — Heroku health snapshot for M1–M6 code-graph rollout. Reads `HEROKU_APP`, `PROD_BASE_URL`, optional `ADMIN_TOKEN`. Playbook: `docs/ROLLOUT_M1_M6.md`.
- `Procfile`: `web` runs Alembic then uvicorn; `worker` runs `arq app.worker.WorkerSettings`.
- **Deploy targets**: Heroku (primary, auto-deploy via GitHub Actions), Docker Compose (`docker-compose.yml`), DigitalOcean App Platform (`.do/app.yaml`). See `INSTALLATION.md`, `docs/DEPLOYMENT.md`, `scripts/deploy-heroku.sh`.

## High-level architecture

The system is an "intelligence layer between humans and their databases" (see `vision.md`). Treat that vision as load-bearing — invariants in `vision.md` §7 (read-only by default, credentials never exposed, every answer traceable, learning per-connection, graceful degradation, user feedback is highest authority, freshness tracked) are enforced in code.

### Request lifecycle (chat)

```
Frontend (ChatPanel)
  → REST POST /api/chat/ask  |  SSE /api/chat/ask/stream  |  WS /api/chat/ws/{project}/{connection}
    → ConversationalAgent.run() (wraps everything in try/except/finally — emits pipeline_end even on crash)
      → OrchestratorAgent (LLM-driven loop: gather → synthesize)
        → Unified router (single LLM call: route + complexity + approach + estimated queries)
        → AdaptivePlanner (quick or full plan; replan up to MAX_PIPELINE_REPLANS=2)
        → StageExecutor — topological scheduler, runs up to PIPELINE_MAX_PARALLEL_STAGES=3 stages concurrently
          → Per-stage sub-agents: SQLAgent / KnowledgeAgent / VizAgent / GitAgent / McpSourceAgent / InvestigationAgent
          → StageValidator + DataGate (intermediate quality checks; DATA_GATE_HARD_CHECKS_ENABLED blocks impossible numbers)
          → Stage failures classified as transient | configuration | data_missing | fatal (non-retryable short-circuits the retry loop)
        → AnswerValidator (LLM gate on partial answers near budget limit)
      → AgentResultValidator (final check before user)
    → WorkflowTracker emits SSE events throughout; TracePersistenceService accumulates spans and batch-inserts RequestTrace + TraceSpan rows at pipeline_end
```

Key files: `backend/app/agents/orchestrator.py`, `adaptive_planner.py`, `stage_executor.py`, `sql_agent.py`, `knowledge_agent.py`, `viz_agent.py`, `git_agent.py`, `answer_validator.py`, `data_gate.py`, `router.py`. Deep-dive: `docs/SYSTEM_ARCHITECTURE.md`, `ARCHITECTURE.md`.

Multilingual: the agent reasons in English but answers in the user's language. Session rotation auto-summarizes near context limits (`session_rotation_enabled`).

### Knowledge indexing pipeline (M1–M6)

The repo indexer (`backend/app/knowledge/pipeline_runner.py`) is a checkpointed multi-stage pipeline. Each stage is feature-flagged and degrades to the legacy regex + dense-only path when disabled:

| Stage | Flag | Default | What it produces |
|---|---|---|---|
| `project_profile` → … → `embed_and_store` | (always on) | — | Baseline EntityInfo + ChromaDB chunks |
| `ast_parse` → `graph_build` | `code_graph_enabled` | **off** | `code_graph_symbols`, `code_graph_edges` |
| `bm25_build` | `hybrid_retrieval_enabled` | **on** | `data/bm25/{project_id}.pkl` |
| `schema_embed` (per connection) | `schema_retrieval_enabled` | **on** | `data/bm25/schema_{connection_id}.pkl` |
| `graph_db_bridge` | `lineage_enabled` | **off** | Code→DB lineage onto EntityInfo |
| `graph_clustering` | `clustering_enabled`, `cluster_llm_label_enabled` | **off** / on | `code_cluster` rows |

Resume safety: on pipeline resume, `state.code_graph` is rehydrated from Postgres via `CodeGraphService.load_graph()` before M5/M6 stages run — never trust an empty in-memory graph after a restart.

Cleanup: `backend/app/services/indexing_artifacts.py` does best-effort cleanup of on-disk BM25 snapshots and the project's ChromaDB collection on project/connection delete. Postgres FK cascades handle the rest.

**Knowledge freshness**: `KnowledgeFreshnessService` combines DB-index age, code↔DB sync status, and Git HEAD vs indexed SHA into a single warning injected into orchestrator and sub-agent prompts.

### Background worker (ARQ)

When `REDIS_URL` is set, long jobs run in the worker process; otherwise `app/core/task_queue.py` runs them in-process on the API event loop (keep both paths working).

Worker functions (`backend/app/worker.py`):

- `run_db_index` — schema indexing for a connection
- `run_code_db_sync` — code↔DB cross-reference
- `run_repo_index` — Git repo knowledge pipeline
- `run_batch` — batch query execution

Maintenance cron (24 h): learning/insight confidence decay, insight TTL expiry, optional backup (`maintenance_interval_hours`).

### API surface (route modules)

All under `backend/app/api/routes/` — see `API.md` for contracts. Grouped by domain:

| Domain | Routes |
|---|---|
| Core | `auth`, `projects`, `connections`, `ssh_keys`, `repos`, `invites` |
| Chat | `chat`, `chat_sessions`, `chat_utility`, `chat_feedback`, `workflows` |
| Knowledge & rules | `rules`, `notes`, `insights`, `feed`, `semantic_layer`, `data_graph` |
| Data quality | `data_validation`, `data_investigations`, `reconciliation`, `connection_learnings` |
| Ops & admin | `metrics`, `logs`, `health_monitor`, `usage`, `tasks`, `backup` |
| Product | `visualizations`, `dashboards`, `schedules`, `batch`, `notifications`, `billing`, `demo`, `exploration`, `temporal`, `models` |

Admin-only endpoints gated by `ADMIN_EMAILS` in config (backup trigger, cluster metrics, etc.).

### Multi-tenancy & access control

- Browser auth: **httpOnly session cookie + CSRF double-submit** (`auth_cookie_enabled`). No `localStorage` JWT. `Authorization: Bearer` still works for non-browser API clients. Set `AUTH_COOKIE_DOMAIN` (e.g. `.checkmydata.ai`) when SPA and API are on different subdomains — otherwise CSRF cookie is unreadable and login fails.
- All routes except `/api/auth/*` and `/api/health` require authentication.
- `Project` is the workspace boundary. `ProjectMember` carries roles (owner/editor/viewer); every project-scoped route must check membership via `app/api/deps.py`.
- DB credentials are Fernet-encrypted at rest with `MASTER_ENCRYPTION_KEY`; the key is required to even boot.
- SSH: `SSH_HOST_KEY_POLICY` defaults to `tofu` and **fail-closes** to `strict` on unknown values. `SSH_PRE_COMMAND_ALLOWLIST_ENABLED` validates pre-commands against an allowlist. Security-sensitive: `backend/app/connectors/ssh_tunnel.py`, `app/services/ssh_key_service.py`, `app/connectors/ssh_pre_commands.py`.
- MCP server (`backend/app/mcp_server/`) is **off by default** (`MCP_ENABLED`). Two auth modes coexist: (1) per-user `cmd_mcp_…` tokens minted via `/api/auth/mcp-tokens` (recommended; resolved by SHA-256 hash to the issuing user), and (2) a server-level `CHECKMYDATA_API_KEY` bound to `MCP_API_KEY_USER_ID` for single-tenant self-hosted deployments. A revoked/expired per-user token never silently falls through to the server key. MCP resources reuse the tools' principal/ownership checks. Tool names are prefixed `checkmydata_*` to avoid collisions with other MCP servers. See `docs/MCP_SERVER.md` for the integration guide and `.claude/skills/checkmydata-mcp/SKILL.md` for the drop-in agent skill.

### Billing & entitlements

Stripe-backed subscriptions when `billing_enabled=True`: Checkout, Customer Portal, idempotent webhooks (`/api/billing/*`). `EntitlementService` enforces plan-derived token limits and connection/project quotas → HTTP 402 with upgrade hint. Token budget gate (`check_budget`) wired into all chat entry points. Frontend: `/pricing`, `BillingPanel`. When billing is off, routes 404 and `USER_DAILY_TOKEN_LIMIT` / `USER_MONTHLY_TOKEN_LIMIT` apply (`0` = unlimited).

### Custom rules

User rules in `rules/` (or `CUSTOM_RULES_DIR`) are injected into orchestrator and SQL agent prompts with budget-aware truncation. Rule freshness check compares query results against loaded rules and proposes updates on discrepancy. Schema-aware rule validation runs on schema refresh.

### GitAgent (live Git access)

Read-only Git operations on the project's local clone (`git_agent.py`, `GitInspector`): commits, diffs, blame, releases, file churn. Gated by `has_repo` probe; path-traversal guard, output/count caps, no hooks. Freshness warning when clone lags indexed HEAD; optional `git_agent_auto_pull`. Findings persist as `code_finding` insights. Roadmap: `docs/GIT_ACCESS_AUDIT_AND_ROADMAP.md`.

### Data validation, investigations, insights

- **DataGate** — intermediate stage quality (`data_gate.py`); hard checks block impossible percentages/dates when `data_gate_hard_checks_enabled=True`.
- **InvestigationAgent** — "wrong data" deep-dive; auto-triggered on suspicious results when `orchestrator_auto_investigate_enabled=True` (default on).
- **Insight memory** — anomalies persisted with TTL per severity; reconciliation confirms/dismisses on new query results. Injected into orchestrator context.
- **Data enrichment** — IP→country, phone→country, aggregation, `cohort_window` between pipeline steps.

### Agent learning memory

Learnings are stored per-connection by default (`cross_connection_learnings_enabled=False`) — do not promote globals casually; this is a vision invariant. The system learns from every outcome (first-shot success/failure, not only retries). Quality gates in `app/services/agent_learning_service.py` enforce minimum lesson length, subject blocklist, and non-ASCII ratio check. Negative feedback rolls back `exposed_learning_ids`. Confidence decay is faster for never-applied learnings (-0.05 vs -0.02 per 30-day cycle). `times_exposed` ≠ "applied". Migration: `f0a1b2c3d4e5`.

### LLM routing & observability

- `backend/app/llm/router.py` fronts OpenAI, Anthropic, and OpenRouter. All LLM calls go through `llm_call_with_retry` with exponential backoff. `LLMAllProvidersFailedError` is **non-retryable**.
- `MetricsCollector` records per-request route, complexity, response_type, replans, retries, SQL calls, wall-clock, plus M2/M5/M6 code-graph counters. Exposed via `/api/metrics` (JSON) and `/api/metrics/prometheus`.
- Sentry on backend (`sentry-sdk[fastapi]`) and frontend (`@sentry/nextjs`) with PII/secret scrubbing.

### Storage

- App data: SQLite in dev (`backend/data/agent.db`), PostgreSQL in production (`DATABASE_URL`).
- Vectors: ChromaDB (`CHROMA_PERSIST_DIR` or `CHROMA_SERVER_URL` for remote); collections named `project_{project_id}`.
- BM25 snapshots: `backend/data/bm25/{project_id}.pkl` and `schema_{connection_id}.pkl`.
- Redis (`REDIS_URL`): rate limiting, agent concurrency tokens, WS tickets, ARQ task queue. In-memory fallback for dev — keep it working when adding Redis features.
- Backups: `backend/data/backups/` when `backup_enabled=True`.

### Frontend architecture

- Routes: `/` (marketing), `/pricing`, `/login`, `/app` (gated SPA), `/dashboard/[id]` (shared viewer), `/about`, `/contact`, `/support`, `/terms`, `/privacy`.
- State: Zustand stores in `frontend/src/stores/` — `app-store`, `auth-store`, `notes-store`, `toast-store`, `task-store`, `log-store`, `reasoning-store`.
- Chat: per-session message caching, in-flight stream abort on session switch; backend continues processing if user navigates away; frontend polls in-progress sessions via `status` field.
- Agent Reasoning Panel: SSE-collected trace persisted in `reasoning-store` (plan, steps, rules/learnings applied).
- Motion: GSAP + ScrollTrigger + Lenis (marketing); Framer Motion (product UI). Tokens in `frontend/src/lib/motion/tokens.ts`. **Degrades under `prefers-reduced-motion`** via app-wide `MotionConfig` — don't bypass.
- Charts: chart.js via react-chartjs-2; compound queries can produce multiple charts per answer.

## Feature flags

Most behavior ships behind flags in `backend/app/config.py`. Gate regressions the same way.

**Code intelligence (note defaults):**

| Flag | Default | Notes |
|---|---|---|
| `hybrid_retrieval_enabled` | on | Falls back to dense-only without BM25 snapshot |
| `schema_retrieval_enabled` | on | Unioned with legacy relevance safety net |
| `code_graph_enabled` | off | CPU-heavy indexing |
| `lineage_enabled` | off | Requires code graph |
| `clustering_enabled` | off | Louvain communities |
| `cluster_llm_label_enabled` | on | Only matters when clustering on |
| `reranker_enabled` | off | Cross-encoder; needs `sentence-transformers` |

**Agent / quality:**

`answer_validator_enabled`, `answer_validator_fail_closed`, `learning_analyzer_mode` (`heuristic | hybrid | llm_first`, default `llm_first`), `query_empty_result_retry`, `orchestrator_result_gate_enabled`, `orchestrator_auto_investigate_enabled`, `data_gate_hard_checks_enabled`, `data_gate_llm_semantics`, `cross_connection_learnings_enabled`, `context_planner_enabled`, `context_planner_mode`, `generate_docs_max_failure_ratio`, `db_index_incremental_enabled`.

**Ingestion automation (all off by default):**

`git_webhook_enabled`, `git_poll_enabled`, `auto_sync_after_index`, `freshness_reconciler_enabled`, `schema_change_alerts_enabled`.

**Platform / security:**

`billing_enabled`, `mcp_enabled`, `security_csp_enabled` / `security_csp`, `security_hsts_enabled`, `session_rotation_enabled`, `backup_enabled`, `sentry_dsn` (off unless set).

## Conventions

### Backend (Python)

- **`ruff`** pinned to exact version (currently `0.15.15`) in `pyproject.toml`, same for `mypy`. Don't widen to ranges — CI reproducibility depends on the pin.
- Line length 100. Rules: `E F I N W UP`. Alembic autogenerated migrations have a per-file ignore — don't manually reformat them.
- Async everywhere — SQLAlchemy 2.0 async + `asyncpg`/`aiosqlite`. No sync I/O on the request path.
- New env vars → `backend/app/config.py` with docstring + `backend/.env.example`.

### Frontend (TypeScript)

- Semantic design tokens from `@theme` in `frontend/src/app/globals.css` (`bg-surface-*`, `text-text-*`, etc.). **Never raw Tailwind palette classes** — see `DESIGN_SYSTEM.md`.
- Typography: DM Sans (`font-sans`) for UI; JetBrains Mono (`font-mono`) for code/SQL/data.
- Icons: `components/ui/Icon.tsx` `PATHS` record only — no external icon packages.
- Accessibility: icon buttons need `aria-label` + `<Tooltip>`; inputs need `aria-label`/`aria-required`/`aria-invalid`; modals need `role="dialog"`, `aria-modal`, focus trap, Escape-to-close.
- Single breakpoint: `max-width: 767px`. Touch targets ≥44px (`.compact-touch` for 36px in dense areas).

### Git / PR

Conventional commits: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `perf`, `security`. Branches: `feat/`, `fix/`, `refactor/`, `docs/`, `test/`, `chore/`. CI must be green; coverage must not drop below 72%. See `CONTRIBUTING.md`.

### New features

Read `vision.md` before any new feature. If a request conflicts with §7 invariants or §8 anti-vision, stop and resolve the misalignment with the user before implementing.

## Where to look first

| Topic | Document |
|---|---|
| Product intent / invariants | `vision.md` |
| Setup & env vars | `INSTALLATION.md`, `backend/.env.example` |
| User guide | `USAGE.md` |
| API contracts | `API.md`, `backend/app/api/routes/` |
| Architecture overview | `ARCHITECTURE.md` |
| Orchestrator deep-dive | `docs/SYSTEM_ARCHITECTURE.md` |
| UI / motion | `DESIGN_SYSTEM.md` |
| Active priorities | `BACKLOG.md`, `ROADMAP.md` |
| Release history | `CHANGELOG.md` |
| Code-graph rollout | `docs/ROLLOUT_M1_M6.md` |
| Knowledge layer | `docs/KNOWLEDGE_CATALOG.md` |
| Live Git roadmap | `docs/GIT_ACCESS_AUDIT_AND_ROADMAP.md` |
| Deployment | `docs/DEPLOYMENT.md`, `INSTALLATION.md#production-deployment` |
| Audit remediation | `docs/AUDIT_REMEDIATION_PLAN_2026-06.md` |
| QA / test plan | `docs/MASTER_TEST_PLAN.md` |
| Contributing | `CONTRIBUTING.md` |
| Security | `SECURITY.md` |
| FAQ / troubleshooting | `FAQ.md` |
| Production planning | `docs/production-plan/` (PRD, tech spec, modules, QA, traceability) |
