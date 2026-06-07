# 04 — Development Backlog

Detailed, buildable tasks. Each task has: ID, name, description, role, priority, complexity,
dependencies, module, the audit finding(s) it closes, and acceptance criteria. P0 security
fixes and the billing build are front-loaded.

**Roles:** BE (backend), FE (frontend), DES (design), DO (DevOps), QA, PM (product).
**Priority:** P0 (launch blocker), P1 (before GA), P2 (post-GA / opportunistic).
**Complexity:** L (low), M (medium), H (high).

## Priority overview

| Priority | Tasks |
| --- | --- |
| P0 | T-SEC-1, T-SEC-2, T-SEC-3, T-SEC-4, T-SEC-6, T-ARCH-5, T-BILL-1, T-BILL-2, T-BILL-3, T-BILL-4, T-BILL-5, T-BILL-6, T-BILL-7, T-OBS-1, T-UX-1, T-QA-1, T-GROW-1 |
| P1 | T-SEC-5, T-SEC-7, T-SCALE-1, T-ARCH-1, T-ARCH-2, T-ARCH-3, T-ARCH-4, T-ARCH-6, T-QA-2, T-QA-3, T-QA-4, T-QA-5, T-OBS-2, T-UX-2, T-UX-3, T-ADMIN-1, T-ADMIN-2, T-LEGAL-1, T-LEGAL-2, T-GROW-2, T-BILL-8, T-BILL-9, T-DOC-1 |
| P2 | T-ADMIN-3, T-GROW-3, T-GROW-4 |

---

## Epic: Security hardening (M1, M2, M11)

### T-SEC-1 — Authenticate MCP server and enforce tenancy
- **Role:** BE · **Priority:** P0 · **Complexity:** M · **Module:** M1 · **Closes:** F-SEC-1
- **Description:** Replace anonymous/hardcoded identity in the MCP server with a real
  authenticated principal and enforce project ownership/membership on every tool. Remove
  `mcp-anonymous` (`backend/app/mcp_server/auth.py:69`) and `user_id="mcp-user"` literals in
  `backend/app/mcp_server/tools.py` (lines 111, 122, 135, 156, 167, 180). Gate MCP behind a
  feature flag (off by default until this lands).
- **Dependencies:** none (can start immediately).
- **Acceptance criteria:**
  - Every MCP tool requires a valid principal mapped to a real `user_id`.
  - Calls for a `project_id` the principal cannot access are rejected (test-proven).
  - No anonymous fallback in production config; flag defaults off.
  - Unit/integration tests cover authorized, unauthorized, and cross-tenant cases.

### T-SEC-2 — Remove JWT from WebSocket URL
- **Role:** BE+FE · **Priority:** P0 · **Complexity:** M · **Module:** M1 · **Closes:** F-SEC-2
- **Description:** `chat_websocket` accepts `token` as a query param
  (`backend/app/api/routes/chat.py:2210-2238`). Replace with a short-lived single-use ticket
  fetched over the authenticated HTTPS API, or a subprotocol header. Scrub tokens from logs.
- **Dependencies:** T-SEC-3 (session model) recommended in parallel.
- **Acceptance criteria:**
  - No token appears in any URL/query string for WS auth.
  - Ticket is short-lived, single-use, and bound to the user/connection.
  - Existing WS functionality preserved (E2E covers connect→stream).

### T-SEC-3 — Move session to httpOnly cookies + CSRF
- **Role:** BE+FE · **Priority:** P0 · **Complexity:** H · **Module:** M1 · **Closes:** F-SEC-3
- **Description:** Stop storing JWT in `localStorage` (`frontend/src/stores/auth-store.ts`).
  Use httpOnly, Secure, SameSite cookies for the session; add CSRF tokens for state-changing
  requests. Update API/WS clients accordingly.
- **Dependencies:** coordinate with T-SEC-2; Needs-validation §7 (external API consumers).
- **Acceptance criteria:**
  - No access/refresh token readable from JS.
  - State-changing requests require valid CSRF; verified by tests.
  - Login/logout/refresh flows work; E2E green.

### T-SEC-4 — Secure SSH host-key verification by default
- **Role:** BE · **Priority:** P0 · **Complexity:** M · **Module:** M2 · **Closes:** F-SEC-4
- **Description:** Default `ssh_host_key_policy` to `strict` (or `tofu` with managed
  known-hosts) instead of `disabled` (`backend/app/connectors/ssh_known_hosts.py:40`,
  `backend/.env.example:199`). Fail closed on unknown keys; make `disabled` an explicit,
  logged, non-production override. Provide TOFU UX for first connect.
- **Dependencies:** none.
- **Acceptance criteria:**
  - Production default verifies host keys; unknown key fails closed.
  - Docs/env examples updated to the secure default.
  - Tests cover strict/tofu/disabled behaviors (extend existing
    `test_ssh_known_hosts.py`).

### T-SEC-5 — Lock down SSH pre-commands
- **Role:** BE · **Priority:** P1 · **Complexity:** M · **Module:** M2 · **Closes:** F-SEC-5
- **Description:** Disable arbitrary `ssh_pre_commands` by default; if required, restrict to
  an allowlist and execute with argument arrays (no shell) in `ssh_exec.py`/`ssh_tunnel.py`.
- **Dependencies:** none.
- **Acceptance criteria:**
  - Default config runs no shell pre-commands.
  - Any allowed command executes without shell interpolation; injection test fails to
    execute arbitrary input.

### T-SEC-6 — Security headers (CSP/HSTS)
- **Role:** BE+FE+DO · **Priority:** P0 · **Complexity:** M · **Module:** M1 · **Closes:** F-SEC-6
- **Description:** Add strict Content-Security-Policy, HSTS, `X-Content-Type-Options`,
  `Referrer-Policy`, and frame-ancestors. Verify in CI.
- **Dependencies:** coordinate CSP with any inline scripts/analytics.
- **Acceptance criteria:**
  - Responses carry the headers; CSP blocks inline/unsafe by default.
  - A header-check step runs in CI and passes.

### T-SEC-7 — Shared (Redis) rate limiting tied to entitlements
- **Role:** BE · **Priority:** P1 · **Complexity:** M · **Module:** M11 · **Closes:** F-SEC-7
- **Description:** Replace in-memory per-process rate limits with a Redis-backed limiter
  keyed by user/IP/route; integrate plan-based limits.
- **Dependencies:** T-SCALE-1.
- **Acceptance criteria:**
  - Limits hold across multiple dynos (load-tested).
  - Limits reflect plan entitlements; exceeded requests get a clear, structured response.

---

## Epic: Billing & monetization (M9)

### T-BILL-1 — Billing data model + migrations
- **Role:** BE · **Priority:** P0 · **Complexity:** M · **Module:** M9 · **Closes:** F-BIZ-1
- **Description:** Add Alembic migrations for `plans`, `subscriptions`, `invoices`,
  `usage_counters`, `stripe_events`, entitlements (or derived), and `audit_log`.
- **Dependencies:** none.
- **Acceptance criteria:**
  - Migrations apply/rollback cleanly on SQLite (dev) and Postgres (prod).
  - Models documented; unique constraint on `stripe_events.stripe_event_id`.

### T-BILL-2 — EntitlementService + plan-gating middleware
- **Role:** BE · **Priority:** P0 · **Complexity:** H · **Module:** M9 · **Closes:** F-BIZ-3
- **Description:** Central service answering "can user/plan do X now?" (connections, seats,
  features, budget). Middleware enforces on connect-source, run-query, invite-member;
  returns structured `402/limit_reached`.
- **Dependencies:** T-BILL-1, T-SCALE-1 (Redis counters).
- **Acceptance criteria:**
  - Gated actions blocked when over-limit with a paywall-renderable payload.
  - Entitlements derived from subscription state; covered by tests for each tier.

### T-BILL-3 — Stripe Checkout + trial
- **Role:** BE+FE · **Priority:** P0 · **Complexity:** M · **Module:** M9 · **Closes:** F-BIZ-1
- **Description:** Create Stripe customer on signup; `POST /billing/checkout` creates hosted
  Checkout for a plan; support 14-day trial (no card) and trial→paid conversion.
- **Dependencies:** T-BILL-1.
- **Acceptance criteria:**
  - User can start Checkout for any paid plan and a trial.
  - Successful payment results in entitlement change (via webhook, T-BILL-5).

### T-BILL-4 — Stripe Customer Portal
- **Role:** BE+FE · **Priority:** P0 · **Complexity:** L · **Module:** M9 · **Closes:** F-BIZ-1
- **Description:** `GET /billing/portal` returns a portal URL for plan/payment/cancellation
  self-service.
- **Dependencies:** T-BILL-3.
- **Acceptance criteria:**
  - User can change plan, update card, and cancel via the portal; changes reflected after
    webhook reconciliation.

### T-BILL-5 — Idempotent Stripe webhook (single source of truth)
- **Role:** BE · **Priority:** P0 · **Complexity:** H · **Module:** M9 · **Closes:** F-BIZ-1
- **Description:** `POST /billing/webhook` verifies signature, dedupes on
  `stripe_event_id`, and is the only writer of subscription state. CSRF-exempt.
- **Dependencies:** T-BILL-1.
- **Acceptance criteria:**
  - Replayed/duplicate events do not double-grant (test-proven).
  - Invalid signatures rejected; subscription state matches Stripe after each relevant event.

### T-BILL-6 — Enforce usage budgets (wire `check_budget`)
- **Role:** BE · **Priority:** P0 · **Complexity:** M · **Module:** M9/M11 · **Closes:** F-BIZ-2, F-FIN-1
- **Description:** Call `usage_service.check_budget()` (`backend/app/services/usage_service.py:59`)
  on the orchestrator/chat entry path; back counters with Redis; record period-of-record in
  `usage_counters`; surface remaining budget to the UI; return paywall payload on exhaustion.
- **Dependencies:** T-BILL-2, T-SCALE-1.
- **Acceptance criteria:**
  - A user cannot exceed the plan token/query budget; over-budget returns a clear
    limit-reached result.
  - Remaining budget visible in UI; counters correct under concurrency (atomic).

### T-BILL-7 — Billing & usage UI + paywall states
- **Role:** FE+DES · **Priority:** P0 · **Complexity:** M · **Module:** M9 · **Closes:** F-BIZ-1
- **Description:** Build `/settings/billing` (plan, usage meters, invoices, portal link) and
  paywall card/modal at trigger points (PRD §10.4–10.5), with all subscription states.
- **Dependencies:** T-BILL-2..6.
- **Acceptance criteria:**
  - Each state (free/trial/active/past_due/canceled) renders correctly.
  - Paywall explains the exact limit and unblocks the action after upgrade.

### T-BILL-8 — Plan catalog configuration/admin
- **Role:** BE · **Priority:** P1 · **Complexity:** L · **Module:** M9 · **Closes:** F-BIZ-3
- **Description:** Manage plan↔Stripe price mapping and limits via config/admin (M10).
- **Dependencies:** T-BILL-1, T-ADMIN-1.
- **Acceptance criteria:** plans editable without code deploy; changes reflected in
  entitlements.

### T-BILL-9 — Overage & fair-use handling
- **Role:** BE+PM · **Priority:** P1 · **Complexity:** M · **Module:** M9 · **Closes:** F-FIN-1
- **Description:** Implement soft caps (80%/100% warnings), hard stop on Free, optional
  metered overage on Team (Needs validation), and fair-use enforcement.
- **Dependencies:** T-BILL-6.
- **Acceptance criteria:** warnings fire at thresholds; overage behavior matches plan;
  abusive usage throttled.

---

## Epic: Architecture & scale (M2, M3, M11)

### T-ARCH-5 — Bound query results (fix MySQL OOM)
- **Role:** BE · **Priority:** P0 · **Complexity:** M · **Module:** M2 · **Closes:** F-ARCH-5
- **Description:** Push `LIMIT` into SQL and use server-side/chunked cursors with row AND
  byte caps before materializing; eliminate `fetchall()`-then-cap in the MySQL connector;
  apply consistently across connectors.
- **Dependencies:** none.
- **Acceptance criteria:**
  - A query returning a very large set cannot OOM a dyno (load-tested with a big table).
  - Caps enforced identically across PG/MySQL/Mongo/ClickHouse; tests prove bounding.

### T-SCALE-1 — Externalize state to Redis (stateless dynos)
- **Role:** BE+DO · **Priority:** P1 · **Complexity:** H · **Module:** M11 · **Closes:** F-ARCH-1
- **Description:** Move sessions, caches, rate-limit counters, usage budgets, and workflow
  intermediates (`_wf_sql_results`, connector/MCP caches) into Redis; make dynos stateless;
  add a background worker/queue for indexing/digests/maintenance.
- **Dependencies:** Redis provisioned.
- **Acceptance criteria:**
  - App behaves consistently across ≥2 dynos (load-tested): no lost workflow state, correct
    limits, shared cache.
  - No per-process mutable shared state remains on the request path.

### T-ARCH-1 — Decompose `api/routes/chat.py`
- **Role:** BE · **Priority:** P1 · **Complexity:** H · **Module:** M3 · **Closes:** F-ARCH-2
- **Description:** Split the ~2,811-line file into transport (HTTP/WS), message validation,
  and an orchestration entry service. Characterization tests first.
- **Dependencies:** T-ARCH-3 alignment.
- **Acceptance criteria:** no single file > agreed line budget; behavior unchanged (tests);
  modules independently unit-testable.

### T-ARCH-2 — Decompose orchestrator/sql_agent + oversized FE components
- **Role:** BE+FE · **Priority:** P1 · **Complexity:** H · **Module:** M3/M7 · **Closes:** F-ARCH-2
- **Description:** Break up `orchestrator.py` (~2,373) and `sql_agent.py` (~1,964) behind
  characterization tests; split `ConnectionSelector.tsx` (~1,302), `ChatPanel.tsx` (~957),
  `Sidebar.tsx` (~924) into container/presentational units.
- **Dependencies:** T-ARCH-1.
- **Acceptance criteria:** reduced file sizes; tests green; no behavior change; components
  have unit tests.

### T-ARCH-3 — Converge dual orchestration paths
- **Role:** BE · **Priority:** P1 · **Complexity:** H · **Module:** M3 · **Closes:** F-ARCH-3
- **Description:** Define one canonical execution contract; make the adaptive pipeline a
  planning strategy within the unified loop sharing `ToolDispatcher` and tests.
- **Dependencies:** T-ARCH-1, T-ARCH-2.
- **Acceptance criteria:** one documented path; parity tests; no divergent behavior between
  former paths.

### T-ARCH-4 — Remove/quarantine deprecated core modules
- **Role:** BE · **Priority:** P1 · **Complexity:** L · **Module:** M3 · **Closes:** F-ARCH-4
- **Description:** Delete (preferred) or quarantine `core/orchestrator.py` +
  `core/tool_executor.py`; ensure no production import path references them.
- **Dependencies:** T-ARCH-3.
- **Acceptance criteria:** no production import of deprecated modules (grep/CI check); tests
  green after removal.

### T-ARCH-6 — Decide default-on advanced retrieval features
- **Role:** BE+PM · **Priority:** P1 · **Complexity:** M · **Module:** M4 · **Closes:** F-ARCH-6
- **Description:** Benchmark `hybrid_retrieval_enabled`, `schema_retrieval_enabled`,
  `code_graph_enabled`, `lineage_enabled`; promote to default-on (with tests) or mark
  experimental; align docs to actual defaults.
- **Dependencies:** indexing on worker (T-SCALE-1) for cost.
- **Acceptance criteria:** each feature has a decided default with quality/latency
  benchmark; docs match config.

---

## Epic: Observability & cost control (M11)

### T-OBS-1 — Error tracking (Sentry) + structured/audit logs
- **Role:** BE+FE+DO · **Priority:** P0 · **Complexity:** M · **Module:** M11 · **Closes:** F-SEC-8
- **Description:** Integrate Sentry (backend+frontend) with PII scrubbing and release
  tagging; emit structured logs with request IDs; write auth/connection/billing/admin events
  to `audit_log`.
- **Dependencies:** T-BILL-1 (audit_log table).
- **Acceptance criteria:** unhandled errors appear in Sentry with context; sensitive data
  scrubbed; audit events recorded.

### T-OBS-2 — Cost guardrails & spend-anomaly alerting
- **Role:** BE+DO · **Priority:** P1 · **Complexity:** M · **Module:** M11 · **Closes:** F-FIN-1
- **Description:** Track per-user/plan LLM spend; alert on anomalies; dashboard gross margin.
- **Dependencies:** T-BILL-6, T-OBS-1.
- **Acceptance criteria:** spend dashboard exists; alert fires on a simulated runaway; tied
  to budget enforcement.

---

## Epic: UX & accessibility (M7)

### T-UX-1 — Auth-gate dashboard and all app routes
- **Role:** FE+BE · **Priority:** P0 · **Complexity:** L · **Module:** M7 · **Closes:** F-UX-1
- **Description:** Add server+client route guards (incl. `/dashboard/[id]`) redirecting
  unauthenticated users to login, preserving destination.
- **Dependencies:** T-SEC-3 (session model).
- **Acceptance criteria:** no unauthenticated access to app routes (E2E-proven).

### T-UX-2 — Wire or remove unused components
- **Role:** FE · **Priority:** P1 · **Complexity:** L · **Module:** M7 · **Closes:** F-UX-2
- **Description:** Wire `InsightFeedPanel.tsx`/`MetricCatalogPanel.tsx` into real flows with
  tests, or remove until needed.
- **Dependencies:** M5/M6 data availability.
- **Acceptance criteria:** no dead UI in the tree; whatever ships is reachable and tested.

### T-UX-3 — Per-route titles + a11y fixes
- **Role:** FE+DES · **Priority:** P1 · **Complexity:** M · **Module:** M7 · **Closes:** F-UX-3
- **Description:** Set per-route document titles/metadata; fix keyboard/focus a11y on
  tooltips and cost estimator; modal focus traps; WCAG AA contrast.
- **Dependencies:** none.
- **Acceptance criteria:** titles update on navigation; a11y checks (T-QA-5) pass for key
  screens.

---

## Epic: Admin & ops (M10)

### T-ADMIN-1 — Role-gated admin console (users, subscriptions, diagnostics)
- **Role:** BE+FE · **Priority:** P1 · **Complexity:** H · **Module:** M10 · **Closes:** F-OPS-1
- **Description:** `/admin/*` API+UI for user/plan management, support impersonation,
  connection diagnostics (no plaintext creds).
- **Dependencies:** M1 roles, T-BILL-2.
- **Acceptance criteria:** unreachable by normal users (test-proven); core ops tasks doable.

### T-ADMIN-2 — Admin audit logging
- **Role:** BE · **Priority:** P1 · **Complexity:** L · **Module:** M10 · **Closes:** F-OPS-1
- **Description:** Record every admin action (actor/target/action/time) to `audit_log`.
- **Dependencies:** T-ADMIN-1, T-OBS-1.
- **Acceptance criteria:** all admin actions produce audit entries; impersonation scoped+logged.

### T-ADMIN-3 — Feature-flag management
- **Role:** BE+FE · **Priority:** P2 · **Complexity:** M · **Module:** M10 · **Closes:** F-ARCH-6
- **Description:** Toggle experimental features per environment/plan from admin.
- **Dependencies:** T-ADMIN-1.
- **Acceptance criteria:** flags toggle live; respected by backend; audited.

---

## Epic: Legal & compliance (M9/M11)

### T-LEGAL-1 — DPA + subprocessor list + LLM data-handling disclosure
- **Role:** PM+BE · **Priority:** P1 · **Complexity:** M · **Module:** M9/M11 · **Closes:** F-LEGAL-1
- **Description:** Publish a DPA and subprocessor list (LLM providers, hosting, email);
  document what data is sent to LLMs and how it is minimized/redacted.
- **Dependencies:** Needs-validation §5.
- **Acceptance criteria:** DPA + subprocessor list public; LLM data-flow documented; passes
  a basic B2B security questionnaire.

### T-LEGAL-2 — Data-retention/PII policy + deletion guarantees
- **Role:** PM+BE · **Priority:** P1 · **Complexity:** M · **Module:** M11 · **Closes:** F-LEGAL-1
- **Description:** Define retention windows for query previews, learnings, and insight
  memory; implement account/project data deletion.
- **Dependencies:** M6 storage.
- **Acceptance criteria:** retention documented and enforced; deletion request removes
  customer-derived data (test-proven).

---

## Epic: Growth & SEO (M12)

### T-GROW-1 — `/pricing` page wired to Checkout/trial
- **Role:** FE+DES+PM · **Priority:** P0 · **Complexity:** M · **Module:** M12 · **Closes:** F-BIZ-3
- **Description:** Build `/pricing` with tiers/FAQ and CTAs into Checkout/trial.
- **Dependencies:** T-BILL-3.
- **Acceptance criteria:** each tier CTA starts the correct Checkout/trial; page tracked in
  funnel.

### T-GROW-2 — SEO foundation (metadata, sitemap, robots, structured data)
- **Role:** FE · **Priority:** P1 · **Complexity:** M · **Module:** M12 · **Closes:** F-UX-3 (SEO part)
- **Description:** Per-route metadata, sitemap, robots, and structured data
  (Article/FAQ/HowTo) for marketing/docs pages.
- **Dependencies:** T-UX-3.
- **Acceptance criteria:** valid structured data; sitemap/robots correct; pages indexable.

### T-GROW-3 — Programmatic comparison/alternative pages
- **Role:** FE+PM · **Priority:** P2 · **Complexity:** M · **Module:** M12
- **Description:** Templated comparison/alternative pages with a quality bar to avoid thin
  content.
- **Dependencies:** T-GROW-2.
- **Acceptance criteria:** pages meet quality/perf bar; tracked in funnel.

### T-GROW-4 — Landing-page CRO
- **Role:** DES+FE+PM · **Priority:** P2 · **Complexity:** M · **Module:** M12
- **Description:** Improve value prop, social proof, and CTAs on marketing pages; A/B-ready.
- **Dependencies:** analytics (T-OBS-1 events).
- **Acceptance criteria:** measurable signup-CTR baseline established; experiment-ready.

---

## Epic: Quality & CI gates (M11)

### T-QA-1 — Align coverage gate with reality
- **Role:** DO+QA · **Priority:** P0 · **Complexity:** L · **Module:** M11 · **Closes:** F-QA-1, F-QA-4
- **Description:** Decide the real coverage target and set `--fail-under` accordingly in
  `.github/workflows/ci.yml:96`; update all docs (`docs/DEPLOYMENT.md:28`,
  `docs/agent-changelog.md`, CONTRIBUTING, README) to the same number. (Proposal: 60% now,
  72% by GA — Needs validation §4.)
- **Dependencies:** none.
- **Acceptance criteria:** CI gate value == documented value everywhere; CI fails below it.

### T-QA-2 — Browser E2E suite (Playwright)
- **Role:** QA+FE · **Priority:** P1 · **Complexity:** M · **Module:** M11 · **Closes:** F-QA-2
- **Description:** E2E for signup→connect→query→result, auth gating, and the paywall/upgrade
  flow; run headless in CI.
- **Dependencies:** T-BILL-7, T-UX-1.
- **Acceptance criteria:** core journeys covered and green in CI.

### T-QA-3 — Load/performance testing
- **Role:** QA+DO · **Priority:** P1 · **Complexity:** M · **Module:** M11 · **Closes:** F-QA-3
- **Description:** k6/Locust scripts for chat/query and connection paths with p50/p95
  targets; scheduled + pre-release runs.
- **Dependencies:** T-SCALE-1, T-ARCH-5.
- **Acceptance criteria:** documented latency/throughput baseline; targets met; OOM path
  proven safe.

### T-QA-4 — SAST + dependency scanning in CI
- **Role:** DO+QA · **Priority:** P1 · **Complexity:** L · **Module:** M11 · **Closes:** F-SEC-9
- **Description:** Add CodeQL/Bandit + `pip-audit`/`npm audit`/Dependabot as CI gates.
- **Dependencies:** none.
- **Acceptance criteria:** scans run on PRs; high-severity findings block merge.

### T-QA-5 — Accessibility checks in CI
- **Role:** QA+FE · **Priority:** P1 · **Complexity:** L · **Module:** M11 · **Closes:** F-UX-3
- **Description:** Automated a11y checks (axe) on key screens.
- **Dependencies:** T-UX-3.
- **Acceptance criteria:** key screens pass automated a11y checks in CI.

### T-DOC-1 — Docs-consistency single source of truth
- **Role:** PM+DO · **Priority:** P1 · **Complexity:** L · **Module:** M11 · **Closes:** F-QA-4
- **Description:** Establish a verified "current state" doc and a check that flags
  coverage/threshold/test-count drift between docs and config.
- **Dependencies:** T-QA-1.
- **Acceptance criteria:** doc/reality mismatches list (from crosscheck) resolved; drift
  check in CI.
