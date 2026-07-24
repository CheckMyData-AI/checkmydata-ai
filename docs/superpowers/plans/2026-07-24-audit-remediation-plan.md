# Audit Remediation 2026-07-24 — Implementation Plan

Spec: `docs/superpowers/specs/2026-07-24-audit-remediation-design.md`
Branch: `fix/audit-remediation-2026-07-24`
Method: TDD per task (failing test → fix → green). No `git push`. Conventional
commits per batch, authored by the orchestrator after each wave's tests pass.

## Wave 1 (parallel, disjoint file sets)

| Batch | Owns (files/dirs) | Tasks |
|---|---|---|
| B1 | `app/connectors/{mongodb,clickhouse}.py`, `app/core/{safety,explain_validator}.py`, `app/services/session_notes_service.py` + their tests | FA-001 mongo truthiness; B2 CH timeout reset; B3 EXPLAIN indexes=1; B4 mongo guard ops; SQLite `greatest` |
| B2 | `app/api/routes/chat_feedback.py`, `app/api/routes/connection_learnings.py`, `app/services/agent_learning_service.py`, `app/agents/{result_handler,sql_prompt}.py`, `app/agents/data_gate.py`, `app/agents/answer_validator.py`, `app/services/sql_result_reconciliation.py` + tests | AQ-1 idempotent downvote; AQ-7 per-user vote dedup (+migration); AQ-2 untrusted framing; AQ-4/5 coercion; AQ-9 verdict parse; AQ-10 float tol + un-xfail DATA-15 |
| B3 | `app/knowledge/repo_url.py`, `app/config.py`, `backend/.env.example`, `app/api/routes/{billing,schedules,data_investigations,chat}.py`, `backend/pyproject.toml` | FA-004 SSRF guard + `repo_allow_private_hosts`; env fail-closed; 5 rate limits; gitpython/mcp bumps |
| B4 | `app/services/{run_coordinator,stale_run_reaper}.py`, `app/knowledge/pipeline_runner.py`, `app/worker.py`, `app/api/routes/connections.py` | FA-007 reap reconcile; FA-008 intra-step heartbeats; RES-3 dup-dispatch; 422→400 |
| B5 | `frontend/src/**`, `frontend/package*.json`, `docs/ux/scenarios.md` | FA-010 flash toast; LogsScreen banners; SCN-041/054/077; next bump + audit fix + msw removal + lazy remark-gfm |

DoD per batch: each fix has a regression test; targeted test files pass;
`ruff check` clean on touched files; frontend batch also `tsc` + `eslint` +
`vitest` green; no files outside the batch's ownership modified.

## Wave 2 (after wave 1 merges into the branch)

| Batch | Owns | Tasks |
|---|---|---|
| B6 | `alembic/versions/` (new), `app/api/routes/{notes,dashboards,data_graph,repos,logs}.py`, `app/models/*.py` (index defs) | index migration (round-trip verified); pagination bounds; `logs.py:168` 400→404 |

DoD: `alembic upgrade head` + `downgrade -1` + `upgrade head` on scratch DB;
targeted route tests pass.

## Stage 6–9

1. Full backend suite (`tests/unit` + `tests/integration` with coverage) —
   green, coverage ≥ 72%.
2. Frontend `vitest run` + `tsc --noEmit` + `eslint --max-warnings=0` — green.
3. `ruff check` + `ruff format --check` + `mypy` — clean.
4. `pip-audit` + `npm audit` — confirm closed CVEs; residual documented.
5. Docs sync: `CHANGELOG.md` [Unreleased] remediation entry,
   `docs/qa-audit/issues.md` + `11-findings-registry.md` statuses → FIXED
   with commit refs, `docs/agent-status.md` refresh.
6. Final report to operator: per-finding status, test evidence, deferrals.

Rollback plan: branch is additive; any batch can be dropped by reverting its
commit without touching the others.
