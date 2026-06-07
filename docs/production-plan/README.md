# CheckMyData.ai — Production-Ready Master Plan

This folder is a self-contained planning package for taking CheckMyData.ai from its
current "mature engineering prototype" state to a commercially launchable SaaS. It is
grounded in the actual codebase: every audit finding cites real files, and every
proposed feature maps to concrete backlog tasks with acceptance criteria.

It is written to serve four roles at once:

| Audience | Read this as | Primary documents |
| --- | --- | --- |
| Product | Product Requirements Document (PRD) | `01-PRD.md` |
| Engineering | Technical Specification | `02-TECH-SPEC.md`, `03-MODULES.md` |
| Delivery / PM | Roadmap + Backlog | `04-BACKLOG.md`, `05-ROADMAP.md` |
| QA | Master test strategy | `06-QA-PLAN.md` |
| Leadership | Risk register + go/no-go | `00-AUDIT-FINDINGS.md` |

## Documents

1. [`00-AUDIT-FINDINGS.md`](./00-AUDIT-FINDINGS.md) — Critical audit of the current
   system: weaknesses, contradictions, gaps, and a risk register across product /
   technical / legal / UX / operational / financial dimensions. Each finding carries
   file-level evidence, severity, recommended fix, and a linked backlog ID. Ends with a
   "Needs validation" list of open decisions for stakeholders.
2. [`01-PRD.md`](./01-PRD.md) — Product definition: target audience and ICPs, value
   proposition, primary user scenarios, onboarding, retention mechanics, monetization
   and pricing, limits/fair-use, and key metrics. Includes the full UX/UI specification
   (screens, states, error/edge/empty states, paywall/billing flow, admin interfaces).
3. [`02-TECH-SPEC.md`](./02-TECH-SPEC.md) — Target architecture: components, backend
   logic, frontend logic, application database, API surface, admin panel, payments,
   analytics, security, scalability, monitoring, and logging. Includes target-state
   diagrams and explicit deltas from the as-built system.
4. [`03-MODULES.md`](./03-MODULES.md) — The system decomposed into 12 modules. For each:
   goal, key functions, user scenarios, technical requirements, dependencies, risks, and
   readiness (Definition of Done) criteria.
5. [`04-BACKLOG.md`](./04-BACKLOG.md) — Detailed development backlog. Each task: ID,
   name, description, role, priority (P0/P1/P2), complexity, dependencies, and acceptance
   criteria. P0 security fixes and the billing build are front-loaded.
6. [`05-ROADMAP.md`](./05-ROADMAP.md) — Phased plan: MVP, Beta, Production Launch,
   Post-launch. Per phase: in-scope, explicitly out-of-scope, expected result, and
   success metrics.
7. [`06-QA-PLAN.md`](./06-QA-PLAN.md) — Test scope, key and critical scenarios, load
   testing, security testing, regression checklist, and CI gate corrections.
8. [`07-TRACEABILITY.md`](./07-TRACEABILITY.md) — Master traceability matrix linking
   findings → backlog → modules → roadmap → QA, the verified doc/reality mismatch list, and
   the internal consistency checks performed on this package.

## How the documents connect

```
00-AUDIT-FINDINGS (problems, evidence, risk)
        │  each finding → backlog ID
        ▼
04-BACKLOG (tasks) ──maps to──► 03-MODULES (DoD per module)
        │                               │
        ▼                               ▼
05-ROADMAP (phases) ◄──────────── 01-PRD + 02-TECH-SPEC (what & how)
        │
        ▼
06-QA-PLAN (verify each phase exit)
```

Traceability convention used throughout:

- Audit findings are `F-<area>-<n>` (e.g. `F-SEC-1`).
- Backlog tasks are `T-<area>-<n>` (e.g. `T-SEC-1`).
- Modules are `M<n>` (e.g. `M9 Billing & Monetization`).
- Roadmap phases are `P0-MVP`, `P1-BETA`, `P2-GA`, `P3-POST`.

Each finding lists the backlog task(s) that close it; each backlog task lists the
module it belongs to and the roadmap phase it lands in.

## Source-of-truth and Linear sync

Per the repository's project-management rule, **Linear is the single source of truth for
tasks, backlog, bugs, and status** (Linear project `checkmydataai`). These Markdown
documents are the *planning artifact* — the reasoning, specification, and acceptance
criteria. The epics and tasks defined in `04-BACKLOG.md` should be mirrored into Linear
as issues (one Linear epic per module, one Linear issue per `T-*` task) rather than
tracked twice. When a task's status changes, update it in Linear; treat this document as
the durable specification and Linear as the live tracker.

Recommended mirroring:

- Linear epic ↔ module (`M1`…`M12`).
- Linear issue ↔ backlog task (`T-*`), copying the acceptance criteria into the issue
  description and applying labels `P0`/`P1`/`P2`, `security`, `billing`, `growth`, etc.
- Link each Linear issue back to the audit finding ID it resolves.

## Scope note

This package is documentation only. It does not modify product code. Where the audit
found bugs or risks, they are captured as prioritized backlog items, not silent edits.
Pricing numbers, tier names, and a few infrastructure assumptions are proposed defaults;
all such items are collected in the "Needs validation" section of `00-AUDIT-FINDINGS.md`
for stakeholder sign-off before build.
