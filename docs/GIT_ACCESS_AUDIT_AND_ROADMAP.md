# Live Git Access — Architecture Audit & Roadmap

This document captures the architecture audit that informed the **Live Git
Access + Release Cohort Analysis** work (Phase 1, delivered) and the phased
roadmap for follow-up improvements to the orchestrator and the system as a
whole. It complements [SYSTEM_ARCHITECTURE.md](SYSTEM_ARCHITECTURE.md) (§7.9
Live Git Access, §8.6 Git-Driven Cohort Analysis) and the project tracker
([Linear — CheckMyData.ai](https://linear.app/sshlg/project/checkmydataai-b7670b0dd990),
Epic **SSH-251**).

## 1. Context

Before this work the orchestrator could reason over **two** knowledge sources:

- the user's **MySQL/Postgres/Mongo/ClickHouse** databases (via `SQLAgent`), and
- a **static snapshot** of the code repository indexed into ChromaDB (via
  `KnowledgeAgent` / the M1–M6 code-intelligence pipeline).

It had **no live Git access** — it could not read the actual commit graph,
diffs, blame, or releases at query time, and therefore could not perform commit
or review analysis, nor correlate releases with downstream business metrics.

The goal of Phase 1 was to (a) give the agent read-only, security-hardened
access to the local Git clone, and (b) bridge **releases → cohort metrics**
(7- and 14-day retention/revenue) so questions like *"how did retention move
after each release?"* are answerable end-to-end.

## 2. Architecture Audit

The design was validated against several engineering perspectives. Findings are
summarized below; each maps to a roadmap phase.

### 2.1 Retrieval / RAG (`rag-architect`)

- **Strong today:** hybrid retrieval (BM25 ⊕ ChromaDB merged via Reciprocal
  Rank Fusion), `RAGFeedback` capture, soft timeouts with single-leg
  degradation, and question-aware schema retrieval.
- **Gaps:** no cross-encoder **reranker** after fusion; no automated
  **RAGAS-style evaluation** in CI; no **temporal metadata** on chunks (so the
  KB cannot itself answer "what changed recently").
- **Decision:** Live Git Access closes the *temporal* gap operationally — the
  agent reads the live history directly rather than relying on stale embeddings,
  and a **clone-freshness warning** tells the LLM when the semantic KB lags the
  working tree. Reranker + RAGAS deferred to **Phase 2**.

### 2.2 Data Engineering (`senior-data-engineer`)

- The `cohort_window` operation is **dimensional modeling in miniature**:
  releases are a *dimension* joined to *fact* rows (events) over time windows.
- Reuse the existing **DataGate** quality checks to validate cohort outputs
  (non-empty windows, parseable dates, column presence) before synthesis.
- Robust date parsing (ISO + fallbacks, tz-naive normalization, unparseable
  rows skipped and counted in the summary) prevents silent miscounts.

### 2.3 ML / LLM Ops (`senior-ml-engineer`)

- **Strong today:** `LLMRouter` with retry, provider fallback, cost accounting,
  and response caching is solid and well-tested.
- **Gaps:** no **answer-quality monitoring** (LLM-as-judge on a sample of
  production answers) and no **router regression suite** to catch routing
  drift. Deferred to **Phase 4**.

### 2.4 Engineering Practices (`engineering-skills` / `engineering-advanced-skills`)

- **Handoff contracts:** `GitAgent` ↔ `SQLAgent` ↔ `DataProcessor` exchange
  plain dicts/markdown, never raw library objects — keeps stages composable and
  testable.
- **Observability:** add Git op timings to `MetricsCollector` (Phase 2) so Git
  latency is visible alongside SQL/RAG.
- **Security (secops):** read-only enforcement, explicit GitPython arg lists (no
  shell), path-traversal guard, output/count caps, and no hook execution — see
  SYSTEM_ARCHITECTURE §7.9.
- **Code review angle:** Phase-1 "review analysis" is derived from commit
  metadata (`review_signals`): merge detection, co-authors, reviewers, and
  `Signed-off-by` trailers. Hosting-platform PR APIs are **Phase 3**.

## 3. Roadmap

| Phase | Scope | Status |
|-------|-------|--------|
| **Phase 1** | `GitInspector` + `GitAgent`, single-loop **and** full pipeline wiring (`analyze_git` stage), `cohort_window` data op, `code_finding` insights, security hardening, tests + docs | ✅ Delivered (Epic SSH-251) |
| **Phase 2** | Cross-encoder reranker after RRF; RAGAS evaluation harness in CI; temporal RAG metadata; Git op timings in `MetricsCollector`; multi-repo-per-project selection | Planned |
| **Phase 3** | GitHub/GitLab API connector for **real PR/review analytics** (reviewers, approvals, review latency, comment threads) + webhooks for push-driven re-index | Planned |
| **Phase 4** | Answer-quality monitoring (LLM-as-judge sampling) + router regression suite to catch routing/quality drift | Planned |

## 4. Phase 1 — What Shipped

- **`GitInspector`** (`backend/app/knowledge/git_inspector.py`) — async,
  read-only GitPython service: `log`, `show`, `diff`, `blame`, `list_releases`,
  `authors_stats`, `file_churn`, `commits_touching`, `review_signals`. Typed
  error taxonomy; edge-case safe (empty/unborn-HEAD repo, missing clone, bad
  SHA, binary, non-UTF-8, no tags).
- **`GitAgent`** (`backend/app/agents/git_agent.py`) — sub-agent mirroring
  `KnowledgeAgent`; clone-freshness warning, opt-in auto-pull, deterministic
  `get_release_timeline` + `write_code_note` helpers.
- **Single-loop wiring** — `analyze_git`, `get_release_timeline`,
  `write_code_note` meta-tools gated by a fast `has_repo` capability probe; new
  `git` router route (downgrades to `explore` without a clone).
- **Pipeline wiring** — `analyze_git` is a first-class planner stage executed by
  `StageExecutor._run_git_stage`, enabling the release→cohort recipe.
- **Release → cohort bridge** — `cohort_window` op in `DataProcessor` computes
  7/14-day retention or revenue per release; structured `params_json` passes the
  release dates and column mapping through `process_data`.
- **Code findings** — persisted as `code_finding` insights (Insight Memory) and
  auto-injected into future prompts.
- **Security + config** — read-only hardening plus config knobs
  (`git_agent_auto_pull`, `max_git_iterations`, `git_max_output_bytes`,
  `git_max_log_count`, `git_clone_pull_timeout_s`).

## 5. Assumptions & Limits (Phase 1)

- "Review analysis" = commit-trailer / merge / author signals; hosting-platform
  PR/review APIs are Phase 3.
- All Git operations are strictly read-only; auth reuses the existing SSH-key
  mechanism.
- Phase 1 targets the canonical `repo_clone_base_dir / project_id` clone;
  per-repo selection for multi-repo projects is a Phase 2 refinement.
