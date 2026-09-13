# ADR-0007 — Recipes: saved, parameterised query chains callable over MCP, invalidated by the index; and the workspace shell

**Status:** accepted 2026-09-14 · **Amends:** ADR-0005 §5 (adds PRJ-15 and PRJ-16) ·
**Owner:** product owner.

Two additions to the Goal #1 plan, both requested on 2026-09-14. The first is a product
capability that the kernel of ADR-0005 makes cheap; the second is the shell the product
is used through. Both are user-facing and therefore start with scenarios
(`docs/ux/scenarios.md`) before any UI is built — the `super-ux` chain, then
`sheleg-design` for the visual layer, then `copywriting` for the strings.

---

## 1. Recipes — what the user asked for, in one paragraph

> When the agent has produced something useful, the user turns it into a **named
> template** — one query or a **chain** of queries and computations for a task — with
> parameters, so next time it runs **without the orchestrator searching again**, from the
> web UI or **over MCP**, prepared in advance and called later. Chains go stale when the
> product changes, so **every repository and database index checks which recipes the
> change touches**, tries to **repair** them, and marks the repaired ones **needs
> verification** until a person confirms.

## 2. What exists and what this builds on

| Existing | What it is | Reused as |
|---|---|---|
| `SavedNote` (`models/saved_note.py`) | one SQL + optional viz + bounded last result, per project/user, shareable | the one-step ancestor; migrated into a one-step recipe |
| `ScheduledQuery` (`models/scheduled_query.py`) | one SQL on a cron with alert conditions | "a recipe on a schedule" — later, the schedule references a recipe instead of carrying SQL |
| `Dashboard` (`cards_json`) | a layout of saved visualisations | cards reference recipe runs |
| `Artifact` + `Provenance` (ADR-0005 §3.2) | table with the SQL/compute that produced it | a recipe **is** a saved artefact chain with the literals lifted into parameters |
| `compute_sql` on DuckDB (ADR-0005 §3.3) | derived numbers as code | a recipe step kind |
| code↔DB map, `tables_declared_in_migration`, CBM `detect_changes` (ADR-0006) | which code touches which tables | the invalidation signal |
| Numbers Gate (ADR-0005 §3.4) | numeric tokens must resolve to artefacts | applies to a recipe's optional narration step |

Nothing here is a fourth store beside notes, schedules and dashboards: notes become
one-step recipes, schedules and dashboards point at recipes.

## 3. Model

```
recipes
  id, project_id, name, slug (unique per project), description
  params_json        JSON Schema of parameters  {date_from: date, country: string, …}
  steps_json         ordered list of steps (below); step ids are the artefact ids of a run
  lineage_json       {connection_id: {table: [columns]}} — extracted, not typed by hand
  status             draft | verified | needs_verification | repaired_unverified | broken
  status_reason      text: "migration 2026_09_01_orders_status touched orders.status"
  version, parent_version_id          every repair is a new version; the verified one stays runnable
  source_message_id, source_run_id    where it came from (the chat answer's RunRecord)
  created_by, verified_by, verified_at, created_at, updated_at, is_shared

steps_json[i]
  {id: "a1", kind: "sql",         connection_id, sql: "SELECT … WHERE created_at >= {{date_from}}"}
  {id: "a2", kind: "compute_sql", inputs: ["a1"], sql: "SELECT country, sum(revenue)/sum(orders) FROM a1 GROUP BY 1"}
  {id: "c1", kind: "chart",       input: "a2", spec: {...viz spec...}}
  {id: "n1", kind: "narrate",     inputs: ["a2"], instructions: "one paragraph, cite artefacts"}   # optional, the only LLM call

recipe_runs
  id, recipe_id, recipe_version, params_json, status (ok|failed|blocked), started_at, duration_ms
  artefacts_json     bounded like SavedNote.last_result_json (CHAT_RAW_RESULT_ROW_CAP), never a warehouse
  gate_verdicts_json, error, run_by, via (web|mcp|schedule|verification)
```

Parameters are bound by **type**, never by string substitution: a `date` parameter becomes
a bound query parameter on the SQL step; `{{…}}` is the template syntax, and a template
that cannot be compiled to bound parameters is refused at save time. `SafetyGuard` runs on
every step at save **and** at run, read-only.

## 4. Lifecycle

**Create.** From any chat answer: "Save as recipe" takes the answer's artefact chain from
its `RunRecord` (the SQL steps with their connection, the compute steps, the chart spec),
proposes parameters by lifting literals (dates, ids, country codes — an LLM proposal the
user confirms or edits), asks for a name, and stores version 1 as `draft`. The first
successful run by its author, or a "Verify" click on a run the user has checked, makes it
`verified`. From scratch: the same editor, empty.

**Run.** Deterministic and orchestrator-free: bind params → execute steps through the
kernel's own nodes (`GraphExecutor` with a static plan that *is* the recipe) → artefacts →
gates. A step that fails does **not** get an LLM repair at run time — a recipe that fails
is `broken` with the error, because silently rewriting a saved query is how a verified
number becomes a different number. Narration, if present, is Numbers-gated like any
answer. p95 target for a recipe without narration: **< 5 s** (no LLM in the path).

**Expose.** MCP tools, added to `app/mcp_server/tools.py`, principal-scoped like the
existing ones:

| Tool | Does |
|---|---|
| `checkmydata_list_recipes(project_id, status?)` | names, descriptions, params schema, status, last verified |
| `checkmydata_get_recipe(project_id, slug)` | the full definition incl. steps and lineage |
| `checkmydata_run_recipe(project_id, slug, params)` | runs it, returns `{artefacts[], caveats[], status, run_id}` — the same payload the web shows (ADR-0005 D6) |
| `checkmydata_save_recipe(project_id, run_id, name, params?)` | turns a previous `query_database` answer into a recipe from an MCP client |

An MCP client can therefore prepare a set of recipes once and call them by name forever
after, with typed parameters, no free text and no orchestrator turn.

**Invalidate.** Two triggers, both already scheduled work:

1. **DB index refresh** (`db_index_pipeline`): diff the new schema against the previous
   for every `(table, column)` in any recipe's `lineage_json` — dropped, renamed, type
   changed, nullable changed → those recipes → `needs_verification`, `status_reason` names
   the column.
2. **Repository index** (`pipeline_runner`, after CBM's `detect_changes`): the changed
   files → tables they declare or touch (`tables_declared_in_migration`, the code↔DB
   map's `write_count`/required filters, CBM `search_code` over the changed set) →
   intersect with recipe lineage → `needs_verification`, `status_reason` names the
   migration or model file.

Lineage is **extracted, not typed**: `sqlglot` (new dependency, MIT) parses each SQL step
in the connection's dialect into `(table, column)` references; compute steps inherit
lineage through their inputs; an unparseable step marks the recipe `needs_verification` on
*every* index rather than pretending to know.

**Repair.** A worker job (`run_recipe_repair`, per project, after the index that
invalidated) does, per affected recipe: dry-run each step (`EXPLAIN` / `LIMIT 0` through
`SafetyGuard`) → if it still runs and the column set is unchanged, the recipe returns to
`verified` **only if it was auto-invalidated by a change that did not touch its columns**
(a migration that added an index); otherwise an LLM proposes a fix given the schema diff,
the migration text and the old SQL → saved as a **new version** with
`repaired_unverified`; the last `verified` version stays runnable and is what MCP runs by
default. **Nothing auto-verifies a repair.** A person runs it, compares (the UI shows
old-vs-new artefact diff, row counts, column sets), and clicks Verify — `vision.md` §7 #6:
user feedback is the highest authority.

**Surface.** Recipe library in the workspace (§6): status badges, reason, "Run", "Verify",
version diff; the chat's "Save as recipe" action on any answer; a `needs_verification`
count on the attention rail. `ScheduledQuery` gains `recipe_id` and stops carrying SQL of
its own in a later change.

## 5. Decisions

1. **A recipe never self-heals silently** — repairs are versions awaiting a human.
2. **Lineage is parsed, and parse failure means "assume affected"** — over-invalidation
   is a notification; under-invalidation is a wrong number.
3. **Runs are orchestrator-free** — that is the whole point; the LLM appears only in the
   optional narration and in the offline repair proposal.
4. **Results are bounded artefacts**, exactly as ADR-0005 decision 3: no result store
   grows into a warehouse (`vision.md` §8).
5. **MCP and web share one payload** — D6 of ADR-0005 extends to recipes.

## 6. PRJ-15 — the workspace shell (UI/UX)

**Reference.** The NotFair workspace: a persistent left rail — workspace switcher with plan
badge, primary navigation (their *Connect MCP*, *Link Accounts*, *Protection*, *Manage
workspace*, *Campaigns*, *Operations*, *Chat*), a referral card and the product's MCP entry
at the bottom — and an **integrations page of cards**, one per source, each with icon,
name, one-line description, an arrow, and a dashed "Request a platform" card at the end.
Dark theme, calm, one accent.

**Mapped onto CheckMyData** (names are placeholders for `copywriting`; the structure is
the decision):

| Rail item | Page | Exists today as |
|---|---|---|
| **Chat** | the grounded chat, artefacts rendered as tables/charts with caveats and "Save as recipe" | `ChatPanel` and 30 chat components |
| **Recipes** | library (§4 Surface) | new |
| **Sources** | the cards page: *Connect a database* (Postgres, MySQL, ClickHouse, MongoDB), *Connect a repository*, *Google Analytics 4*, and dashed *App Store Connect* / *Google Play* / *Request a source* cards that say "not yet" instead of storing a key nothing can use (audit A-08) | `ConnectionSelector`, `VendorCredentialsPanel`, repos |
| **Knowledge** | index status, freshness, sync history, code↔DB map, re-index | `ConnectionHealth`, `/sync-history`, attention rail |
| **Protection** | read-only mode, safety guard verdicts, audit log, SSH keys, credentials | scattered across Settings |
| **Connect MCP** | per-user MCP token, ready-to-paste configs for Claude Code / Cursor / Claude Desktop, tool list incl. recipes | `/api/auth/mcp-tokens`, `docs/MCP_SERVER.md` |
| **Manage workspace** | members and roles, plan and usage, billing | `BillingPanel`, members |

**Route.** Scenario-first: `docs/ux/scenarios.md` gains the shell's navigation scenarios and
the recipe scenarios (create from answer, run with params, verify a repair, run over MCP),
`docs/ux/flows.md` and `screens.md` extend beyond the data-onboarding scope for these
screens; `sheleg-design` decides tokens and rhythm (the dark, single-accent style pack);
`copywriting` writes every rail label and card sentence from the brand pack. Accessibility
rules of `DESIGN_SYSTEM.md` apply unchanged (44 px targets, `aria-*`, focus traps).

**What PRJ-15 does not do.** It does not redesign the chat's reasoning panel, does not add
marketing pages, and does not change any backend contract — it consumes the artefact
payload wave 2 defines.

## 7. Plan amendment (ADR-0005 §5)

| Project | Size | Depends on | Track |
|---|---|---|---|
| **PRJ-16 Recipes** — model, save-from-answer, run, MCP tools, lineage extraction, invalidation on both indexes, repair job, verify flow | **L** (10–12 days) | wave 2 (`Artifact`, `compute_sql`, `GraphExecutor` static plan) and ADR-0006 wave 0.5 (CBM `detect_changes`) | chat track, after wave 2; can start its model + lineage + invalidation half during wave 2 |
| **PRJ-15 Workspace shell** — scenarios, flows/screens, design tokens, rail + Sources cards + Connect MCP page + Knowledge page, Recipes library UI (with PRJ-16) | **L** (10–12 days incl. scenarios) | wave 2's artefact payload for the chat rendering; nothing else | **third track**, starts after wave 1, in parallel with wave 2 |

Neither moves D1–D7. Recipes strengthen D2 and D6 (a recipe run is the most grounded
answer the product can give: no free text on the way in, artefacts on the way out).
Total to Goal #1 stays ~36 days on the chat track; the shell adds a parallel track of ~12
days; recipes land right after wave 2.

## 8. Not decided here

Recipe sharing across projects (vision §7 #4 says learnings are per connection; a recipe
carries a connection, so cross-project sharing would need a written carve-out); recipe
marketplace/templates shipped with the product; migrating `ScheduledQuery` fully onto
recipes (a follow-up once PRJ-16 is verified in production).
