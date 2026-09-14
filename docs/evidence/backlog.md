# Board

Rows carry a source and a computed priority. The 2026-09-13 audit's fourteen projects are
sequenced by ADR-0005 (waves), ADR-0006 (buy-before-build) and ADR-0007 (recipes, shell);
this board holds what falls outside a named project or arrives mid-run.

| id | Priority | Row | Source | Status |
|---|---|---|---|---|
| B-01 | P1 | Codebase-wide AST guard for LLM tool-call argument types — PRJ-01 fixed one analyzer; `learning_analyzer`, `adaptive_planner`, `router` and every flat-loop tool parse the same way | PRJ-01 carry-over → PRJ-14 | open |
| B-02 | P1 | Run the unit suite against Postgres (asyncpg) as well as SQLite in CI — `Text` vs dict and `Numeric` vs float differences are invisible on SQLite | PRJ-01 carry-over → PRJ-14 | open |
| B-03 | P1 | Compile every SQL string passed to psycopg across `app/`, not only `PgVectorStore` | PRJ-01 carry-over → PRJ-14 | open |
| B-04 | P2 | `_wf_*` dicts → per-request `RequestState`; PRJ-01 made the `extra` dict the single carrier, the drains still exist beside it | PRJ-01 carry-over → PRJ-03 | open |
| B-06 | **P0** | **The code↔DB map lost 86% of its `matched` rows to the 2026-09-10 model switch, and fixing the write is what made it visible.** Measured on production 2026-09-14: the map of 09-09 held 283 rows — 138 `matched`, 13 `unknown`; the map written 02:17 UTC on 09-14 holds 300 — **19 `matched`, 132 `unknown`**, 144 rows at confidence 1, only 19 with `required_filters_json`. The DB side did not move: `db_index` holds the same 214 tables and all 214 appear in the map, so 214 rows had both sides available and 21 got a matched/mismatch verdict. The cause is in the log — `LLM sync batch: 3/5 used fallback`, `fallback (no tool call)` — `deepseek/deepseek-v4-flash-0731` frequently returns no tool call at all, and the fallback writes `unknown` at confidence 1. **This was invisible while `store_sync` was failing**, because the old good map stayed in place; one model switch did two kinds of damage, the loud one to the write and the silent one to the content. Options: pin the sync analyzer to a stronger model (as `INDEXING_LLM_MODEL_BY_DOC_TYPE` already does per doc type), retry once on a no-tool-call response, or move `DEFAULT_LLM_MODEL` back and pay for it. **Needs an operator decision — it is a cost/quality trade, and the map is what Goal #1 calls "the database that knows the product".** | PRJ-01 post-deploy measurement | open |
| B-07 | P3 | ~130 stale remote branches on the origin (`fix/*`, `docs/*` from closed work). Housekeeping; delete after confirming each is merged | PRJ-01 observation | open |
| B-05 | P3 | Stale comment class: `orchestrator.py` carried a sentence describing behaviour PRJ-01 changed; a comment naming a mechanism should name the test that holds it | PRJ-01 stage-9 finding | open |
