# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Product snapshot

- **What it is**: AI-powered database query agent — natural language → SQL, codebase Q&A, visualizations, team workspaces.
- **Supported databases**: PostgreSQL, MySQL, ClickHouse, MongoDB (via `backend/app/connectors/`), plus **SQLite** — file-backed, added 2026-08-20 because the demo path has created `db_type="sqlite"` connections since it existed while `ADAPTER_REGISTRY` had no entry for it, so every demo connection raised `Unsupported adapter: sqlite` on the first question. Not offered in the connection UI; it is what the demo runs on (`app/services/demo_data.py`).
- **Supported analytics sources**: `Connection.source_type` also accepts three analytics vendors (`backend/app/analytics/`, family defined once in `app/analytics/source_types.py`): **`ga4`** (Google Analytics 4 — the only one with a collector today), plus **`appstore`** and **`googleplay`**, reserved for m1/m2 (connection creation refuses them with 422 until their fact tables land). Runbook: `docs/ANALYTICS_SOURCES.md`.
- **LLM providers**: OpenAI, Anthropic, OpenRouter (`backend/app/llm/router.py`).
- **Task tracking**: [Linear — CheckMyData.ai](https://linear.app/sshlg/project/checkmydataai-b7670b0dd990).
- **Tests**: **7,009 total** — 6,326 backend collected + 683 frontend Vitest across 93 files (measured 2026-08-20: `pytest tests/ --collect-only -q`, `npx vitest run`; the full backend run is `6322 passed, 4 skipped, 1 xfailed`). Backend coverage **78%** (39,830 statements, 8,625 missed — `pytest tests/ --cov=app`, 2026-08-19); the CI gate `fail_under` is **72%**.
- **Recent work**: current release **`[1.16.0]`** — GA4 as a first-class data source (vendor-credential store, scheduled collection behind an import journal, `AnalyticsAgent` with honesty gates, charting) plus the `vision.md` §8 carve-out recorded in `docs/adr/0001-external-report-cache.md`. `[1.15.1]` (see `CHANGELOG.md`). `[1.15.0]` cut the intelligence-remediation program (W0–W6): data-quality honesty (truncation/partial-data caveats, DataGate on both paths), hybrid retrieval + ContextPack (provenance + reranker), orchestrator live step-budget termination + single-loop/pipeline path unification, DB schema-capture depth across all four connectors, code↔DB trust signals (exact git-freshness states), code-graph correctness, and self-completing embedding reconcile — plus the June orchestrator-audit remediation (DataGate semantic gate, cross-tenant SSE/WS leak fix, `/api/chat/ask` concurrency cap, MCP call timeout). `[1.15.1]` is embedding-loader log hygiene + infra guidance. Benchmark-gated default-on flags: `code_graph_enabled`, `lineage_enabled`, `context_planner_enabled` — **not** `reranker_enabled`, which is `False` in `config.py:602` and has been since the 2026-08-10 correction; that correction reached the flags table and the deploy notes below but not this line, which is AUD-0819-17. Prior hardening (billing, cookie auth, MCP/SSH, Redis limits, Sentry) shipped in `[1.14.0]`.

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

### ⚠️ Deploy notes (intelligence remediation release)

Two operator actions are required when deploying the intelligence-remediation branch to production:

**1. ChromaDB reindex — AUTOMATIC (self-completing deploy)**
Embedding-config changes (`CHROMA_EMBEDDING_MODEL` / `EMBEDDER_MAX_TOKENS`) are reconciled automatically at startup: `app/ops/embedding_reconcile.reconcile_embeddings` runs in the FastAPI `lifespan`, compares the current fingerprint against the `deploy_state.embedding_fingerprint` marker, and enqueues a one-shot full reindex of all projects when it changed — idempotent, multi-dyno-safe (Postgres advisory lock), degrades gracefully, never blocks boot. Migration `d5e6f7a8b9c0` seeds the OLD fingerprint on databases that already have projects so the first deploy of this feature reindexes the existing backlog once. **No manual step required.** Manual override (rarely needed): `from app.services.embedding_reindex import queue_embedding_reindex`, or the "Re-index repository" UI action per project.

**2. `code_graph_enabled` + `lineage_enabled` now default-on — ensure ≥2 worker cores**
Both flags flip to `True` in this release. Code-graph indexing is CPU-intensive. To defer: set env `CODE_GRAPH_ENABLED=false` and `LINEAGE_ENABLED=false`.

**0. Worker memory — `EMBEDDING_UPSERT_BATCH_SIZE` defaults to 8, and that is the fix**
Before 2026-08-19 the production worker was SIGKILLed at `code_symbol_embed` (R15,
1053 MiB against a 512 MiB quota) and **no repo-index run reached `pipeline_end`** —
`grep -c pipeline_end` over a two-hour log window returned 0. ChromaDB's bundled ONNX
MiniLM pads every document to 256 tokens, so the batch handed to one `upsert` sizes the
transformer's activations and nothing else. Measured through `VectorStore.add_documents`
over 960 chunks: **batch 200 → 967 MiB peak / 9.3 s; batch 8 → 415 MiB peak / 10.9 s.**
The default trades ~17% wall clock for ~552 MiB. Raise it only on a dyno with headroom.

**0b. The symbol-UID schema bump reindexes itself — no operator step**
`SYMBOL_UID_SCHEMA` (`app/knowledge/ast_parser.py`) is part of
`embedding_fingerprint()`, so the 2026-08-19 UID change (methods now carry their
enclosing scope) makes `reconcile_embeddings` enqueue one `force_full` reindex per
project at startup — advisory-locked, idempotent, non-blocking. Required because
`save_incremental` merges by FILE, not by UID: symbols in unchanged files keep the old
form and cross-file edges to them are pruned until a clean rebuild. Expect one slower
first boot after deploy, and confirm it by looking for a `pipeline_end` that now
arrives.

**3. `reranker_enabled` is default-OFF — and so is the 768-d embedder**
`sentence-transformers` is not in the production image and never was; it now lives in the optional `ml` extra. Consequences while it is absent: the reranker is a no-op, and `CHROMA_EMBEDDING_MODEL=BAAI/bge-base-en-v1.5` (768-d) is silently ignored — Chroma embeds at 384-d with `all-MiniLM-L6-v2`. Turning the extra on requires more dyno memory (the worker already runs over quota) **and a full re-index**, because 384-d and 768-d vectors are not comparable.

## High-level architecture

The system is an "intelligence layer between humans and their databases" (see `vision.md`). Treat that vision as load-bearing — invariants in `vision.md` §7 (read-only by default, credentials never exposed, every answer traceable, learning per-connection, graceful degradation, user feedback is highest authority, freshness tracked) are enforced in code.

### Request lifecycle (chat)

```
Frontend (ChatPanel)
  → REST POST /api/chat/ask  |  SSE /api/chat/ask/stream  |  WS /api/chat/ws/{project}/{connection}
    → ConversationalAgent.run() (wraps everything in try/except/finally — emits pipeline_end even on crash)
      → OrchestratorAgent (LLM-driven loop: gather → synthesize)
        → Unified router (single LLM call: route + complexity + approach + estimated queries)
        → Two execution paths — selected by route_result.use_complex_pipeline (complexity=complex OR
          needs_multiple_data_sources OR estimated_queries≥3):
          PATH A — single tool-loop: iterative gather/synthesize, up to max_orchestrator_iterations (default 20)
            → ORCH-T01: step budget is a live termination signal (wrap-up entered when counter hit)
            → ORCH-T02: wrap-up only when ≥1 data retrieval attempted
            → ORCH-T03: re-prompts once on no-tool/no-data turn to keep loop alive
          PATH B — multi-stage pipeline (ORCH-R01: now taken for complex non-DB questions too):
            → AdaptivePlanner (quick or full plan; replan up to MAX_PIPELINE_REPLANS=2)
            → **One wall-clock deadline per request, established once and shared** (F-SQL-03, 2026-08-21): `_new_pipeline_deadline()` in `orchestrator.py` is passed to every `StageExecutor.execute()` and into `_run_pipeline_replans`, which refuses to start another plan once it is spent. `execute()` only computes its own when handed none, so a standalone caller (eval harness, tests) still gets a budget. Before this, `execute()` computed `monotonic() + budget` on **every entry** and the replan loop re-enters it per replan — so Path B's worst case was `(1 + max_pipeline_replans) x pipeline_max_wall_seconds`, i.e. **540 s against a documented 180 s limit** (`pipeline_max_wall_seconds` defaults to 0 → falls back to `agent_wall_clock_timeout_seconds`=180). ORCH-V02 had bounded the retries *inside* one plan and left the plan count multiplying that bound.
            → StageExecutor — topological scheduler, runs up to PIPELINE_MAX_PARALLEL_STAGES=3 stages concurrently
              → Per-stage sub-agents: SQLAgent / KnowledgeAgent / VizAgent / GitAgent / McpSourceAgent / InvestigationAgent
              → StageValidator + DataGate (intermediate quality checks; DATA_GATE_HARD_CHECKS_ENABLED blocks impossible numbers)
              → Stage failures classified as transient | configuration | data_missing | fatal (non-retryable short-circuits retry)
        → Shared gates (both paths — ORCH-A01/A02):
            → ResultValidation (DataGate + result gate + reconcile) on every SQL result
            → AnswerQualityGate on final answer
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
| `ast_parse` → `graph_build` | `code_graph_enabled` | **on** | `code_graph_symbols`, `code_graph_edges` |
| `bm25_build` | `hybrid_retrieval_enabled` | **on** | `data/bm25/{project_id}.pkl` |
| `schema_embed` (per connection) | `schema_retrieval_enabled` | **on** | `data/bm25/schema_{connection_id}.pkl` |
| `graph_db_bridge` | `lineage_enabled` | **on** | Code→DB lineage onto EntityInfo |
| `graph_clustering` | `clustering_enabled`, `cluster_llm_label_enabled` | **off** / on | `code_cluster` rows |

Resume safety: on pipeline resume, `state.code_graph` is rehydrated from Postgres via `CodeGraphService.load_graph()` before M5/M6 stages run — never trust an empty in-memory graph after a restart.

Cleanup: `backend/app/services/indexing_artifacts.py` does best-effort cleanup of on-disk BM25 snapshots and the project's ChromaDB collection on project/connection delete. Postgres FK cascades handle the rest.

**Knowledge freshness**: `KnowledgeFreshnessService` combines DB-index age, code↔DB sync status, and Git HEAD vs indexed SHA into a single warning injected into orchestrator and sub-agent prompts.

### Analytics source pipeline (GA4)

A second, non-SQL ingestion path for external report APIs. `vision.md` §8 carries an explicit carve-out for it (cache-with-provenance, **not** a warehouse) — rationale, alternatives and retention in `docs/adr/0001-external-report-cache.md`. Operator runbook: `docs/ANALYTICS_SOURCES.md`.

```
adapter → journal → fact tables → AnalyticsAgent
```

| Stage | Where | What it does |
|---|---|---|
| **Adapter** | `app/analytics/ga4/adapter.py` (`GA4Adapter`), reports in `ga4/reports.py`, knobs vs secret split in `ga4/config.py` | Pages GA4's Data API on `offset` (Δ1 — a single un-paginated call silently truncates at 10 000 rows), requests `keep_empty_rows` so a dead day is a zero and not a gap (Δ2), and reads `PropertyQuota` (Δ3). Maps vendor failures onto the taxonomy in `app/analytics/errors.py`: 401→auth, 403→permission, 404→empty, 429/5xx→transient, spent bucket→quota. **Only transient/quota are retried** (`app/analytics/http.py::retry_async`, honours `Retry-After`, bounded at 60 s) — retrying an auth/permission error burns quota and can never succeed. |
| **Journal** | `app/analytics/journal.py`, table `analytics_imports`, UNIQUE `(connection_id, report, period)` | One verdict per period: `ok` \| `empty` \| `failed`. Pending is **`expected − done`**, never `max(period)` — a hole below the high-water mark must refill, so a `failed` period stays owed while an `empty` one is complete. The most recent `analytics_refetch_tail_periods` are always re-fetched (vendors revise). `prune()` runs in the 24 h maintenance cron. |
| **Fact tables** | `app/models/analytics_ga4.py`; `ga4_overview_daily`, `ga4_geo_daily`, `ga4_platform_daily`, `ga4_trend_daily`, `ga4_event_daily` | Natural-keyed on `(connection_id, property_id, date, …dimensions)` with `ON CONFLICT DO UPDATE`, so re-collecting a period overwrites rather than duplicates. Counts are `BigInteger`, revenue is `Numeric(18,4)` — never float. **Raw vendor payloads are never persisted.** |
| **Collection** | `app/services/analytics_collect_service.py` | Per-period isolation: one failing period never aborts the run but is always journalled; an auth/permission error stops that report. Exit contract `ok` \| `partial` \| `failed` — errors with rows written is `partial`, errors with none is `failed`, and **no errors with zero rows is `ok`** (nothing was due). A run that dies before any report is journalled under the reserved report name `_connect`. |
| **Agent** | `app/agents/analytics_agent.py`, tool `query_analytics_source` (`app/agents/tools/analytics_tools.py`) | Reads the **local fact tables**, never the vendor and **never free-form SQL** — three parameterised tools (`list_reports`, `query_report`, `coverage`). Gates in spec order: DataGate hard checks → truncation/partial caveat → freshness → `AnswerQualityGate`. Budget exhaustion returns `no_result`, and an answer with no tool call behind it is refused outright rather than published. Results chart through `VizAgent` like any tabular result. |

Gating: `ContextLoader.has_analytics_sources(project_id)` decides whether `query_analytics_source` is exposed, mirroring `has_mcp_sources`. `AnalyticsPipeline` (`app/pipelines/analytics_pipeline.py`) is registered in `PIPELINE_REGISTRY` for all three vendor keys. `is_queryable_database()` in `connection_service.py` — not "has a config" — is the predicate for "is there a database to query"; an analytics connection must never advertise `query_database`.

### Background worker (ARQ)

When `REDIS_URL` is set, long jobs run in the worker process; otherwise `app/core/task_queue.py` runs them in-process on the API event loop (keep both paths working).

Worker functions (`backend/app/worker.py`):

- `run_db_index` — schema indexing for a connection
- `run_code_db_sync` — code↔DB cross-reference
- `run_repo_index` — Git repo knowledge pipeline
- `run_batch` — batch query execution
- `run_analytics_collect` — collect one analytics connection's reports into its fact tables (per-function timeout `analytics_collect_job_timeout_seconds`)

Hourly cron loops in `app/main.py`, same shape and both multi-dyno-safe (hour-scoped `redis_lock` + day-scoped `task_id`): `_daily_knowledge_sync_cron_loop` (repo index → DB index → code↔DB sync, gated on `daily_knowledge_sync_enabled`) and `_analytics_collect_cron_loop` (analytics collection wave, gated on `analytics_collect_enabled`). Both read their flag **once at start-up** — flipping it needs a restart. They share `daily_knowledge_sync_timezone` so both agree what "3 a.m." means.

Maintenance cron (24 h): learning/insight confidence decay, insight TTL expiry, analytics journal prune, optional backup (`maintenance_interval_hours`).

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
- **Email verification (F-PROJ-01):** email/password registrations start `email_verified=False` and do **not** auto-accept email-based invites until the address is verified via `POST /api/auth/verify-email`; Google logins are pre-verified. Sensitive auth actions persist to a durable `audit_logs` table (F-AUTH-15) in addition to the `audit` logger line.
- **Tenant isolation (R3):** resource mutations are project-scoped — never a bare resource id. Global rules / SSH keys / SSH tunnels are owner-scoped (admin gate for global rules; tunnel cache key carries a credential discriminator; SSH-key lookups are owner-strict; cross-connection learning promotion stays within the project owner).
- `Project` is the workspace boundary. `ProjectMember` carries roles (owner/editor/viewer); every project-scoped route must check membership via `app/api/deps.py`.
- DB credentials are Fernet-encrypted at rest with `MASTER_ENCRYPTION_KEY`; the key is required to even boot. **Rotatable since 2026-08-21 (F-CONN-05):** `MASTER_ENCRYPTION_KEYS_OLD` holds retired keys for reading only, new ciphertext always uses the primary, and `app/ops/encryption_reconcile.py` re-encrypts all seven encrypted columns at boot when the primary's fingerprint changes — advisory-locked, idempotent, marker advanced only on a clean sweep. `pending_rotation_count` says whether the old key can be dropped. Runbook: `SECURITY.md` → *Rotating the encryption key*.
- **Read-only enforcement (vision §7 #1) is layered, not just a regex.** When a connection is `is_read_only`, each connector opens a DB-enforced read-only session — Postgres `server_settings={"default_transaction_read_only":"on"}`, MySQL `init_command="SET SESSION TRANSACTION READ ONLY"` (autocommit stays on), ClickHouse `settings={"readonly":1}`, MongoDB rejects write ops + `$out`/`$merge` + server-side JS (`$where`/`$function`/`$accumulator`). On top, `core/safety.py` `SafetyGuard` applies a **statement-initial allow-list** in read-only mode (query must start with SELECT/WITH/SHOW/EXPLAIN/DESCRIBE/DESC/TABLE/VALUES/EXISTS and be single-statement) plus the DDL/DML denylist. Every raw-SQL entry point routes through `SafetyGuard` (agent ValidationLoop, batch `/execute`, note exec, MCP). For full assurance also use a read-only DB user (and Mongo `--noscripting`).
- SSH: `SSH_HOST_KEY_POLICY` defaults to `tofu` and **fail-closes** to `strict` on unknown values. `SSH_PRE_COMMAND_ALLOWLIST_ENABLED` validates pre-commands against an allowlist. Security-sensitive: `backend/app/connectors/ssh_tunnel.py`, `app/services/ssh_key_service.py`, `app/connectors/ssh_pre_commands.py`.
- MCP server (`backend/app/mcp_server/`) is **off by default** (`MCP_ENABLED`). Two auth modes coexist: (1) per-user `cmd_mcp_…` tokens minted via `/api/auth/mcp-tokens` (recommended; resolved by SHA-256 hash to the issuing user), and (2) a server-level `CHECKMYDATA_API_KEY` bound to `MCP_API_KEY_USER_ID` for single-tenant self-hosted deployments. A revoked/expired per-user token never silently falls through to the server key. For **remote multi-tenant** use the server can be ASGI-mounted into the API at `/mcp` (`MCP_MOUNT_ENABLED`, default off — requires `MCP_ENABLED` too), where a pure-ASGI middleware resolves the bearer token **per request** to a principal carried in a `ContextVar` (many users, one endpoint, each scoped to their own projects; the standalone `--transport streamable-http` mode is single-principal/env-bound). The mounted transport is stateless; `MCP_ALLOWED_HOSTS` opt-in enables DNS-rebinding Host validation. MCP agent tools also run the shared token-budget gate (`UsageService.check_token_budget`) and acquire `agent_limiter` concurrency slots. MCP resources reuse the tools' principal/ownership checks. Tool names are prefixed `checkmydata_*` to avoid collisions with other MCP servers. See `docs/MCP_SERVER.md` for the integration guide and `.claude/skills/checkmydata-mcp/SKILL.md` for the drop-in agent skill.

### Billing & entitlements

Stripe-backed subscriptions when `billing_enabled=True`: Checkout, Customer Portal, idempotent webhooks (`/api/billing/*`). `EntitlementService` enforces plan-derived token limits and connection/project quotas → HTTP 402 with upgrade hint. Token budget gate (`check_budget`) wired into all chat entry points. Frontend: `/pricing`, `BillingPanel`. When billing is off, routes 404 and `USER_DAILY_TOKEN_LIMIT` / `USER_MONTHLY_TOKEN_LIMIT` apply (`0` = unlimited).

### Custom rules

User rules in `rules/` (or `CUSTOM_RULES_DIR`) are injected into orchestrator and SQL agent prompts with budget-aware truncation — the budget lives in `rules_to_context` (`RULES_CONTEXT_MAX_CHARS`, default 3000), **not** at the call sites. Corrected 2026-08-21: this sentence was true at two of five callers and false at three, and the two that capped sliced the joined string. Whole rules are dropped now, never half of one, and the notice says how many were omitted so an answer can admit it may not reflect them. Rule freshness check compares query results against loaded rules and proposes updates on discrepancy. Schema-aware rule validation runs on schema refresh.

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
- **Usage accounting & post-call budget gate** (`app/llm/usage_sink.py`): `LLMRouter(usage_sink=…)` observes `(prompt_tokens, completion_tokens, total_tokens, provider, model)` after every successful call; `DbUsageSink` persists each call via `UsageService.record_usage` **and** re-checks the user's budget so a long agent run hard-stops at the next safe boundary instead of overshooting. `AdaptivePlanner`, `AnswerValidator`, and `QueryRepairer` carry the sink so their LLM calls are counted too. **MCP tools** build the router with `DbUsageSink` and acquire `agent_limiter` for parity with the chat path (no usage/budget bypass via MCP). Streaming responses are not yet sinked (tracked as a known gap).
- `MetricsCollector` records per-request route, complexity (no longer `"unknown"` — ORCH-A03), response_type, replans, retries, SQL calls, wall-clock, plus M2/M5/M6 code-graph counters. Exposed via `/api/metrics` (JSON) and `/api/metrics/prometheus`.
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
| `sql_agent_safety_net_min_relevance` | 3 | RET-R10: min `relevance_score` for safety-net tables; raise to 4 for tighter filtering, 2 to restore legacy behaviour |
| `code_graph_enabled` | **on** | CPU-heavy indexing; gated on `python -m app.eval.graph_benchmark` (W6) |
| `lineage_enabled` | **on** | Requires code graph; enabled together with `code_graph_enabled` (W6) |
| `clustering_enabled` | off | Louvain communities |
| `cluster_llm_label_enabled` | on | Only matters when clustering on |
| `reranker_enabled` | **off** | Cross-encoder. **Corrected 2026-08-10**: this was documented as default-on while `sentence-transformers` was in no dependency list, so it was a no-op in every deployment that ever ran. Install the optional extra (`pip install -e '.[ml]'`) to enable it for real |
| `context_planner_enabled` | **on** | Query-aware ContextPack lazy loading; mode `heuristic` (zero-cost) or `llm` (default ON as of W2) |

**Agent / quality:**

`answer_validator_enabled`, `answer_validator_fail_closed`, `learning_analyzer_mode` (`heuristic | hybrid | llm_first`, default `llm_first`), `query_empty_result_retry`, `orchestrator_result_gate_enabled`, `orchestrator_auto_investigate_enabled`, `data_gate_hard_checks_enabled`, `data_gate_llm_semantics`, `cross_connection_learnings_enabled`, `context_planner_mode`, `generate_docs_max_failure_ratio`, `db_index_incremental_enabled`.

**SQL tool-loop bounds** (added 2026-08-08 — the loop was previously bounded by `max_sql_iterations` alone, and the orchestrator's `agent_wall_clock_timeout_seconds` cannot interrupt it because the whole SQL agent runs inside one orchestrator iteration):

| Flag | Default | Env | Notes |
|---|---|---|---|
| `sql_timeout_breaker_threshold` | 2 | `SQL_TIMEOUT_BREAKER_THRESHOLD` | Consecutive timeout-terminated `execute_query` calls on one connection, within one request, before the loop stops. Any successful query resets it. **Non-positive raises at boot** — `0` would read as configured and behave as absent |
| `sql_agent_deadline_enabled` | on | `SQL_AGENT_DEADLINE_ENABLED` | Honour the request's remaining wall clock inside the SQL tool loop |

A timeout also gets **exactly one** LLM repair, prompted to narrow scope rather than rewrite logic (`_MAX_TIMEOUT_REPAIRS` in `app/core/validation_loop.py`); the second one ends the loop as `transient`. `TIMEOUT` is deliberately **not** in `_TRANSIENT_RETRY_ERRORS` — that path re-runs the same query after a sub-second backoff, which against a 30 s timeout buys another 30 s.

`max_orchestrator_iterations` default is **20** (was 100 before W0 intelligence-remediation; set higher only if complex multi-hop queries time out at the wall-clock limit).

**Intelligence remediation W0 landmarks** (spec: `docs/superpowers/specs/2026-07-03-intelligence-remediation-design.md`): `derive_result` helper + `ResultValidation` façade + `AnswerQualityGate`; `DataGate` Decimal/truncation fixes; C-D schema-capture surface (`object_kind`, `sample_values`, `distinct_count`, `null_pct`) on `ColumnInfo`/`TableInfo`/`SchemaInfo` + `DbIndex` migration; `RequestTrace` routing column `complexity` + migration (**correction 2026-08-08**: `approach` and `route_ms` were named here but never existed — `grep -rln "approach" backend/alembic/versions/` is empty and `app/models/request_trace.py:54-56` has only `route`, `complexity`, `estimated_queries`); chunk metadata + `retrieval_degraded` scaffold; hotspot decomposition of `sql_agent`/`orchestrator` (`result_handler`, `_record_request_metrics`). New Prometheus counters: `retrieval_degraded_total`, `datagate_block_total`, `filter_guard_degrade_total`. **`retrieval_degraded_total` was uninterpretable until 2026-08-21 (F-KNOW-07):** it labelled every empty leg `reason="empty_result"`, including a working BM25 index whose query simply had no lexical overlap — so it fired on the normal path and a non-zero value proved nothing. It now carries the real cause (`no_snapshot`, `corrupt`, `schema_mismatch`, `score_error`, `timeout`, `error`) and is **not** incremented for `no_match` / `no_query_tokens`. `retrieval_degraded_total{leg="bm25",reason="no_snapshot"}` is the one to watch, and it should now be ~zero: **F-KNOW-12 is closed** (2026-08-21). BM25 snapshots still live on each dyno's ephemeral disk — that part was never the fixable half. The real defect was that `web` and `worker` are separate Heroku process types with separate filesystems, so the repo index wrote the `.pkl` on the worker and the chat path read for it on the web dyno; the leg had no snapshot **at all**, not merely after a restart. Snapshots are derived from `KnowledgeDoc` rows, so `app/ops/bm25_local_reconcile.py` rebuilds any missing one at start-up in **both** processes — no shared storage, no advisory lock (each disk needs its own copy), and missing-only: staleness needs a clone and stays with the pipeline.

**Intelligence remediation W3 landmarks** (orchestrator termination + path unification, ORCH-T01–T03/A01–A03/R01/P01–P04/PR01/CP01/RP01–RP02): live step-budget termination; wrap-up gate; no-tool re-prompt (T03); routing metrics always populated; prompt de-dup (~200 tokens/req saved); ContextPlanner word-boundary cue matching; StageValidator scoped to data stages; trivial-plan bounce + degraded propagation; cohort_window param unification; complex non-DB questions routed to pipeline (ORCH-R01); `ResultValidation` wired into pipeline SQL stage (A01); `AnswerQualityGate` wired into pipeline final answer (A02). Pipeline answers may now return `response_type: "step_limit_reached"` when budget exhausted.

**Intelligence remediation W4 landmarks** (schema-capture depth, DBIDX-D1–D18): MongoDB native introspection via aggregation pipelines (`distinct_values`/`approx_stats` overrides); ClickHouse sort-key (`is_sort_key`); PostgreSQL enum labels + CHECK constraints; VIEWs/MATERIALIZED VIEWs indexed with `object_kind`; column comments + indexes rendered in schema context (D8); approx_stats persisted to `DbIndex.column_stats_json` + `column_distinct_values_json` (D9); deterministic completeness gate (D10); schema-cache bust on re-index (D12); dead `SchemaIndexer` deleted (D13); `reltuples < 0` treated as unknown (D14); LLM table/column prompt caps (D15/D16); ClickHouse + Mongo freshness timestamps (D17/D18). New config keys: `mongo_schema_sample_size` (100), `db_index_stats_enabled` (on), `db_index_stats_max_columns` (20), `db_index_stats_sample_cap` (100 000), `db_index_max_tables_analyzed` (500), `db_index_max_prompt_columns` (100). **R9/D7 handoff**: `ColumnInfo.distinct_values/distinct_count/numeric_format/enum_labels` are populated and persisted; downstream waves read from the index.

**Intelligence remediation W5 landmarks** (code↔DB trust signals, SYNC-L2/L3/L5/L6/L7/L8/L9 + low-batch L11–L14): `classify_freshness()` in `git_tracker.py` uses `iter_commits` for exact AHEAD/BEHIND/DIVERGED states (L3); `KnowledgeFreshnessService` maps each state to a distinct warning + severity (DIVERGED=critical); `EntityExtractor` attributes SQL column refs per-statement with noise-token stripping (L2); `_compute_column_drift()` produces deterministic sorted set-diff overriding LLM `sync_status` when both sides are known (L5); migration `c9b8a7f6e5d4` adds `CodeDbSync.column_mismatch_json`; sync loaders match on `(schema,table)` pair for schema-qualified ORM models (L6); bare-suffix keying normalised across all loaders (L7); empty-graph warning gated on `lineage_enabled OR clustering_enabled` (L8); op-kind uses word-boundary regex (L9); `_coerce_confidence` rounds floats before clamping (L11); `CallerRef.depth_estimated` sentinel replaces fabricated depth (L12); enum-table link uses word-boundary token matching (L13); DB-index TTL reads from `settings.db_index_ttl_hours` (L14). New config keys: `git_freshness_fetch_origin` (off — gates remote fetch for cross-machine accuracy; env `GIT_FRESHNESS_FETCH_ORIGIN`), `db_index_ttl_hours` (24; env `DB_INDEX_TTL_HOURS`).

**Ingestion automation (all off by default):**

`git_webhook_enabled`, `git_poll_enabled`, `auto_sync_after_index`, `freshness_reconciler_enabled`, `schema_change_alerts_enabled`.

**Analytics sources** (`docs/ANALYTICS_SOURCES.md`; all six read from `backend/app/config.py`, all validated at boot — a non-positive value raises rather than silently idling the collector):

| Setting | Default | Env | Notes |
|---|---|---|---|
| `analytics_collect_enabled` | **off** | `ANALYTICS_COLLECT_ENABLED` | Master switch for the hourly wave. Off per the ingestion-automation house rule — it calls third-party APIs on a schedule. Read once at start-up. |
| `analytics_backfill_days` | 30 | `ANALYTICS_BACKFILL_DAYS` | Window width in periods of the report's grain, always ending **yesterday** (today is partial at the vendor). Overridden per connection by `source_config.backfill_days`. |
| `analytics_refetch_tail_periods` | 2 | `ANALYTICS_REFETCH_TAIL_PERIODS` | Recent periods refetched even when already collected — GA4 settles within ~48 h. `0` disables the tail. |
| `analytics_collect_job_timeout_seconds` | 1800 | `ANALYTICS_COLLECT_JOB_TIMEOUT_SECONDS` | Registered on the ARQ function (arq has no per-enqueue timeout) and passed to the in-process fallback. |
| `analytics_http_attempts` | 3 | `ANALYTICS_HTTP_ATTEMPTS` | Attempts per vendor call. Transient/quota only — auth/permission are never retried. |
| `analytics_journal_retention_days` | 400 | `ANALYTICS_JOURNAL_RETENTION_DAYS` | Journal prune horizon (24 h maintenance cron). Fact rows are **kept**; only the journal is pruned. |

Per-connection, **not** a global flag: `collection_enabled` (default **on**) and `collection_hour` (default **3**, local to `daily_knowledge_sync_timezone`). `collection_enabled` pauses only the *schedule* — `POST /api/connections/{id}/collect` deliberately ignores it, since pulling on demand is how a credential fix is verified.

**Platform / security:**

`billing_enabled`, `mcp_enabled`, `mcp_mount_enabled` (HTTP mount, requires `mcp_enabled`), `security_csp_enabled` / `security_csp`, `security_hsts_enabled`, `session_rotation_enabled`, `backup_enabled`, `sentry_dsn` (off unless set).

**Crash recovery / heartbeat:**

| Flag | Default | Notes |
|---|---|---|
| `reaper_enabled` | on | `StaleRunReaper` runs in web + worker; set off to disable |
| `heartbeat_interval_seconds` | 30 | How often running jobs tick `heartbeat_at` |
| `reaper_interval_seconds` | 60 | How often the reaper sweeps for stuck rows |
| `stale_running_heartbeat_timeout_seconds` | 300 | Rows older than this are reset to `failed` |

Stuck `running` DB-index / sync / repo-index rows self-heal: a crashed worker stops touching `heartbeat_at`, and the reaper flips the row to `failed` on the next sweep so the UI surfaces the failure instead of spinning indefinitely. New endpoint `GET /api/projects/{id}/sync-history` (see `API.md`) returns the last N daily-sync audit rows with per-project outcome details.

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
| Analytics sources (GA4) | `docs/ANALYTICS_SOURCES.md` (operator runbook), `docs/adr/0001-external-report-cache.md` (why caching is allowed) |
| Live Git roadmap | `docs/GIT_ACCESS_AUDIT_AND_ROADMAP.md` |
| Deployment | `docs/DEPLOYMENT.md`, `INSTALLATION.md#production-deployment` |
| Audit remediation | `docs/AUDIT_REMEDIATION_PLAN_2026-06.md` |
| QA / test plan | `docs/MASTER_TEST_PLAN.md` |
| Contributing | `CONTRIBUTING.md` |
| Security | `SECURITY.md` |
| FAQ / troubleshooting | `FAQ.md` |
| Production planning | `docs/production-plan/` (PRD, tech spec, modules, QA, traceability) |
| UX scenarios (source of truth) | `docs/ux/scenarios.md` |

## UX scenarios — hard rule (super-ux)

- `docs/ux/scenarios.md` is the source of truth for all user-facing behavior.
- Any change that touches user-facing behavior MUST update
  `docs/ux/scenarios.md` in the same change (add/adjust scenarios, statuses,
  coverage).
- Any new feature or project STARTS with scenarios: draft them, validate
  against existing scenarios (conflicts, overlaps, gaps), get them approved —
  only then design and build UI.
- Use the `ux-scenarios` skill to maintain the base and `ux-audit` to verify
  the codebase against it.
