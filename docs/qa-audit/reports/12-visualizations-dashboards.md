# Module 12 — Visualizations & Dashboards — Audit Report

**Round 1** · 2026-06-24 · Scope: `routes/dashboards.py`, `routes/visualizations.py`,
`agents/viz_agent.py`, `services/dashboard_service.py`, `models/dashboard.py`.

Documented contract: dashboards are a workspace feature; `/dashboard/[id]` is a "shared viewer"
frontend route; charts via chart.js; compound queries can yield multiple charts. `vision.md §7`:
freshness tracked.

**Positive notes (verified):**
- **No public/unauthenticated dashboard endpoint exists** — every dashboards route requires
  `get_current_user` + `require_role` (`dashboards.py:57/85/97/117/143`); visualizations
  `/render` + `/export` require auth too (`visualizations.py:33/48`). The "shared viewer" is
  shared *within the project* (membership-gated), not public — no anonymous data leak.
- Correct visibility logic: `require_role(viewer)` then `if creator_id != user and not
  is_shared: 403` (`:102-103`) — non-shared dashboards are creator-only.
- `update` uses a field whitelist (`ALLOWED_UPDATE_FIELDS = title/layout_json/cards_json/
  is_shared`) — no `project_id`/`creator_id` mutation; create requires **editor**.
- Visualization inputs are row-capped (`rows` `max_length` 10k/50k).

Severity: 🔴 Critical · 🟠 High · 🟡 Medium · 🟢 Low · ⚪ Info

---

## F-VIZ-01 — 🟡 Medium — Dashboard cards are client-supplied data **snapshots** served verbatim with no freshness signal

**Type:** Bug (freshness / data accuracy, §7)
**Location:** `models/dashboard.py:31-32` (`layout_json`/`cards_json` Text); `dashboards.py:24-25`
(`cards_json: str` up to **500,000** chars accepted from the client); `dashboard_service.get` just
returns the row (no re-query).

**Description.** A dashboard stores `cards_json` (and `layout_json`) verbatim from the client; the
GET path returns it unchanged with **no re-execution** of the underlying queries. So a dashboard is
a **point-in-time snapshot** of whatever data the creator embedded. Shared viewers can see
arbitrarily **stale** numbers with no freshness indicator or "as of" timestamp on the data —
contradicting the §7 "freshness tracked" invariant. (It also means whatever data the creator
captured is shown to all viewer+ members regardless of whether they could reproduce the query;
acceptable within a project's viewer role, but worth being deliberate about.)

**Proposed fix.** Either (a) store the *query/spec* per card and re-run on view with the viewer's
access (live + correctly scoped), or (b) stamp each card snapshot with an "as of" timestamp and
surface a staleness warning (reusing `KnowledgeFreshnessService`-style signalling) in the viewer.

---

## F-VIZ-02 — 🟡 Medium — `cards_json`/`layout_json` stored verbatim from the client → stored-XSS vector (pending frontend render check)

**Type:** Security (stored XSS — cross-layer)
**Location:** `dashboards.py:24-25` (accepts up to 500KB client JSON), persisted unparsed; rendered
by the frontend dashboard viewer.

**Description.** The backend stores `cards_json`/`layout_json` exactly as the client sends them and
never parses or sanitises them. Whatever the frontend renders from these blobs (card titles,
labels, descriptions, and DB-derived values) is attacker-influenceable — both by a malicious
editor and by DB data flowing into chart labels. If the frontend renders any of it as HTML (rather
than text/canvas), this is **stored XSS** that fires for every viewer of a shared dashboard.

**Impact.** Potential stored XSS in the shared-dashboard viewer; severity confirmed by the
frontend rendering path (Module 19).

**Proposed fix.** Validate `cards_json` server-side against a strict schema (known card types,
typed fields) and reject unexpected structures; on the frontend, render all card text as text
(never `innerHTML`/`dangerouslySetInnerHTML`). Track the frontend check as part of Module 19.

---

## F-VIZ-03 — 🟢 Low — No structural/JSON validation or per-card bound on `cards_json`

**Type:** Robustness / hygiene
**Location:** `dashboards.py:24-25`, `dashboard_service.create/update`.

**Description.** `cards_json` is accepted as an opaque ≤500KB string with no check that it's valid
JSON or that per-card data is bounded. Malformed JSON is stored and only fails at render time;
500KB × many dashboards drives storage growth and large response payloads.

**Proposed fix.** Parse + validate JSON shape on write (reject invalid/oversized), bound the number
of cards and per-card data rows.

---

## Test gaps (⚪ Info)

- No test that a shared dashboard surfaces a freshness/"as of" signal (F-VIZ-01).
- No test that malicious `cards_json` (script in a card title) is sanitised/escaped end-to-end
  (F-VIZ-02).
- No test that invalid `cards_json` is rejected at write time (F-VIZ-03).

## Summary

| id | sev | one-line |
|----|-----|----------|
| F-VIZ-01 | 🟡 | Dashboard cards are stale data snapshots, no freshness signal (§7) |
| F-VIZ-02 | 🟡 | `cards_json` stored verbatim from client → stored-XSS vector (confirm in Module 19) |
| F-VIZ-03 | 🟢 | No JSON/structure/size validation of `cards_json` |

**Next-round focus:** `viz_agent` chart-type selection correctness and whether it embeds full
result data vs aggregates; multi-chart compound-answer assembly; export endpoint format handling
(CSV/Excel injection — formula injection via `=`/`+`/`-`/`@` leading cells in exported data);
`/dashboard/[id]` frontend data-fetch path (Module 19 cross-check for the XSS render).
