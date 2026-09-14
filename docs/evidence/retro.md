# Retrospective — standing instructions and run stamps

**Standing instructions bind the next run.** Held to ten; each is pruned when its three
retirement triggers fire (the defect class has a guard, the code it describes is gone, or
two runs pass without it applying).

| # | Instruction | Born | Retires when |
|---|---|---|---|
| S-01 | A test fixture for an LLM tool call must mirror a **model**, not the tool schema. A fixture that hands back exactly what the schema declares proves the parser reads its own documentation. | PRJ-01 (four nights of production failure behind 8 698 green tests) | a codebase-wide coercion layer exists (B-01) and its own tests use model-shaped input |
| S-02 | SQL composed for a driver must be validated by **that driver's** parser in a test, not by reading it. psycopg3, asyncpg and SQLite disagree about what a string is. | PRJ-01 (#344's `LIKE 'sym:%'`) | B-03 makes it codebase-wide |
| S-03 | When a defect is invisible at the call site that causes it, the regression lock is an **AST guard**, not an assertion about behaviour. Both guards written in PRJ-01 found something the grep for the same thing had missed. | PRJ-01 | never — this is a technique, not a patch |
| S-04 | Before pushing to `main`, check `indexing_runs` for a run in flight. A push deploys, and a deploy kills a running rebuild. Run the check as its **own command**, not in the same line as the push — a result that arrives with the push cannot stop it. | 2026-09-14 (a docs push went out while two nightly runs were mid-flight; the check was in the same command) | the deploy pipeline itself refuses to restart a dyno holding a running `index_repo` |

## Run stamps

| Run | Commit | Diverged? |
|---|---|---|
| PRJ-01 production hotfix wave | `259cfea5` | see the entry below |

## Entries

### PRJ-01 — the grep that found two of three

**Symptom.** The stage-0 read of `orchestrator.py` used `grep -rn "extra={"` and found two
sites rebuilding the context's `extra` dict. The AST guard written at stage 5 found
**three**: `orchestrator.py:2753` builds the dict into a local variable first
(`new_extra = {...}` then `replace(context, extra=new_extra)`), so no line matches the
pattern the grep looked for.

**Surfaced at** stage 5 (build). **Owned by** stage 0 (harvest) — the brief's REQ table
named "two sites" as a fact.

**Root cause.** A grep answers "which lines look like this", and the question was "which
calls do this". The third site does the same thing in two statements.

**Fix, by grade.** Structural: the guard is the test, and it is now the thing that counts
the sites — not a number written into a brief. Recorded as S-03 above.

**The check that catches it next time.** `test_the_orchestrator_never_rebuilds_the_context_extra_dict`
fails on any `replace(context…, extra=…)` however it is spelled.
