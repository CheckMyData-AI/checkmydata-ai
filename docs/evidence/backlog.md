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
| B-05 | P3 | Stale comment class: `orchestrator.py` carried a sentence describing behaviour PRJ-01 changed; a comment naming a mechanism should name the test that holds it | PRJ-01 stage-9 finding | open |
