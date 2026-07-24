# Agent Status

## Current Snapshot

| Field | Value |
|-------|-------|
| Date | 2026-07-24 |
| Version | 1.15.1 (branch `fix/audit-remediation-2026-07-24`, head `fee7b49`) |
| Basis | Full repository audit + remediation — [`docs/qa-audit/full-audit-2026-07-24/`](qa-audit/full-audit-2026-07-24/) (10 reports: baseline, traceability, API contract, UX verification, live E2E, cross-DB, agent quality, security, resilience, performance; per-finding status in `11-findings-registry.md`) |

This file is a point-in-time snapshot, refreshed by the 2026-07-24 audit remediation (branch
`fix/audit-remediation-2026-07-24`, 8 commits). It replaces the audit-time snapshot taken
before the fixes (5,439 backend / 526 frontend tests, 77.74% coverage).

## Health Summary

| Check | Status | Details |
|-------|--------|---------|
| Backend Unit + Integration (pytest) | PASS | 5580 passed + 5 skipped + 1 xfailed, 0 failed |
| Backend Coverage (combined) | 78.03% | CI gate: 72% |
| Backend Ruff Lint | PASS | 0 violations |
| Backend Ruff Format | PASS | 784 files |
| Backend Mypy | PASS | 0 errors (350 source files) |
| Frontend Tests (Vitest) | PASS | 546/546 (79 files) |
| Frontend TypeScript / ESLint | PASS | per CI |
| UX scenario verification | PASS | 112/112 scenarios verified against code: 109 PASS / 3 PARTIAL at audit; the 3 PARTIAL (SCN-041 auto-growing textarea, SCN-054 per-step elapsed, SCN-077 Cancel in create-rule modal) were implemented in the remediation — now all PASS |
| Total tests | ~6,125 | 5,580 backend + 546 frontend |

## Changes Since the Last Snapshot (2026-03 → 2026-07)

- **`[1.14.0]`** — production hardening: billing (Stripe plans/quotas), cookie auth (httpOnly + CSRF), MCP/SSH hardening, Redis-backed rate limits, Sentry.
- **`[1.15.0]`** — intelligence remediation (W0–W6): data-quality honesty, hybrid retrieval + ContextPack, orchestrator termination + path unification, DB schema-capture depth, code↔DB trust signals, code-graph correctness, self-completing embedding reconcile.
- **`[1.15.1]`** — embedding-loader log hygiene + infra guidance.
- **UX audit remediation (2026-07-19)** — email verification (F-PROJ-01), forgot/reset password (F-AUTH-13), decline invite, dashboard delete + batch results view, honesty sweep, logout toast. See `CHANGELOG.md` [Unreleased].
- **Security release R3 (2026-06-25, `fbf8112`)** — cross-tenant isolation & IDOR sweep (F-RULE-01/05, F-DG-07/09, F-GRAPH-01, F-SSH-08/06, F-LEARN-07). **0 open High findings** in `docs/qa-audit/issues.md`.
- **Full-audit remediation (2026-07-24, branch `fix/audit-remediation-2026-07-24`)** — 8 commits, 40 FIXED / 5 PARTIAL / 99 deferred of 144 findings: MongoDB motor-truthiness Critical (FA-001), ClickHouse timeout recovery + `EXPLAIN indexes=1`, mongo guard parity, learning-feedback idempotency + per-user vote dedup (AQ-1/AQ-7, closing F-LEARN-08/F-LEARN-03), prompt-injection guards (AQ-2), DataGate coercion (AQ-4/5), git-SSRF guard + fail-closed `ENVIRONMENT` + 5 missing rate limits, reaper/heartbeat races (FA-007/008/RES-3), session-expired flash + list retries + SCN-041/054/077, hot-path indexes (migration `eff7aad70326`) + pagination bounds, `next` 15.5.21 + gitpython/mcp/pyasn1 CVE floors. Details: `docs/qa-audit/full-audit-2026-07-24/11-findings-registry.md`.

## Known Issues (as of 2026-07-24, post-remediation)

1. ~~**CRITICAL — MongoDB connector broken with real motor**~~ — **FIXED** (`0567e21`): `if not self._db` → `is None` ×5 (motor forbids truthiness), plus regression tests with a truthiness-forbidding fake.
2. **Live LLM golden path unverified** — `OPENROUTER_API_KEY` in `backend/.env` is invalid (401 "User not found"), `OPENAI_API_KEY`/`ANTHROPIC_API_KEY` empty; all LLM calls fail auth, so live E2E covered only graceful-degradation paths. Rotate keys and rerun flows 5/6/13. See `04-e2e-live.md` (FA-135).
3. **Vulnerable dependencies — residual** — backend: `chromadb 1.5.9` (CVE-2026-45829, no upstream fix), `ecdsa` (CVE-2024-23342, no fix; not exploitable under the HS256 algorithm whitelist); frontend: `postcss`/`sharp` transitive inside `next` 15.x (3 high — fix requires a next major upgrade, deferred). Closed by the remediation: `gitpython>=3.1.51`, `mcp==1.28.1`, `pyasn1>=0.6.4`, `next` 15.5.21 (GHSA-ggv3-7p47-pfv8). Details: `07-security.md` S-02/S-05/S-06.
4. **DataGate deferred cluster (AQ-3/AQ-6/AQ-8)** — flat-path "block" is advisory text, not enforcement (FA-027); false-positive hard-fail on monetary `conversion_*` columns (FA-030); name-only classification with `data_gate_llm_semantics` never wired (FA-032). Folded into the R12 plan in `docs/qa-audit/issues.md`.
5. **Low-coverage hot spots** — `billing_service.py` 49%, `trace_persistence_service.py` 52%, `worker.py` 56%; no HTTP tests for billing checkout/portal/webhook routes. See `00-baseline.md`.
6. **God files / maintainability (CB-M4)** — `agents/orchestrator.py` (2,525 LOC), `agents/sql_agent.py` (2,017), `knowledge/pipeline_runner.py` (1,769), `api/routes/chat.py` (1,724). High blast radius; decomposition tracked in `docs/qa-audit/issues.md` §7.
7. **API.md documentation drift** — 65 endpoints undocumented (Billing, Connection Learnings, Runs, Health Monitor sections missing entirely; FA-014/015/016). Pointer note added to `API.md`; full list in `02-api-contract.md`. Full regeneration of API.md is a separate owed task.
8. **Local env hygiene (FA-006 residual)** — root `.env.local` still carries the dev `JWT_SECRET=change-me-in-production` + `DEBUG=true`; the fail-closed `ENVIRONMENT` default (`97616b7`) now refuses to boot with default secrets outside dev, but set a strong `JWT_SECRET` before any real deploy.
9. **notes.md credentials** — file is **no longer on disk** (verified 2026-07-24, `07-security.md` S-08); credentials that were in it are still formally compromised — rotation remains owed (FA-037).
10. **Old "dead code" claim — resolved** — previously flagged `exploration_engine.py:326` / `cli_output_parser.py:38` sites checked 2026-07-24: `exploration_engine.py` now lives at `backend/app/core/exploration_engine.py` and both sites are live code. No dead code at those locations.

## Next Priorities

1. Rotate LLM API keys, then rerun the live golden-path E2E (chat ask, indexing enrichment; flows 5/6/13).
2. Deferred audit clusters: AQ-3/AQ-6/AQ-8 DataGate enforcement (FA-027/030/032 → R12), gsap+lenis→motion consolidation (FA-012), API.md regeneration (FA-014–016), prod `REDIS_URL` check + startup alert (FA-013).
3. `next` major upgrade to clear the postcss/sharp residual (FA-005/FA-035); track upstream fixes for `chromadb`/`ecdsa`.
4. Coverage push on billing / worker / trace-persistence; add billing route HTTP tests.
5. Env hygiene: strong `JWT_SECRET` in `.env.local` before any real deploy (FA-006 residual); notes.md credential rotation (FA-037).
