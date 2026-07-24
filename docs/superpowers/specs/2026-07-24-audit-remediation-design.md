# Audit Remediation 2026-07-24 — Design Spec

Date: 2026-07-24
Source: `docs/qa-audit/full-audit-2026-07-24/11-findings-registry.md` (144 findings: 1 Critical, 12 High, 35 Medium, 61 Low, 35 Info)
Branch: `fix/audit-remediation-2026-07-24`

## 1. Goal

Fix all Critical and High findings, all Medium findings with a safe,
well-scoped fix, and Low quick-wins that touch the same files. Every fix
ships with a regression test (TDD) and follows existing repo conventions
(ruff 100-col, async everywhere, feature flags for behavior changes,
conventional commits).

## 2. Scope

### In scope (by batch)

**B1 — DB connectors (Critical FA-001 + High B2 + Medium/Low)**
- FA-001/B1: `mongodb.py` — `if not self._db:` raises `NotImplementedError`
  with real motor (Database has no `__bool__`). Fix: `if self._db is None:`
  at `mongodb.py:212,319,387,413,436`. Regression test must use a fake whose
  `__bool__` raises `NotImplementedError` (mirrors real motor), replacing the
  masking `_FakeDB` pattern.
- B2: `clickhouse.py:174-196` — client-side timeout leaves the session
  occupied; subsequent queries fail "concurrent queries within the same
  session". Fix: on timeout, terminate/reset the session so the next query
  uses a fresh one.
- B3: `explain_validator.py:133-142` — plain `EXPLAIN` never mentions
  where/prewhere on CH 24.8 → false "full scan" warnings. Fix: use
  `EXPLAIN indexes=1` and detect `Condition`/`Granules`.
- B4: `safety.py:127-145` — `validate_mongo` also blocks `$out`, `$merge`,
  `$where`, `$function`, `$accumulator` at the SafetyGuard layer (parity with
  the connector-level guard).
- B1-e2e: `session_notes_service.py:439` — `func.greatest()` crashes on
  SQLite. Fix with portable equivalent (CASE / Python-side clamp).

**B2 — Learnings & agent gates (High AQ-1/AQ-2 + Medium)**
- AQ-1: `chat_feedback.py:64-101` — make negative feedback idempotent:
  one rollback per (message, user); do not re-apply −0.3 on repeat downvote;
  do not re-create/promote the "User flagged…" lesson on repeats. Mirror the
  existing positive-path guard.
- AQ-7: `connection_learnings.py:248-311` — per-user vote dedup on
  confirm/contradict: one active vote per (learning, user); re-vote reverses
  or no-ops. Minimal persistence (new small model + Alembic migration or
  reuse of an existing vote table — implementer's choice, documented).
- AQ-2: prompt-injection hardening — wrap verbatim DB rows in prompts with
  explicit untrusted-data framing (`result_handler.py:28-29`, SQL prompt
  builder); keep `record_learning` quality gates rejecting instruction-shaped
  subjects; no architecture change.
- AQ-4/AQ-5: `data_gate.py` — value-range hard checks must coerce native
  `datetime`/`date` and numeric strings before classification.
- AQ-9: `answer_validator.py:197-201` — parse string verdicts explicitly
  (`bool("false") is True` bug).
- AQ-10: `sql_result_reconciliation.py:121-134` — float tolerance in
  reconcile (abs tol ~1e-6 rel); un-xfail DATA-15 (keep xfail DATA-21).
- Deferred (documented, needs product/design decision): AQ-3 (DataGate block
  symmetry between paths), AQ-6/AQ-8 (percent classification semantics).

**B3 — Security (High FA-004 + Medium/Low)**
- FA-004: `repo_url.py` — after scheme/arg validation, DNS-resolve the host
  and reject private/loopback/link-local/reserved addresses (SSRF guard).
  New opt-out config `repo_allow_private_hosts` (default False) with
  docstring + `.env.example` entry, per env-var conventions. Applied to both
  `check-access` and index paths.
- Config fail-closed: `config.py:62` — `environment` default must not bypass
  production secret guards; make unset/unknown behave as production
  (fail-closed), set explicit `ENVIRONMENT=development` in `.env.example`.
- Rate limits: add `@limiter.limit` to billing `checkout`/`portal`
  (`billing.py:91,111`), `schedules.py:167` PATCH, investigations
  `confirm-fix`, chat `ws-ticket`.
- Deps: `gitpython>=3.1.51` (GHSA fixes), `mcp==1.28.1` (CVE-2026-59950;
  pin moves from 1.27.2 — run full mcp test suite), pyasn1 bump via floor.
- Docs: `.env.example` comment warning against `source .env` shell pattern
  (breaks JSON `CORS_ORIGINS`); ensure docker-compose examples never ship
  `JWT_SECRET=change-me-in-production` silently.

**B4 — Resilience (High FA-007/FA-008/RES-3 + Medium)**
- FA-007: `run_coordinator.py:371` + `stale_run_reaper.py:64-73` — reaped
  runs must be reconcilable: a late `pipeline_end` for a reaped run flips it
  to its true terminal state (completed/failed by event) instead of dropping
  the event; reap reason recorded in the run summary.
- FA-008: `pipeline_runner.py` — heartbeat ticks inside long steps lacking
  intra-step emits: `ast_parse`, `code_symbol_embed`, `bm25_build`,
  `clone_or_pull` (`:200,518,549,1233`). Tick cadence ≤ heartbeat timeout.
- RES-3: duplicate-dispatch window — post-index steps keep heartbeating (or
  move run to a distinct non-reapable phase) so the guards at
  `connections.py:207,716,960-965` cannot start a second index while the
  first is alive.
- `connections.py:506` — business-validation error 422→400 (consistency).

**B5 — Frontend & UX (High FA-010 + Medium/Low)**
- FA-010: `_client.ts:16-17` — session-expired toast must survive the
  redirect: stash a flash message (sessionStorage) before
  `window.location.href="/login"`; login page shows it once. Reset
  `sessionExpiredHandled` when auth succeeds again. Unify the three
  session-expired texts (`_client.ts:16`, `_client.ts:119`,
  `auth-store.ts:74,87`) into one constant. Update SCN-011 in
  `docs/ux/scenarios.md` (hard rule).
- LogsScreen: error banner + Retry on runs/errors tabs too
  (`LogsScreen.tsx:147`).
- Scenario PARTIALs: SCN-041 auto-growing textarea (`ChatInput.tsx:32-48`),
  SCN-054 per-step elapsed (`ReasoningPanel.tsx:42-86`), SCN-077 Cancel
  button in create-rule modal (`RulesManager.tsx:226`). Update scenario
  statuses/evidence.
- Deps: bump `next` to the patched 15.x (GHSA-ggv3-7p47-pfv8), run
  `npm audit fix` for postcss/sharp/fast-uri/brace-expansion (lockfile-only
  where possible), remove unused `msw`, make `remark-gfm` imports lazy in
  `ChatMessage.tsx:6` / `SQLExplainer.tsx:5` (move into the dynamic
  react-markdown wrapper).

**B6 — Perf & API hygiene (Medium/Low, wave 2)**
- Alembic migration adding indexes: `chat_messages(session_id, created_at)`,
  `agent_learnings(connection_id, is_active, confidence)`,
  `notifications(user_id, is_read, created_at)`,
  `request_traces(session_id)`, `request_traces(message_id)`.
- Pagination bounds (`Query(ge=, le=)`) on list endpoints missing them:
  notes, dashboards, data-graph metrics/relationships, repos docs.
- `logs.py:168` — 400→404 for unknown error_id.

### Out of scope (recorded deferrals)

God-file decomposition (`orchestrator.py`, `sql_agent.py`, CB-M4), animation
triad consolidation (perf refactor), removal of the unused intelligence
surface (~17 endpoints, needs product decision), python-jose→PyJWT
migration, dependency lock file, full API.md regeneration (65 endpoints —
pointer note added), AQ-3/AQ-6/AQ-8 (design decisions), chromadb/ecdsa CVEs
(no upstream fix), load testing, Playwright browser E2E, prod Heroku config
review, `.env.local` local file contents (untracked; operator action).

## 3. Invariants (must not regress)

- vision.md §7: read-only enforcement, per-connection learnings, feedback
  authority, graceful degradation, freshness tracking.
- All 5439 backend + 526 frontend tests green; coverage ≥ 72% gate.
- Migrations: single head, working downgrade (verified by round-trip).
- UX: `docs/ux/scenarios.md` updated in the same change for any
  user-facing behavior change (repo hard rule).

## 4. Verification plan

- Per-batch: new failing test first, fix, targeted test file green.
- Stage 6: full `pytest tests/unit tests/integration` + `vitest run`.
- Stage 7: `ruff check`, `ruff format --check`, `mypy app/
  --ignore-missing-imports`, `tsc --noEmit`, `eslint --max-warnings=0`.
- Post-fix audits: `pip-audit`, `npm audit` re-run to confirm CVE closure.
