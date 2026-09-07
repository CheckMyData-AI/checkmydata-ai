# UX Screens

<!-- Managed with super-ux (ux-contract v4). The design map: every screen and state with its Figma frame, wireframe, code coverage, and resources. Update in the same change as any interface change; when Figma is enabled, update the frame too. -->

The UI map for the **data-onboarding** scope of [flows.md](flows.md). Screens here
are referenced by the flows and covered by `SCN-129`–`SCN-145`.

**There are no Figma frames and none are expected.** `foundation.md` → *Design
tooling* records that decision for the whole project: the scenario is the design
deliverable, the visual layer is fixed by `DESIGN_SYSTEM.md`, and where a layout
needs showing it is an ASCII sketch in the repository. So the `Figma` column reads
`n/a (text-only)` throughout, and that is a recorded decision rather than a gap.

## Index

| ID | Screen | Used by | Figma | Status | Coverage |
|----|--------|---------|-------|--------|----------|
| SCR-01 | Data workspace | FLW-01, FLW-02, FLW-03, FLW-04 | n/a (text-only) | drifted | frontend/src/components/connections/ConnectionsPanel.tsx |
| SCR-02 | Source-kind chooser | FLW-02 | n/a (text-only) | designed | none yet |
| SCR-03 | Source form | FLW-02 | n/a (text-only) | drifted | frontend/src/components/connections/ConnectionSelector.tsx |
| SCR-04 | Repository form | FLW-03 | n/a (text-only) | designed | none yet |
| SCR-05 | Describe panel | FLW-02, FLW-03, FLW-05 | n/a (text-only) | designed | none yet |
| SCR-06 | Refresh estimate | FLW-04 | n/a (text-only) | designed | none yet |
| SCR-07 | Document viewer | FLW-04 | n/a (text-only) | drifted | frontend/src/components/knowledge/KnowledgeDocs.tsx |
| SCR-08 | Answer seal | FLW-01, FLW-05 | n/a (text-only) | drifted | frontend/src/components/ui/Seal.tsx |
| SCR-09 | Project form | FLW-01 | n/a (text-only) | built | frontend/src/components/projects/ProjectSelector.tsx |
| SCR-10 | Sidebar rail | FLW-01, FLW-02, FLW-03, FLW-04, FLW-05 | n/a (text-only) | drifted | frontend/src/components/Sidebar.tsx |

`drifted` on six of ten is the finding, not an accident of bookkeeping: each of
those screens exists in code and does something narrower than the flow needs. The
two that were `blocked` became `designed` when D1 and D3 were decided on
2026-09-07, and `SCR-10` joined the map when D4 was — the rail was always there and
had never been specified, which is how it reached thirteen sections.

## Design system

- **Style pack:** custom — `DESIGN_SYSTEM.md`, extended rather than replaced. No new visual language is introduced by this scope.
- **Figma library:** none (see above)
- **Tokens in code:** `frontend/src/app/globals.css` (`@theme` semantic tokens — `bg-surface-*`, `text-text-*`; raw Tailwind palette classes are banned)
- **Component source:** `frontend/src/components/`
- **Assets:** icons are the `PATHS` record in `frontend/src/components/ui/Icon.tsx` only — no icon packages
- **Type:** DM Sans (`font-sans`) for UI, JetBrains Mono (`font-mono`) for code, SQL and data
- **Breakpoint:** one, `max-width: 767px`; touch targets ≥44 px (`.compact-touch` for 36 px in dense areas)
- **Motion:** degrades under `prefers-reduced-motion` through the app-wide `MotionConfig` — not bypassed per screen

## Web surfaces

- **Web surfaces:** no. Every screen in this scope sits behind authentication in `/app`, so none is indexable and none needs an SEO/AEO treatment.

## Screens

### SCR-01: Data workspace

- **Used by:** FLW-01 (steps 2–6), FLW-02 (step 1), FLW-03 (step 1), FLW-04 (step 1)
- **Purpose:** answers one question — *what is connected to this project, and what does it still need?* (IS-01). It is the work, not a summary of it (IS-03).
- **Elements:** "Data" top-bar entry; three group headers with counts — Databases & sources, Repositories, Documentation; per-group **Add** (the ONE primary action per group); one card per item carrying type icon, name, capability chip, read-only chip, freshness printed on its own action, counts, and the first line of its description or the `No purpose set` placeholder; per-card in-place expander; per-card Edit / Test / Index / Describe / Delete; the project's nightly sync hour with an editable control; a one-line credential-handling note beside the sources group.
- **States:**

  | State | Trigger | Figma frame | Behavior |
  |-------|---------|-------------|----------|
  | empty | project has no sources, no repository, no docs | n/a | three empty groups, each one sentence on what it unlocks, one primary action; the ordering is stated — a source first, because the nightly wave skips a project with no active connection |
  | loading | lists in flight | n/a | group skeletons at the card's own height, so nothing moves when data arrives (IS-07) |
  | error | one group's list failed | n/a | that group shows an inline error with Retry; the other two still render — one failure does not blank the screen |
  | success | at least one item | n/a | grouped cards, each with capability and freshness |
  | withheld | the account may not run scheduled work | n/a | the sync-hour control renders disabled with its reason, and repository cards read `last indexed manually` rather than implying a nightly refresh (SCN-147) |

- **Layout:** the sketch in `SCN-129`. Full content width, not the `max-w-xl` the current panel uses.
- **Wireframe:** the ASCII sketch inside `SCN-129` (per the text-only decision)
- **Coverage:** frontend/src/components/connections/ConnectionsPanel.tsx (the narrow wrapper this supersedes); frontend/src/app/app/page.tsx (the `connections` centre panel it mounts into)
- **Scenarios:** SCN-129, SCN-131, SCN-132, SCN-133
- **Resources:** `frontend/src/components/knowledge/KnowledgeHealthPanel.tsx` (the run/retry/cancel card to reuse rather than reinvent), `frontend/src/components/ui/ListError.tsx`, `backend/app/services/connection_service.py` (`is_queryable_database` — the predicate the capability chip must read), `backend/app/api/routes/projects.py` (the `sync-schedule` route that has no interface today)
- **Status:** drifted — the screen exists at `max-w-xl` and re-renders the sidebar's compact list, so it is a second view of the sidebar rather than a management surface. Roles: a viewer sees cards without Edit / Index / Delete, and their absence is explained rather than shown dead (IS-17).

### SCR-02: Source-kind chooser

- **Used by:** FLW-02 (step 1)
- **Purpose:** turn "add a source" into the one decision that changes every field after it, before any field is shown.
- **Elements:** three grouped options — Database (postgres / mysql / clickhouse / mongodb), MCP server, Analytics source (GA4; App Store and Google Play named as not yet available rather than hidden); Cancel. The grouping is the shipped Basedash shape; a flat list of eight was the alternative and hides that these three kinds behave differently downstream.
- **States:**

  | State | Trigger | Figma frame | Behavior |
  |-------|---------|-------------|----------|
  | success | opened | n/a | three groups, keyboard-navigable, no default selection |
  | error | none possible | n/a | nothing is fetched here; it renders from static config |

- **Coverage:** none yet
- **Scenarios:** SCN-130
- **Resources:** `backend/app/analytics/source_types.py` (the vendor family, defined once — the chooser must read it, not restate it)
- **Status:** designed

### SCR-03: Source form

- **Used by:** FLW-02 (steps 2–3)
- **Purpose:** prove the source connects before it is saved.
- **Elements:** name; type select with default port; host / port / database / user / password, or the connection-string alternative; SSH tunnel fields (host, user, key select); read-only toggle; send-sample-data toggle; **Test connection** (the primary action until it passes, then Create); Create / Cancel; inline result panel beside the fields.
- **States:**

  | State | Trigger | Figma frame | Behavior |
  |-------|---------|-------------|----------|
  | loading | test or create in flight | n/a | the button carries the progress; fields stay readable and disabled |
  | error | test failed, validation failed, create failed, quota reached | n/a | inline, on the field that caused it where there is one; every value preserved |
  | success | created | n/a | form collapses, the new card appears with `Index now` offered |

- **Coverage:** frontend/src/components/connections/ConnectionSelector.tsx
- **Scenarios:** SCN-130, SCN-025, SCN-026, SCN-027, SCN-028, SCN-029, SCN-030, SCN-113
- **Resources:** `backend/app/api/routes/connections.py` (the `ConnectionCreate` contract — `db_type` is `postgres`, not `postgresql`)
- **Status:** drifted — the form logic is shipped and correct, but it lives in a modal opened from the sidebar and an empty name returns silently, so the primary action reads as dead. What changes here is the host and the error surfacing, not the fields.

### SCR-04: Repository form

- **Used by:** FLW-03 (steps 1–2)
- **Purpose:** attach a repository as its own object, with its own key, branch and status.
- **Elements:** name; repository URL; branch (default `main`); SSH-key select with a link out to key creation; live access-probe result panel; Create (disabled until a probe passes) / Cancel.
- **States:**

  | State | Trigger | Figma frame | Behavior |
  |-------|---------|-------------|----------|
  | loading | probe in flight | n/a | debounced after typing stops; the panel says it is probing rather than going blank |
  | error | five distinguished causes | n/a | host unreachable / host key not trusted / key rejected / repository not found / branch missing — each its own message; not-found does not confirm the id exists |
  | success | reachable | n/a | resolved head shown, Create enabled |
  | empty | no SSH key on the account | n/a | the key select explains what it needs and links to creation, returning with the new key selected |

- **Coverage:** none yet
- **Scenarios:** SCN-137, SCN-138, SCN-140, SCN-142, SCN-143
- **Resources:** `backend/app/api/routes/repos.py` (`check-access`, and the repositories CRUD that exists but nothing indexes), `backend/app/services/repository_service.py`, `backend/app/models/repository.py`
- **Status:** designed — **D1 resolved 2026-09-07: several repositories per project.** So this screen lists many, each with its own key, branch and run state, and the index queue of FLW-03 is part of the spec rather than a contingency. It is not buildable against today's backend on its own: `project_repositories` has CRUD and no consumer, so the form must land together with the repository dimension in the indexing pipeline, the code graph, the BM25 snapshot, the docs and GitAgent.

### SCR-05: Describe panel

- **Used by:** FLW-02 (step 4), FLW-03 (step 3), FLW-05 (step 3)
- **Purpose:** let a human tell the agent what a source or repository is, so it stops inferring.
- **Elements:** for a source — a multi-line field, a character counter against the cap, and one line stating that the text is sent to the agent with every question on this connection; for a repository — role, owned-source select, and an ignore-path list with add/remove; Save / Cancel; read-only rendering for a viewer.
- **States:**

  | State | Trigger | Figma frame | Behavior |
  |-------|---------|-------------|----------|
  | empty | nothing described yet | n/a | `No purpose set — the agent will infer one`, with the field ready |
  | loading | saving | n/a | Save carries the progress |
  | error | over the cap, invalid ignore pattern, save failed | n/a | counter warns and Save is refused with the overage; an invalid pattern is named and the rest still save; a failed save keeps the text so nothing is retyped |
  | success | saved | n/a | the card's subtitle becomes the first line of the text |

- **Coverage:** none yet
- **Scenarios:** SCN-134, SCN-136, SCN-139
- **Resources:** `backend/app/knowledge/custom_rules.py` (`rules_to_context` — the budget discipline this must inherit: whole entries dropped, never half of one), `backend/app/models/connection.py` and `backend/app/models/repository.py` (neither has a description column today)
- **Status:** designed — **D3 resolved 2026-09-07: one free-text field.** A source is described by a single capped textarea; nothing about it is validated, which is the accepted cost of shipping it. The decision covers the *description* only, and the repository's ignore list stays a structured list on purpose: the extractor consumes those as file patterns, so a sentence cannot drive them. The security property was never part of the decision and holds regardless — this is user-authored text reaching a prompt, so it is injected as data under its own heading, never as instructions the agent must obey.

### SCR-06: Refresh estimate

- **Used by:** FLW-04 (steps 1–2)
- **Purpose:** make the cost of regenerating documentation visible before it is spent.
- **Elements:** which repository; how many documents are due; the sentence that this calls an LLM; a duration estimate from the last measured rate; Confirm / Cancel; an "open the running one" alternative when a run is already active.
- **States:**

  | State | Trigger | Figma frame | Behavior |
  |-------|---------|-------------|----------|
  | success | opened | n/a | scope, cost and duration stated; Confirm is the primary action |
  | empty | nothing is due | n/a | says so and offers a forced full refresh separately, so "nothing to do" is not mistaken for a broken button |
  | error | the estimate cannot be computed | n/a | the run is still offerable, with the estimate replaced by "duration unknown" rather than a guess |

- **Coverage:** none yet
- **Scenarios:** SCN-144
- **Resources:** `backend/app/knowledge/pipeline_runner.py` (the `generate_docs` step; measured ~4.8 documents/minute, ~9 375 s for 758 documents), `frontend/src/components/knowledge/RunCard.tsx`
- **Status:** designed

### SCR-07: Document viewer

- **Used by:** FLW-04 (step 4)
- **Purpose:** answer *can I trust this document* — where it came from, and how old it is (IS-02, IS-16).
- **Elements:** document body; source-path line; commit chip; generated-at timestamp; freshness label — `current` / `behind by N commits` / `provenance unknown` / `cannot compare`; "Refresh this repository" link; repository name when more than one is connected.
- **States:**

  | State | Trigger | Figma frame | Behavior |
  |-------|---------|-------------|----------|
  | loading | fetching the body | n/a | skeleton at the body's height |
  | empty | no documents generated | n/a | `No indexed documents yet` with the route to generating them — distinct from "nothing matches a filter" (IS-06) |
  | error | body failed to load | n/a | inline error with Retry, the metadata still shown |
  | success | loaded | n/a | body plus provenance; a stale label is never rendered as `current` |

- **Coverage:** frontend/src/components/knowledge/KnowledgeDocs.tsx
- **Scenarios:** SCN-145, SCN-061
- **Resources:** `backend/app/api/routes/repos.py` (the docs list already returns `commit_sha` and `updated_at` — the data for the label exists and is not displayed)
- **Status:** drifted — the viewer ships and the provenance fields are already on the wire; nothing renders them, so a document two months behind head reads exactly like a current one.

### SCR-08: Answer seal

- **Used by:** FLW-01 (step 6), FLW-05 (steps 1–2)
- **Purpose:** show what the agent was told, so a wrong instruction can be found and corrected rather than argued with.
- **Elements:** the existing seal; a context list naming the connection description, repository context, rules and learnings that were injected; per-entry expander showing the verbatim text; "Edit this" link into `SCR-05`; the omitted-context notice with its count and names; the repositories searched, including those that returned nothing.
- **States:**

  | State | Trigger | Figma frame | Behavior |
  |-------|---------|-------------|----------|
  | empty | nothing beyond the schema was injected | n/a | says so explicitly — the section is not omitted, because an absent section reads as "not shown" rather than "nothing was added" |
  | success | context was injected | n/a | every entry listed and expandable to verbatim text |

- **Coverage:** frontend/src/components/ui/Seal.tsx
- **Scenarios:** SCN-135, SCN-136, SCN-141, SCN-122
- **Resources:** `backend/app/agents/orchestrator.py` (what is recorded per request — an entry cannot be shown that was never persisted)
- **Status:** drifted — the seal ships and states how an answer is known at the level of sources and freshness; it does not yet list the free-text instructions that shaped it, which is the half this scope needs.

### SCR-09: Project form

- **Used by:** FLW-01 (step 1)
- **Purpose:** create the project. Name only is required; everything else is changeable later.
- **Elements:** name; repository URL and branch (moving out to `SCR-04` when D1 is decided); SSH-key select; per-project LLM model selectors; Create / Cancel.
- **States:**

  | State | Trigger | Figma frame | Behavior |
  |-------|---------|-------------|----------|
  | loading | creating | n/a | Create carries the progress |
  | error | empty name, duplicate name (409), quota (402), unowned SSH key (404) | n/a | inline on the field for the first two; the quota refusal names the plan's project count and the upgrade route |
  | success | created | n/a | the project becomes active and lands on its empty `SCR-01` |

- **Coverage:** frontend/src/components/projects/ProjectSelector.tsx
- **Scenarios:** SCN-016, SCN-018, SCN-100
- **Resources:** `backend/app/api/routes/projects.py`, `backend/app/services/plan_catalogue.py` (`base` allows one project — the number the tooltip must state before the click)
- **Status:** built — unchanged by this scope except that its repository fields move to `SCR-04` once D1 is decided, and that the plan's project allowance is stated before the button is pressed rather than after.

### SCR-10: Sidebar rail

- **Used by:** every flow — it is present on all authenticated screens
- **Purpose:** answers exactly two questions and no others (IS-01): *where am I* and *what needs me*. It is not a control panel; management is `SCR-01`.
- **Elements:** project switcher, fixed at the top and never collapsible; `Needs you` group, **absent** when empty, with a count and at most five entries plus `N more →`; five flat navigation entries — Chat, Data, Knowledge, Dashboards, Activity — with no collapse and no nesting; `Recent` chat list with `all chats →`; account entry at the foot. No create, edit or delete control anywhere in the rail.
- **States:**

  | State | Trigger | Figma frame | Behavior |
  |-------|---------|-------------|----------|
  | success | signed in, project active | n/a | switcher, attention group if non-empty, five entries, recent list; selection marked |
  | empty | nothing needs attention | n/a | the `Needs you` group is **absent** — not an empty box, because a permanent "all good" panel trains people to stop reading the rail (IS-05, IS-06) |
  | loading | lists in flight | n/a | navigation renders immediately from static config; only the recent list and the attention group show placeholders, so the rail is navigable before any request returns |
  | error | a query failed | n/a | per-block inline retry; "could not check" in the attention group is rendered distinctly from "nothing needs you", and navigation never degrades |

- **Layout:**

```
  +--------------------------+
  | [v] nicegram             |   switcher - fixed, not collapsible
  +--------------------------+
  | NEEDS YOU            (2) |   absent entirely when empty
  |  !  api index failed 3h  |
  |  !  hub never indexed    |
  +--------------------------+
  |  Chat                    |   five flat entries, no collapse
  |  Data                    |
  |  Knowledge               |
  |  Dashboards              |
  |  Activity                |
  +--------------------------+
  | RECENT                   |   the only list in the rail
  |  revenue by country      |
  |  failed payments         |
  |  all chats ->            |
  +--------------------------+
  | [a] account & settings   |
  +--------------------------+
```

- **Wireframe:** the sketch above, per the text-only decision
- **Coverage:** frontend/src/components/Sidebar.tsx
- **Scenarios:** SCN-149, SCN-150, SCN-133
- **Resources:** `frontend/src/components/ui/SidebarSection.tsx` (the collapsible primitive the rail should almost stop using), `backend/app/services/knowledge_freshness_service.py`, `backend/app/api/routes/logs.py`, `backend/app/api/routes/projects.py` (`sync-history`) — the three sources the attention group reads, all of which already exist
- **Status:** drifted — **D4 resolved 2026-09-07.** The rail today is 976 lines and thirteen `SidebarSection` blocks: SSH Keys, Vendor Credentials, Projects, Repository, Connections, Chat History, Knowledge, Custom Rules, Schedules, Dashboards, Usage, Analytics and Request History, stacked in one column at equal weight. Account configuration, project management, work and reports in one list is why it answers neither question above. `SCN-149` records what leaves and where each part goes.

## Readiness check

| Screen | One question (IS-01) | Four states one design (IS-05) | Common action without opening a row (IS-09) | Destructive names the consequence (IS-14) | Long op survives navigation (IS-15) | Role absence explained (IS-17) |
|---|---|---|---|---|---|---|
| SCR-01 | yes | yes | yes — Index and Describe are on the card | delegated to SCN-142 | yes | yes |
| SCR-02 | yes | n/a — nothing is fetched | n/a | n/a | n/a | n/a |
| SCR-03 | yes | yes | n/a | n/a | n/a | inherited from SCR-01 |
| SCR-04 | yes | yes | n/a | yes (SCN-142 names removed and kept artefacts) | yes | inherited from SCR-01 |
| SCR-05 | yes | yes | n/a | n/a | n/a | yes — read-only for a viewer |
| SCR-06 | yes | yes | n/a | n/a | yes | inherited from SCR-01 |
| SCR-07 | yes | yes | n/a | n/a | n/a | n/a — read-only for everyone |
| SCR-08 | yes | yes (empty is a stated sentence) | n/a | n/a | n/a | n/a |
| SCR-09 | yes | yes | n/a | delegated to SCN-019 | n/a | yes — the two create refusals differ |
| SCR-10 | yes — two, and they are the same question twice over | yes (empty is an absence, by design) | yes — an attention entry routes straight to its remedy | n/a — the rail takes no destructive action | n/a | yes — entries a role cannot use are absent and explained |
