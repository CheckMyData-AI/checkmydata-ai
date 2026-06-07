# 00 — Audit Findings & Risk Register

This document is the critical audit of CheckMyData.ai as it exists today. It records what
is genuinely strong, what is weak or missing, where the documentation contradicts the
code, and the risks that block a commercial production launch. Every finding cites
real files and is assigned a severity, a recommended fix, and the backlog task(s) that
close it (`T-*`, defined in `04-BACKLOG.md`).

## 0. Method and scope

The audit covered the full repository: backend (FastAPI multi-agent system, connectors,
services, MCP server), frontend (Next.js 15 app), database/migrations, CI/CD, and the
existing documentation set. Findings were validated by reading source, not by trusting
docs. Where a claim could not be verified from code it is marked **Needs validation**
(see Section 8).

## 1. What is genuinely strong (keep, do not regress)

These are real strengths and should be protected by the Definition of Done and the
regression checklist in `06-QA-PLAN.md`:

- **Mature multi-agent architecture.** Orchestrator + specialized agents (SQL, Knowledge,
  Git, MCP source) with an LLM router supporting OpenAI/Anthropic/OpenRouter and fallback.
- **Read-only safety posture for data.** `SafetyGuard` enforces read-only SQL; connectors
  are read-only; Git access is read-only with path-traversal guards and output caps.
- **Real RAG.** Chroma vector store + BM25 with reciprocal rank fusion, AST-based code
  intelligence, schema retrieval, and code↔DB lineage.
- **Secrets encrypted at rest.** Fernet encryption for connection credentials via
  `MASTER_ENCRYPTION_KEY`.
- **Migrations exist.** SQLAlchemy 2.x + Alembic; JWT auth with bcrypt; Google OAuth and
  transactional email integrations present.
- **CI runs unit + integration with coverage and caching.** A combined coverage flow and
  artifact upload already exist in `.github/workflows/ci.yml`.

The problems below are about *commercial readiness, security hardening, scale, and
honesty of documentation* — not about the core idea, which is sound.

## 2. Severity scale

| Severity | Meaning | Launch impact |
| --- | --- | --- |
| S1 Critical | Exploitable security hole, data-loss, or launch blocker | Must fix before any paid/public launch |
| S2 High | Serious correctness/scale/compliance gap | Must fix before GA (P2) |
| S3 Medium | Quality, maintainability, or UX gap | Should fix in Beta/GA window |
| S4 Low | Polish, debt, or doc hygiene | Opportunistic |

## 3. Security findings

### F-SEC-1 (S1) — MCP server has no real authentication or tenancy
**Evidence:** `backend/app/mcp_server/auth.py:69` returns `{"user_id": "mcp-anonymous", "email": ""}`
for unauthenticated access; `backend/app/mcp_server/tools.py` hardcodes
`user_id="mcp-user"` for every tool call (lines 111, 122, 135, 156, 167, 180) and passes
`project_id` from the caller with no ownership check.
**Impact:** Anyone who can reach the MCP endpoint can run agent tools against any
`project_id` as a synthetic identity, bypassing the per-user/project access checks that the
HTTP/WebSocket API enforces. This is a cross-tenant data-exposure path.
**Fix:** Require an authenticated principal for every MCP tool (API key or OAuth token
mapped to a real `user_id`), resolve `project_id` ownership/membership exactly like the
HTTP API, and remove the anonymous fallback in production. Gate MCP behind a feature flag
that is off by default until auth lands.
**Backlog:** `T-SEC-1`.

### F-SEC-2 (S1) — JWT transmitted in WebSocket URL query string
**Evidence:** `backend/app/api/routes/chat.py:2210-2238` — the `chat_websocket` endpoint
accepts `token: str | None = None` as a query parameter and decodes it for auth.
**Impact:** Query strings are routinely logged by proxies, load balancers, and access
logs, and are visible in browser history. A leaked JWT grants full account access for its
lifetime.
**Fix:** Authenticate the WebSocket via a subprotocol header or a short-lived,
single-use ticket exchanged over an authenticated HTTPS call, not via the URL. Shorten
token lifetime and add rotation. Scrub tokens from any logging.
**Backlog:** `T-SEC-2`.

### F-SEC-3 (S1) — JWT stored in browser `localStorage`
**Evidence:** Frontend auth store persists the access token in `localStorage`
(`frontend/src/stores/auth-store.ts`), and API/WebSocket clients read it from there.
**Impact:** Any XSS anywhere in the app (or in a dependency) can exfiltrate the token.
There is no CSP to reduce XSS blast radius (see F-SEC-6).
**Fix:** Move to `httpOnly`, `Secure`, `SameSite` cookies for the session, with CSRF
protection for state-changing requests; keep only non-sensitive UI state in
`localStorage`.
**Backlog:** `T-SEC-3`.

### F-SEC-4 (S1) — SSH host-key verification disabled by default
**Evidence:** `backend/app/connectors/ssh_known_hosts.py:40` defaults
`ssh_host_key_policy` to `"disabled"`; `backend/.env.example:199` ships
`SSH_HOST_KEY_POLICY=disabled`; README documents default `disabled`.
**Impact:** SSH-tunneled database connections are vulnerable to man-in-the-middle, since
the server's host key is not verified by default. The mechanism for `tofu`/`strict` exists
but is opt-in.
**Fix:** Default to `strict` (or `tofu` with a managed known-hosts store) in production;
fail closed when a key is unknown; document the secure default and make `disabled` an
explicit, logged, non-production-only override.
**Backlog:** `T-SEC-4`.

### F-SEC-5 (S2) — SSH pre-commands are a shell-injection surface
**Evidence:** `ssh_pre_commands` are executed around tunneled exec paths
(`backend/app/connectors/ssh_exec.py`, `ssh_tunnel.py`); values are user/config supplied.
**Impact:** If any pre-command string is influenced by untrusted input, it becomes remote
command execution on the tunnel host.
**Fix:** Disallow arbitrary pre-commands by default; if needed, restrict to an allowlist,
execute with argument arrays (no shell), and validate/encode inputs.
**Backlog:** `T-SEC-5`.

### F-SEC-6 (S2) — No CSP / HSTS / security headers
**Evidence:** No Content-Security-Policy, Strict-Transport-Security, or related headers
configured in the frontend (`next.config`) or backend middleware.
**Impact:** Larger XSS/clickjacking/downgrade attack surface; compounds F-SEC-3.
**Fix:** Add a strict CSP, HSTS, `X-Content-Type-Options`, `Referrer-Policy`, and frame
ancestors policy; verify with securityheaders-style checks in CI.
**Backlog:** `T-SEC-6`.

### F-SEC-7 (S2) — Rate limiting is in-memory and per-process
**Evidence:** Rate limiting is implemented as per-process in-memory counters; there is no
shared store enforced across dynos (no Redis-backed limiter wired as the limit authority).
**Impact:** Under horizontal scaling (multiple Heroku dynos), limits are multiplied by the
dyno count and effectively bypassable; abuse and cost-spend controls are unreliable.
**Fix:** Move rate limiting and abuse controls to a shared store (Redis) keyed by
user/IP/route; make limits tie into billing entitlements.
**Backlog:** `T-SEC-7`, depends on `T-SCALE-1`.

### F-SEC-8 (S2) — No error tracking / security observability
**Evidence:** No Sentry (or equivalent) integration in backend or frontend; reliance on
logs only.
**Impact:** Production incidents, auth failures, and exploitation attempts are hard to
detect and triage; no alerting.
**Fix:** Add Sentry (backend + frontend) with PII scrubbing, plus structured audit logs
for auth, connection, and billing events.
**Backlog:** `T-OBS-1`.

### F-SEC-9 (S3) — No SAST/dependency scanning in CI
**Evidence:** `.github/workflows/ci.yml` runs lint/test/coverage but no static security
analysis or dependency vulnerability scan.
**Impact:** Known-vulnerable dependencies and common insecure patterns ship undetected.
**Fix:** Add SAST (e.g. CodeQL/Bandit for Python, ESLint security rules) and dependency
scanning (e.g. `pip-audit`, `npm audit`/Dependabot) as CI gates.
**Backlog:** `T-QA-4`.

## 4. Commercialization findings (the biggest product gap)

### F-BIZ-1 (S1) — There is no commercialization layer at all
**Evidence:** No billing, payments, pricing, plans, or paywall anywhere in the codebase.
The only "usage"/"cost" surfaces are LLM-cost UI (`UsageStatsPanel`, `CostEstimator`) and
a backend `usage_service.py` that defines token budgets but does not enforce them.
**Impact:** The product cannot charge money. Per the stated intent (SaaS with payments,
pricing, paywall), this is the central missing capability.
**Fix:** Build billing end to end (Stripe Checkout + Customer Portal + webhooks),
plan/seat/entitlement model, paywall and upgrade flows, and a `/pricing` page. Specified
in `01-PRD.md` (flows/screens), `02-TECH-SPEC.md` (data model + webhook idempotency),
`03-MODULES.md` (M9), and `04-BACKLOG.md`.
**Backlog:** `T-BILL-1`…`T-BILL-9`.

### F-BIZ-2 (S2) — Usage budgets exist but are dead code
**Evidence:** `backend/app/services/usage_service.py:59` defines `check_budget(...)` and a
`BudgetExceededError` (referenced only in `CHANGELOG.md`), but no caller invokes
`check_budget` anywhere in the app — it is never wired into the request/agent path.
**Impact:** There is no enforced ceiling on LLM token spend per user/plan. A single user
(or abuse) can drive unbounded cost. This is both a financial risk and the natural
metering hook for billing.
**Fix:** Wire `check_budget` into the orchestrator/chat entry path, back it with a shared
store, surface remaining budget in the UI, and connect overage to plan entitlements.
**Backlog:** `T-BILL-6`, depends on `T-SCALE-1`.

### F-BIZ-3 (S2) — No `/pricing`, no plan concept, no entitlement checks
**Evidence:** No pricing route in `frontend/src/app`; no plan/subscription tables in
models; feature access is binary (authenticated or not), not plan-gated.
**Impact:** No way to differentiate tiers, run trials, or convert free→paid.
**Fix:** Define value metric, tiers, entitlements, and a `/pricing` page; add
plan-gating middleware and UI paywall states.
**Backlog:** `T-BILL-2`, `T-BILL-3`, `T-GROW-1`.

## 5. Architecture & scale findings

### F-ARCH-1 (S2) — Per-process in-memory state breaks under multi-dyno scale
**Evidence:** Workflow SQL results (`_wf_sql_results`), connector pools, MCP caches, and
rate-limit counters live in process memory; no externalized shared state.
**Impact:** Horizontal scaling produces inconsistent behavior (cache misses, lost
intermediate results, multiplied limits). WebSocket affinity is also implied.
**Fix:** Externalize shared/ephemeral state to Redis (and object storage where
appropriate); make the app horizontally scalable and stateless per request.
**Backlog:** `T-SCALE-1`.

### F-ARCH-2 (S2) — God-files concentrate risk and slow change
**Evidence:** `backend/app/api/routes/chat.py` ≈ 2,811 lines (single file containing the
HTTP + WebSocket entry, message validation, and orchestration glue);
`backend/app/agents/orchestrator.py` ≈ 2,373 lines; `backend/app/agents/sql_agent.py`
≈ 1,964 lines. Large frontend components: `ConnectionSelector.tsx` ≈ 1,302 lines,
`ChatPanel.tsx` ≈ 957, `Sidebar.tsx` ≈ 924.
**Impact:** High change-risk, hard to test in isolation, hard to onboard, merge-conflict
hotspots.
**Fix:** Decompose along clear seams (transport vs orchestration vs tool dispatch;
presentational vs container components) with characterization tests first.
**Backlog:** `T-ARCH-1`, `T-ARCH-2`.

### F-ARCH-3 (S3) — Dual orchestration paths can diverge
**Evidence:** Routing chooses between a "unified tool loop" and a "complex pipeline"
(AdaptivePlanner + StageExecutor); both implement overlapping behavior.
**Impact:** Behavioral drift between paths; bugs fixed in one path persist in the other;
double the test surface.
**Fix:** Define one canonical execution contract; make the pipeline a strategy within the
unified loop or clearly delimit when each is used, with shared tool dispatch and shared
tests.
**Backlog:** `T-ARCH-3`.

### F-ARCH-4 (S3) — Deprecated-but-maintained modules drift
**Evidence:** `backend/app/core/orchestrator.py` and `backend/app/core/tool_executor.py`
are described as deprecated yet remain in the tree and are still maintained.
**Impact:** Confusion about the real entry path; accidental edits to dead paths; stale
behavior copied forward.
**Fix:** Either delete (preferred) or quarantine behind an explicit legacy flag with a
removal date; ensure no production path imports them.
**Backlog:** `T-ARCH-4`.

### F-ARCH-5 (S2) — MySQL fetches all rows before applying the row cap (OOM risk)
**Evidence:** MySQL connector materializes results via `fetchall()` and then applies the
row limit, rather than streaming/limiting at the cursor/SQL level.
**Impact:** A large result set can exhaust memory and crash the dyno before the cap is
applied — a denial-of-service and reliability risk.
**Fix:** Enforce `LIMIT` in SQL, use server-side cursors / chunked fetch, and cap bytes as
well as rows; apply consistently across connectors.
**Backlog:** `T-ARCH-5`.

### F-ARCH-6 (S3) — Key advanced features default OFF
**Evidence:** `hybrid_retrieval_enabled`, `schema_retrieval_enabled`,
`code_graph_enabled`, `lineage_enabled` default to off in config.
**Impact:** The shipped product is materially weaker than the documented capabilities;
"hidden" features are untested in the default path and create a doc/reality gap.
**Fix:** Decide per feature: promote to default-on (with tests + benchmarks) or document
clearly as experimental/opt-in; align docs with the default configuration.
**Backlog:** `T-ARCH-6`.

## 6. Quality / observability / docs-vs-reality findings

### F-QA-1 (S2) — Coverage gate is 40%, but docs claim ~72%
**Evidence:** `.github/workflows/ci.yml:96` enforces `python -m coverage report
--fail-under=40`; `docs/DEPLOYMENT.md:28` documents the 40% gate; meanwhile
`docs/agent-changelog.md:42` claims coverage was boosted to "72.00%, meeting the CI
`cov-fail-under=72` threshold." The enforced gate and the narrative disagree.
**Impact:** False confidence; reviewers believe coverage is enforced at 72% when CI only
fails below 40%. Regressions between 40% and 72% pass silently.
**Fix:** Pick the real target, set `--fail-under` to it, and make every doc match the CI
value. Track coverage as a trend, not just a floor.
**Backlog:** `T-QA-1`.

### F-QA-2 (S2) — No browser E2E tests
**Evidence:** Frontend tests are Vitest unit/component only; no Playwright/Cypress E2E
covering login → connect → query → result → (paywall) flows.
**Impact:** Critical user journeys, including the future billing flow, have no end-to-end
safety net.
**Fix:** Add Playwright E2E for the core journeys and run in CI (headless).
**Backlog:** `T-QA-2`.

### F-QA-3 (S2) — No load/performance testing
**Evidence:** No k6/Locust scripts or performance budget in CI; no documented latency
SLOs validated under load.
**Impact:** Scale behavior (especially the in-memory/state issues above) is unverified;
no capacity baseline before launch.
**Fix:** Add load tests for chat/query and connection paths with explicit p50/p95
targets; run on a schedule and pre-release.
**Backlog:** `T-QA-3`.

### F-QA-4 (S3) — Documentation/reality mismatches beyond coverage
**Evidence:** Test-count and coverage narratives in `docs/agent-changelog.md` and
`CHANGELOG.md` reference different thresholds over time (e.g. 68→69, then 72) that do not
match the live `--fail-under=40`; feature docs describe capabilities that are
default-off (F-ARCH-6).
**Impact:** Erodes trust in documentation; new contributors are misled.
**Fix:** Establish a single "current state" doc generated/verified against config; add a
docs-consistency check. The crosscheck pass in this package fixes the known list.
**Backlog:** `T-QA-1`, `T-DOC-1`.

## 7. UX, legal, and operational findings

### F-UX-1 (S2) — `/dashboard/[id]` has no auth gate
**Evidence:** The dashboard route renders without an enforced authentication guard.
**Impact:** Unauthenticated navigation to a dashboard URL can expose UI/state it should
not; inconsistent with the rest of the app's auth.
**Fix:** Add a route guard (middleware + server check) redirecting unauthenticated users
to login; verify with E2E.
**Backlog:** `T-UX-1`.

### F-UX-2 (S3) — Unwired components shipped in the tree
**Evidence:** `InsightFeedPanel.tsx` and `MetricCatalogPanel.tsx` exist but are not wired
into the app navigation/flows.
**Impact:** Dead UI, confusing for contributors, untested surface.
**Fix:** Either wire them into a real flow (with tests) or remove until needed.
**Backlog:** `T-UX-2`.

### F-UX-3 (S3) — SPA title not updated per route; a11y gaps
**Evidence:** Document title is not updated on client navigation; tooltip and
cost-estimator components have keyboard/focus a11y gaps.
**Impact:** Poor accessibility and SEO/shareability for the app shell; WCAG issues.
**Fix:** Set per-route titles/metadata; fix keyboard focus, ARIA, and contrast per the
design system; add a11y checks to CI.
**Backlog:** `T-UX-3`, `T-QA-5`.

### F-LEGAL-1 (S2) — No DPA, subprocessor list, or data-retention/PII policy for connected customer databases
**Evidence:** Terms and Privacy pages exist, but there is no Data Processing Addendum, no
published subprocessor list, and no documented retention/PII handling policy for the
customer data that flows through queries, previews, learnings, and insight memory.
**Impact:** Blocks B2B sales (security review fails) and creates GDPR/▱compliance exposure,
since customer data is processed and partially cached (previews to the LLM, learnings,
insight memory).
**Fix:** Publish a DPA + subprocessor list (LLM providers, hosting, email), define
retention windows and deletion guarantees, and document what data is sent to LLMs and how
it is minimized/redacted.
**Backlog:** `T-LEGAL-1`, `T-LEGAL-2`.

### F-FIN-1 (S2) — No cost guardrails on LLM spend; no abuse/fair-use limits tied to billing
**Evidence:** F-BIZ-2 (budgets unenforced) + F-SEC-7 (limits bypassable at scale) combine:
there is no reliable ceiling on per-user LLM cost.
**Impact:** Unbounded COGS; a single abusive or runaway account can produce large bills.
**Fix:** Enforce per-plan token/query budgets in a shared store, alert on spend anomalies,
and define fair-use limits in the pricing tiers.
**Backlog:** `T-BILL-6`, `T-SEC-7`, `T-OBS-2`.

### F-OPS-1 (S3) — No admin/ops console
**Evidence:** No internal admin surface for user/plan management, impersonation for
support, connection diagnostics, or feature-flag control.
**Impact:** Support and operations require direct DB access; slow, risky, unauditable.
**Fix:** Build a minimal admin console (M10) with audit logging and role gating.
**Backlog:** `T-ADMIN-1`…`T-ADMIN-3`.

## 8. Needs validation (stakeholder decisions before build)

These items are assumptions or open decisions captured here so they are not silently baked
in. They are flagged in the PRD/Tech Spec where used.

1. **Pricing & packaging.** Proposed defaults (value metric = connections + queries/seats;
   Free / Pro / Team / Enterprise). Final tier names, prices, and limits need sign-off.
2. **Deployment target.** Assumed Heroku primary + Docker; Redis added for shared state.
   Multi-region is **not** assumed for MVP. Confirm.
3. **Mobile.** Assumed responsive web for MVP; native app is Post-launch. Confirm.
4. **Coverage target.** Recommend raising the real `--fail-under` to a committed number
   (proposal: 60% backend now, 72% by GA). Needs agreement.
5. **LLM data handling.** Confirm which providers are in scope, whether zero-retention API
   tiers are used, and what redaction is required before sending customer data/schema to
   LLMs (affects DPA).
6. **Auth model for MCP.** Confirm API-key vs OAuth and whether MCP is in MVP scope or
   gated off until GA.
7. **Session model.** Confirm move to httpOnly cookies (affects any external API consumers
   currently relying on bearer tokens).
8. **Default-on features.** Decide which of hybrid retrieval / schema retrieval / code
   graph / lineage become default-on for paid tiers.

## 9. Finding → backlog traceability

| Finding | Severity | Backlog | Module | Phase |
| --- | --- | --- | --- | --- |
| F-SEC-1 MCP auth/tenancy | S1 | T-SEC-1 | M1 | P0-MVP |
| F-SEC-2 WS token in URL | S1 | T-SEC-2 | M1 | P0-MVP |
| F-SEC-3 JWT in localStorage | S1 | T-SEC-3 | M1 | P0-MVP |
| F-SEC-4 SSH host-key default | S1 | T-SEC-4 | M2 | P0-MVP |
| F-SEC-5 SSH pre-commands | S2 | T-SEC-5 | M2 | P0-MVP |
| F-SEC-6 CSP/HSTS | S2 | T-SEC-6 | M1 | P0-MVP |
| F-SEC-7 Rate limit shared store | S2 | T-SEC-7 | M11 | P1-BETA |
| F-SEC-8 Error tracking | S2 | T-OBS-1 | M11 | P0-MVP |
| F-SEC-9 SAST/dep scan | S3 | T-QA-4 | M11 | P1-BETA |
| F-BIZ-1 No billing layer | S1 | T-BILL-1..9 | M9 | P0-MVP |
| F-BIZ-2 Budgets dead code | S2 | T-BILL-6 | M9/M11 | P0-MVP |
| F-BIZ-3 No pricing/plans | S2 | T-BILL-2, T-BILL-3, T-GROW-1 | M9/M12 | P0-MVP |
| F-ARCH-1 In-memory state | S2 | T-SCALE-1 | M11 | P1-BETA |
| F-ARCH-2 God-files | S2 | T-ARCH-1, T-ARCH-2 | M3 | P1-BETA |
| F-ARCH-3 Dual orchestration | S3 | T-ARCH-3 | M3 | P1-BETA |
| F-ARCH-4 Deprecated modules | S3 | T-ARCH-4 | M3 | P1-BETA |
| F-ARCH-5 MySQL OOM | S2 | T-ARCH-5 | M2 | P0-MVP |
| F-ARCH-6 Features default-off | S3 | T-ARCH-6 | M4/M5 | P1-BETA |
| F-QA-1 Coverage 40 vs 72 | S2 | T-QA-1 | M11 | P0-MVP |
| F-QA-2 No E2E | S2 | T-QA-2 | M11 | P1-BETA |
| F-QA-3 No load tests | S2 | T-QA-3 | M11 | P1-BETA |
| F-QA-4 Doc/reality mismatch | S3 | T-QA-1, T-DOC-1 | M11 | P0-MVP |
| F-UX-1 Dashboard auth gate | S2 | T-UX-1 | M7 | P0-MVP |
| F-UX-2 Unwired components | S3 | T-UX-2 | M7 | P1-BETA |
| F-UX-3 Title/a11y | S3 | T-UX-3, T-QA-5 | M7 | P1-BETA |
| F-LEGAL-1 DPA/retention | S2 | T-LEGAL-1, T-LEGAL-2 | M9/M11 | P1-BETA |
| F-FIN-1 Cost guardrails | S2 | T-BILL-6, T-SEC-7, T-OBS-2 | M9/M11 | P0-MVP |
| F-OPS-1 No admin console | S3 | T-ADMIN-1..3 | M10 | P1-BETA |

See `04-BACKLOG.md` for the full task definitions and acceptance criteria.
