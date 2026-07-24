# Agent Status

## Current Snapshot

| Field | Value |
|-------|-------|
| Date | 2026-07-24 |
| Version | 1.15.1 (commit `e695caa`, branch `main`) |
| Basis | Full repository audit — [`docs/qa-audit/full-audit-2026-07-24/`](qa-audit/full-audit-2026-07-24/) (10 reports: baseline, traceability, API contract, UX verification, live E2E, cross-DB, agent quality, security, resilience, performance) |

This file is a point-in-time snapshot, refreshed by the 2026-07-24 full audit. It replaces the
stale Cycle 7 snapshot (2026-03, 2487 unit / 410 int / 72.03%).

## Health Summary

| Check | Status | Details |
|-------|--------|---------|
| Backend Unit + Integration (pytest) | PASS | 5439 passed + 4 skipped + 2 xfailed, 0 failed (~5445 collected) |
| Backend Coverage (combined) | 77.74% | CI gate: 72% |
| Backend Ruff Lint | PASS | 0 violations |
| Backend Ruff Format | PASS | 775 files |
| Backend Mypy | PASS | 0 errors; 4 `annotation-unchecked` notes (`connectors/clickhouse.py:284`, `knowledge/vector_store.py:124`, `api/routes/chat.py:923,947`) |
| Frontend Tests (Vitest) | PASS | 526/526 (75 files) |
| Frontend TypeScript / ESLint | PASS | per CI |
| UX scenario verification | PASS | 112/112 scenarios verified against code: 109 PASS / 3 PARTIAL (SCN-041 auto-growing textarea, SCN-054 per-step elapsed, SCN-077 Cancel in create-rule modal) |
| Total tests | ~5,970 | 5,445 backend + 526 frontend |

## Changes Since the Last Snapshot (2026-03 → 2026-07)

- **`[1.14.0]`** — production hardening: billing (Stripe plans/quotas), cookie auth (httpOnly + CSRF), MCP/SSH hardening, Redis-backed rate limits, Sentry.
- **`[1.15.0]`** — intelligence remediation (W0–W6): data-quality honesty, hybrid retrieval + ContextPack, orchestrator termination + path unification, DB schema-capture depth, code↔DB trust signals, code-graph correctness, self-completing embedding reconcile.
- **`[1.15.1]`** — embedding-loader log hygiene + infra guidance.
- **UX audit remediation (2026-07-19)** — email verification (F-PROJ-01), forgot/reset password (F-AUTH-13), decline invite, dashboard delete + batch results view, honesty sweep, logout toast. See `CHANGELOG.md` [Unreleased].
- **Security release R3 (2026-06-25, `fbf8112`)** — cross-tenant isolation & IDOR sweep (F-RULE-01/05, F-DG-07/09, F-GRAPH-01, F-SSH-08/06, F-LEARN-07). **0 open High findings** in `docs/qa-audit/issues.md`.

## Known Issues (as of 2026-07-24)

1. **CRITICAL — MongoDB connector broken with real motor** — `if not self._db` raises `NotImplementedError` (motor `Database` forbids truthiness); connect/execute paths fail against a real MongoDB 7 without a monkeypatch. See `05-cross-db.md` (B1).
2. **Live LLM golden path unverified** — `OPENROUTER_API_KEY` in `backend/.env` is invalid (401 "User not found"), `OPENAI_API_KEY`/`ANTHROPIC_API_KEY` empty; all LLM calls fail auth, so live E2E covered only graceful-degradation paths. Rotate keys and rerun flows 5/6/13. See `04-e2e-live.md`.
3. **Security audit: 3 High open** (`07-security.md`) — S-01 SSRF via git URL (`validate_repo_url` doesn't block loopback/private hosts, `knowledge/repo_url.py:47-66`); S-02 `next@15.5.12` HTTP request smuggling (GHSA-ggv3-7p47-pfv8, upgrade Next); S-03 root `.env.local` carries default `JWT_SECRET=change-me-in-production` + `DEBUG=true` (untracked file; fix before any real deploy).
4. **Vulnerable dependencies** — backend: `gitpython 3.1.50`→3.1.51, `mcp 1.27.2`→1.28.1, `pyasn1 0.6.3`→0.6.4, `chromadb 1.5.9` (no fix), `ecdsa` (transitive, no fix); frontend: `sharp`, `postcss`, `fast-uri`, `brace-expansion` (all have fixes). Details: `07-security.md` S-05/S-06.
5. **AQ-1 (High) — negative feedback not idempotent** — repeated 👎 on the same message re-punishes exposed learnings and pumps a garbage lesson (viewer-reachable). Tracks F-LEARN-08 in `docs/qa-audit/issues.md`. See `06-agent-quality.md`.
6. **Low-coverage hot spots** — `billing_service.py` 49%, `trace_persistence_service.py` 52%, `worker.py` 56%; no HTTP tests for billing checkout/portal/webhook routes. See `00-baseline.md`.
7. **God files / maintainability (CB-M4)** — `agents/orchestrator.py` (2,525 LOC), `agents/sql_agent.py` (2,017), `knowledge/pipeline_runner.py` (1,769), `api/routes/chat.py` (1,724). High blast radius; decomposition tracked in `docs/qa-audit/issues.md` §7.
8. **API.md documentation drift** — 65 endpoints undocumented (Billing, Connection Learnings, Runs, Health Monitor sections missing entirely). Pointer note added to `API.md`; full list in `02-api-contract.md`. Full regeneration of API.md is a separate owed task.
9. **notes.md credentials** — file is **no longer on disk** (verified 2026-07-24, `07-security.md` S-08); credentials that were in it are still formally compromised — rotation remains owed.
10. **Old "dead code" claim — resolved** — previously flagged `exploration_engine.py:326` / `cli_output_parser.py:38` sites checked 2026-07-24: `exploration_engine.py` now lives at `backend/app/core/exploration_engine.py` and both sites are live code. No dead code at those locations.

## Next Priorities

1. Fix the MongoDB connector truthiness bug (05-cross-db B1) + ClickHouse post-timeout session wedge (B2).
2. Rotate LLM API keys, then rerun the live golden-path E2E (chat ask, indexing enrichment).
3. Dependency upgrades: Next.js (S-02), gitpython/mcp/pyasn1 (S-05), frontend `npm audit fix` (S-06).
4. Env hygiene: strong `JWT_SECRET` + explicit `ENVIRONMENT` in `.env.local` (S-03/S-04).
5. Coverage push on billing / worker / trace-persistence; add billing route HTTP tests.
