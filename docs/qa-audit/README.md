# CheckMyData.ai — QA Deep-Audit Plan & Tracker

> **Purpose.** A recurring, module-by-module **bug / inaccuracy / bad-decision hunt** across
> every business module. Distinct from [`docs/MASTER_TEST_PLAN.md`](../MASTER_TEST_PLAN.md)
> (which catalogues test-coverage gaps) — this audit reads the *code and docs* looking for
> real defects, security issues, design smells, and dev/prod parity traps, and records each
> with a concrete proposed fix.
>
> **Loop.** Round 1 sweeps every module once. Round 2+ re-sweeps each module looking for what
> earlier rounds missed and goes deeper. Findings accumulate in per-module reports under
> [`reports/`](reports/). Nothing here is committed automatically — these are analysis artifacts.

## Methodology (per module, per round)

1. **Docs pass** — read the module's documented contract (CLAUDE.md, `API.md`, `docs/*`,
   `vision.md` invariants) and note what it *claims* to do.
2. **Code pass** — read the actual implementation (routes → services → models → connectors).
3. **Hunt** — bugs, race conditions, error-handling gaps, security holes, dev/prod parity
   traps, vision-invariant violations, perf foot-guns, and doc↔code mismatches.
4. **Report** — append findings to `reports/NN-<module>.md`. Each finding is self-contained:
   id, severity, type, `file:line`, description, impact, **concrete proposed fix**, status.
5. **Track** — update the status table below.

## Severity scale

| Sev | Meaning |
|-----|---------|
| 🔴 Critical | Exploitable / data-loss / breaks a `vision.md §7` invariant in prod |
| 🟠 High | Security weakness, correctness bug on a common path, or silent data corruption |
| 🟡 Medium | Bug on an edge path, design flaw, dev/prod parity trap, missing hardening |
| 🟢 Low | Minor inaccuracy, polish, defensive-coding gap |
| ⚪ Info | Observation / test-gap / doc mismatch, no direct user impact |

Finding id format: `F-<MODULE>-NN` (e.g. `F-AUTH-01`).

## Module map & status

Modules derive from the route/agent/connector decomposition (CLAUDE.md "API surface" +
`backend/app/`). Each row tracks the latest round that swept it and the open-findings count.

| # | Module | Scope (primary code) | R1 | R2 | Open findings |
|---|--------|----------------------|----|----|---------------|
| 01 | **Auth & Session** | `routes/auth.py`, `services/auth_service.py`, `core/auth_cookies.py`, `api/deps.py`, `routes/mcp_tokens.py` | ✅ | ✅ | 12 |
| 02 | **Projects, RBAC & Invites** | `routes/projects.py`, `project_member`, `routes/invites.py`, `services/invite_service.py`, `deps.py` membership | ✅ | ✅ | 12 |
| 03 | **Connections & Connectors** | `routes/connections.py`, `connectors/{postgres,mysql,clickhouse,mongodb,base}.py`, `services/connection_service.py` | ✅ | ✅ | 9 |
| 04 | **SSH Tunnel & Keys** | `connectors/ssh_*.py`, `routes/ssh_keys.py`, `services/ssh_key_service.py` | ✅ | — | 7 |
| 05 | **Chat & Orchestration** | `routes/chat*.py`, `agents/orchestrator.py`, `adaptive_planner.py`, `stage_executor.py`, `workflows.py` | 🔄 | — | 6 |
| 06 | **SQL Agent & Query Exec** | `agents/sql_agent.py`, `query_planner.py`, query execution path | ✅ | — | 5 |
| 07 | **Knowledge & Indexing** | `knowledge/pipeline_runner.py`, `routes/repos.py`, BM25/schema embed, code graph, lineage, clustering | 🔄 | — | 5 |
| 08 | **GitAgent (live Git)** | `agents/git_agent.py`, `GitInspector`, path-traversal guards | ✅ | — | 3 |
| 09 | **Data Validation / Investigations / DataGate** | `agents/data_gate.py`, `investigation_agent.py`, `routes/data_validation.py`, `data_investigations.py`, `reconciliation.py` | 🔄 | — | 6 |
| 10 | **Insights & Learning memory** | `routes/insights.py`, `feed.py`, `connection_learnings.py`, `services/agent_learning_service.py` | 🔄 | — | 5 |
| 11 | **Rules engine** | `routes/rules.py`, `knowledge/custom_rules.py`, rule injection/validation | ✅ | — | 4 |
| 12 | **Visualizations & Dashboards** | `routes/visualizations.py`, `dashboards.py`, `agents/viz_agent.py` | 🔄 | — | 3 |
| 13 | **Schedules, Batch & Worker** | `routes/schedules.py`, `batch.py`, `worker.py`, `core/task_queue.py`, StaleRunReaper | 🔄 | — | 6 |
| 14 | **Billing & Entitlements** | `routes/billing.py`, `usage.py`, `EntitlementService`, Stripe webhooks | 🔄 | — | 4 |
| 15 | **MCP Server** | `mcp_server/`, `routes/mcp_tokens.py`, ASGI mount, per-request principal | 🔄 | — | 4 |
| 16 | **Notifications, Notes & Feed** | `routes/notifications.py`, `notes.py`, `feed.py` | 🔄 | — | 3 |
| 17 | **LLM routing & Observability** | `llm/router.py`, `routes/metrics.py`, `logs.py`, `health_monitor.py`, Sentry, tracing | 🔄 | — | 4 |
| 18 | **Semantic layer / Data graph / Temporal / Exploration** | `routes/semantic_layer.py`, `data_graph.py`, `temporal.py`, `exploration.py`, `models.py`, `demo.py` | 🔄 | — | 4 |
| 19 | **Frontend SPA** | `frontend/src/stores/*`, `ChatPanel`, dashboard, auth flow, marketing | ✅ | — | 3 |

Legend: ✅ swept this round · 🔄 in progress · ⬜ pending · — n/a yet

## Round log

- **Round 1** — started 2026-06-23. Sweeping modules 01→19 once each.
  - 01 Auth & Session — done → [`reports/01-auth-session.md`](reports/01-auth-session.md) (10 findings; 1 High parity trap, 4 Medium).
  - 02 Projects, RBAC & Invites — done → [`reports/02-projects-rbac-invites.md`](reports/02-projects-rbac-invites.md) (9 findings; 1 High access-harvest, 5 Medium).
  - 03 Connections & Connectors — done → [`reports/03-connections-connectors.md`](reports/03-connections-connectors.md) (7 findings; 2 High read-only-invariant, 3 Medium). **Theme: read-only §7 invariant rests on a bypassable regex, not DB-level enforcement.**
  - 04 SSH Tunnel & Keys — done → [`reports/04-ssh-tunnel-keys.md`](reports/04-ssh-tunnel-keys.md) (7 findings; 2 Medium: TOFU fail-open, ClickHouse password in argv). Ruled out config command-injection (escaping present) and private-key exposure (not returned).
  - 05 Chat & Orchestration — **first pass** (🔄 deep internals deferred to R2) → [`reports/05-chat-orchestration.md`](reports/05-chat-orchestration.md) (6 findings; 3 Medium: WS revocation-until-disconnect, orphan sessions, relay 60s stall). Verified strong: WS ticket auth, limiter balance, replan cap, budget gate.
  - 06 SQL Agent & Query Exec — done → [`reports/06-sql-agent-query-exec.md`](reports/06-sql-agent-query-exec.md) (5 findings; 3 Medium: prompt-injection via DB content, row_count accuracy, retry blow-up). Verified strong: agent path is ValidationLoop-guarded, EXPLAIN is non-executing, safety block non-retryable.
  - 07 Knowledge & Indexing — **first pass** (🔄 pipeline/resume deferred to R2) → [`reports/07-knowledge-indexing.md`](reports/07-knowledge-indexing.md) (5 findings). 🔴 **CRITICAL F-KNOW-01: RCE via unvalidated `repo_url` git transport (`ext::`/`file://`/SSRF) — no transport allowlist anywhere (confirms obs 21201).** Also git-SSH `StrictHostKeyChecking=no`.
  - 08 GitAgent (live Git) — done → [`reports/08-git-agent.md`](reports/08-git-agent.md) (3 findings; 1 Medium: unvalidated rev/sha → `git show/diff --output=<file>` file-write read-only bypass). Verified strong: path-traversal guard, byte caps, arg-lists, `--` path separation.
  - 09 Data Validation / Investigations / DataGate — **first pass** (🔄 routes deferred to R2) → [`reports/09-data-validation-investigations-datagate.md`](reports/09-data-validation-investigations-datagate.md) (6 findings; 4 Medium: `Decimal` bypasses hard-check, sample-only range check, fuzzy-classification hard-fail, JSON-cell crash). Verified strong: hard checks on by default, investigation bounded + SafetyGuard'd.
  - 10 Insights & Learning memory — **first pass** (🔄 route authz deferred to R2) → [`reports/10-insights-learning-memory.md`](reports/10-insights-learning-memory.md) (5 findings; 2 Medium: stored prompt-injection via lessons, non-ASCII gate rejects CJK). Verified strong: per-connection scoping enforced, tiered decay matches spec.
  - 11 Rules engine — done → [`reports/11-rules-engine.md`](reports/11-rules-engine.md) (4 findings). 🟠 **HIGH F-RULE-01: no authz on global (`project_id=null`) rule creation + `list_all` unions globals into every project → any user injects authoritative instructions cross-tenant.** Verified clean: no unsafe YAML, project rules require editor+membership.
  - 12 Visualizations & Dashboards — **first pass** (🔄 export/frontend XSS deferred to R2/M19) → [`reports/12-visualizations-dashboards.md`](reports/12-visualizations-dashboards.md) (3 findings; 2 Medium: snapshot staleness, `cards_json` stored-XSS vector). Verified strong: no public endpoint, all routes auth+membership gated.
  - 13 Schedules, Batch & Worker — **first pass** (🔄 run_batch/run_coordinator deferred to R2) → [`reports/13-schedules-batch-worker.md`](reports/13-schedules-batch-worker.md) (6 findings; 4 Medium: schedule revocation gap, viewer-runs-raw-SQL batch, NULL-heartbeat reap race, ARQ→in-process web-dyno fallback). Verified strong: schedules auth, multi-dyno single-flight, task_queue fallback hygiene.
  - 14 Billing & Entitlements — **first pass** (🔄 usage/quota-site verification deferred to R2) → [`reports/14-billing-entitlements.md`](reports/14-billing-entitlements.md) (4 findings; 2 Medium: stale-metadata plan resolution, quota TOCTOU). **Verified strong: webhook signature fails-closed, race-safe idempotency, atomic retry-correct apply, server-set checkout identity.**
  - 15 MCP Server — **first pass** (🔄 resources/key-service deferred to R2) → [`reports/15-mcp-server.md`](reports/15-mcp-server.md) (4 findings). 🟠 **HIGH F-MCP-01: MCP agent runs check the token budget but never RECORD usage → budget/billing token limits bypassed via MCP (live in prod).** Also no `agent_limiter` (concurrency bypass). Verified strong: per-request principal isolation (pure-ASGI ContextVar), no server-key fall-through, per-tool `can_access`.
  - 16 Notifications, Notes & Feed — **first pass** (🔄 feed agent deferred to R2) → [`reports/16-notifications-notes-feed.md`](reports/16-notifications-notes-feed.md) (3 findings, all Low/Info). **Comparatively clean** — notifications strictly user-scoped (no IDOR), notes access-controlled, `execute_note` cross-project-guarded + SafetyGuard'd.
  - 17 LLM routing & Observability — **first pass** (🔄 trace-scoping/logs deferred to R2) → [`reports/17-llm-routing-observability.md`](reports/17-llm-routing-observability.md) (4 findings; 1 Medium: silent cross-provider fallback → data governance). **Largely solid** — failover semantics, Sentry PII/secret scrubbing, admin-gated metrics.
  - 18 Semantic/Graph/Temporal/Exploration/Models/Demo — **first pass** (🔄 per-handler role review deferred to R2) → [`reports/18-semantic-graph-temporal-exploration.md`](reports/18-semantic-graph-temporal-exploration.md) (4 findings; 1 Medium: demo project is `:memory:` SQLite with no seeding → empty demo). Verified: routes auth-gated, models endpoint doesn't leak API key.
  - 19 Frontend SPA — done → [`reports/19-frontend-spa.md`](reports/19-frontend-spa.md) (3 findings; 1 Medium: failing Vitest tests). **Frontend security strong** — react-markdown no-raw-html, http(s)-only links, no JWT in localStorage, correct CSRF double-submit → **downgrades F-VIZ-02 stored-XSS**.

### ✅ Round 1 complete — 2026-06-24

**19/19 modules swept · ~98 findings.** Severity tally: **1 Critical, 3 High, ~30 Medium**, rest Low/Info.

**Top findings (fix-first):**
1. 🔴 **F-KNOW-01** — RCE via unvalidated `repo_url` git transport (`ext::`/`file://`/SSRF); no allowlist anywhere.
2. 🟠 **F-RULE-01** — no authz on global (`project_id=null`) rule creation → cross-tenant prompt injection into every project.
3. 🟠 **F-MCP-01** — MCP agent runs never record token usage → token-budget/billing bypass (live in prod).
4. 🟠 **F-CONN-01/02** — read-only §7 invariant rests on a bypassable regex at scattered call-sites, not DB-level enforcement.
5. 🟡 **F-AUTH-01** — SQLite FK enforcement off → all `ondelete=CASCADE` are no-ops in dev/test (orphaned encrypted secrets; tests pass-for-nothing).

**Cross-cutting themes (for Round 2 deep dives):**
- **Read-only enforcement chokepoint** — F-CONN-01/02, F-SQL-04, F-SCHED-02, F-NOTE-01 all share one root cause; a single connector/DB-level fix closes them.
- **Prompt-injection chain** — DB data (F-SQL-01) → persisted in learnings (F-LEARN-01) / rules (F-RULE-01) → influences all future answers.
- **git option/transport injection** — F-KNOW-01 (`ext::`), F-GIT-01 (`--output` file-write).
- **Silent error handling** — ~51 `except: pass` (F-CHAT-05, obs 21209) mask failures; honest-degradation principle.
- **Snapshot staleness** — dashboards (F-VIZ-01) / notes (F-NOTE-03) serve cached data without freshness signals (§7).

**Round 2 plan:** re-sweep 01→19, prioritising the 🔄 modules' deferred deep-dives (orchestrator internals, pipeline resume, run_batch guard, trace-scoping, per-handler roles) and hunting findings R1 missed.

- **Round 2** — started 2026-06-24.
  - 01 Auth & Session — done → +2 findings (F-AUTH-11 🟡 prod secret guard fails *open* unless `environment` exactly `production`/`prod`; F-AUTH-12 🟢 MCP tokens never expire by default). **Ruled out:** no `alg=none`/confusion (algorithms=[HS256]), prod secrets fail-closed via model_validator, MCP tokens check `is_active` (deactivation revokes MCP).
  - 02 Projects, RBAC & Invites — done → +3 findings (F-PROJ-10 🟡 no ownership transfer/co-owner → owner departure strands/destroys workspace; F-PROJ-11 🟢 `add_member` race → 500; F-PROJ-12 🟢 no self-service leave). **Ruled out:** `update` can't change `owner_id` (whitelist), owner can't be removed (no orphaning).
  - 03 Connections & Connectors — done → +2 findings (F-CONN-08 🟡 `QueryResult.error=str(e)` unredacted → DSN/password leaks to members+logs; F-CONN-09 🟢 agent connector cache FIFO/instance-scoped). **Ruled out:** ConnectionResponse excludes secrets (obs 21203), all connectors parameterize values, agent pool cache bounded+disconnects (F-CONN-07 mitigated).

## Report location note

Reports live in `docs/qa-audit/` (in-repo, alongside other audit docs). The original request
said to drop reports "где-нибудь в ндшне" — that location was ambiguous, so I chose the
in-repo audit tree for now. If you meant a specific folder (an Obsidian/notes vault, a `.nd`
dir, etc.), say so and I'll relocate the tree.
