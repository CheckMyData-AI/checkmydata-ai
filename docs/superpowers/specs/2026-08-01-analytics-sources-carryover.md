# Carry-over ledger — analytics data sources (GA4 · ASC · Play)

> Append-only. Written by every stage the moment something is deferred, dropped or
> left half-done. Read **in full** at stage 10. Deferred out loud is forgotten.

| # | Stage | Item | Why | Where it goes | Status |
|---|---|---|---|---|---|
| C1 | 0 | OAuth sign-in for Google sources (GA4, Play) | D4 chose paste + reusable credential table; OAuth needs a client registration, callback routes, refresh-token rotation and Google verification review | `BACKLOG.md` | deferred |
| C2 | 0 | GA4 realtime reports; extra Apple analytics report types | D7 scoped to blueprint parity; realtime also fights the cache-with-provenance model | `BACKLOG.md` | deferred |
| C3 | 0 | SQL access over the analytics cache (SQLAgent parity) | D2 chose a dedicated sub-agent instead | `BACKLOG.md` | deferred |
| C4 | 0 | Query-repair loop, query-failure learning, sql_reconciliation for analytics | D3 — statement-shaped, no meaning for a tool-loop agent | `BACKLOG.md` | deferred |
| C5 | 0 | ~~Production deploy + stage-8 post-deploy verification~~ | ~~D10 stops each module at an open PR~~ | — | **resolved 2026-08-01** — operator revised D10 to a standing go per module ("1, автономно до конца"); deploy + stage 8 are now in-scope and run per module |
| C6 | 0 | **Standing cost (R1): every future quality gate must be wired twice** — once for SQL, once for analytics | Consequence of D2 | `BACKLOG.md` — revisit if a third non-SQL source appears | recorded |
| C7 | 0 | Reconcile `query_mcp_source` tool description, which names "Google Analytics" as its use case | Now misleading: GA4 is a first-class source, not an MCP one | REQ-027 (docs) — update the tool description in M0 | open |
| C8 | 1 | ASC report types newly available since the blueprint: `INSTALLS`, `FIRST_ANNUAL`, `WIN_BACK_ELIGIBILITY`, `SUBSCRIPTION_OFFER_CODE_REDEMPTION`; sub-types `SUMMARY_INSTALL_TYPE`, `SUMMARY_TERRITORY`, `SUMMARY_CHANNEL` | D7 froze scope at blueprint parity | `BACKLOG.md` | deferred |
| C9 | 1 | Apple's newer **Analytics Reports API** (`/v1/analyticsReportRequests`) — request/poll/download, categories App Usage + Commerce | D7 blueprint parity; a distinct flow from `salesReports` | `BACKLOG.md` | deferred |
| C10 | 1 | A3 (frankfurter keyless/available) **validated by live probe**, not assumed | — | — | **closed** |
| C11 | 3 | **Stale premise in the stage-0 brief**: `docs/ux/lint.py` was named as a lint command and a deploy gate, but it does not exist. This project has `docs/ux/scenarios.md` (format v1, Init sweep 2026-07-19) and no foundation/flows/screens/linter | The brief assumed a full super-ux chain; the project only ever adopted the scenarios layer | **Corrected in place**: REQ-013 and the stage-7 lint row now name `tests/unit/docs/test_ux_scenarios.py`, a real check written in m0 that asserts index↔body parity and resolvable `Coverage:` paths | **resolved** |
| C12 | 3 | Full super-ux chain (`foundation.md` personas/JTBD/CJM, `flows.md`, `screens.md`, a linter) for the whole product | Building it is re-architecting the project's entire UX documentation — far outside this brief. D9's "text-only" recorded in a `Design tooling` note instead | `BACKLOG.md` | deferred |
