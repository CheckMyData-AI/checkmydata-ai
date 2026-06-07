# 06 — QA & Test Plan

This is the master test strategy: what to test, the key and critical scenarios, load and
security testing, the regression checklist, and the CI gate corrections required to make
quality claims honest. It is the verification layer for each roadmap phase exit.

## 1. Objectives

- Prove the core query loop is correct, safe (read-only), and explainable.
- Prove the new billing layer is reliable and replay-safe (money correctness).
- Prove security fixes actually hold (auth/tenancy, sessions, SSH, headers).
- Prove the system scales without losing state or leaking limits.
- Make CI gates match documented claims (close F-QA-1/F-QA-4).

## 2. Test scope and layers

| Layer | Tooling | Scope |
| --- | --- | --- |
| Backend unit | Pytest | services, connectors, agents, entitlement/billing logic |
| Backend integration | Pytest | API routes, webhook, orchestration paths, DB/migrations |
| Frontend unit/component | Vitest | components, stores, API clients |
| E2E (browser) | Playwright (`T-QA-2`) | full user journeys incl. paywall |
| Load/performance | k6 or Locust (`T-QA-3`) | chat/query/connection under concurrency |
| Security | SAST + DAST + targeted cases (`T-QA-4`) | injection, tenancy, headers, secrets |
| Accessibility | axe (`T-QA-5`) | key screens |

## 3. Key functional test cases (must pass)

### Core query loop (M2/M3/M4)
- TC-CORE-1: Connect each DB type (PG/MySQL/Mongo/ClickHouse); test-connection success and
  failure produce correct UI states.
- TC-CORE-2: Natural-language question → read-only SQL generated, executed, results + chart
  returned; the SQL is shown.
- TC-CORE-3: `SafetyGuard` blocks any non-read SQL (INSERT/UPDATE/DELETE/DDL) — must reject.
- TC-CORE-4: Empty result handled gracefully (offer to broaden), not as a hard error.
- TC-CORE-5: Self-repair path: an initially invalid query is repaired and reported as
  adjusted.
- TC-CORE-6: Code+data investigation (S-3) uses lineage and cites code + data.

### Auth & tenancy (M1) — security-critical
- TC-AUTH-1: Unauthenticated access to protected routes (incl. `/dashboard/[id]`) redirects
  to login (closes F-UX-1).
- TC-AUTH-2: No JWT readable from `localStorage`; session is httpOnly cookie (F-SEC-3).
- TC-AUTH-3: WebSocket cannot authenticate via URL token; ticket/subprotocol required
  (F-SEC-2).
- TC-AUTH-4: MCP tool call without a valid principal is rejected; cross-tenant `project_id`
  is denied (F-SEC-1).
- TC-AUTH-5: User A cannot read/act on User B's project/connection via any API/WS/MCP path.

### Connections & safety (M2)
- TC-CONN-1: SSH connection with unknown host key fails closed under default policy
  (F-SEC-4).
- TC-CONN-2: SSH pre-commands cannot execute injected shell input (F-SEC-5).
- TC-CONN-3: Large result set is bounded by SQL `LIMIT` + byte cap and does not OOM the
  process (F-ARCH-5) — see load test LT-3.

### Billing & entitlements (M9) — money-critical
- TC-BILL-1: Checkout for each paid plan creates a subscription and grants entitlements
  after webhook.
- TC-BILL-2: Trial starts without a card and converts to paid correctly.
- TC-BILL-3: Webhook signature invalid → rejected; valid → state updated.
- TC-BILL-4: Duplicate/replayed webhook (same `stripe_event_id`) does NOT double-grant
  (idempotency).
- TC-BILL-5: Over-budget request returns a structured limit-reached/paywall payload, not a
  generic error (F-BIZ-2).
- TC-BILL-6: Connection/seat over-limit blocked with paywall; upgrade unblocks the action
  (S-4).
- TC-BILL-7: Customer Portal change (upgrade/downgrade/cancel) reconciles entitlements.
- TC-BILL-8: Past_due/canceled states render correctly and gate access appropriately.

### Observability & admin (M10/M11)
- TC-OBS-1: Unhandled error is captured in Sentry with request context and scrubbed PII.
- TC-ADMIN-1: Normal user cannot reach `/admin/*` (403); admin can; action is audited.
- TC-ADMIN-2: Impersonation is scoped and produces an audit-log entry.

## 4. Critical scenarios (release gates — any failure blocks release)

1. Read-only invariant: no path can mutate a connected customer database (TC-CORE-3,
   connector review).
2. Cross-tenant isolation: no user can access another tenant's data via API/WS/MCP
   (TC-AUTH-4/5).
3. Money correctness: no double-grant, no entitlement without webhook confirmation
   (TC-BILL-3/4/7).
4. Cost ceiling: enforced budget prevents unbounded LLM spend (TC-BILL-5).
5. Memory safety: a large query cannot OOM/crash a dyno (TC-CONN-3, LT-3).
6. Session secrecy: no token in URL or `localStorage` (TC-AUTH-2/3).

## 5. Load & performance testing (`T-QA-3`)

Targets are proposals (Needs validation §4 in audit) and finalized at GA.

| ID | Scenario | Target |
| --- | --- | --- |
| LT-1 | Concurrent chat/query sessions | p95 answer latency < 12s at target concurrency |
| LT-2 | Multi-dyno consistency (≥2 dynos) | no lost workflow state; rate limits hold globally (validates T-SCALE-1/T-SEC-7) |
| LT-3 | Large-result query | bounded memory; no OOM; caps enforced (validates T-ARCH-5) |
| LT-4 | Webhook burst | all events processed exactly once; no double-grant |
| LT-5 | Connection pool saturation | graceful degradation, no crash |

Run on a schedule and before each release; capture a baseline and track regressions.

## 6. Security testing (`T-QA-4`)

- **SAST:** CodeQL/Bandit (Python), ESLint security rules (JS/TS) on every PR.
- **Dependency scanning:** `pip-audit`, `npm audit`/Dependabot; high-severity blocks merge.
- **DAST / targeted manual cases:** SQL injection attempts (must be blocked by read-only +
  parameterization), auth bypass on WS/MCP, cross-tenant access, header presence (CSP/HSTS),
  secret leakage in logs, SSH host-key MITM, SSH pre-command injection.
- **Pre-GA:** third-party penetration test; close findings before GA (P2 exit).

## 7. Accessibility testing (`T-QA-5`)

- Automated axe checks on workspace, connections, pricing, billing, login.
- Manual keyboard-only pass on tooltips, cost estimator, and modals (F-UX-3).
- WCAG AA contrast verified against the design system.

## 8. Regression checklist (run before every release)

Protect the existing strengths and the newly fixed risks:

- [ ] Read-only SQL enforced; non-read statements rejected (TC-CORE-3).
- [ ] All four connectors connect, query, and bound results (TC-CORE-1, TC-CONN-3).
- [ ] Core query loop returns answer + SQL + chart (TC-CORE-2).
- [ ] Auth gating on all app routes incl. dashboard (TC-AUTH-1).
- [ ] No token in URL/localStorage (TC-AUTH-2/3).
- [ ] MCP auth + tenancy enforced (TC-AUTH-4/5).
- [ ] SSH host-key fail-closed default (TC-CONN-1).
- [ ] Billing: subscribe, trial, portal, cancel all correct (TC-BILL-1/2/7/8).
- [ ] Webhook idempotency holds (TC-BILL-4).
- [ ] Budget enforcement blocks over-limit spend (TC-BILL-5).
- [ ] Sentry captures errors; admin actions audited (TC-OBS-1, TC-ADMIN-1/2).
- [ ] CSP/HSTS headers present (security scan).
- [ ] Coverage/E2E/load/SAST/a11y CI gates green.
- [ ] Migrations apply and roll back cleanly.

## 9. CI gate corrections (closes F-QA-1, F-QA-4)

Current state (verified): `.github/workflows/ci.yml:96` enforces
`python -m coverage report --fail-under=40`, and `docs/DEPLOYMENT.md:28` documents 40% —
while `docs/agent-changelog.md:42` narrates a 72% threshold. These disagree.

Required changes:
1. **Decide the real coverage target** (proposal: 60% backend now → 72% by GA) and set
   `--fail-under` to it in `ci.yml` (`T-QA-1`).
2. **Make every doc match** the CI value: `docs/DEPLOYMENT.md`, `docs/agent-changelog.md`,
   CONTRIBUTING, README. Remove contradictory historical threshold claims or clearly mark
   them as historical (`T-DOC-1`).
3. **Add frontend coverage reporting** to CI alongside backend.
4. **Add new CI jobs:** Playwright E2E (`T-QA-2`), load smoke (`T-QA-3` lite on PR, full on
   schedule), SAST + dependency scan (`T-QA-4`), axe a11y (`T-QA-5`).
5. **Add a docs-consistency check** that fails when the documented coverage/threshold does
   not equal the CI value (`T-DOC-1`).

## 10. Definition of "tested" per phase

- **P0-MVP:** all Critical scenarios (§4) pass; coverage gate aligned and green; billing
  webhook idempotency proven; OOM path proven safe.
- **P1-BETA:** E2E + load + SAST + a11y gates green; multi-dyno consistency proven (LT-2).
- **P2-GA:** penetration test passed; SLO targets validated under load; coverage at GA
  target.
