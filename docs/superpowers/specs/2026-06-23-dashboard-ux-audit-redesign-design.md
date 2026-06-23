# CheckMyData.ai — Dashboard UX Research Audit & Role-Adaptive Redesign

- **Date:** 2026-06-23
- **Status:** Draft for review (brainstorming → spec)
- **Author:** UX research audit (Claude, design skills)
- **Scope (locked with stakeholder):**
  - Coverage: **all roles, end-to-end** — first-session admin, owner, editor, viewer, **self-hosted operator** (`ADMIN_EMAILS`).
  - Theme: **dual-theme (light + dark) with a toggle is a firm requirement.**
  - Direction: **full role-adaptive rebuild** — surfaces compose per role; operator gets a dedicated `/admin` console.
  - Depth: **deep** — per-scenario journey tables (step → automate/manual → interface → gap + severity), key findings, target experience, **wireframes/mockups**, and funnel KPIs.
- **North star (from `vision.md`):** "intelligence layer between humans and their databases." The dashboard must feel like *the agent does the work; the user just consumes the result* — **light, airy, calm, automated**. §7 invariants (read-only by default, credentials never exposed, every answer traceable, graceful degradation, user feedback is highest authority, freshness tracked) are load-bearing and must survive the redesign.

---

## 0. Executive summary

### 0.1 Top findings (severity-ranked)

| # | Finding | Severity | Where |
|---|---|---|---|
| F1 | **Two conflicting "getting started" surfaces** — onboarding wizard is DB-first (5 steps); sidebar checklist is **SSH-first** (3 steps). They disagree and the SSH-first order is false friction. | 🔴 | `OnboardingWizard.tsx`, `Sidebar.tsx:484` |
| F2 | **Self-hosted operator has no UI at all** — only `metrics.py` + `backup.py` are `require_admin`; operators live on raw JSON/curl. | 🔴 | `deps.py:78`, no `/admin` route |
| F3 | **The "dashboard" is a 12-section power-tool sidebar, not an agent-first surface** — everything is always visible regardless of role/task; cognitive load is high; contradicts "user just consumes." | 🔴 | `Sidebar.tsx` |
| F4 | **No light theme, no toggle** — hardcoded dark Zinc in `@theme`; not airy. | 🔴 | `globals.css:31` |
| F5 | **Project Overview is a thin health page, not a home** — no "what can I do / what changed / ask something" entry point. | 🟡 | `ProjectOverview.tsx` |
| F6 | **Connection setup is all-manual** — no connection-string paste→autofill, no type auto-detect; high activation friction. | 🟡 | `connections/` |
| F7 | **Indexing blocks momentum** — onboarding stalls on "Index your database" instead of progressive readiness. | 🟡 | wizard step 2 |
| F8 | **No post-activation guidance** — `is_onboarded` flips silently; no nudges to invite team / schedule / save a board. | 🟡 | `app/page.tsx:121` |
| F9 | **Role surfaces are gated by hiding, not by composition** — editor/viewer see the owner shell with buttons removed, not a surface designed for them. | 🟡 | `usePermission.ts`, `Sidebar.tsx` |
| F10 | **Settings is a single flat panel** mixing account, project, MCP tokens; no place for theme/language/notification prefs. | 🟢 | `SettingsPanel.tsx` |

### 0.2 Direction

Rebuild the authenticated experience as a **role-adaptive, agent-first cockpit**:

- **Home = Ask.** A calm conversational/answer surface is the default. Saved answers and boards are one hop away.
- **Setup recedes.** Connections, indexing, rules, schedules become *agent-assisted contextual flows* + a quiet **Workspace** hub — not 12 always-open sidebar sections.
- **Surfaces compose per role** (viewer → editor → owner → operator), not "owner shell minus buttons."
- **Operator gets `/admin`** — a dedicated, read-mostly ops console (health, metrics, backups, cluster, MCP tokens, stale-run reaper).
- **Light + dark** on a single token contract; light is the airy default for new users; system-preference aware; toggle in the account menu.

---

## 1. Method & sources

This audit is **code-grounded**, not from memory. Primary sources read:

- App shell & panel routing: `frontend/src/app/app/page.tsx`
- Navigation IA & onboarding checklist: `frontend/src/components/Sidebar.tsx`
- First-session funnel: `frontend/src/components/onboarding/OnboardingWizard.tsx`
- Home/overview: `frontend/src/components/projects/ProjectOverview.tsx`
- Settings: `frontend/src/components/settings/SettingsPanel.tsx`
- Roles (frontend): `frontend/src/hooks/usePermission.ts`
- Roles/admin (backend): `backend/app/api/deps.py`, route modules in `backend/app/api/routes/`
- Theme tokens: `frontend/src/app/globals.css`
- Product invariants: `CLAUDE.md`, `vision.md`

Design lenses applied: `frontend-design`, `minimalist-ui`, `ui-ux-pro-max`, `product-skills:ux-researcher-designer`, `design:design-critique`, `design:accessibility-review`, `marketing-skills:onboarding-cro` (activation funnel), `tailwind-design-system` / `anthropic-skills:theme-factory` (dual-theme tokens).

---

## 2. Role model & access matrix

Two **orthogonal** axes exist in code:

1. **Project membership role** (`ProjectMember.role`): `owner | editor | viewer` → `usePermission()`.
2. **Server admin** (`ADMIN_EMAILS` → `require_admin`): the self-hosted **operator**, independent of project role.

Plus a transient **requestor** state: a logged-in user with `!canCreate` who must request access (`RequestAccessModal`, wizard step-0 "requires approval").

| Capability | Viewer | Editor | Owner | Operator |
|---|:---:|:---:|:---:|:---:|
| Ask questions / view answers | ✅ | ✅ | ✅ | (as member) |
| View dashboards/boards, give feedback | ✅ | ✅ | ✅ | — |
| Save query / note | ✅ | ✅ | ✅ | — |
| Create dashboards, save viz, batch | — | ✅ | ✅ | — |
| Author custom rules | — | ✅ | ✅ | — |
| Index repo (`canIndex`) | — | ✅ | ✅ | — |
| Create/manage **connections** | — | — | ✅ | — |
| Manage **SSH keys** | — | — | ✅ | — |
| **Schedules** | — | — | ✅ | — |
| **Invites / members / roles / approval** | — | — | ✅ | — |
| **Billing / usage / upgrade** | — | — | ✅ | — |
| **MCP tokens** (per-user) | ✅* | ✅* | ✅* | ✅* |
| Analytics / request-history / traces | — | — | ✅ | — |
| Delete project | — | — | ✅ | — |
| **Server metrics / Prometheus** | — | — | — | ✅ |
| **Trigger/monitor backups** | — | — | — | ✅ |
| **Cluster metrics / reaper / worker health** | — | — | — | ✅ |

\* MCP tokens are per-user and minted via `/api/auth/mcp-tokens`; available to any authenticated user, surfaced today inside Settings.

**Design implication:** the current shell renders the **owner** composition and *removes* controls for lesser roles (F9). A role-adaptive rebuild instead **composes the minimum surface** for each role and *adds* capability as the role grows. The operator is a different persona entirely and belongs on its own route.

---

## 3. Design principles

### 3.1 Light & airy

Targets (vs. today's dense dark tool):

- **Whitespace as default.** Section padding `20–24px`; card gap `16px`; generous line-height (`1.5` body). Today's sidebar uses `text-[10px]/[11px]` micro-type and tight `py-2` rows — reads as a control panel, not a calm product.
- **Type scale.** Establish a real scale: Display 24/30, H1 18/24, H2 15/20, Body 14/20, Small 13/18, Caption 12/16. Retire the `10px` labels except for dense tabular metadata.
- **Fewer borders, more elevation.** Replace ubiquitous `border-border-subtle` hairlines with soft elevation (shadow + surface step) in light; keep subtle borders in dark. Airy = fewer lines.
- **One accent.** Blue accent reserved for primary action and "agent is working." Status colors (success/warn/error) only for status.
- **Progressive disclosure.** Default screens show the *answer and the next action*; configuration and internals are one click deeper.

### 3.2 Dual-theme architecture (token contract)

**Implementation pattern (Tailwind v4 + runtime theming):** today tokens are static in `@theme`. Move the raw values into `:root` (light) and `.dark` (dark) custom properties, and have `@theme inline` *reference* them so all existing `bg-surface-*`, `text-text-*` utilities keep working unchanged:

```css
/* globals.css */
@theme inline {
  --color-surface-0: var(--surface-0);
  --color-surface-1: var(--surface-1);
  /* …every semantic token aliases a runtime var… */
  --color-text-primary: var(--text-primary);
  --color-accent: var(--accent);
}

:root {            /* LIGHT (airy default for new users) */
  --surface-0: #fafafa;  --surface-1: #ffffff;  --surface-2: #f4f4f5;  --surface-3: #e4e4e7;
  --border-subtle: #e4e4e7; --border-default: #d4d4d8;
  --text-primary: #18181b; --text-secondary: #52525b; --text-tertiary: #71717a; --text-muted: #a1a1aa;
  --accent: #2563eb; --accent-hover: #3b82f6; --accent-strong: #1d4ed8; --accent-muted: #2563eb14;
  --success: #059669; --warning: #d97706; --error: #dc2626; --info: #2563eb;
}

.dark {            /* DARK (current values, preserved) */
  --surface-0: #09090b;  --surface-1: #18181b;  --surface-2: #27272a;  --surface-3: #3f3f46;
  --border-subtle: #27272a; --border-default: #3f3f46;
  --text-primary: #fafafa; --text-secondary: #a1a1aa; --text-tertiary: #84848e; --text-muted: #52525b;
  --accent: #3b82f6; --accent-hover: #60a5fa; --accent-strong: #1d4ed8; --accent-muted: #3b82f620;
  --success: #34d399; --warning: #fbbf24; --error: #f87171; --info: #60a5fa;
}
```

| Token | Light | Dark | Role |
|---|---|---|---|
| surface-0 | `#fafafa` | `#09090b` | app canvas |
| surface-1 | `#ffffff` | `#18181b` | cards / panels |
| surface-2 | `#f4f4f5` | `#27272a` | hover / inset |
| surface-3 | `#e4e4e7` | `#3f3f46` | strong fill |
| border-subtle | `#e4e4e7` | `#27272a` | hairline |
| text-primary | `#18181b` | `#fafafa` | headings/body |
| text-secondary | `#52525b` | `#a1a1aa` | secondary |
| accent | `#2563eb` | `#3b82f6` | primary action |

- **Toggle & persistence:** `light | dark | system` selector in the account menu; persisted to `localStorage` + user prefs; an inline `<head>` script applies `.dark` before paint to avoid FOUC. Respects `prefers-color-scheme` when `system`.
- **Status tints** use darker hues in light for WCAG AA contrast on light surfaces; muted `…14`–`…20` alpha fills for chips work in both.
- **Charts (chart.js):** chart palette must read from CSS vars per theme; gridlines/labels swap with theme.
- **Constraint:** zero per-component hardcoded hex — everything routes through tokens, so the toggle is total.

### 3.3 Agent-driven interaction principles

- **Answer-first.** The default unit is an answer (or a board of answers), not a form. Setup is *consequence of intent* ("ask about your orders" → agent notices no connection → inline connect).
- **Automate the boring, confirm the consequential.** Auto-detect / auto-test / auto-index / auto-suggest; require explicit human confirmation only for destructive or outward-facing actions (per global guardrails) and for anything touching the read-only/credentials invariants.
- **Always traceable, never noisy.** The reasoning trace, freshness, and cost are *available* (one affordance away), not *shouting*. Today the Reasoning panel + 30 chat cards risk overwhelming; default to a calm summary, expand on demand.
- **Honest degradation in the UI.** When a stage fails or data is stale, the UI says so plainly with a next step — never a silent spinner or a fake-confident number (mirrors DataGate / freshness invariants).

### 3.4 Motion & accessibility

- Keep the existing `MotionConfig reducedMotion="user"` and `prefers-reduced-motion` discipline; redesign must not bypass it (`motion-designer` lens).
- Maintain a11y contract already in code: `aria-label` + `Tooltip` on icon buttons, focus-visible rings, dialog focus-trap + Escape, ≥44px touch targets. Re-verify all new surfaces with `design:accessibility-review`; target WCAG AA in **both** themes (light status colors chosen for this).

---

## 4. Role-adaptive information architecture (the new shell)

### 4.1 Surface composition per role

Instead of one 12-section sidebar, a **slim primary nav** whose items appear by role, plus a **Workspace** hub that absorbs setup:

| Nav item | Viewer | Editor | Owner | Purpose |
|---|:--:|:--:|:--:|---|
| **Ask** (home) | ✅ | ✅ | ✅ | conversational/answer cockpit |
| **Boards** | ✅ | ✅ | ✅ | dashboards + saved answers |
| **Activity** | ✅ | ✅ | ✅ | chat history, your tasks, notifications |
| **Authoring** | — | ✅ | ✅ | rules, viz/board builder, batch |
| **Workspace** | — | — | ✅ | connections, code, schedules, team, billing, knowledge, MCP, settings |
| **Insights/Analytics** | — | — | ✅ | feedback analytics, request history/traces |

**Editor = author within an existing workspace (locked decision):** the editor authors *content* (rules, boards, visualizations, batch) inside a workspace the owner has already set up. Editors do **not** see the Workspace hub — connections, SSH, schedules, team, billing, MCP, and knowledge config are owner-only. Consequently **schedules stay owner-managed**; the "Schedule this answer" CTA (§5.5) is owner-gated, while editors promote answers to **boards/rules** instead.

The **operator** is *not* in this nav. Operator signs in and (if `ADMIN_EMAILS`) sees an **`/admin`** entry → a separate console (§5.13).

### 4.2 New shell wireframe (desktop, light theme — "Ask" home, owner)

```
┌────────────────────────────────────────────────────────────────────────────┐
│  ◆ CheckMyData     Project ▾   Connection ▾                  ◷  🔔   (avatar)│  ← calm top bar
├──────────────┬─────────────────────────────────────────────────────────────┤
│  Ask      ●  │                                                               │
│  Boards      │      Good afternoon, Sergey.                                  │
│  Activity    │      Ask anything about  orders_db ·  ready ✓                 │
│              │                                                               │
│  ─ workspace │      ┌─────────────────────────────────────────────────┐     │
│  Authoring   │      │  Ask your data…                              ↵   │     │  ← single focal input
│  Workspace   │      └─────────────────────────────────────────────────┘     │
│  Insights    │       Try:  ▸ Revenue last 30d   ▸ Top customers   ▸ Churn    │  ← schema-grounded chips
│              │                                                               │
│              │      What changed                                            │
│              │      • Schema re-indexed 2h ago   • 1 scheduled report ready  │  ← freshness/activity digest
│              │      • Invite: 2 teammates pending                            │
│              │                                                               │
│              │      Recent answers                              See all →    │
│              │      ┌────────────┐ ┌────────────┐ ┌────────────┐            │
│              │      │ MRR by mo. │ │ Failed pmts│ │ Cohort ret.│            │  ← saved-answer cards
│              │      └────────────┘ └────────────┘ └────────────┘            │
└──────────────┴─────────────────────────────────────────────────────────────┘
```

Notes: setup (connections, SSH, rules, schedules) is **not** on screen — it lives under *Workspace* and is surfaced contextually when the agent needs it. The home answers "what can I do / what changed / ask something," fixing F3 + F5.

### 4.3 Viewer composition (same shell, fewer items)

```
┌──────────────┐   Ask · Boards · Activity only.  No Authoring/Workspace/Insights.
│  Ask      ●  │   Home shows: ask input + suggested questions + shared boards.
│  Boards      │   "Save" and "feedback" present; all create/config absent BY DESIGN
│  Activity    │   (composed, not "owner shell minus buttons").
└──────────────┘
```

### 4.4 Workspace hub (owner) — absorbs the old sidebar setup sections

```
Workspace
  ├ Connections   (PG/MySQL/ClickHouse/Mongo, SSH tunnel)   ← was sidebar §
  ├ Code & indexing (repo, freshness, re-index)
  ├ Schedules
  ├ Custom rules
  ├ Team & access (invites, roles, approvals)
  ├ Billing & usage (plan, quotas, upgrade)
  ├ Knowledge health (index age, sync, freshness)
  ├ MCP tokens
  └ Settings (account, theme ☀/🌙, language, notifications)
```

This is the file map for the new shell; per-surface UX detail follows in §5.

---

## 5. Scenario audits

Legend: **A/M** = Automate / Manual decision · **S** = severity gap (🔴 high / 🟡 medium / 🟢 ok). Each scenario: journey table → key findings → target experience.

### 5.1 Activation — first session (admin / workspace creator)

Funnel: landing/login → first successful answer → activated.

| # | Step | A/M | Interface needed | Current state / gap | S |
|---|---|---|---|---|---|
| 0 | Land + sign up (Google/email) | Auto: Google SSO 1-click; Manual: email+pw | Login + "what happens next" framing | `/login` exists; no value preview / expectation-setting | 🟡 |
| 1 | Create workspace/project | Manual (name); could auto-default | 1-field project create | Wizard step 0 **conflates project + connection** | 🟡 |
| 2 | Add DB connection | **Auto**: paste connection-string → parse type/host/port; auto SSH detect | Form with string-paste + auto type | `ConnectionForm` exists; **no paste→autofill** (F6) | 🔴 |
| 3 | Test connection | **Auto** (wizard auto-tests on entry) | Inline status + fix hints | Works; remediation hints thin | 🟢 |
| 4 | Index schema/DB | **Auto**, background, **non-blocking** | Progress + "keep going" | Feels like a wall (F7); should be progressive readiness | 🟡 |
| 5 | Connect code (optional) | Manual (repo URL + SSH key) | Repo connect + explicit Skip | SSH key as early barrier; skip not prominent | 🟡 |
| 6 | Ask first question | **Auto**: schema-grounded starter prompts | Chat input + suggested prompts | `SuggestionChips` exist but **not first-run-guaranteed / schema-grounded** (F6) | 🔴 |
| 7 | First answer + trace | Auto (full pipeline) | Answer card, calm trace, "was this right?" | Rich cards exist; **"aha" not celebrated**, no trace/feedback tour | 🟡 |
| 8 | Activation confirmed | Auto: set `is_onboarded` | Subtle success + next-step nudges | Flag flips silently (F8) | 🔴 |

**Key findings:** F1 (two getting-started surfaces), F6, F7, F8 concentrate here. SSH-first sidebar checklist actively misleads.
**Decisions to automate:** connection-string paste→parse (**yes**); keep auto-test; make indexing **non-blocking** with a progressive readiness gate; **add** schema-grounded first-run prompts; move SSH to "only when a tunnel is needed"; merge the two getting-started surfaces into one.
**Target experience:** a single, calm, ≤3-decision wizard ("paste connection → we test & index in the background → ask your first question"), with the home digest taking over as the persistent "what's next" surface after activation. Mockup: §8 W1.

### 5.2 Owner — connections & SSH keys

| # | Step | A/M | Interface needed | Current state / gap | S |
|---|---|---|---|---|---|
| 1 | Add connection | Auto: string parse, type detect, port prefill | Connection form (paste-first) | All-manual fields (F6) | 🟡 |
| 2 | SSH tunnel (if needed) | Auto: detect "host unreachable → suggest tunnel"; Manual: pick key | Inline tunnel setup within connection flow | SSH keys are a **separate top sidebar section** decoupled from connections | 🔴 |
| 3 | Generate/upload SSH key | Manual | Key manager (in Workspace) | `SshKeyManager` exists but surfaced first, out of context | 🟡 |
| 4 | Test & save | Auto-test | Inline status | OK | 🟢 |
| 5 | Edit / rotate / delete connection | Manual; confirm destructive | List + edit + guarded delete | Exists; delete-confirm patterns present | 🟢 |
| 6 | Connection health monitoring | Auto (poll) | Health chip on home + Workspace | `ConnectionHealth` exists (overview/sidebar) | 🟢 |

**Key findings:** SSH keys are presented as a *prerequisite step* rather than a *just-in-time* sub-flow of "add connection," inflating activation friction (ties to F1).
**Decisions:** auto-detect tunnel need and fold SSH into the connection flow; keep SSH key management available in Workspace for power users; connection-string paste as the primary path.
**Target:** "Add connection" = paste string → auto type/health → (only if unreachable) "looks like this DB is private — set up an SSH tunnel?" inline. Mockup: §8 W2.

### 5.3 Owner — code repo connect / index / freshness

| # | Step | A/M | Interface needed | Current state / gap | S |
|---|---|---|---|---|---|
| 1 | Connect repo | Manual (URL + key) | Repo connect form | Exists (wizard step 3 / project) | 🟢 |
| 2 | Index repo | Auto-start, background | Progress (`WorkflowProgress`) | Exists; good compact progress | 🟢 |
| 3 | Freshness: HEAD vs indexed | Auto (probe) | Freshness chip + "re-index" | `KnowledgeFreshnessService`, repo status in sidebar | 🟡 (buried in sidebar) |
| 4 | Re-index on drift | Auto-offer / Manual confirm | One-click re-index + auto-pull option | Exists (`Check`/`Re-index now`) | 🟢 |
| 5 | Index failure recovery | Auto (reaper flips stuck→failed) | Honest failure + retry | Reaper + sync-history exist; surfacing thin in UI | 🟡 |

**Key findings:** the mechanics are solid (checkpointed pipeline, reaper, freshness) but **buried in a collapsed sidebar section**; freshness should be a first-class home signal.
**Decisions:** keep auto-index + reaper; promote freshness to the home "What changed" digest; keep `git_agent_auto_pull` opt-in.
**Target:** "Code & indexing" card in Workspace + a freshness line in the home digest; failures shown as honest, actionable rows.

### 5.4 Owner — team, invites, roles, access approval

| # | Step | A/M | Interface needed | Current state / gap | S |
|---|---|---|---|---|---|
| 1 | Invite teammate | Manual (email + role) | Invite form | `InviteManager` (nested in Settings → Team) | 🟡 |
| 2 | Assign/change role | Manual | Member list w/ role select | Exists | 🟢 |
| 3 | Approve access request | Manual; Auto-notify | Requests inbox + 1-click approve | `PendingInvites` / `RequestAccessModal`; approval surface thin | 🟡 |
| 4 | Revoke / remove member | Manual; confirm | Guarded action | Exists | 🟢 |

**Key findings:** team management is **buried two levels deep** (Settings → Project → Team & Invites toggle); access **requests** lack a clear owner inbox.
**Decisions:** elevate to Workspace → "Team & access" as a first-class surface; requests become a notification + inbox row with inline approve/deny.
**Target:** one "Team & access" screen: members table (role inline-editable), pending invites, pending access requests — all actionable in place.

### 5.5 Owner — schedules (recurring queries/reports)

| # | Step | A/M | Interface needed | Current state / gap | S |
|---|---|---|---|---|---|
| 1 | Create schedule | Manual (query + cadence) | Schedule builder | `ScheduleManager` (sidebar, owner) | 🟡 |
| 2 | From an existing answer | **Auto-offer**: "schedule this" on any answer | CTA on answer card | Not surfaced from answers | 🔴 |
| 3 | Monitor runs / outcomes | Auto | Run history + status | Exists (runs/sync-history) | 🟢 |
| 4 | Auto-pause on failure/budget | Auto | Status + reason | Auto-pause gate exists | 🟢 |
| 5 | Edit / disable | Manual | List actions | Exists | 🟢 |

**Key findings:** scheduling is decoupled from where intent forms (the answer). The highest-value path — "I like this answer → run it weekly" — doesn't exist.
**Decisions:** add "Schedule this" to answer cards (Auto-offer); keep manual builder in Workspace.
**Target:** any answer → "Schedule" → cadence picker → lands in Workspace → Schedules.

### 5.6 Owner — billing, usage, upgrade (paywall funnel)

| # | Step | A/M | Interface needed | Current state / gap | S |
|---|---|---|---|---|---|
| 1 | See plan & quota usage | Auto | Usage meter (tokens, connections, projects) | `BillingPanel` + `UsageStatsPanel` (sidebar Operations) | 🟢 |
| 2 | Hit a limit (402) | Auto | Inline, contextual upgrade prompt | `EntitlementService` → 402; frontend prompt quality unclear | 🟡 |
| 3 | Upgrade / checkout | Manual | Stripe Checkout | `/pricing`, BillingPanel; exists | 🟢 |
| 4 | Manage subscription | Manual | Customer Portal | Exists | 🟢 |
| 5 | Credit-pack top-up | Manual | Top-up CTA | Exists (verified live) | 🟢 |

**Key findings:** billing is functionally complete but **lives in a low-traffic sidebar group**; the 402 → upgrade moment (the actual conversion point) needs a calm, contextual paywall, not a hard wall (`marketing-skills:paywall-upgrade-cro` lens).
**Decisions:** keep mechanics; redesign the **limit-hit moment** as an inline, value-framed prompt ("you've used 90% of this month's queries — keep going with Pro"); surface usage in Workspace → Billing.
**Target:** non-punitive usage meter + contextual upgrade at the moment of value. Mockup: §8 W4.

### 5.7 Owner/any — MCP tokens

| # | Step | A/M | Interface needed | Current state / gap | S |
|---|---|---|---|---|---|
| 1 | Mint per-user token | Manual | Token create + copy-once | `McpTokenManager` (in Settings) | 🟢 |
| 2 | Understand what it grants | — | Scope explanation + skill link | Explanation thin | 🟡 |
| 3 | Revoke | Manual; confirm | List + revoke | Exists | 🟢 |

**Key findings:** functional; discoverability and "what is this / how do I use it" (link to `docs/MCP_SERVER.md` / agent skill) are weak.
**Decisions:** move to Workspace → MCP, add a one-paragraph "what this enables" + copy-paste client config.
**Target:** token list + inline setup snippet + scope note.

### 5.8 Owner — knowledge freshness & health

| # | Step | A/M | Interface needed | Current state / gap | S |
|---|---|---|---|---|---|
| 1 | See index age / sync / Git drift | Auto | Single freshness signal | `KnowledgeFreshnessService` + `KnowledgeHealthPanel` | 🟡 (fragmented) |
| 2 | Act on staleness | Auto-offer / Manual | "Refresh now" | Re-index exists | 🟢 |
| 3 | Schema-change alerts | Auto (opt-in) | Notification | Flag off by default | 🟢 |

**Key findings:** freshness is computed well but **scattered** across overview + sidebar + chat-prompt injection; users have no single "is my data current?" answer.
**Decisions:** consolidate into one freshness signal shown on home digest + Workspace → Knowledge.
**Target:** one health card: "Schema ✓ 2h · Code ✓ HEAD · DB sync ✓" with drill-in.

### 5.9 Owner — analytics & request history (traces)

| # | Step | A/M | Interface needed | Current state / gap | S |
|---|---|---|---|---|---|
| 1 | See feedback analytics | Auto | Charts | `FeedbackAnalyticsPanel` (sidebar) | 🟢 |
| 2 | Inspect a request trace | Manual | Trace timeline (spans) | `LogsScreen` / RequestTrace; functional | 🟡 (developer-grade UI) |
| 3 | Diagnose a bad answer | Manual | Trace → stage → SQL → data gate | Spans exist; narrative thin | 🟡 |

**Key findings:** traces are powerful but presented developer-first; owners want "why was this answer wrong/slow," not raw spans.
**Decisions:** keep raw traces under Insights; add a human-readable "answer explainer" linking feedback → trace.
**Target:** Insights surface with feedback trends + a "review answers" queue that links to traces.

### 5.10 Editor — authoring (rules, dashboards, viz, batch)

| # | Step | A/M | Interface needed | Current state / gap | S |
|---|---|---|---|---|---|
| 1 | Author a custom rule | Manual; Auto-validate | Rule editor + schema validation | `RulesManager`; rule freshness/validation exist | 🟢 |
| 2 | Rule discrepancy → update | **Auto-propose** | "Rule looks outdated — update?" | Engine proposes on discrepancy | 🟢 |
| 3 | Build a dashboard/board | Manual | Board builder | `DashboardList` + `dashboards/` | 🟡 (build flow heavy) |
| 4 | Save an answer as viz | **Auto-offer** | "Add to board" on answer | Partial | 🟡 |
| 5 | Batch queries | Manual | `BatchRunner` | Exists (header button) | 🟢 |

**Key findings:** authoring is capable but **fragmented across modal + sidebar + header**; the natural flow "good answer → add to board / save as rule" is under-supported.
**Decisions:** unify under **Authoring**; add "Add to board" / "Save as rule" affordances on answer cards.
**Target:** answer → one-click promote to board or rule; Authoring tab as the home for builders.

### 5.11 Viewer — consume (ask, boards, feedback)

| # | Step | A/M | Interface needed | Current state / gap | S |
|---|---|---|---|---|---|
| 1 | Ask a question | Manual | Ask cockpit (read-only data) | Sees owner shell w/ create removed (F9) | 🟡 |
| 2 | View shared boards | Manual | Boards | `/dashboard/[id]` shared viewer exists | 🟢 |
| 3 | Give feedback on answer | Manual | Thumbs / "wrong data" | Feedback + `WrongDataModal` exist | 🟢 |
| 4 | Save a query | Manual | Notes | `NotesPanel` exists | 🟢 |

**Key findings:** viewers get a stripped owner UI rather than a purpose-built consume surface (F9); empty sidebar groups read as "missing," not "not for you."
**Decisions:** compose viewer shell from scratch (Ask · Boards · Activity only).
**Target:** clean consume cockpit; no dead/disabled controls.

### 5.12 Core query loop (all roles) — the central scenario

| # | Step | A/M | Interface needed | Current state / gap | S |
|---|---|---|---|---|---|
| 1 | Type / pick a question | Manual; Auto-suggest | Ask input + chips | Exists | 🟢 |
| 2 | Clarify if ambiguous | Auto (agent asks) | `ClarificationCard` | Exists | 🟢 |
| 3 | Readiness / cost preview | Auto | `ReadinessGate` + `CostEstimator` | Exist; may add friction if too loud | 🟡 |
| 4 | Agent runs (plan→SQL→viz) | Auto | Calm progress (`StageProgress`) | Exists; **30 card types risk noise** | 🟡 |
| 5 | Answer + viz | Auto | Answer + chart + SQL explainer | Rich (`SQLResultSection`, charts) | 🟢 |
| 6 | Trace / reasoning | Auto, on-demand | Collapsed-by-default trace | `ReasoningPanel` always-present drawer | 🟡 |
| 7 | Wrong-data / investigation | Auto-trigger | `InvestigationProgress`, reconciliation | Exists (auto-investigate) | 🟢 |
| 8 | Act on answer | Manual | Save / Add to board / Schedule / Export | Save exists; board/schedule promote weak (F→§5.5/5.10) | 🟡 |

**Key findings:** the loop is feature-rich to the point of **visual noise**; the calm default (answer + one-line trust signal) is missing. The "what do I do with this answer" step is under-served.
**Decisions:** default to a **calm answer** (result + "✓ verified · 2.1s · trace") with progressive expansion; consolidate the 30 cards into a smaller set of expandable blocks; add a unified answer action bar (Save · Board · Schedule · Export · Feedback).
**Target:** answer-first card with a single trust line and an action bar; trace/cards on demand. Mockup: §8 W3.

### 5.13 Self-hosted operator — `/admin` console (net-new)

Today: **no UI** (F2). Backend offers `metrics` (JSON + Prometheus), `backup` (trigger/list), `health_monitor`, stale-run reaper, worker/dyno health, MCP runtime.

| # | Step | A/M | Interface needed | Current state / gap | S |
|---|---|---|---|---|---|
| 1 | See system health | Auto | Status board (web/worker/redis/db/chroma) | Only `/api/health*`, no UI | 🔴 |
| 2 | Watch metrics/throughput | Auto | Metrics dashboard (route/complexity/retries/latency) | JSON/Prometheus only | 🔴 |
| 3 | Trigger / monitor backups | Manual; Auto-status | Backup panel | Endpoint only | 🔴 |
| 4 | Inspect stuck/stale runs | Auto (reaper) + Manual | Reaper view + force-fail | Reaper runs headless | 🟡 |
| 5 | MCP runtime status | Auto | Mount status, active principals | Logs only | 🟡 |
| 6 | Manage admins / flags | Manual | Read-mostly config view | env-only | 🟡 |

**Key findings:** an entire persona is UI-less. For self-hosted/single-tenant operators this is the difference between "observable product" and "curl the API."
**Decisions:** build a **dedicated `/admin` route** (gated by `require_admin` / `ADMIN_EMAILS`), read-mostly, that visualizes existing endpoints. No new backend needed for v1 — it's a UI over `metrics` + `backup` + `health` + `runs`.
**Target:** operator console: Health board · Metrics · Backups · Runs/Reaper · MCP runtime. Mockup: §8 W5.

---

## 6. Consolidated gap matrix (severity-sorted)

| ID | Gap | Scenario | Severity | Fix area |
|---|---|---|---|---|
| F2 | Operator has no UI | 5.13 | 🔴 | New `/admin` console |
| F1 | Two conflicting getting-started surfaces (DB-first wizard vs SSH-first checklist) | 5.1 | 🔴 | Merge into one onboarding |
| F3 | 12-section power-tool sidebar, not agent-first | 4, all | 🔴 | Role-adaptive shell |
| F4 | No light theme / toggle | 3.2 | 🔴 | Dual-theme tokens |
| F6 | Connection setup all-manual (no string paste) | 5.1, 5.2 | 🔴→🟡 | Paste→parse |
| — | SSH presented as prerequisite, not just-in-time | 5.2 | 🔴 | Fold into connection flow |
| — | "Schedule this answer" missing | 5.5 | 🔴 | Answer action bar |
| F5 | Overview is a thin health page, not a home | 5.1, 4.2 | 🟡 | Ask-home + digest |
| F7 | Indexing blocks onboarding momentum | 5.1 | 🟡 | Non-blocking readiness |
| F8 | No post-activation nudges | 5.1 | 🟡 | Next-steps digest |
| F9 | Lesser roles get "owner shell minus buttons" | 5.11, 4.3 | 🟡 | Composed role surfaces |
| — | Query loop visual noise (30 cards, always-on trace) | 5.12 | 🟡 | Calm answer default |
| — | Team/billing/freshness buried in sidebar depth | 5.4/5.6/5.8 | 🟡 | Workspace hub |
| — | Traces are developer-grade for owners | 5.9 | 🟡 | Answer explainer |
| F10 | Flat settings; no theme/lang/notif prefs home | 3.2, 4.4 | 🟢 | Settings in Workspace |
| — | MCP token "what is this" weak | 5.7 | 🟢 | Inline setup snippet |

## 7. Funnel KPIs (per journey — to instrument & target)

| Journey | Primary metric | Secondary | Today | Target signal |
|---|---|---|---|---|
| Activation (5.1) | % new users → first successful answer | time-to-first-answer; step drop-off | unmeasured in UI | ↑ activation, ↓ TTFA, ↓ wizard abandonment |
| Connection setup (5.2) | % connection attempts that succeed first try | SSH-tunnel failure rate | — | ↑ first-try success via paste/auto-detect |
| Query loop (5.12) | answers per active user / week | thumbs-up rate; wrong-data rate; replans | partial (MetricsCollector) | ↑ answers, ↑ 👍, ↓ wrong-data |
| Answer → action (5.5/5.10) | % answers saved/boarded/scheduled | — | ~0 (no affordance) | ↑ promotion rate |
| Upgrade (5.6) | 402-hit → upgrade conversion | time-on-plan-limit | — | ↑ contextual upgrade CTR |
| Team (5.4) | invites sent → accepted | access-request → approve latency | — | ↑ seats, ↓ approval latency |
| Operator (5.13) | console adoption (self-hosted) | MTTR on stuck runs | n/a (no UI) | console used instead of curl |

Instrument via existing `MetricsCollector` + frontend analytics; expose activation/funnel counters where missing.

## 8. Key-screen wireframes (collected)

**W1 — Onboarding (merged, 3 decisions)**
```
Step 1/3  Connect your data
  ┌───────────────────────────────────────────┐
  │  Paste a connection string                 │
  │  postgres://user:•••@host:5432/orders       │
  └───────────────────────────────────────────┘
   Detected:  PostgreSQL · host private?  ☐ use SSH tunnel
   [ Test & continue ]   (auto-tests, then auto-indexes in background)

Step 2/3  We're indexing in the background…  ▓▓▓▓▓░░ 70%   [ Skip, I'll ask now → ]
Step 3/3  Ask your first question
   Try:  ▸ How many orders this month?  ▸ Revenue by week  ▸ Top 10 customers
```

**W2 — Add connection (paste-first, JIT SSH)**
```
Connections ▸ Add
  [ Paste connection string ]  ──auto──▶  type ✓  host ✓  port ✓
  ⚠ Can't reach host directly → "This looks private. Set up an SSH tunnel?"  [ Yes ]
      └ pick key ▾  /  + generate key
  [ Test ]  ● connected
```

**W3 — Calm answer card (query loop)**
```
┌ Revenue grew 12% MoM ───────────────────────────────────┐
│  [ bar chart ]                                           │
│  ✓ verified · 2.1s · 1 query        ▸ how I got this     │  ← trust line; trace on demand
│  ───────────────────────────────────────────────────────│
│  Save  ·  Add to board  ·  Schedule  ·  Export  ·  👍 👎  │  ← unified action bar
└──────────────────────────────────────────────────────────┘
```

**W4 — Contextual upgrade (paywall moment)**
```
┌ You've used 90% of June's queries ──────────────┐
│ Keep your momentum — Pro lifts the cap to 10×.   │
│ [ See Pro ]   [ Maybe later ]                    │   ← calm, value-framed, non-blocking
└──────────────────────────────────────────────────┘
```

**W5 — `/admin` operator console**
```
┌ Admin · system ─────────────────────────────────────────────┐
│ Health   ● web  ● worker  ● redis  ● postgres  ● chroma      │
│ Metrics  reqs/min ▁▂▅▇  p95 1.8s  replans 4%  retries 2%     │
│ Backups  last ✓ 03:00  size 412MB        [ Run backup ]      │
│ Runs     2 running · 0 stuck · reaper ✓        [ view ]      │
│ MCP      mounted ✓ /mcp · 3 active principals                │
└──────────────────────────────────────────────────────────────┘
```

(Live, themed mockups of W1, W3, W5 are rendered inline in chat alongside this spec.)

## 9. Prioritized roadmap (phased role-adaptive rebuild)

Each phase is independently shippable behind a flag; ordered by value/risk.

- **Phase 0 — Token foundation (enabler, low risk).** Refactor `@theme` → runtime CSS vars (`:root`/`.dark`), add light palette, FOUC-safe theme script, `light|dark|system` toggle in account menu. No layout change. *Unblocks all "airy" work.* Flag: `theme_switcher_enabled`.
- **Phase 1 — Activation funnel.** Merge the two getting-started surfaces into W1; connection-string paste→parse; JIT SSH; non-blocking indexing; schema-grounded first prompts; post-activation digest. (`onboarding-cro` lens.)
- **Phase 2 — Ask-home + calm answer.** Replace thin Overview with the Ask cockpit + "What changed"/recent-answers digest; calm answer card W3 + unified action bar (Save/Board/Schedule/Export/Feedback); collapse trace by default.
- **Phase 3 — Role-adaptive shell.** Slim nav (Ask·Boards·Activity + role items); Workspace hub absorbs setup; composed viewer/editor surfaces (kill F9).
- **Phase 4 — Workspace hub depth.** Team & access, Billing (contextual upgrade W4), Connections, Code, Schedules, Rules, Knowledge, MCP, Settings as first-class surfaces.
- **Phase 5 — `/admin` operator console.** W5 over existing metrics/backup/health/runs endpoints.
- **Phase 6 — Polish.** Motion pass, accessibility re-audit in both themes, charts theme-aware, KPI instrumentation.

Each phase: TDD (Vitest + component tests), error/empty/loading states, a11y in both themes, docs updated in the same change (per project Definition of Done).

## 10. Open questions, assumptions, risks

**Resolved decisions (stakeholder, 2026-06-23)**
- D1: **Default theme = light** for *new* users (airy first impression); existing users keep their last choice / system pref.
- D2: **Editor = author within an existing workspace** — Ask/Boards/Activity + Authoring only; no Workspace-setup access (§4.1).
- D3: **Schedules stay owner-managed**; "Schedule this answer" CTA is owner-gated; editors promote answers to boards/rules.
- D4: **`/admin` = in-app route**, lazy-loaded, gated by `require_admin` (not a separate bundle).

**Remaining assumptions (confirm at planning)**
- A2: `/admin` v1 is **read-mostly** over existing endpoints; no new backend services.
- A3: The role-adaptive rebuild keeps the current REST/SSE/WS chat contract unchanged (frontend-only IA change).
- A4: Mobile (≤767px) parity required for Ask/Boards/Activity; `/admin` may be desktop-first.

**Risks**
- R1: Token refactor touches every component — mitigate with the alias pattern (§3.2) so utilities are unchanged; visual-regression pass.
- R2: Hiding setup behind Workspace could hurt power-user speed — mitigate with a command palette (⌘K) to jump anywhere.
- R3: Calming the query loop must not remove traceability (vision §7) — trace stays one affordance away, never gone.
- R4: Scope is large — phases are independently flagged and shippable to de-risk.

## 11. Human steps (isolated; autonomous path is complete without these)

1. **Stakeholder decisions:** confirm A1–A4 and Q1–Q4 above.
2. **Brand/visual sign-off:** approve the light palette (§3.2) and the "airy" density targets (§3.1) — optionally via a Figma/visual review.
3. **Analytics access:** confirm where activation/funnel KPIs (§7) should be reported (existing `MetricsCollector` vs. product analytics).
4. **Self-hosted operator validation:** a real operator validates `/admin` v1 covers their workflow.

---

### Next step
On approval of this audit + direction, proceed to **`superpowers:writing-plans`** to turn Phases 0–6 into an implementation plan (contracts-first: token system and role/IA shell locked before parallel surface work), per the project's subagent-driven workflow.
