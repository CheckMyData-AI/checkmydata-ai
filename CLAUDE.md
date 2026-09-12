# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Product snapshot

- **What it is**: AI-powered database query agent — natural language → SQL, codebase Q&A, visualizations, team workspaces.
- **Supported databases**: PostgreSQL, MySQL, ClickHouse, MongoDB (via `backend/app/connectors/`), plus **SQLite** — file-backed, added 2026-08-20 because the demo path has created `db_type="sqlite"` connections since it existed while `ADAPTER_REGISTRY` had no entry for it, so every demo connection raised `Unsupported adapter: sqlite` on the first question. Not offered in the connection UI; it is what the demo runs on (`app/services/demo_data.py`).
- **Supported analytics sources**: `Connection.source_type` also accepts three analytics vendors (`backend/app/analytics/`, family defined once in `app/analytics/source_types.py`): **`ga4`** (Google Analytics 4 — the only one with a collector today), plus **`appstore`** and **`googleplay`**, reserved for m1/m2 (connection creation refuses them with 422 until their fact tables land). Runbook: `docs/ANALYTICS_SOURCES.md`.
- **LLM providers**: OpenAI, Anthropic, OpenRouter (`backend/app/llm/router.py`). **Which model an unpinned call runs on is `DEFAULT_LLM_MODEL`** (empty = each adapter's hardcoded default), added 2026-09-09 after measuring that 8.06M tokens/30d of background work — code↔DB sync, validators, learning analyzer — rode the adapter constant `openai/gpt-4o` while both workloads that HAD a knob were already on cheaper models. Three model streams, three homes: background = `DEFAULT_LLM_MODEL` (production: `deepseek/deepseek-v4-flash-0731`), chat = per-project `agent_llm_model`/`sql_llm_model` (production: `z-ai/glm-5.2`), indexing docs = per-project `indexing_llm_model` + per-doc-type `INDEXING_LLM_MODEL_BY_DOC_TYPE` (production: `qwen/qwen3.8-flash`). A slash-namespaced default with a native provider is refused at boot. Prices are NOT in code — `model_pricing_service` reads the live OpenRouter catalogue. Changing the indexing model does not invalidate the T03 doc cache (the model is deliberately not in `content_hash`).
- **Task tracking**: [Linear — CheckMyData.ai](https://linear.app/sshlg/project/checkmydataai-b7670b0dd990).
- **Tests**: **8,965 total** — 8,216 backend collected (8,219 minus 3 deselected) + 749 frontend Vitest across 97 files (measured 2026-09-09: `pytest tests/ --collect-only -q`, `npx vitest run`; the full backend run is `8,208 passed, 7 skipped, 3 deselected, 1 xfailed`). The 7,528 previously recorded here was measured 2026-08-26 and was stale by 1,437 — the figure this bullet exists to keep honest is the one most likely to rot, so re-run both commands rather than editing the number. Backend coverage **82%** (41,023 statements, 7,383 missed — combined unit+integration, CI on #228); the CI gate `fail_under` is **80%**. **The 78% previously recorded here was measured before `concurrency = ["greenlet", "thread"]` reached `[tool.coverage.run]`** — coverage stopped tracing at the first `await` into SQLAlchemy, so ~1,065 statements ran and were counted as untested. The same run measured 79% without the setting and 82% with it (CI on #227 vs #228).
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
| `make lint` | `ruff format --check app/ tests/` **then** `ruff check app/ tests/`. The format check is first because CI runs it first — and because it was absent here until 2026-09-11, which cost two CI cycles in one afternoon: `make check` passed locally on a tree CI rejected in sixty seconds. |
| `make check` | `make lint` + `make test-all` (backend only — no frontend lint/tsc). |

**CI parity** (`.github/workflows/ci.yml`):

```bash
cd backend && .venv/bin/ruff format --check app/ tests/
cd backend && .venv/bin/ruff check app/ tests/
cd backend && .venv/bin/mypy app/ --ignore-missing-imports
cd frontend && npx tsc --noEmit && npx eslint . --max-warnings=0 && npm test
```

CI also runs a **coverage gate of 80%** on the *combined* unit+integration run (matches `fail_under` in `backend/pyproject.toml`; `test_coverage_gate_is_stated_once.py` fails when the two files — or this sentence — disagree). Per-step pytest passes `--cov-fail-under=0` deliberately — the single authoritative gate is the combined `coverage report --fail-under=80` step. Don't add a per-step floor. Raised 72 → 80 on 2026-08-26: the gate had not moved while the greenlet tracing bug kept its input ten points low. A retrieval eval gate runs `test_retrieval_eval.py` + `test_reranker.py` + `tests/unit/eval/test_real_retriever_eval.py`. **The first two do not measure the product's retrieval** — they check the golden set, the metric math, and that an *oracle* clears the thresholds, which is why both retrieval defects of 2026-09 passed CI green. The third (Ш1, 2026-09-04) runs the production `HybridRetriever` with a real BM25 leg over a fixture corpus and a stub dense leg, so RRF, `hybrid_min_score`, `hybrid_max_rank` and the degradation labels are the shipped ones. The **embedder** is not in CI: `pytest -m slow_eval` covers it, opt-in, because the model is a ~90 MB cold download — the run itself measures 4.5 s, so a cached model would make it affordable in CI.

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
- **The deploy verifies the release it made, and migrations run in the channel that deploys (P0-4, 2026-09-11).** Until then `deploy.yml`'s two `curl -s -X PATCH` calls exited 0 on any HTTP status, and the health check that followed polled a public URL served by whatever release was live — so a rotated API key produced a green pipeline and a production that silently stopped receiving deploys. The job now captures the release version **before** the PATCH and waits for a higher one whose `status` is `succeeded`. **`Dockerfile.release`** is the deployed backend image with `alembic upgrade head` as its CMD, declared as the `release` process type in the same formation PATCH, so Heroku runs it before the release goes live and a failed migration aborts the deploy. That closes the gap measured the same day: `heroku ps` showed the web formation running `sh -c uvicorn app.main:app …` with no alembic anywhere, while `alembic_version` matched the repository head only because another channel had applied it once. The worker is verified by polling `/dynos` for a `worker` dyno `up` on the new release; deploys **queue** instead of cancelling, because a cancellation between the two release steps leaves backend and frontend on different commits. And `run_migrations` takes a session-level `pg_advisory_lock` — blocking, not the `try_` form the idempotent reconciles use, because the caller's next line assumes the schema is at head.

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

**And "a dyno with headroom" turned out not to mean Standard-2X (T05, measured 2026-09-09).**
The worker is Standard-2X now — 1 GiB, twice the quota that picked 8, `heroku ps` verified —
so the obvious move was 32. Set on production (v351) and a `force_full` enqueued against
`esim-php`; `code_symbol_embed` began on 26 014 symbols and the worker went over quota
**within twenty seconds and kept climbing**:

```
23:46:24  code_symbol_embed: started (Embedding 26014 code symbols…)
23:46:44  Process running mem=1082M (105.7%)   Error R14
23:47:03  Process running mem=1089M (106.4%)   Error R14
23:47:22  Process running mem=1094M (106.9%)   Error R14
```

Reverted to the code default the same hour (v352) and the rebuild re-enqueued. So the
number to carry is not "8 was for 512 MiB": **batch 32 does not fit in 1 GiB on this
workload either**, and doubling the dyno bought less than doubling the batch. 16 is
untested and each trial costs a full rebuild of the only production project, so it stays
untested until there is a reason better than symmetry. The `DELIBERATE` entry written for
32 was removed with the value — a recorded decision must describe what is deployed.

**0c. A rebuild no longer re-buys prose about files that did not change (T03, 2026-09-09)**
`generate_docs` is the most expensive step the product runs: ~9 375 s of a 12 039 s full
rebuild, 758 documents at ~4.8/min, 1.7–2.0M tokens — and **535 of those documents describe
database migrations**, files never edited after they merge. Full rebuilds are routine, not
exceptional: every `SYMBOL_UID_SCHEMA` / `GRAPH_EXTRACTION_SCHEMA` / embedding-config bump
enqueues one, so each structural fix to the extractor paid for the same prose again.

`knowledge_docs.content_hash` now records what a document was generated FROM
(`app/knowledge/doc_cache.py`: content + doc_type + enrichment_context + `DOC_GEN_SCHEMA`),
and `should_reuse_document` decides. **`DOC_GEN_SCHEMA` is deliberately not in
`embedding_fingerprint()`, and the independence runs both ways** — inside it, a reworded
prompt would re-embed every chunk of every project; and the UID/graph constants inside the
document key would discard 758 cached documents whenever a symbol's identity moved, which
is the cost this exists to avoid. The commit sha is absent for the same reason: a rebuild
triggered by a schema bump has not edited one migration.

`NULL` on an existing row means *generated before the cache existed* — unknown, not
unchanged — so the first run after deploy regenerates and records; the one after is cheap.
**No backfill**: a hash derived from the stored document would assert it matches inputs
nobody compared. `existing_docs_map` is now loaded on both branches (it was incremental-only,
which is why the expensive path had nothing to compare against).

`INDEXING_LLM_MODEL_BY_DOC_TYPE` (JSON, empty by default) overrides the model per doc type.
Setting it in production is a config change and belongs in `DELIBERATE`.

**Measured in production 2026-09-09, once the cache was warm.** A full rebuild of
`esim-php` ran 08:28:08 → 10:01:37 — **5 609 s**, against 12 039–12 329 s cold:

```
generate_docs: completed (generated=188 reused=575)   2 687 s   ← 9 375 s cold
code_symbol_embed: completed                          2 582 s
bm25_build: completed (31 392 chunks from 763 docs)       27 s
pipeline_end: completed (Indexed 10228 files, 722 schemas)
```

`generate_docs` fell **71%** and is no longer the dominant step — it and
`code_symbol_embed` are now roughly equal, where the first used to be four times the
second. All 763 documents now carry a `content_hash`, so the next rebuild reuses
essentially all of them.

The cache grew *across* interrupted attempts, which is the property the key was designed
for: three runs orphaned by restarts took `reused` from 304 → 575 (migrations 113 → 384),
because every document each attempt finished recorded its hash. An interrupted rebuild is
no longer wasted work.

**0d. A reindex that drops the vectors must confirm the rebuild was queued (2026-09-09).**
Found by doing it, while measuring T05. `queue_embedding_reindex` drops the project's
collection and then calls `enqueue`, which returns `None` on failure rather than raising —
so the failure was logged as `enqueued run_repo_index for project X (job=None)` at INFO,
and the summary said `done — 1 project(s) queued` **counted from the argument list**.

One level up it is worse: `reconcile_embeddings` **discarded the return value**, advanced
the `embedding_fingerprint` marker unconditionally, and logged "reindexed N project(s)"
from `len(ids)`. A failed enqueue therefore left the collections dropped, nothing queued,
and a marker asserting the rebuild had happened — which the nightly cron cannot undo,
because it is `force_full=False` and only a clean run rebuilds. Three claims computed from
the input instead of the outcome, in a row.

Now: a `None` job id logs at ERROR naming the consequence, both summaries count what
actually happened, and the marker is **not advanced** when nothing could be queued, so the
next boot retries. The marker still advances on ENQUEUE rather than on completion — that
part was right, since waiting for an asynchronous rebuild would block boot.

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
        → Shared gates (both paths — ORCH-A01/A02, and on RESUME since 2026-09-11):
            → ResultValidation (DataGate + result gate + reconcile) on every SQL result
              — a `requery` directive is a **warning**, not a stage failure. It used to
              be an error only on the pipeline path, so a clean zero-row result ("how
              many refunds in July?" against a month with none) burned both planner
              replans and returned a failed pipeline, while the flat loop answered it
              (ORCH-02). Only `block` — DataGate's impossible-value verdict — fails a
              stage.
            → AnswerQualityGate on final answer. `_execute_resume` is a second
              implementation of the tail and ran without it, and without the freshness
              warning, publishing as `pipeline_complete` an answer the fresh path
              downgrades to `step_limit_reached` (ORCH-06).
            → Truncation is aggregated across **every** query-bearing stage, for the
              caveat, for the table shown, and for the answer gate. Both read only the
              *last* stage with rows, so a capped SQL stage followed by a fresh GA4
              stage published the capped total as complete (ORCH-09).
      → AgentResultValidator (final check before user)
    → WorkflowTracker emits SSE events throughout; TracePersistenceService accumulates spans and batch-inserts RequestTrace + TraceSpan rows at pipeline_end
```

Key files: `backend/app/agents/orchestrator.py`, `adaptive_planner.py`, `stage_executor.py`, `sql_agent.py`, `knowledge_agent.py`, `viz_agent.py`, `git_agent.py`, `answer_validator.py`, `data_gate.py`, `router.py`. Deep-dive: `docs/SYSTEM_ARCHITECTURE.md`, `ARCHITECTURE.md`.

**`QueryResult` is the currency between stages, and it was named in none of these
documents** until 2026-09-03 — while being the single most connected node in the
repository (600 edges, `graphify god-nodes`, measured after a full re-extract). Defined in
`app/connectors/base.py:301`: `columns`, `rows`, `row_count`, `truncated`, plus `error` and
a machine-readable `error_type` the classifier trusts instead of pattern-matching prose the
application wrote itself.

It matters because **`StageResult.query_result` is what makes a stage chainable.** A stage
that returns only a `summary` can be read by the synthesis and by nothing else: DataGate's
six checks, `StageValidator`'s `expected_columns`/`min_rows`, and every `process_data`
transform are all guarded by `if qr:` and skip a text-only stage entirely. So "does this
stage populate `query_result`?" decides whether a later stage can compute on its output or
only quote it. Four producers populate it — `_run_sql_stage`
(`stage_executor.py:807`), `_run_analytics_stage` (`:1104`), `_run_process_data_stage`
(`:1200`) and `StageResult.from_summary_dict` (`stage_context.py:220`, a resumed stage's
sample rows). `query_mcp_source`, `search_codebase`, `analyze_git` and `analyze_results` do
not, which is why nothing downstream can compute on their output.

Multilingual: the agent reasons in English but answers in the user's language. Session rotation auto-summarizes near context limits (`session_rotation_enabled`).

### Knowledge indexing pipeline (M1–M6)

The repo indexer (`backend/app/knowledge/pipeline_runner.py`) is a checkpointed multi-stage pipeline. Each stage is feature-flagged and degrades to the legacy regex + dense-only path when disabled:

| Stage | Flag | Default | What it produces |
|---|---|---|---|
| `project_profile` → … → `embed_and_store` | (always on) | — | Baseline EntityInfo + ChromaDB chunks |
| `ast_parse` → `graph_build` | `code_graph_enabled` | **on** | `code_graph_symbols`, `code_graph_edges` |
| `bm25_build` | `hybrid_retrieval_enabled` | **on** | `data/bm25/{project_id}.json.gz` |
| `schema_embed` (per connection) | `schema_retrieval_enabled` | **on** | `data/bm25/schema_{connection_id}.json.gz` |
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
| **Adapter** | `app/analytics/ga4/adapter.py` (`GA4Adapter`), reports in `ga4/reports.py`, knobs vs secret split in `ga4/config.py` | Pages GA4's Data API on `offset` (Δ1 — a single un-paginated call silently truncates at 10 000 rows), requests `keep_empty_rows` so a dead day is a zero and not a gap (Δ2), and reads `PropertyQuota` (Δ3). Maps vendor failures onto the taxonomy in `app/analytics/errors.py`: 401→auth, 403→permission, **400/404→invalid-request**, 429/5xx→transient, spent bucket→quota. **Only transient/quota are retried** (`app/analytics/http.py::retry_async`, honours `Retry-After`, bounded at 60 s) — retrying an auth/permission error burns quota and can never succeed. `AnalyticsEmpty` now means one thing only — *a 2xx that carried no rows*; 404 used to map there, and `empty` is a **done** status, so a deleted property recorded every period as "collected, and it was zero" while the badge read `ok`. A spent bucket is noted from the response and refuses the **next** call for that property rather than discarding the page that spent it, and a property that fails inside `fetch` no longer discards the properties that succeeded. |
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
- `run_repo_index` — Git repo knowledge pipeline (per-function timeout `repo_index_job_timeout_seconds`, **21600 s** — this line said 16200 until 2026-08-31 while `config.py:596` said 21600; the ceiling test asserts only `>= measured x 1.25`, so nothing went red). This job carries the **full** rebuild — `force_full=True` plus the chained code↔DB sync. The nightly cron runs the same pipeline with `force_full=False, chain_sync=False` under its own 7200 s ceiling, so **the two ceilings cover different work and must not be tied together**. Reading the cron's 42.4-minute incremental run as a full rebuild is what sized this knob at 1800 and then 3600, and each cut a real run off: 1800.02 s inside `code_symbol_embed`, 3600.00 s inside `generate_docs` at document 80 of 758. A full rebuild of that 9 981-file repository measures **12 039 s (3.34 h)** — `generate_docs` ~9 375 s at ~4.8 docs/min, `code_symbol_embed` **2 260–2 582 s** (two readings at the code-default batch size against the same 26 014 symbols — a range rather than the ~2 300 s this line used to assert) — summed from the segments of the run that reached `pipeline_end`. A second, independent full rebuild on 2026-08-31 — enqueued by hand after the extraction fixes — measured **12 329 s** end to end and reached `pipeline_end: completed (Indexed 10004 files, 718 schemas)`, so the figure is a range rather than a single reading. Asserted in `tests/unit/services/test_repo_index_ceiling.py`, which also fails if the cron stops being incremental.
- **A resume no longer repays `code_symbol_embed`.** `_run_steps` reads the completed-step set once (`pipeline_runner.py:168`) and gated only four steps on it; `code_symbol_embed` recorded completion that nothing read, so every resume spent its 38 minutes again and attempt N+1 reached no further than attempt N — no ceiling could fix that. Measured after the gate: enqueue → `generate_docs` in **96 s**, against ~36 min before. `ast_parse` and `graph_build` stay ungated deliberately (in-memory state; graph merge), and a test fails if either joins the gated set.
- `run_batch` — batch query execution
- `run_analytics_collect` — collect one analytics connection's reports into its fact tables (per-function timeout `analytics_collect_job_timeout_seconds`)

**An hourly cron acts for the hour it was WOKEN for, not the one the clock reports
(fixed 2026-09-08).** Both loops slept to an hour boundary and then called a
dispatcher that read `datetime.now()` again — two guesses where one intention would
do. Measured on production over eight consecutive hours, the wave acted for
`20, 21, 21, 23, 23, 1, 2, 3`: two hours ran twice and two never ran, one of them
**hour 0**, which is `daily_knowledge_sync_hour`'s default and so the only hour that
mattered. The last completed `daily_sync` was 2026-09-06 and nothing ran for two
days. Silent in both directions: the hour-scoped Redis lock made the repeat a no-op,
and a skipped hour logs nothing at all. The loops now pass `at=next_hour`; the
argument defaults to `None` so a standalone caller still works.

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
- **A chat session with no owner belonged to everybody, until 2026-09-11 (P0-3; AUTH-02/03, BIZ-04).** `chat_sessions.user_id` is `ondelete="SET NULL"` and migration `d8a2f4b19c73` added the column nullable **with no backfill**, so ownerless rows are the ordinary residue of an account deletion, not a corner case. Three readers treated NULL as "yours": `_require_session_owner` guarded with `if session_obj.user_id and session_obj.user_id != user_id`, where a falsy owner short-circuits the comparison — and checked **no project membership at all**, so any authenticated user holding the id could read, rename or delete the transcript; `list_sessions` and the `ensure_welcome_session` count **unioned** `user_id IS NULL` into a user-scoped query, which is the delivery mechanism for those ids; and `validate_session_access` — what `/api/chat/ask` and `/ask/stream` consult before continuing a session — repeated the short-circuit, so the next caller could append their turns to a departed colleague's history. The codebase already refuses this union by name for its other two owner-scoped stores (`ssh_key_service.py:71-76`, `vendor_credential_service.py:158-165`). **D-TENANCY-1: an unattributable session is orphaned, not public** — nothing can recover whose it was, and inventing an owner would assert something false, so the row becomes unreachable. No backfill for the same reason; measured before shipping, production holds 28 sessions and **0 ownerless**, so no live access changed. `_require_session_owner` now demands ownership *and* membership — ownership is not membership, since a person removed from a project keeps their user id. And `DELETE /api/auth/account` deletes the user's sessions wherever they live: owned projects cascaded, foreign ones did not, which is what left them ownerless in someone else's project (BIZ-04). Deleted rather than anonymised — an anonymised transcript still carries the questions asked and the rows shown.
- `Project` is the workspace boundary. `ProjectMember` carries roles (owner/editor/viewer); every project-scoped route must check membership via `app/api/deps.py`.
- DB credentials are Fernet-encrypted at rest with `MASTER_ENCRYPTION_KEY`; the key is required to even boot. **Rotatable since 2026-08-21 (F-CONN-05):** `MASTER_ENCRYPTION_KEYS_OLD` holds retired keys for reading only, new ciphertext always uses the primary, and `app/ops/encryption_reconcile.py` re-encrypts all seven encrypted columns at boot when the primary's fingerprint changes — advisory-locked, idempotent, marker advanced only on a clean sweep. `pending_rotation_count` says whether the old key can be dropped. Runbook: `SECURITY.md` → *Rotating the encryption key*.
- **Read-only enforcement (vision §7 #1) is layered, not just a regex.** When a connection is `is_read_only`, each connector opens a DB-enforced read-only session — Postgres `server_settings={"default_transaction_read_only":"on"}`, MySQL `init_command="SET SESSION TRANSACTION READ ONLY"` (autocommit stays on), ClickHouse `settings={"readonly":1}`, MongoDB rejects write ops + `$out`/`$merge` + server-side JS (`$where`/`$function`/`$accumulator`). On top, `core/safety.py` `SafetyGuard` applies a **statement-initial allow-list** in read-only mode (query must start with SELECT/WITH/SHOW/EXPLAIN/DESCRIBE/DESC/TABLE/VALUES/EXISTS and be single-statement) plus the DDL/DML denylist. **Both read a copy of the query with comments stripped while the connector executes the original, so the stripper is part of the guard, not a tidy-up.** Until 2026-09-02 it was two regexes that did not know about quoting, and `SELECT '/*' AS a; DROP TABLE users; SELECT '*/' AS b` was checked as `SELECT ' ' AS b` and returned `is_safe=True` in read-only mode. Comment fences are now found by one left-to-right scan that also knows the quoting forms, and it is **dialect-aware** (`sql_dialect_for`): `#` opens a comment on MySQL and ClickHouse but is an operator character on PostgreSQL, MySQL's `--` needs a following whitespace, and dollar quoting is PostgreSQL-only. Where a dialect is ambiguous the scan keeps text rather than dropping it — leftover text can only cause a refusal, missing text causes an execution. Every raw-SQL entry point routes through `SafetyGuard` (agent ValidationLoop, batch `/execute`, note exec, MCP). For full assurance also use a read-only DB user (and Mongo `--noscripting`).

  **Three more holes closed 2026-09-11 (P0-2; SQL-01/02/04/06/11/12/13), and they share one shape: the guard was written against the SQL engine, and the thing on the other end of the string is not always one.** (1) **In SSH-exec mode the executor is `psql`, not Postgres.** The query was piped to the client's stdin, where a line beginning `\` is a client meta-command — `\!` runs a shell command on the bastion, `\copy … TO PROGRAM` runs one, `\i`/`\o` read and write files — and `SafetyGuard` inspects a first token and SQL keywords, none of which know that. Reachable by a project **viewer** through a saved note (`notes.py:97,111`). Closed twice over: the guard refuses any backslash outside a literal, and the built-in templates now pass the SQL as an **argument** (`psql -c`, `mysql -e`, `clickhouse-client -q`), which removes the capability rather than denying it. A custom template still pipes — nothing else can work when the client is unknown — and is covered by the guard alone. (2) **A SELECT can read the filesystem and make requests**: `pg_read_file`, `pg_ls_dir`, `lo_import`, MySQL `LOAD_FILE`, ClickHouse `file()`/`url()` (SSRF needing no file privilege) all passed, because they are SELECTs and a DB-enforced read-only session does not block a read. Denylisted per dialect, on the *call* rather than the word, so `SELECT file, url FROM downloads` still works. (3) **The DML denylist could not see past a space**: `WITH t AS (UPDATE "my table" SET x=1 RETURNING id) SELECT * FROM t` passed, because the UPDATE pattern spans the table name. DML is now caught by POSITION — start of text, or just after `(` or `;` — which needs to know nothing about table names, with `(?!\s*\()` so MySQL's `REPLACE(str,a,b)` stays a function. All three read the query with comments **and string literals** blanked, so a payload cannot hide in a literal and an ordinary literal is not a false refusal.

  **`is_read_only` now reaches the CLI in SSH-exec mode.** It appeared once in that connector, deciding retry idempotency, so for a whole connector class the "layering" above was the regex alone. The client is now asked for an engine-enforced session — `PGOPTIONS='-c default_transaction_read_only=on'`, `mysql --init-command="SET SESSION TRANSACTION READ ONLY"`, `clickhouse-client --readonly=1`. A **custom** template cannot be decorated (the client is unknown) and logs a WARNING naming that, rather than implying enforcement. `ssh_command_template` is validated for the same shell metacharacters `ssh_pre_commands` are — at save and at build, since a stored row can predate the check; screening one half of a shell line joined by `&&` screened neither (SQL-06). SSH-exec output is cut **on a line boundary** and the cut is reported: `QueryResult` omitted `truncated=`, so a 10 MB fragment was presented as a complete answer and its last half-line was parsed as a row. `format_template` gained the missing escaping context — a placeholder inside `'…'` inside `-e "…"` is SQL-escaped, so a database named `my db` no longer produces `''my db''` and a quote in the name cannot close the literal (SQL-13).
- SSH: `SSH_HOST_KEY_POLICY` defaults to `tofu` and **fail-closes** to `strict` on unknown values. `SSH_PRE_COMMAND_ALLOWLIST_ENABLED` (default on) gates **only** the command-shape allowlist (`export`/`NAME=`/`source`/`cd`). Since 2026-08-21 (F-SSH-03) the count cap, length cap, non-empty-string check and shell-metacharacter screen apply whether it is on or off — it used to disable all five, so the documented "emergency hatch" also opened the injection surface. Opening it logs once per process. All exec-template values are shell-escaped, `db_port` included (F-SSH-04). Security-sensitive: `backend/app/connectors/ssh_tunnel.py`, `app/services/ssh_key_service.py`, `app/connectors/ssh_pre_commands.py`, `app/connectors/ssh_exec.py`. **Reconnect never re-runs a command it cannot prove is safe to repeat (F-SSH-07, 2026-08-21):** `_run_command(..., idempotent=False)` is the default, the query path derives it from `is_read_only` or `core/safety.is_read_only_statement`, and a non-repeatable command interrupted mid-flight raises "it may already have run" rather than being re-sent.
- MCP server (`backend/app/mcp_server/`) is **off by default** (`MCP_ENABLED`). Two auth modes coexist: (1) per-user `cmd_mcp_…` tokens minted via `/api/auth/mcp-tokens` (recommended; resolved by SHA-256 hash to the issuing user), and (2) a server-level `CHECKMYDATA_API_KEY` bound to `MCP_API_KEY_USER_ID` for single-tenant self-hosted deployments. A revoked/expired per-user token never silently falls through to the server key. For **remote multi-tenant** use the server can be ASGI-mounted into the API at `/mcp` (`MCP_MOUNT_ENABLED`, default off — requires `MCP_ENABLED` too), where a pure-ASGI middleware resolves the bearer token **per request** to a principal carried in a `ContextVar` (many users, one endpoint, each scoped to their own projects; the standalone `--transport streamable-http` mode is single-principal/env-bound). The mounted transport is stateless; `MCP_ALLOWED_HOSTS` opt-in enables DNS-rebinding Host validation. MCP agent tools also run the shared token-budget gate (`UsageService.check_token_budget`) and acquire `agent_limiter` concurrency slots. MCP resources reuse the tools' principal/ownership checks. Tool names are prefixed `checkmydata_*` to avoid collisions with other MCP servers. See `docs/MCP_SERVER.md` for the integration guide and `.claude/skills/checkmydata-mcp/SKILL.md` for the drop-in agent skill.

### Billing & entitlements

Stripe-backed subscriptions when `billing_enabled=True`: Checkout, Customer Portal, idempotent webhooks (`/api/billing/*`). `EntitlementService` enforces plan-derived token limits and connection/project quotas → HTTP 402 with upgrade hint. Token budget gate (`check_budget`) wired into all chat entry points. Frontend: `/pricing`, `BillingPanel`. When billing is off, routes 404 and `USER_DAILY_TOKEN_LIMIT` / `USER_MONTHLY_TOKEN_LIMIT` apply (`0` = unlimited).

**Four paid tiers, no free one, priced on how much data we index.** The ladder lives once, in `app/services/plan_catalogue.py`: `base` $199 / 1 GB, `scale` $599 / 2 GB, `team` $900 / 5 GB, `enterprise` $1500 / unlimited — `max_index_bytes` is per project, and `0` means unlimited as it does in every other column on `plans`. The axis is not new: `base` has been described as "1 GB index" since 2026-08-31 while the table had no column to hold the figure. `estimate_index_bytes()` is the meter, built from row counts rather than a storage query because the index spans Postgres, a vector store that may be pgvector or Chroma, and gzip snapshots on an ephemeral disk. Anchor: `esim-php`, the one real project, measures ~16 MB against `base`'s 1 GB.

**The token ceiling is the layer that binds LLM spend, and until 2026-09-11 nothing did (P0-1, ADR-0003).** Two layers were each disarmed by the belief that the other held. The per-account OpenRouter key is minted, encrypted, metered, renewed and revoked — and **never presented to the provider**: `OpenRouterAdapter` binds the shared operator key at construction and `LLMRouter` carries no account context, so `key_encrypted` is decrypted in exactly one place, inside `provision()`, whose only caller discards the return value. The plan's token ceilings were `0` — *unlimited* — and `plan_catalogue.py`'s own docstring said they stay 0 because the key's dollar balance "is the only place that can enforce it mid-request". Migration `c3d4e5f6a7b8` did write real numbers into `plans`; the lifespan's `plan_catalogue_reconcile` — a blind field-by-field overwrite running **after** the release phase — reset them on every boot, so the gate was armed and disarmed within one start-up and no log line marked it (DATA-01).

Now: **`PAID_TIERS` owns the ceilings and derives them** from each tier's promised dollars (`PROMISED_CREDIT_USD`) divided by one measured constant; the migration's body is neutralised so there is a single writer. The key stays as provider-side attribution and a second belt on the OpenRouter path. **`BLENDED_USD_PER_MILLION_TOKENS = 0.25` is 2.2× the aggregate $0.1145/M actually measured on production** after the 2026-09-10 model switch — not the worst-case stream. The first calibration used the priciest stream ($1.85/M, chat) and capped `base` at 16.2M tokens/month against a real account's **16 464 277 tokens in 30 days**: a bound below observed use, for the exact workload `base` is sold for. `agent_llm_model` is a field the customer sets (`projects.py:52,97`), so no token figure can bound dollars exactly; the margin is named instead, and the worst case is bounded at ~$221 against a $199 subscription. Ceilings: `base` 40M/day · 120M/month, `scale` 120M · 360M, `team` 200M · 600M, `enterprise` unlimited. **The instrument that needs no margin is dollars** — `estimated_cost_usd` has been 100% populated since #285 (2026-09-04); it is a board row, not a rider.

Three more halves of the same seam closed with it: `_limit_for` now anchors on `usage_at_period_start` rather than live `usage`, so a $10 top-up no longer forgives the $28 already spent (BILL-02); `_INCLUDED_CREDIT_USD` covers all four tiers, with `enterprise` provisioned **no key** because "no monthly cap" has no ceiling to carry and `0.0` — what a `.get` default was sending — is the one reading that contradicts it (BIZ-02, D-SPEND-2b); and six routers that spent tokens through a `NullUsageSink` now carry a `DbUsageSink`, including the learning analyzer, which fires after nearly every answer (API-08, BILL-10). `tests/unit/test_no_unmetered_llm_router.py` is the AST guard that keeps it that way — allowlisted exceptions carry their reason in the file.

**`max_index_bytes` is now compared to something (T08 / D5, 2026-09-09).** The tier copy
has sold "1 GB index" since 2026-08-31, the column has held the number since the catalogue
reconcile, and `estimate_index_bytes` has sat beside it — called from a test and from
nothing else. The promise, the meter and the limit all existed and nothing compared them.

**D5 chose to warn, not to block**, for the reason the scheduled-work gate already
settled: a product that refuses to index is a product nobody can evaluate, and the account
most likely to be over quota is the one getting the most out of a trial. Over quota puts
one `warning`-severity line on the rail (`AttentionService._index_over_quota`, kind
`index_over_quota`, route `panel=settings`), logs, and increments
`index_over_quota_total`. Indexing runs exactly as before.

**The protocol was deliberately NOT widened.** `Entitlements` has four methods and its
guard demands a written argument for a fifth; the argument for `may_run_scheduled_work` was
that a *capability* fits none of the three ceilings. This is not that — a warning asks no
permission, it reads a number the plan publishes. So `index_quota_bytes` is a module helper
shaped exactly like `may_run_scheduled_work`, degrading **open**: a provider that predates
the question or whose lookup raises yields `0`, which means unlimited. A billing outage
must not print "you are over quota" on a rail where the reader can neither verify nor act
on it.

Three ways the check says no, each a decision: quota `0` is unlimited (skipped **before**
the counting queries, so an `enterprise` project pays nothing for a known answer); an
unmeasurable size is not evidence of a breach; and `>` rather than `>=`, because the meter
is an estimate from row counts and its precision does not justify a boundary warning.
Anchor: `esim-php` measures ~460 MB against `base`'s 1 GB.

**The catalogue reaches the database by reconcile, not by a seed.** `app/ops/plan_catalogue_reconcile.py` upserts the tiers in the FastAPI `lifespan` — advisory-locked, idempotent, never blocks boot — and migration `e5f6a7b8c9d0` adds only the column. Seeding a price list inside a migration freezes it at that revision: the code would say $900 while the row a customer resolves against still said $199, and nothing would compare them.

**No subscription is not the cheapest plan.** `free` was retired from sale on 2026-08-31, but `get_plan` deliberately does not filter on `is_active` (sold subscriptions must keep resolving), so every unsubscribed user still resolved to `free` and inherited its 100 000-token daily ceiling. Measured on production 2026-09-06: the owner burned 1 666 411 tokens on a full repository index, and the code↔DB sync queued behind it was refused with *"upgrade your plan at /pricing"* — a page that cannot take payment because no Stripe keys are set. A 3 h 37 m index completed and the step it exists to feed was turned away. Resolution now leaves the ladder instead of descending it: no subscription, or a `canceled`/`unpaid` one, returns `_no_plan()` — plan id `"none"`, every limit `0`, the catalogue not consulted at all. **That degrades OPEN, and until 2026-09-07 it was the absence of a decision rather than one.** The decision has now been taken, and it is neither of the two options that were on the table: an unpaid project is **not** blocked and **not** fully served — setup and hand-driven use stay open, and **scheduled** work needs a subscription. Blocking makes the product unevaluable; serving unattended nightly LLM work to accounts that pay nothing is the cost the tier exists to meter. Implemented 2026-09-07 (`SCN-146`/`SCN-147`/`SCN-148`), and the two halves shipped together because separating them is an outage: the day the gate lands, every account without a subscription — this deployment's owner included — stops syncing.

- **The gate** is a fourth question on the `Entitlements` protocol, `may_run_scheduled_work`, asked through `app.entitlements.may_run_scheduled_work` — the module helper, never a provider directly. Three scheduled paths ask it and nothing else does: `_dispatch_daily_knowledge_sync_wave` (per project owner), `_dispatch_analytics_collect_wave` (per the connection's project owner) and `_scheduler_loop` (per `ScheduledQuery.user_id`, filtered *before* `claim_due` so a withheld schedule stays due). A manual index or a chat question is never gated — the user is present and asking.
- **Everything fails towards letting the work run**, because this withholds a capability rather than enforcing a limit, so a broken check that withheld would be an invisible outage. A provider that predates the fourth method answers yes (the whole point of the structural `Protocol` is that the private package satisfies it without importing this repo, so an older one has no such method); a lookup that raises logs and allows; `billing_enabled=False` allows **twice over** — the registry never installs the commercial provider (`main.py`), and `EntitlementService.may_run_scheduled_work` also returns early on the flag rather than trusting the caller. That second belt was added because a test caught the first version withholding automation from self-hosted builds through the two direct instantiations that bypass the registry (`billing.py`, `usage_service.py`).
- **The grant** is `PLAN_GRANTS` (`email=plan_id`, JSON list) reconciled by `app/ops/plan_grant_reconcile.py` in the lifespan, **strictly after** the catalogue reconcile — a grant names a plan id and the row has to exist first. Advisory-locked, idempotent, never blocks boot. An unknown plan id is **refused, not defaulted**. A real Stripe subscription outranks a grant and is left alone. A granted row carries **no** `stripe_subscription_id`, which is what keeps `BillingService.reconcile` from cancelling it — that sweep filters on the column being non-null and names manual grants as the reason.
- **`past_due` keeps running**: an expired card is not a decision to stop paying, and cutting the nightly sync on the first failed charge is a punishment whose cause the user cannot see.

**Operator action required on this deployment.** `BILLING_ENABLED=true` with no Stripe key means no account can buy a plan, so set `PLAN_GRANTS` or the nightly sync stops for everyone: `heroku config:set PLAN_GRANTS='["<owner-email>=enterprise"]'`. Confirm with the boot line `Plan grant reconcile at startup: ok (granted=1 …)`. The retired `free` row must still EXIST — `BillingService` writes `plan_id="free"` as a foreign-key target when a subscription is created and when Stripe reports one deleted.

### Custom rules

User rules in `rules/` (or `CUSTOM_RULES_DIR`) are injected into orchestrator and SQL agent prompts with budget-aware truncation — the budget lives in `rules_to_context` (`RULES_CONTEXT_MAX_CHARS`, default 3000), **not** at the call sites. Corrected 2026-08-21: this sentence was true at two of five callers and false at three, and the two that capped sliced the joined string. Whole rules are dropped now, never half of one, and the notice says how many were omitted so an answer can admit it may not reflect them. Rule freshness check compares query results against loaded rules and proposes updates on discrepancy. Schema-aware rule validation runs on schema refresh.

### GitAgent (live Git access)

Read-only Git operations on the project's local clone (`git_agent.py`, `GitInspector`): commits, diffs, blame, releases, file churn. Gated by `has_repo` probe; path-traversal guard, output/count caps, no hooks. Freshness warning when clone lags indexed HEAD; optional `git_agent_auto_pull`. Findings persist as `code_finding` insights. Roadmap: `docs/GIT_ACCESS_AUDIT_AND_ROADMAP.md`.

### IMPORTS edges: a language the parser does not know produces silence, not an error

Production recorded **28 033 imports and 0 IMPORTS edges** (measured 2026-08-31), and the
count came from a log line, so nothing contradicted it — the parser found the imports and
the resolver could not turn one into a path.

Two independent failures, either sufficient alone. `_parse_import` had no branch for PHP
or Ruby, so both fell to the generic fallback, which stores **the whole statement** as the
module (`use App\Models\User;`, keyword and semicolon included) and leaves
`imported_names` empty — and `_resolve_imports` emitted nothing without a name. Separately,
`_candidate_module_paths` knew only a Python dotted module, a relative JS/TS path, and a
slash path tried against `.ts/.tsx/.js/.jsx/.py`; a PHP namespace has neither a dot nor a
slash, so it took the Python branch and produced `App\Models\User.py`.

Resolution is now by **path suffix** against the repository's own file list, not by
convention: "`App\` means `app/`" is PSR-4, a claim about someone else's composer.json,
and `Illuminate\Support\Facades\DB` lives under `vendor/laravel/framework/src/…`, which
no convention predicts. Ambiguity resolves to nothing, with the importing file's extension
as tie-break; a nameless `require` is capped at `_MAX_IMPORT_FANOUT`.

**An extractor change now rebuilds the graph by itself.** `GRAPH_EXTRACTION_SCHEMA`
(`ast_parser.py`) rides `embedding_fingerprint()` beside `SYMBOL_UID_SCHEMA`, so the
deploy enqueues one idempotent `force_full` rebuild. It has to: `save_incremental` merges
by FILE, so an incremental run re-reads only what changed and an extractor that starts
seeing something new reaches only the files somebody happens to edit. Separate from the
UID constant on purpose — a symbol keeps its identity while every edge around it changes.
**Bump it whenever `ast_parser` or `code_graph` changes what is extracted or how it
resolves**, not when a UID moves.

The general shape, worth carrying to the next grammar added: **a language the extractor
does not know does not fail — it returns an empty or nonsense result that reads exactly
like "this repository has no imports."** Adding a grammar to `GRAMMARS` is not the same as
supporting it end to end; check that each stage downstream has a branch for it.

### Code↔DB `sync_status`: structure outranks the model

`matched` claims both sides exist, so that precondition is checked before anything is
asked. `resolve_sync_status()` (`code_db_sync_pipeline.py`) decides in order: no DB side →
`code_only`, no code side → `db_only`; then SYNC-L5's column arithmetic settles `matched`
versus `mismatch`; then — and only when both sides exist with columns unknown on one — the
LLM's reading stands.

**A table with NO side is not `db_only` either (fixed 2026-09-08).** The first branch of
`resolve_sync_status` read `return "code_only" if has_code_info else "db_only"` — inside
the branch that has just established there is no DB side, so it contradicted the rule
stated two paragraphs above it. Measured on production: **43 of 256 map rows named tables
absent from `db_index`**, all with `updated_at` from the latest run, and 20 of them
carried `db_only` — a claim about the customer's database made about names the indexer
never saw there, including `axios`, `vue`, `const`, `export` and `import`. Every one had
`entity_name`, `entity_file_path` NULL and `read_count = write_count = 0`: no evidence
from either side. It now returns `unknown`, a write-path guard refuses any status
CLAIMING a DB side for a table absent from `db_index` (and deletes such rows left by
older versions — the prune keeps everything in `matched_tables`, so a refused row would
otherwise survive forever), and `_scan_table_usage` no longer registers a table before
knowing whether anything reads or writes it.

Before 2026-08-27 the model decided by default. `_match_tables` builds the code-only tail
with an empty `db_context`, SYNC-L5 needs both column sets and so never fired for those
rows, and eleven tables with **no `db_index` row at all** were stored as `matched` in
production — `bs`, `zes`, `esim`, `interfaces` among them.

### Code↔DB table names: a declaration outranks a guess

The link between a repository and a database rests on knowing which tables the code uses.
Two sources, and they are not equal:

- **Declared.** `Schema::create('x')` (Laravel), `create_table :x` (Rails),
  `op.create_table("x")` (Alembic), `CREATE TABLE x`, `CreateModel(name="X")` (Django),
  `protected $table` / `__tablename__`. `tables_declared_in_migration()`
  (`repo_analyzer.py`) reads all of them. The previous inline regex required whitespace
  before the name and therefore found **nothing** in a Laravel repository — not
  `Schema::create(`, not `op.create_table(`, not `create_table :x`.
- **Inferred.** A class name pluralised — `class User` → `users`. Necessary, because
  Laravel and Rails name most tables implicitly, and the source of every false table in
  production: `_extract_model_names` takes every `class \w+` in a non-Python file, and
  `ORM_PATTERNS["sqlalchemy"]` matches the bare word `Column` anywhere, so generated PHP
  reached the ORM branch and each of its classes became a "model".

Everything that records a table name now passes `is_plausible_table_name()` — four shape
rules (length ≥ 3, starts with a letter, not a keyword or common word, not a bare plural
suffix on a fragment or keyword). Shape, not a blocklist: a list of the 33 words that
appeared would pass that repository and fail the next. `_model_name_to_table` returns
`""` rather than a guess it cannot stand behind, and the caller skips it.

`eloquent` is now in `ORM_PATTERNS`; it was absent, which is why Laravel only ever reached
the ORM branch by accident.

### Required filters: the predicate is prose, and the reader must expect that

`code_db_sync.required_filters_json` is written by an LLM, and the tool description that
asks for it gave this example verbatim: `{"status": "= 1 (processed only)"}`. The guard
took everything after `=` — commentary included — and escaped it into the pattern, so
`was_handled = 1 (processed only)` was what SQL had to contain. Whatever failed to parse
fell back to a bare `\bcol\b` presence check, which a mention in the SELECT list
satisfies.

Measured 2026-08-31 against production: **159 predicates configured, 1 enforced
correctly** — 59 unsatisfiable across 57 tables, 98 vacuous. Both halves were invisible
because the guard's own tests used clean predicates (`= 1`, `IS NULL`), a shape the
writer never produces. It cost ~23 s of unsatisfiable LLM repair per query: 190 s of one
269 s failure, whose database work totalled **one second**.

The rules now, in `required_filter_guard.py`:

- **Parse from the left** — operator, then operand; a tail is accepted only when empty or
  wholly parenthesised. `= 'pending' or 'completed'` is not enforced rather than
  half-enforced.
- **A bound is satisfied by any narrowing** of that column. `created_at >= '2023-01-01'`
  says which rows are valid, so a six-month window satisfies it. Demanding the literal
  date false-blocks nearly every question, because most ask about a recent period.
- **An unenforceable requirement is not claimed as checked** — skipped, counted in
  `required_filter_unenforceable_total`, still passed to the model as context. The old
  presence-check fallback reported a pass it had never performed.

The degrade-on-final-attempt rule (SYNC-L1) stays, but it is no longer load-bearing: it
existed to survive a guard nothing could satisfy, and its warning — "the answer is
returned WITHOUT them" — was false every time it fired on a correct query.

### `db_index` and `trigger='auto'`: a person pressed a button, and it did not come back

**Who starts an `auto` run — measured 2026-09-09, because a run nobody can attribute is a
run nobody can explain.** Three paths reach `trigger="auto"`, all through
`_ensure_db_index_wf` (`connections.py:70`): the `FreshnessReconciler` loop
(`main.py:821`, gated on `freshness_reconciler_enabled` — default `False` and **not set on
production**, so it has never run there), `POST /connections/{id}/test`, and
`POST /connections/{id}/refresh-schema` (only where an index already exists). The manual
`/index-db` route mints its own run and is `trigger='manual'`.

So every `auto` run on production was **user-initiated**, which is what makes the measured
durations a product problem rather than a background one: **30 279 s (8 h 25 m) on
2026-08-13 and 23 198 s on 2026-08-19**, against the same 213 tables a `schedule` run
covers in **1 544 s** on average. All completed; all ended at `fetch_samples`; and the log
named **not one table**, so the cause cannot be recovered from it.

Nothing bounded the step: one `asyncio.gather` over every table, each doing a sample query
plus up to `db_index_stats_max_columns` distinct-value queries plus approximate statistics,
against the customer's database and often through an SSH tunnel.
`db_index_fetch_samples_budget_seconds` (1800, non-positive raises at boot) now bounds it.
On exhaustion the step keeps what it sampled and skips the rest **by name**, and the run
completes — a table without column statistics is a gap the prompt can work around, eight
hours against a live database is not. A skipped table is given the same empty `QueryResult`
a failed sample produces, deliberately: downstream already branches on "no evidence for
this table", and a third state would need a new branch at every reader.

Per-table timing is logged above `SamplingBudget.SLOW_TABLE_SECONDS` (5 s) only — 213 lines
per run would hide the four that explain the duration — and the one-line summary prints on
clean runs too, so silence never reads as a passing check. Counter:
`db_index_sample_budget_exhausted_total`.

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
- `MetricsCollector` records per-request route, complexity (no longer `"unknown"` — ORCH-A03), response_type, replans, retries, SQL calls, wall-clock, plus M2/M5/M6 code-graph counters. Exposed via `/api/metrics` (JSON) and `/api/metrics/prometheus`. **It holds them in memory, and until 2026-09-04 nothing carried them any further.** ORCH-A03 works: `orchestrator.py` writes the router's three signals into `context.extra`, which is what this collector reads. But `replace(context, …)` returns a *copy*, so the caller holding the original never saw them, and the persisted `request_traces` row took its values from `finalize_trace`'s own defaults — **`route` and `complexity` read `"unknown"` in 222 production traces out of 222**, measured 2026-09-03, while the counter beside them was right. `replans` still has only the in-memory home, and the counter resets on every dyno restart, so *"how often did the pipeline replan, and did it help"* is unanswerable over history (Ш0b). The trace now gets the routing from `TraceMeta` (`app/core/trace_meta.py`), which `finalize_trace` **requires** — the fix is the shape of #267, not another kwarg with a default.
- **A zero `total_tokens` is an absence, and the 2026-08-28 fix only covered half the
  writers (T09, 2026-09-09).** That fix put the derivation in `router.py::_usage_total`,
  which is the per-LLM-call sink. The four REQUEST-level writers in `chat.py` (`:541`,
  `:930`, `:1297`, `:1861`) still read `usage.get("total_tokens", 0)` and handed that zero
  through, and `record_usage` only derived on `is None` — so a `0` produced by a `.get`
  default was stored as a measurement. Measured on production: **10 rows of 9 423**, among
  them `prompt=175 669 / completion=4 587 / total=0` at $0.99 (claude-opus-4.8, 09-04) and
  `prompt=177 838 / completion=3 316 / total=0` (gpt-4o, 09-05). `check_budget` sums that
  column, so those calls charged **nothing** against daily, monthly and plan limits with
  billing on. The derivation now lives in `UsageService.record_usage` — the one funnel all
  five writers pass, including the next one — and treats a falsy total as absent. A
  provider-reported total is never zero, so `_usage_total`'s preference for it is
  untouched and still right (prompt caching makes the billed total differ from the sum).
  **Not backfilled**, deliberately: 361 410 uncounted tokens against 64 263 898 counted is
  0.56%, and rewriting historical usage records for that is not proportionate.
- Sentry on backend (`sentry-sdk[fastapi]`) and frontend (`@sentry/nextjs`) with **two** scrubbing layers, because each misses what the other catches. Layer 1 is Sentry's `EventScrubber` over KEY names, denylist extended 33 → 39 (`dsn`, `database_url`, `auth_key`, … are not in its default). Layer 2 is `before_send` over VALUES, and it walks `extra` and `contexts` as well as exceptions, log entries and breadcrumbs — those two containers were reached by neither layer until 2026-08-26. `release` comes from `HEROKU_SLUG_COMMIT` (needs `heroku labs:enable runtime-dyno-metadata`), and is `None` rather than invented when absent.

### Storage

- App data: SQLite in dev (`backend/data/agent.db`), **Supabase PostgreSQL 17.6 in production since 2026-08-29** (`DATABASE_URL`). Reached through the **Supavisor pooler on port 5432 (session mode)**, and both halves of that are forced rather than chosen: `db.<ref>.supabase.co` publishes an AAAA record and no A record while Heroku dynos have no outbound IPv6, so the pooler is the only route; and transaction mode (6543) breaks the named prepared statements SQLAlchemy's asyncpg dialect uses by default, intermittently. Revisit session mode when connection count is a measured constraint, not before. The former Heroku database is still attached as `HEROKU_PG_ROLLBACK_URL` — it was read, never written, and is the only rollback. **`public` is not served by the Data API** and RLS is on all 65 tables with no grants to `anon`/`authenticated`; see `scripts/migrate_to_supabase.sh` for why that is load-bearing rather than tidy.
- **The Supavisor session-mode ceiling is a measured constraint now (2026-09-09).** This
  file already said "revisit session mode when connection count is a measured constraint,
  not before" — this is that measurement. The pooler caps the project at
  **`pool_size: 15`**, and the application is configured to want more than twice that:
  SQLAlchemy `db_pool_size=5` plus `db_pool_overflow=10` is up to 15 per process, and
  `PgVectorStore` opens its own psycopg pool of `max(2, db_pool_size // 2)` = 2 — so **up
  to 17 per process, up to 34 across `web` and `worker`**. It survives because the pools
  are lazy: at rest each process holds 5 + 2 = 7, and 7 × 2 = **14 of 15**. There is no
  headroom at all, and any overflow connection, one-off dyno or `psql` session pushes it
  over. Observed doing exactly that: `psycopg_pool.PoolTimeout: couldn't get a connection
  after 30.00 sec` on `web` at 02:43:21, and `FATAL: (EMAXCONNSESSION) max clients reached
  in session mode` from outside. `/api/health` stayed 200 throughout — existing
  connections keep working, which is why this can saturate without an alarm.

  **The arithmetic is checkable now, which is the half that was missing.** It lived in
  three files that never referred to each other — `config.py`'s two pool settings and the
  psycopg pool built inside `PgVectorStore` — so nothing could notice they added up to
  more than the pooler allows. `DB_CONNECTION_CEILING` is what the pooler permits in
  total; when set, the boot **refuses** a configuration whose worst case cannot fit:
  `(db_pool_size + db_pool_overflow + max(2, db_pool_size // 2)) * 2 + 1 <= ceiling`,
  the `2` being `web` + `worker` and the `+1` reserved for an operator — the saturation
  was found by a `psql` session failing, and a budget that fills the pooler exactly leaves
  nobody able to look at the database precisely when someone needs to. Default `0` checks
  nothing, because a self-hosted install talking straight to Postgres has no such limit.

  **Resolved 2026-09-09.** The pooler's `default_pool_size` was unset, so the platform
  default of 15 applied; it is now **40** (Management API,
  `PATCH /v1/projects/{ref}/config/database/pooler`), and `DB_CONNECTION_CEILING=40` is set
  so the boot validator checks against the real limit. 40 covers the app's worst case plus
  one reserved for an operator (35) and leaves **17 of the database's 57 usable
  connections** — `max_connections` 60 minus 3 reserved, measured — for direct clients:
  migrations, `psql`, and the platform's own. Do not raise it further without re-measuring
  `max_connections`: Supavisor's servers and every direct connection come out of the same
  60, and exhausting *that* is worse than exhausting the pooler.

  Verified after the change: a `psql` session that had been refused with `EMAXCONNSESSION`
  connected on the first attempt, and the deployed validator refuses the 5 + 10 + 2
  configuration against a ceiling of 15 — the shape that saturated production.
- Vectors: **`VECTOR_STORE_BACKEND` picks the backend, and its default is `auto`** — resolved by `DATABASE_URL`: `pgvector` on Postgres (table `doc_embeddings`, one row per chunk, HNSW `vector_cosine_ops`), `chroma` on SQLite (`CHROMA_PERSIST_DIR` or `CHROMA_SERVER_URL`; collections named `project_{project_id}`). Neither literal would serve both: `pgvector` breaks a fresh `make setup`, which creates SQLite where the `doc_embeddings` migration is a deliberate no-op, and `chroma` leaves a real deployment on the store described next. An explicit value pins it; an explicit `pgvector` on SQLite raises rather than downgrading silently. The decision lives in the pure `resolve_backend()` — construction opens a psycopg pool, so the choice is untestable through the factory anywhere Postgres is absent. **`auto` means the answer is written nowhere an operator can read, so the boot log names it** (`vector store: … (auto-resolved …)` / `(pinned …)`). **ChromaDB's persist dir on Heroku is the container filesystem** — wiped on every dyno restart, and `web`/`worker` are separate process types with separate copies. An empty store makes `pipeline_runner` set `force_full`, a full rebuild costs 12 039 s against the nightly ceiling of 7 200 s, so the store was empty again by morning: **`index_repo` completed 16 times in 94 runs**. Embeddings are identical across backends (bundled ONNX `all-MiniLM-L6-v2`, 384-d) and the metric matches the `{"hnsw:space": "cosine"}` the collections were created with, so the swap does not move retrieval ranking. pgvector is available on both deployments (0.8.1 Heroku, 0.8.2 Supabase). Requires Postgres — the migration is a deliberate no-op on SQLite, and asking for pgvector there fails at start-up saying so.
- BM25 snapshots: `backend/data/bm25/{project_id}.json.gz` and `schema_{connection_id}.json.gz` — **gzip JSON, not pickle, since 2026-08-21 (F-KNOW-06)**: `pickle.load` executes its payload, and `BM25_DATA_DIR` is configurable. The tokenized corpus is stored and `BM25Okapi` is rebuilt on load; a leftover `.pkl` is deleted, never read. Both are rebuilt from Postgres at start-up when missing (`app/ops/bm25_local_reconcile.py`).
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

### Deployment vs. code default — `make config-drift`

Production is allowed to differ from a code default, but only on the record. Ten
undocumented divergences were found on 2026-08-23 and unset on 2026-08-25, one of them
`CROSS_CONNECTION_LEARNINGS_ENABLED`, which `vision.md` §7 calls an invariant.

`make config-drift` compares every boolean setting deployed on Heroku against
`backend/app/config.py` and **exits non-zero** on anything that is not recorded, with a
reason, in the `DELIBERATE` map in `scripts/config_drift.py`. Five entries live there
today: `BILLING_ENABLED`, `DAILY_KNOWLEDGE_SYNC_ENABLED`, `GIT_AGENT_AUTO_PULL`,
`MCP_ENABLED`, `MCP_MOUNT_ENABLED`. Adding a key is how you record a decision; it belongs
in the same change as the `heroku config:set` it describes.


Most behavior ships behind flags in `backend/app/config.py`. Gate regressions the same way.

**Code intelligence (note defaults):**

| Flag | Default | Notes |
|---|---|---|
| `hybrid_retrieval_enabled` | on | Falls back to dense-only without BM25 snapshot |
| `hybrid_min_score` | **0.0** | Floor on the **fused** RRF score. Was `0.03` until 2026-09-02, which made retrieval an AND-gate: RRF gives `1/(rrf_k+rank)` *per leg*, so the most a single-leg hit can score is `1/61 = 0.0164` and the floor sat above all of it — 0 of 40 single-leg documents and 82 of 1 600 two-leg rank pairs survived. A value at or above `1/(rrf_k+1)` now **raises at boot** rather than being clamped |
| `hybrid_max_rank` | 30 | The rank cut-off RET-R5 actually wanted: drop a document only when **both** legs ranked it worse than this (0 = off). A rank, so it means the same thing at any `rrf_k` — the float it replaced was tuned against `rrf_k = 60` and would have changed meaning silently if anyone edited that constant |
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

**Intelligence remediation W3 landmarks** (orchestrator termination + path unification, ORCH-T01–T03/A01–A03/R01/P01–P04/PR01/CP01/RP01–RP02): live step-budget termination; wrap-up gate; no-tool re-prompt (T03); routing metrics always populated **in the in-memory collector only — the persisted trace was not wired until Ш0a on 2026-09-04**; prompt de-dup (~200 tokens/req saved); ContextPlanner word-boundary cue matching; StageValidator scoped to data stages; trivial-plan bounce + degraded propagation; cohort_window param unification; complex non-DB questions routed to pipeline (ORCH-R01); `ResultValidation` wired into pipeline SQL stage (A01); `AnswerQualityGate` wired into pipeline final answer (A02). Pipeline answers may now return `response_type: "step_limit_reached"` when budget exhausted.

**Intelligence remediation W4 landmarks** (schema-capture depth, DBIDX-D1–D18): MongoDB native introspection via aggregation pipelines (`distinct_values`/`approx_stats` overrides); ClickHouse sort-key (`is_sort_key`); PostgreSQL enum labels + CHECK constraints; VIEWs/MATERIALIZED VIEWs indexed with `object_kind`; column comments + indexes rendered in schema context (D8); approx_stats persisted to `DbIndex.column_stats_json` + `column_distinct_values_json` (D9); deterministic completeness gate (D10); schema-cache bust on re-index (D12); dead `SchemaIndexer` deleted (D13); `reltuples < 0` treated as unknown (D14); LLM table/column prompt caps (D15/D16); ClickHouse + Mongo freshness timestamps (D17/D18). New config keys: `mongo_schema_sample_size` (100), `db_index_stats_enabled` (on), `db_index_stats_max_columns` (20), `db_index_stats_sample_cap` (100 000), `db_index_max_tables_analyzed` (500), `db_index_max_prompt_columns` (100). **R9/D7 handoff**: `ColumnInfo.distinct_values/distinct_count/numeric_format/enum_labels` are populated and persisted; downstream waves read from the index.

**Intelligence remediation W5 landmarks** (code↔DB trust signals, SYNC-L2/L3/L5/L6/L7/L8/L9 + low-batch L11–L14): `classify_freshness()` in `git_tracker.py` uses `iter_commits` for exact AHEAD/BEHIND/DIVERGED states (L3); `KnowledgeFreshnessService` maps each state to a distinct warning + severity (DIVERGED=critical); `EntityExtractor` attributes SQL column refs per-statement with noise-token stripping (L2) — **and that stripping was insufficient for table NAMES until 2026-08-27**: it blanked comments and string literals but left six SQL keywords as the only filter, so `TABLE_REF_SQL` (`FROM|JOIN|INTO|UPDATE|TABLE` + a word) also matched prose, and `_model_name_to_table` pluralised one- and two-character tokens into plausible names. Production's code↔DB map for the one real customer named 39 tables of which **six existed** — see `is_plausible_table_name` and `tables_declared_in_migration`; `_compute_column_drift()` produces deterministic sorted set-diff overriding LLM `sync_status` when both sides are known (L5); migration `c9b8a7f6e5d4` adds `CodeDbSync.column_mismatch_json`; sync loaders match on `(schema,table)` pair for schema-qualified ORM models (L6); bare-suffix keying normalised across all loaders (L7); empty-graph warning gated on `lineage_enabled OR clustering_enabled` (L8); op-kind uses word-boundary regex (L9); `_coerce_confidence` rounds floats before clamping (L11); `CallerRef.depth_estimated` sentinel replaces fabricated depth (L12); enum-table link uses word-boundary token matching (L13); DB-index TTL reads from `settings.db_index_ttl_hours` (L14). New config keys: `git_freshness_fetch_origin` (off — gates remote fetch for cross-machine accuracy; env `GIT_FRESHNESS_FETCH_ORIGIN`), `db_index_ttl_hours` (24; env `DB_INDEX_TTL_HOURS`).

**Ingestion automation (all off by default)** — the rule is *nothing calls out on a schedule unasked*, so membership is decided by whether the thing reaches outward, not by whether it is automatic:

`git_webhook_enabled`, `git_poll_enabled`, `freshness_reconciler_enabled`, `schema_change_alerts_enabled`.

**`auto_sync_after_index` left this family on 2026-08-27 and now defaults ON.** It never belonged: measured against `code_db_sync_pipeline.py`, the sync has zero references to `adapter`, `connector`, `execute_query`, `introspect`, `httpx` or `aiohttp` — it opens no connection to anything. Its inputs are the stored `DbIndex` and the code knowledge, both already local, and its output is the code↔DB map, which is **what a repo index produces** rather than a separate ingestion.

The grouping had a consequence. Unset in production on 2026-08-25 alongside eight genuine ingestion flags, it meant a full re-index on 2026-08-27 rebuilt the graph (25 491 symbols, 2 134 edges) while the map kept the previous night's `updated_at`. "The index ran and the map did not" is the wrong default for a product whose value is that map's freshness.

The flag itself stays, for the reason the old grouping never named: the sync runs an LLM (`CodeDbSyncAnalyzer`), so it costs **tokens per run**. Turning it off now switches off a cost rather than a phantom outward call.

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

**Capability claims are checked at every boot.** `app/ops/capability_report.py` runs in the `lifespan` and logs one line per configured capability the runtime does not actually provide — `reranker_enabled` or `chroma_embedding_model` without the `ml` extra, and `chroma_server_url` at CRITICAL because the installed `chromadb` carries GHSA-f4j7-r4q5-qw2c (pre-auth code injection, no fixed version) and only the absence of an HTTP listener keeps it unreachable. It logs on success too, so silence never reads as a passing check, and it never raises.

**Platform / security:**

`billing_enabled`, `mcp_enabled`, `mcp_mount_enabled` (HTTP mount, requires `mcp_enabled`), `security_csp_enabled` / `security_csp`, `security_hsts_enabled`, `session_rotation_enabled`, `backup_enabled`, `sentry_dsn` (off unless set).

**Crash recovery / heartbeat:**

| Flag | Default | Notes |
|---|---|---|
| `reaper_enabled` | on | `StaleRunReaper` runs in web + worker; set off to disable |
| `heartbeat_interval_seconds` | 30 | How often running jobs tick `heartbeat_at` |
| `reaper_interval_seconds` | 60 | How often the reaper sweeps for stuck rows |
| `stale_running_heartbeat_timeout_seconds` | 300 | Rows older than this are reset to `failed` |

**A reap is provisional, and two places treated it as final (2026-09-01).** Production,
every timestamp from the database: a schedule run started 22:00:20 on the **web** dyno,
`graph_build` began 22:01:22, the row was **reaped at 22:07:11**, the reaper's replacement
started **22:13:32** on the **worker** dyno, and the reaped run emitted
`pipeline_end completed` at **22:49:08** — it was never dead. Two full repo indexes ran
concurrently for 36 minutes on the memory-constrained process.

Two independent causes. The pipeline's beat (`pipeline_runner.py`) was
`UPDATE … WHERE workflow_id = :wf AND status = 'running'`, so the instant the reaper
flipped the row the beat stopped matching and a working run could **never re-assert
liveness** — the guess made itself true, while `_reconcile_reaped_run` existed all along to
fold a late `pipeline_end` back in. And `RunCoordinator._active_run` filtered on **status**,
the one field a wrong reap falsifies. It now consults `heartbeat_at` through `_is_live()`,
where **only `failed` + `REAP_ERROR` is provisional** — `completed`, `cancelled` and an
honest `failed` are statements, and treating their last beat as life blocked legitimate
retries (caught by the existing coordinator tests, not by the new ones).

**A zero-row beat is now logged**, once per gap. A targeted `UPDATE` matching nothing
raises nothing, and that silence is why the beat gap behind the 22:07 reap still cannot be
explained from the data. `rowcount == -1` ("could not tell") is kept distinct from `0`.

**Repo-index mutual exclusion is cross-process, and was already (T07, measured
2026-09-09).** This paragraph used to read *"Still open: mutual exclusion is per-process
only"*, on the grounds that `_indexing_locks` (`repos.py:53`) is a module-level dict of
`asyncio.Lock` while the entry points span both process types. Both halves of that are
true; the conclusion was not, because the dict is not what enforces exclusion. Three
facts, each now checked by `tests/unit/services/test_run_exclusion_cross_process.py`
rather than asserted:

- `IndexingRun` is constructed in **exactly one place**, `RunCoordinator.start`
  (`run_coordinator.py:281`) — the test walks `app/` and fails if a second site appears.
- The rule is enforced by the **database**: `uq_indexing_runs_active_one`, a partial
  unique index on `(project_id, kind, coalesce(connection_id, ''))` limited to
  `status IN ('queued','running','cancelling')`, declared for **both** SQLite and
  PostgreSQL (`models/indexing_run.py:85`). A row inserted by hand, bypassing the
  coordinator entirely, is refused — which is what "another process" means.
- The TOCTOU window is closed by catching `IntegrityError`, rolling back (mandatory — the
  session is poisoned otherwise) and re-querying for the winner.

What the 2026-09-01 incident actually was: not a missing lock. The reaper flipped a live
run to `failed` and `_find_active` filtered on **status**, the one field a wrong reap
falsifies. Closed by `_is_live`. So `_indexing_locks` is a fast path that saves a round
trip, and a Redis lock would add nothing — its TTL would need renewing by the same beat
that failed there. The comment at `repos.py:53` now says so, because a reader who takes
those dicts for the mechanism will build the lock nobody needs.

**A reaped run now reaches `error_log` (N3, 2026-08-25).** `RunCoordinator` catalogs failures only on terminal-event paths (`run_coordinator.py:317`, `:450`, `:485`); the reaper flips rows with a bulk `UPDATE` and emits no terminal event, so 143 failed runs produced 3 catalog rows. `StaleRunReaper` reads the doomed rows before killing them and catalogs each — message carries the step (`stale run reaped (step: graph_build)`), so the concentration that identifies a cause is visible in `/api/logs` rather than only in ad-hoc SQL. The run's `error` column stays exactly `REAP_ERROR`, because `run_coordinator.py:393` compares it verbatim to reconcile a run that turns out to be alive.
**The beat runs *inside* a step, not only at its edges (N1, 2026-08-25).** `RunCoordinator.step` wrote `heartbeat_at` on entry and on success and nothing between, so any single step longer than `stale_running_heartbeat_timeout_seconds` (300) was reaped **while it was still working**. Production: 64 of 70 repo-index failures, all `current_step='graph_build'`, `error='stale run reaped'`, every day from 2026-08-07. It was invisible for thirteen days because a heartbeat *did* exist — `_run_index_background` (`repos.py:556-563`) ticks `IndexingCheckpoint`, and the reaper's `stale run reaped` marker lands on `IndexingRun`, a different row. The fix is in `step` because all four repo-index entry points (ARQ task, manual route, retry route, daily sync) reach the pipeline through it, and because `IndexingRun` is created and finished there. The writer uses **its own session** — the step's `db` driven from two tasks is a race, not a heartbeat — and a targeted `UPDATE` rather than an ORM load, so it cannot carry a stale `version` or overwrite columns it does not own.

**The repo-index path beat the WRONG ROW until 2026-09-08 — the N1 trap, twice.** N1 put
the beat inside `RunCoordinator.step`; the repo-index paths never enter a `step`, so they
kept the beat they already had — `_run_index_background` ticking `IndexingCheckpoint`,
which is not the row `StaleRunReaper` reads. Measured: a manual catch-up started 15:19:11,
wrote its last `IndexingRun.heartbeat_at` at 15:20:00, logged `code_graph: built 408
symbols, 516 edges` at 15:20:01, then five minutes of worker silence — no restart, no
R14/R15 — and was reaped at 15:25:10 while alive. It explains the 52 historical
`graph_build` reaps and why nightly `index_repo` failed 54 of 66 times in 30 days. `_hb`
now beats both rows. Hidden the same way both times: **a heartbeat does exist nearby, on
a different row.** When a run is reaped and the process is demonstrably alive, check
*which row* is being ticked before anything else.

**A beat nobody can schedule is worth exactly what no beat is worth (2026-09-08).** The
same `graph_build` step, a third time — and the two previous fixes were both necessary and
both insufficient. Production, every timestamp from the log:

```
20:49:26  graph_build: started (82 parsed files)
20:49:27  code_graph: built 408 symbols, 516 edges
          ...14 min 30 s of complete silence...
20:55:09  Reaper: reset stale runs — repo=1 runs=2 (timeout=300s)
21:03:57  graph_build: re-parsing 231 reverse-dependent file(s)   <- STILL ALIVE
```

Between those two log lines `pipeline_runner.py:1758-1761` does two things:
`CodeGraphService.load_graph`, and `reverse_dependents` over the result. The second
measures **0.009 s** on the production graph, so all of it is the first — and inside it,
the `CodeGraph` constructor, on one expression at `code_graph.py:158`:
`key=f"{e.edge_type}:{len(self._graph.edges)}"`. `G.edges` is a **view**, and `len()` on
it walks the adjacency structure, so asking once per edge makes construction O(E×(V+E)).
Measured at the production shape (25 695 symbols, 68 263 edges): **209.6 s on a 2026
laptop**, several times that on a dyno core. It is synchronous Python with no `await` in
it, so the heartbeat coroutine cannot be scheduled for its entire duration. The key's
value is read by nothing — it only keeps parallel edges distinct — so the position in the
list serves: **0.10 s**.

The general shape, which is the part worth carrying: **the reaper measures a coroutine's
ability to be scheduled, not a process's liveness.** Any CPU-bound stretch on the event
loop longer than `stale_running_heartbeat_timeout_seconds` reads as death, and the run's
own logs will show it working afterwards. When a heartbeat gap has no restart, no R14/R15
and no error beside it, look for blocking work on the loop before looking for a crash —
and prefer a test that counts operations over one that measures time, because a
timing-ratio test for exactly this defect **passed against it**.

Two independent costs were fixed on the same day and only one of them was the reap:
`save_incremental` also rewrote the whole graph (~94 000 rows, 837 571 parameter values,
for a 408-symbol delta) and now writes the delta — 1 176 values. That is a real saving and
it was never the starvation; the run never reached persistence.

**And the delta's own first version was slower than what it replaced.** R3-1's prune was
written as a correlated `NOT EXISTS` per endpoint over every edge in the project: correct,
and **1 195 s** for a 36-symbol delta against the same shape, versus 0.06 s now. The fix is
not a faster query but a smaller question. R3-1 requires that an edge must not survive
pointing at a symbol **this run removed** — which is exactly `doomed_uids - new uids`, a
targeted `DELETE` on `(project_id, dst_uid)` proportional to the change. The in-memory
merge asked the whole-project question only because it already held the graph.

That narrowing also settles a disagreement between the two write paths, and the direction
is the surprising one. `CodeGraph` keeps edges to unresolved UIDs **on purpose**
(`code_graph.py:153`: "so the graph remains queryable") and `save`, the full rebuild,
stores them — while the old incremental prune deleted every one of them on every run. So a
full index and an incremental index produced different graphs for the same repository, and
the incremental was the lossy one. Nothing could depend on the swept state, because the
next full rebuild restored it.

**A directly-enqueued repo index now mints its run row (2026-08-31).**
`run_repo_index_task` began a bare workflow and no `IndexingRun`, so the path
`reconcile_embeddings` uses — every deploy-triggered `force_full` rebuild — was invisible
to the reaper, to `heartbeat_at`, to `/api/projects/{id}/sync-history` and to the duplicate
guard. Measured: a 12 091 s rebuild ran to completion with zero rows in `running`. The
manual route and the daily sync always minted theirs, which is why the gap was invisible.
It falls back to the bare workflow if the row cannot be written — the row is bookkeeping,
the index is the work.

**And the worker could not enqueue anything at all (2026-09-09).** Found within the hour
by the ERROR line the orphan sweep above was given for exactly this purpose:

```
04:30:09  ERROR app.core.task_queue: No coro_factory for in-process fallback of task run_repo_index
04:30:09  ERROR app.ops.orphan_runs: … orphaned by a restart and could NOT be put back
04:30:09  INFO  app.ops.orphan_runs: 1 running index_repo run(s) seen, 0 put back
```

`app.core.task_queue.enqueue` routes through a module-level `_arq_pool`, and
`init_task_queue` — the only thing that builds it — was called in `app/main.py`'s FastAPI
lifespan and **nowhere in the worker**. The worker *consumes* through arq's own connection,
so taking work was never affected; everything in that process that puts work **back** was
a no-op that returned `None`. That is the orphan sweep, and `StaleRunReaper._requeue`
reached from the worker's own `reaper_loop` — so the reaper's re-enqueue after a reap had
never worked from the worker, only from the copy on `web`. Which is why the requeue budget
looked *exhausted* when it was really *unusable*.

`worker.startup` now calls `init_task_queue(redis_url)` before anything enqueues, and a
test pins that ORDER rather than merely its presence — the sweep ran two lines too early
and that was the whole defect.

**A restart is not a failing run, and the reaper could not tell (2026-09-09).** Three
full rebuilds of `esim-php` died in one night. The first two matched deploys to the
second — `v352` at 23:47:54 against a last beat of 23:47:53, `v353` at 00:00:45 against
00:00:25 — and the third was `Stopping all processes with SIGTERM` seven seconds after
its last beat, **with no release behind it**: Heroku cycles dynos on its own. A full
rebuild of that repository takes hours and the platform restarts the dyno roughly daily,
so the two collide without anybody doing anything wrong.

`StaleRunReaper._requeue` was the only recovery, and it is the wrong instrument twice: it
waits `stale_running_heartbeat_timeout_seconds` (300) to conclude the run is dead, and it
spends `reaper_requeue_max_attempts` (2 per 6 h) — a budget meant for runs that fail on
their own merits. Two restarts exhausted it, so the third reap was refused with *"the run
is failing for its own reasons, not a restart"*, which was wrong and unknowable from its
data. Observed live at 01:01:26 while measuring this.

Two changes, and the first is the one that matters. **A restarting worker puts back what
it replaced** (`app/ops/orphan_runs.py`, called from `worker.startup` before it takes any
job): a run is stamped with `boot_id` and `owner` when it starts, and an `index_repo` run
still `running` under a *different* boot id belonged to the process this one took over
from. The replacement is the only thing in the system that knows that for free — and a
new `BOOT_ID` is generated on every process start, so a deploy and a dyno-cycle are
covered alike, where `HEROKU_RELEASE_VERSION` only moves on the first. It marks the row
terminal with its own `ORPHAN_ERROR` (never `REAP_ERROR`, which spends the failure budget
and which `run_coordinator` compares verbatim) and enqueues the replacement inheriting
`force_full`.

**Any push to `main` deploys, and a deploy kills a running full rebuild.** Recorded
because knowing the rule did not stop me breaking it: `deploy.yml` fires on a successful
CI run over a `push` to `main`, so a documentation-only commit restarts both dynos exactly
as a code change does. On 2026-09-09 a commit whose own text said "shipping releases
through one is a losing race" orphaned the third consecutive rebuild. Before starting a
full rebuild, finish merging.

**It prevents loss, not repetition, and that is deliberate.** The replacement starts at
`clone_or_pull`, because `force_full` is inherited and a full rebuild has no checkpoint to
resume from — only a clean run reconciles what `save_incremental` merges by FILE, which is
the whole reason the rebuild was full. So a full rebuild still needs an uninterrupted
window, and shipping releases through one is a losing race: observed 2026-09-09, three
consecutive runs orphaned at 63%, 33% and 33% of the way. What blunts the cost is the
document cache — each attempt regenerates fewer documents than the last, because every one
it finished recorded its `content_hash`. Verified in production: `1 put back` at 07:27:41
and again at 08:04:45, both carrying `ORPHAN_ERROR` so neither spent the reaper's budget,
and the replacement started 36 s after the first — against 300 s of waiting followed by a
refusal.

Second, `_requeue_attempts` no longer counts a reap whose run started under a different
release. An unstamped run still counts — unknown means counted, or the bound stops
bounding.

Ownership matters because `index_repo` runs on **both** process types: the queue path on
`worker`, the manual route on `web`. A worker sweeping the web dyno's runs would kill an
index that is running perfectly.

**A reaped `index_repo` is now put back (2026-08-31).** The reaper destroyed the run and
re-enqueued nothing, which most kinds survive — the nightly cron re-runs them. `index_repo`
does not: `reconcile_embeddings` advances the `embedding_fingerprint` marker on **enqueue**,
so a deploy restarting the worker mid-rebuild leaves a marker asserting the rebuild
happened, and the nightly cron is `force_full=False` and cannot redo what only a clean run
does. `StaleRunReaper._requeue` re-enqueues it, inheriting `force_full` from the run's
`meta_json`, bounded at `reaper_requeue_max_attempts` (2) per `reaper_requeue_window_hours`
(6) and counted from rows carrying `REAP_ERROR` — a run failing on its own merits does not
spend the budget, and an unreadable count returns the bound rather than zero. Only that
kind, because `run_repo_index` runs `generate_docs` through an LLM and the worker is the
memory-constrained process.

**The nightly sync now says when it nearly ran out of night (T06, 2026-09-09).** The
longest COMPLETED `daily_sync` on production took **7 214.9 s** against
`daily_knowledge_sync_job_timeout_seconds` = 7 200 — it finished by luck, and nothing said
so. ARQ's timeout does not warn on the way up, it cancels, so the first symptom of a
repository outgrowing the budget is a night that simply did not sync, with the run before
it looking exactly like a success. `budget_warning()` logs at WARNING above
`BUDGET_WARNING_FRACTION` (0.85) of the budget and increments
`daily_sync_budget_near_ceiling_total`.

A **fraction**, not a second threshold constant: a hard-coded alarm beside a configurable
limit fails both ways — raise the ceiling and it fires on every ordinary run until someone
deletes it, lower the ceiling and it never fires again. The timeout is read at the moment
of the check, so a run that outlives a config change is judged against the ceiling that is
actually about to cancel it. A non-positive timeout degrades **quiet**, because an alarm on
every run trains the operator to ignore the one that matters. This is a different ceiling
from `repo_index_job_timeout_seconds` (21 600) — see the two-ceilings note above.

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

Conventional commits: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `perf`, `security`. Branches: `feat/`, `fix/`, `refactor/`, `docs/`, `test/`, `chore/`. CI must be green; coverage must not drop below 80%. See `CONTRIBUTING.md`.

**A conflicted PR runs no checks at all, and its page looks identical to one whose checks have not started yet (measured 2026-09-11).** GitHub evaluates `pull_request` workflows against `refs/pull/N/merge`, which does not exist while the merge is conflicted — so `gh pr checks` answers *"no checks reported"*, the PR shows no red, and nothing is running. Two PRs sat like that for half an hour before the cause was found; closing and reopening did not help, and neither did an empty commit, because neither addresses the conflict. **Rebase first, then look for the run.**

What made it certain rather than unlucky: **every PR prepends to the same `## [Unreleased]` heading in `CHANGELOG.md`**, so the first one to merge conflicts all the others by construction. With several in flight that is not a risk, it is a guarantee. Either serialise the merges, or keep the changelog entry out of the feature branch and add it in one pass afterwards — and if a branch is cut from another feature branch rather than from `main`, it inherits that branch's conflicts as well, which is its own reason to always name the base: `git checkout -b <new> main`.

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
| UX funnels & drop-off points | `docs/ux/flows.md` (FLW-01–FLW-05, data-onboarding scope) |
| UX screen/state map | `docs/ux/screens.md` (SCR-01–SCR-09) |

## UX scenarios — hard rule (super-ux)

- `docs/ux/scenarios.md` is the source of truth for all user-facing behavior.
- **The chain now has three layers, and they are not equally complete.**
  `scenarios.md` covers the whole product (**153 scenarios; 141 `implemented`, 12
  `draft`** — measured 2026-09-12 by `make ux-status`, and asserted by
  `test_the_ux_base_checks_all_three_documents.py`, because the previous figure
  here said 151/128/23 while the generated block in the document itself counted
  153/141/12 and nothing compared the two). `flows.md` (FLW-01–05) and `screens.md` (SCR-01–10) were added
  2026-09-07 and cover **only the data-onboarding scope** — adding a project,
  connecting sources and repositories, describing them, refreshing the docs, and the
  sidebar rail every flow starts from. Outside that scope there is no flow layer, so
  a scenario there carries no `Traces:` and that is correct rather than missing.
- **A scenario id may carry a lowercase suffix, and the tooling used to miss it.**
  `SCN-101a` matched neither `_ROW` in `scripts/ux_verification_status.py` nor
  either regex in the format test, so it was absent from every count and unchecked
  on both sides of the body/index pairing. Invisible while it read `implemented`
  like its neighbours; a wrong status the moment it changed. Both now accept
  `SCN-\d+[a-z]?`. Related: a draft's Index audit cell must be bare `—`. A date or
  a `PASS` there is counted as a live verification, so parking history in that cell
  makes a draft read as verified — the history goes in the body.
- **Run `make ux-status` AFTER staging, never before.** The block's
  *Referenced from code or tests* figure comes from `git grep`, which sees only
  TRACKED files — so a new test that names a scenario is invisible until it is
  added, and a block generated before `git add` disagrees with the table the
  moment the commit lands. `test_the_block_agrees_with_the_table_it_summarises`
  then fails on a tree where nothing is actually wrong.
- **The index table stays at six columns.** `scripts/ux_verification_status.py`
  reads status and last-audit by position, so a `Traces` column would silently
  shift both. New scenarios carry `Traces:` in the body instead.
- **A `draft` row owes no audit date or verdict.** `test_ux_scenarios.py`
  demanded one from every row, which left a designed-but-unbuilt scenario two ways
  to pass and made the cheaper one a `PASS` nobody measured. Scoped to statuses
  that claim something was built; drafts are still counted under *Never verified*.
- Any change that touches user-facing behavior MUST update
  `docs/ux/scenarios.md` in the same change (add/adjust scenarios, statuses,
  coverage).
- Any new feature or project STARTS with scenarios: draft them, validate
  against existing scenarios (conflicts, overlaps, gaps), get them approved —
  only then design and build UI.
- Use the `ux-scenarios` skill to maintain the base and `ux-audit` to verify
  the codebase against it.
