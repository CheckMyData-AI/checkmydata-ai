# 01 — Product Requirements Document (PRD)

This is the product definition for CheckMyData.ai as a commercially launchable SaaS. It
covers who it is for, the value it delivers, the core scenarios, onboarding and retention,
monetization and pricing, limits, key metrics, and the full UX/UI specification including
the new paywall/billing flow and admin interfaces.

## 1. Product summary

CheckMyData.ai is an AI data-and-codebase analyst. A user connects their databases
(Postgres, MySQL, MongoDB, ClickHouse) and, optionally, their code repository, then asks
questions in natural language. A multi-agent system plans the work, writes and runs
read-only SQL, retrieves relevant code and schema context, and returns an answer with the
evidence (query, results, visualizations) behind it. It remembers what it learns about a
project to get faster and more accurate over time.

The product is read-only by design for customer data: it never mutates connected
databases, and code access is read-only.

## 2. Target audience & ICPs

| ICP | Who | Core job-to-be-done | Why CheckMyData |
| --- | --- | --- | --- |
| **ICP-1: Data-curious operator** (PM, ops, founder, analyst-adjacent) | Knows the business questions, not SQL | "Answer my data question without waiting on the data team" | Natural-language → trustworthy SQL + chart, no SQL skills required |
| **ICP-2: Engineer / data engineer** | Comfortable with SQL but time-poor | "Explore an unfamiliar DB/codebase fast; skip boilerplate queries" | Schema + code + lineage context; correct SQL fast; sees the query |
| **ICP-3: Small data team lead** | Owns a shared DB, fields ad-hoc requests | "Deflect repetitive ad-hoc questions; let the team self-serve safely" | Read-only safety, shared project memory, collaboration |

Primary launch ICP: **ICP-1 and ICP-2** in startups/SMBs (10–200 employees) running their
own application databases. ICP-3 drives the Team tier and seats.

Anti-personas (not targeting at launch): regulated enterprises requiring on-prem only;
users who need write/ETL operations; pure BI-dashboard buyers wanting a Looker
replacement.

## 3. Core value proposition

> Ask your database and codebase questions in plain language and get a correct,
> explainable answer in seconds — without writing SQL, without giving anyone write access,
> and with an assistant that learns your data model over time.

Differentiators that the product can actually back with code today:

- **Explainable, not a black box:** every answer can show the SQL, the rows, and the
  retrieved context.
- **Read-only and safe:** `SafetyGuard` + read-only connectors + read-only Git.
- **Code-aware:** RAG over the actual repository (AST, schema retrieval, code↔DB lineage),
  not just the database.
- **Learns the project:** agent learnings + insight memory improve accuracy and speed.

## 4. Primary user scenarios

Each scenario lists the trigger, steps, and the "done" outcome. These map to the E2E test
suite in `06-QA-PLAN.md`.

### S-1: First value (activation)
1. User signs up (email or Google), lands in an empty workspace.
2. Connects a database (guided form; credentials encrypted at rest).
3. Asks a first question (a suggested prompt is offered).
4. Gets an answer with SQL + results + a chart.
**Done:** user has run ≥1 successful query within the first session ("activation").

### S-2: Ad-hoc analysis (core loop)
1. User asks a business question in natural language.
2. Agent plans, retrieves schema/code context, generates read-only SQL, runs it, returns
   answer + visualization.
3. User refines ("break this down by month"), agent iterates.
**Done:** user gets an answer they trust, optionally pins/saves it.

### S-3: Codebase + data investigation
1. User connects a repository (read-only) alongside the DB.
2. Asks a question that spans code and data ("which service writes to `orders`, and how
   many orders failed yesterday?").
3. Agent uses code↔DB lineage + SQL to answer.
**Done:** answer cites both code locations and data results.

### S-4: Hitting a limit → upgrade (monetization)
1. Free user exhausts a plan limit (e.g. monthly query budget or 2nd connection).
2. Paywall explains the limit and the value of upgrading; shows the plan.
3. User upgrades via Stripe Checkout; entitlement updates immediately.
**Done:** user is on a paid plan and the blocked action now succeeds.

### S-5: Team collaboration
1. Owner invites a teammate to a project.
2. Teammate joins, sees shared connections and project memory (per role).
3. Both query the same project; learnings are shared.
**Done:** ≥2 active members in a project, seat-based billing reflects it.

### S-6: Manage subscription
1. User opens billing settings.
2. Views plan, usage vs limits, invoices; opens Stripe Customer Portal to change
   plan/payment method or cancel.
**Done:** changes reflected in entitlements and UI.

## 5. Onboarding

Goal: get to first successful query (activation) as fast as possible.

- **Step 0 — Sign up:** email/password or Google OAuth. Verify email asynchronously (do
  not block first query).
- **Step 1 — Connect a source:** guided connection form with provider presets,
  test-connection button, clear error messages, and an option to use a sample/demo
  database for users who want to try before connecting real data.
- **Step 2 — Guided first question:** show 3 suggested prompts derived from the connected
  schema; one click runs one.
- **Step 3 — Show the answer anatomy:** first answer highlights "here's the SQL, here's the
  data, here's the chart" so users learn to trust it.
- **Empty states everywhere** (see UX spec) guide the next action.

Activation metric: % of new signups that run ≥1 successful query in the first session.
Target ≥ 45% at GA.

## 6. Retention mechanics

- **Project memory compounding value:** the more you use a project, the smarter it gets
  (agent learnings, insight memory) — surfaced to the user as "what I've learned about this
  project."
- **Saved/pinned answers & history:** quick re-run and sharing.
- **Insight feed (wire up M5/F-UX-2):** proactive surfaced findings keep users returning.
- **Collaboration:** shared projects create multi-user stickiness.
- **Email digests (transactional infra already present via Resend):** weekly "insights in
  your data" digest.

Retention metrics: W1/W4 retention of activated users; queries per active user per week.

## 7. Monetization & pricing

**Value metric (proposed, Needs validation):** a blend of *connections* (number of
connected sources), *query volume* (monthly successful queries / LLM token budget), and
*seats* (team members). This aligns price with both cost (LLM tokens) and value
(breadth of data access + team usage).

### Proposed tiers (defaults — finalize per `00-AUDIT-FINDINGS.md` §8)

| Tier | Price (proposed) | Connections | Query/token budget | Seats | Key gating |
| --- | --- | --- | --- | --- | --- |
| **Free** | $0 | 1 | Low monthly budget | 1 | Core query loop, no code repo, community support |
| **Pro** | ~$29/mo | 3 | Medium budget | 1 | Code repo + lineage, saved answers, priority models |
| **Team** | ~$99/mo + per-seat | 10 | High budget, pooled | 3 included, then per-seat | Collaboration, shared memory, admin basics |
| **Enterprise** | Custom | Custom | Custom + zero-retention LLM | Custom | SSO, DPA, audit logs, SLA |

- **Trial:** Pro features free for 14 days on signup (no card), then downgrade to Free.
- **Overage:** soft cap with in-app warning at 80%/100%; hard stop on Free, metered
  overage option on Team (Needs validation).
- **Entitlements** are enforced server-side (plan-gating middleware) and surfaced in the UI
  (usage meters, paywall).

This requires the billing build (`M9`) and ties directly to F-BIZ-1/2/3 and F-FIN-1.

## 8. Limits & fair-use

- Per-plan monthly **token budget** (enforced via `usage_service.check_budget`, wired in
  `T-BILL-6`).
- Per-plan **connection count** and **seat count** (entitlement checks).
- Per-request **row cap and byte cap** on query results (also a safety control, `T-ARCH-5`).
- **Rate limits** per user/route via shared store (`T-SEC-7`).
- **Abuse controls:** spend-anomaly alerts (`T-OBS-2`); automatic throttle on runaway loops
  (orchestrator iteration ceiling already exists; tie to plan).

## 9. Key metrics

| Category | Metric | Definition | GA target |
| --- | --- | --- | --- |
| Acquisition | Signup→activation | % of signups running ≥1 successful query in session 1 | ≥ 45% |
| Engagement | WAU/MAU | Active users weekly/monthly | Trend up |
| Engagement | Queries / active user / week | Core-loop usage | ≥ 10 |
| Retention | W4 retention (activated) | Activated users active in week 4 | ≥ 35% |
| Conversion | Free→paid | % of activated free users converting within 30d | ≥ 4% |
| Revenue | NRR | Net revenue retention (Team/Enterprise) | ≥ 100% |
| Reliability | Query success rate | successful answers / attempts | ≥ 95% |
| Reliability | p95 answer latency | end-to-end for typical query | < 12s (Needs validation) |
| Cost | LLM COGS / active user | gross margin guardrail | within target margin |

## 10. UX/UI specification

This section defines the screens, their states, error/edge/empty states, the paywall/
billing flow, and admin interfaces. It builds on the existing design system
(`DESIGN_SYSTEM.md`). New screens are marked **NEW**.

### 10.1 Information architecture / main screens

| Screen | Route | Purpose |
| --- | --- | --- |
| Marketing home | `/` | Value prop, CTA to sign up |
| Pricing **NEW** | `/pricing` | Tiers, FAQ, CTA → checkout/trial |
| Auth | `/login`, `/signup` | Authentication |
| Workspace / Chat | `/` (app) or `/chat` | Core query loop |
| Connections | `/connections` | Manage data/code sources |
| Dashboard | `/dashboard/[id]` | Saved views/visualizations (auth-gated, F-UX-1) |
| Project memory | within workspace | "What I've learned" + insight feed |
| Billing & usage **NEW** | `/settings/billing` | Plan, usage meters, invoices, portal link |
| Account settings | `/settings/*` | Profile, security, team |
| Admin console **NEW** | `/admin/*` (role-gated) | Internal ops (M10) |

### 10.2 Core workspace / chat screen

Layout: left sidebar (projects, connections, history), center chat, right context panel
(SQL/result/visualization and "answer anatomy").

States:
- **Empty (no connection):** prominent "Connect your first data source" with a "Try sample
  database" secondary action.
- **Empty (connection, no queries):** show 3 schema-derived suggested prompts.
- **Loading / streaming:** show agent steps (planning → retrieving → querying → answering)
  with the ability to stop.
- **Answer:** message + collapsible "SQL", "Results table", "Chart", "Context used".
- **Refinement:** follow-up input pre-seeded with the prior query context.
- **Error states:** see §10.6.
- **Limit reached:** inline paywall card (see §10.5) instead of an answer.

### 10.3 Connections screen

- List of connections with status (connected / error / testing), type, last used.
- Add/edit form: provider preset, host/port/db, credentials (encrypted), optional SSH
  tunnel (with host-key policy surfaced; secure default per `T-SEC-4`), optional code repo.
- **Test connection** with explicit success/failure messaging.
- Empty state: guided first-connection (mirrors onboarding Step 1).
- Edge cases: connection at plan limit → upgrade prompt; failing connection → diagnostic
  details and retry.

### 10.4 Billing & usage screen **NEW**

- **Current plan** card: tier, price, renewal date, seats used/included.
- **Usage meters:** queries/token budget used vs limit (this period), connections used vs
  limit, with 80%/100% warning styling.
- **Invoices:** list with download links (from Stripe).
- **Manage:** "Open billing portal" (Stripe Customer Portal) for plan changes, payment
  method, cancellation.
- States: free (with upgrade CTA), trialing (days left + convert CTA), active, past_due
  (payment retry banner), canceled (reactivate CTA).

### 10.5 Paywall / billing flow **NEW**

Trigger points: 2nd connection on Free, monthly budget exhausted, code-repo feature on
Free, inviting a teammate beyond seat limit.

Flow:
1. **Paywall card/modal** explaining exactly which limit was hit, what upgrading unlocks,
   and the price; primary CTA "Upgrade", secondary "See plans" (→ `/pricing`).
2. **Stripe Checkout** (hosted) for the selected plan; trial users may convert without
   re-entering data.
3. **Webhook-driven entitlement update** (idempotent); UI reflects the new plan
   immediately on return, with optimistic state plus reconciliation.
4. **Success state:** the previously blocked action is retried automatically.
5. **Failure/cancel state:** return to app with a non-punitive message and a way to retry.

Edge cases: webhook delay (show "activating your plan…" with poll/refresh), payment
failure (past_due banner + retry), duplicate webhook (idempotency key, no double-grant),
downgrade (entitlements reduce at period end, with clear messaging).

### 10.6 Error, edge, and empty states (global rules)

- **Auth required:** protected routes (including `/dashboard/[id]`, F-UX-1) redirect to
  login, preserving intended destination.
- **Query errors:** distinguish (a) connection error, (b) SQL/validation error (agent
  self-repairs where possible, surfaced as "I adjusted the query"), (c) empty result
  (offer to broaden), (d) timeout/budget (clear message + next step).
- **Large results:** enforce row/byte caps (`T-ARCH-5`); offer download/pagination rather
  than dumping everything.
- **Network/streaming drop:** reconnect WebSocket gracefully; never lose the user's
  question.
- **Permission errors:** clear "you don't have access to this project" messaging.
- **Empty states:** every list (projects, connections, history, invoices) has a purposeful
  empty state with the next best action.
- **Accessibility:** per-route document titles (F-UX-3), keyboard-navigable tooltips and
  cost estimator, focus management in modals, WCAG AA contrast.

### 10.7 Admin interfaces **NEW** (M10)

Role-gated `/admin` console for internal staff:
- **Users:** search, view plan/usage, suspend, and (audited) impersonate for support.
- **Subscriptions:** view/adjust plan, comp credits, see Stripe linkage.
- **Connections (diagnostics only):** status and error history (never credentials in
  plaintext).
- **Feature flags:** toggle experimental features per environment/plan (F-ARCH-6).
- **Audit log:** every admin action recorded (actor, target, action, time).

All admin actions are audited and require an elevated role; no admin surface is reachable
by normal users.

## 11. Out of scope for this PRD cycle

- Write/ETL operations on customer databases (read-only is a core invariant).
- Native mobile apps (responsive web only at launch; native is Post-launch).
- Full BI dashboarding suite (basic saved views only).
- On-prem/self-hosted distribution (Enterprise consideration, Post-launch).

## 12. Traceability

- Billing/paywall → `M9`, tasks `T-BILL-*`, closes F-BIZ-1/2/3, F-FIN-1.
- Pricing/growth pages → `M12`, tasks `T-GROW-*`.
- Dashboard auth gate → `T-UX-1` (F-UX-1).
- A11y/title → `T-UX-3`, `T-QA-5` (F-UX-3).
- Admin console → `M10`, `T-ADMIN-*` (F-OPS-1).
- Architecture/scale/security that constrain UX → see `02-TECH-SPEC.md`.
