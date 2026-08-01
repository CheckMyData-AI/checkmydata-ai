# Carry-over ledger — analytics data sources (GA4 · ASC · Play)

> Append-only. Written by every stage the moment something is deferred, dropped or
> left half-done. Read **in full** at stage 10. Deferred out loud is forgotten.

| # | Stage | Item | Why | Where it goes | Status |
|---|---|---|---|---|---|
| C1 | 0 | OAuth sign-in for Google sources (GA4, Play) | D4 chose paste + reusable credential table; OAuth needs a client registration, callback routes, refresh-token rotation and Google verification review | `BACKLOG.md` | deferred |
| C2 | 0 | GA4 realtime reports; extra Apple analytics report types | D7 scoped to blueprint parity; realtime also fights the cache-with-provenance model | `BACKLOG.md` | deferred |
| C3 | 0 | SQL access over the analytics cache (SQLAgent parity) | D2 chose a dedicated sub-agent instead | `BACKLOG.md` | deferred |
| C4 | 0 | Query-repair loop, query-failure learning, sql_reconciliation for analytics | D3 — statement-shaped, no meaning for a tool-loop agent | `BACKLOG.md` | deferred |
| C5 | 0 | **Production deploy + stage-8 post-deploy verification** | D10 stops each module at an open PR; the operator merges | runs only if the operator merges in-session — otherwise carry-over with commands: `heroku logs -a checkmydata-api`, `GET /api/health` | **deferred by design** |
| C6 | 0 | **Standing cost (R1): every future quality gate must be wired twice** — once for SQL, once for analytics | Consequence of D2 | `BACKLOG.md` — revisit if a third non-SQL source appears | recorded |
| C7 | 0 | Reconcile `query_mcp_source` tool description, which names "Google Analytics" as its use case | Now misleading: GA4 is a first-class source, not an MCP one | REQ-027 (docs) — update the tool description in M0 | open |
