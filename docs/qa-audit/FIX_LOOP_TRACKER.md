# QA Fix Loop — Tracker

> **What this is.** The autonomous remediation loop that consumes the per-module audit
> reports in [`reports/`](reports/) and fixes the findings. The audit agent keeps writing
> and extending the reports; this loop takes them one module at a time and drives each to
> production: **decompose → spec + plan → implement (logs + tests, TDD) → lint → deploy →
> verify no regressions → next module.**
>
> Source of truth for loop state. Each `/loop` wake-up reads this file to know which module
> and which phase it is on, then advances.

## Per-module cycle (phases)

| Phase | What happens | Gate to advance |
|-------|--------------|-----------------|
| **P0 Spec** | Read `reports/NN-*.md`, read the touched source, decompose every finding, write spec (`docs/superpowers/specs/2026-06-24-qa-fix-NN-*-design.md`) + plan (`docs/superpowers/plans/2026-06-24-qa-fix-NN-*.md`). Commit docs. | Spec + plan committed |
| **P1 Implement** | TDD per finding (failing test → fix → green). Add structured logs + audit entries. Frequent conventional commits. | All planned findings done, local tests green |
| **P2 Verify** | `make check` (ruff format check, ruff, mypy, full backend tests, coverage ≥ 72%); frontend `tsc + eslint + vitest` when frontend touched. | Full local CI parity green |
| **P3 Deploy** | Merge module branch → `main`, push (triggers Heroku auto-deploy). | Push succeeds, CI green |
| **P4 Post-deploy** | Verify prod health (`/api/health`), scan Heroku logs for new errors/regressions ("нет паков"). Mark module done; advance pointer. | Prod healthy, no new errors |

**Deploy safety:** deploy only at module boundaries, only after P2 is fully green locally.
Work happens on `fix/security-audit-2026-06-24`; P3 merges to `main`.

## Module order & status

Order = audit fix-first priority, then ascending module number. `▶` = current pointer.

| Order | Module | Report | Findings | Status | Phase |
|------:|--------|--------|---------:|--------|-------|
| ▶ 1 | 01 Auth & Session | [01](reports/01-auth-session.md) | 12 (2 High, 4 Med, 6 Low) | **in progress** | P0 |
| 2 | 07 Knowledge & Indexing | [07](reports/07-knowledge-indexing.md) | 5 (🔴 F-KNOW-01 RCE) | pending | — |
| 3 | 11 Rules engine | [11](reports/11-rules-engine.md) | 4 (🟠 F-RULE-01 cross-tenant) | pending | — |
| 4 | 15 MCP Server | [15](reports/15-mcp-server.md) | 4 (🟠 F-MCP-01 budget bypass) | pending | — |
| 5 | 03 Connections & Connectors | [03](reports/03-connections-connectors.md) | 7 (read-only invariant) | pending | — |
| 6 | 04 SSH Tunnel & Keys | [04](reports/04-ssh-tunnel-keys.md) | 7 | pending | — |
| 7 | 05 Chat & Orchestration | [05](reports/05-chat-orchestration.md) | 6 | pending | — |
| 8 | 06 SQL Agent & Query Exec | [06](reports/06-sql-agent-query-exec.md) | 5 | pending | — |
| 9 | 08 GitAgent | [08](reports/08-git-agent.md) | 3 | pending | — |
| 10 | 09 Data Validation / DataGate | [09](reports/09-data-validation-investigations-datagate.md) | 6 | pending | — |
| 11 | 10 Insights & Learning memory | [10](reports/10-insights-learning-memory.md) | 5 | pending | — |
| 12 | 12 Visualizations & Dashboards | [12](reports/12-visualizations-dashboards.md) | 3 | pending | — |
| 13 | 13 Schedules, Batch & Worker | [13](reports/13-schedules-batch-worker.md) | 6 | pending | — |
| 14 | 14 Billing & Entitlements | [14](reports/14-billing-entitlements.md) | 4 | pending | — |
| 15 | 16 Notifications, Notes & Feed | [16](reports/16-notifications-notes-feed.md) | 3 | pending | — |
| 16 | 17 LLM routing & Observability | [17](reports/17-llm-routing-observability.md) | 4 | pending | — |
| 17 | 18 Semantic/Graph/Temporal/Exploration | [18](reports/18-semantic-graph-temporal-exploration.md) | 4 | pending | — |
| 18 | 02 Projects, RBAC & Invites | [02](reports/02-projects-rbac-invites.md) | 9 | pending | — |
| 19 | 19 Frontend SPA | [19](reports/19-frontend-spa.md) | 3 | pending | — |

Legend: pending · in progress · done

## Change log (loop)

- **2026-06-24** — Loop initialized. Module 01 selected; spec + plan being written (P0).
