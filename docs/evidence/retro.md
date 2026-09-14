# Retrospective — standing instructions and run stamps

**Standing instructions bind the next run.** Held to ten; each is pruned when its three
retirement triggers fire (the defect class has a guard, the code it describes is gone, or
two runs pass without it applying).

| # | Instruction | Born | Retires when |
|---|---|---|---|
| S-01 | A test fixture for an LLM tool call must mirror a **model**, not the tool schema. A fixture that hands back exactly what the schema declares proves the parser reads its own documentation. | PRJ-01 (four nights of production failure behind 8 698 green tests) | a codebase-wide coercion layer exists (B-01) and its own tests use model-shaped input |
| S-02 | SQL composed for a driver must be validated by **that driver's parser** in a test — and the parser proves **syntax, not meaning**. Check the identifiers against the schema in the same test, or the next error is simply a different error. | PRJ-01 (#344's `LIKE 'sym:%'`, then `doc_id` behind it) | B-03 makes it codebase-wide and B-02 runs the suite against Postgres |
| S-03 | When a defect is invisible at the call site that causes it, the regression lock is an **AST guard**, not an assertion about behaviour. Both guards written in PRJ-01 found something the grep for the same thing had missed. | PRJ-01 | never — this is a technique, not a patch |
| S-04 | Before pushing to `main`, check `indexing_runs` for a run in flight. A push deploys, and a deploy kills a running rebuild. Run the check as its **own command**, not in the same line as the push — a result that arrives with the push cannot stop it. | 2026-09-14 | the deploy pipeline refuses to restart a dyno holding a running `index_repo` |
| S-05 | Write an assertion from the **contract** — the schema, the model, the migration — never from the code under test. An assertion copied out of the implementation passes by construction and locks in whatever that implementation got wrong. | PRJ-01 (`assert "doc_id LIKE" in sql`, which proved the escaping fixed while vouching for a column that has never existed) | never — this is how a test earns its authority |
| S-06 | Verify a fix on the **artefact it was supposed to produce**, not on the bookkeeping around it. A run row can say `failed` while the job it describes completed. | PRJ-01 (R6: the row read `failed: stale run reaped`, the log read `completed … tables=300, 619.54s`) | PRJ-02 makes the status trustworthy |
| S-07 | A watch whose window includes history will fire on history. Scope a monitor to the run you started — by start time or id — and put the elapsed seconds outside the change-detection key, or it emits on every poll. | PRJ-01 (a 6-hour window raised a false alarm on the previous night's failure) | never — tooling hygiene |

## Run stamps

| Run | Commit | Diverged? |
|---|---|---|
| PRJ-01 production hotfix wave | `259cfea5` … `23fd0f24` | yes — four entries below |

## Entries

### 1. The grep that found two of three

**Symptom.** The stage-0 harvest used `grep -rn "extra={"` and found two sites rebuilding
the context's `extra` dict. The AST guard written at stage 5 found **three**:
`orchestrator.py:2753` builds the dict into a local variable first, so no line matches.

**Surfaced at** stage 5. **Owned by** stage 0 — the brief's REQ table named "two sites"
as a fact.

**Root cause.** A grep answers "which lines look like this"; the question was "which calls
do this".

**Fix, by grade.** Structural: the guard is now the thing that counts the sites, not a
number written into a brief. Recorded as S-03.

### 2. Parseable is not correct

**Symptom.** The test written for R2 ran psycopg's own scanner over the composed SQL and
passed. The first production rebuild after the deploy died one line later on
`UndefinedColumn: column "doc_id" does not exist`.

**Surfaced at** stage 8 (post-deploy). **Owned by** stage 5 — the test was written to
reproduce the error message rather than to establish the contract.

**Root cause.** The production error said "psycopg will not parse this", so the test
proved psycopg would parse it. Two defects sat in one clause and the outer one hid the
inner one; validating the outer proved nothing about the clause.

**Fix, by grade.** Structural: the test now also checks every identifier against
`DocEmbedding.__table__.columns`. Recorded as S-02's second sentence.

### 3. A test that asserted the bug

**Symptom.** That same test contained `assert "doc_id LIKE" in sql`. It was green, and it
vouched for a column name the table has never had.

**Surfaced at** stage 8, while fixing entry 2. **Owned by** stage 5.

**Root cause.** The assertion was copied out of the implementation. An assertion written
from the code cannot disagree with the code.

**Fix, by grade.** Structural, and it is the sharper half of entry 2: a green check that
was written from the implementation actively misleads the next reader, because the next
reader trusts it. Recorded as S-05.

### 4. Verified on the bookkeeping, nearly

**Symptom.** The monitor watching R6 was written to break on the run's status. It would
have reported "the fix does not work" on a run that completed successfully.

**Surfaced at** stage 8, before it could produce a wrong verdict — the reap was expected
from the audit, so the measurement was moved to the artefact in time.

**Owned by** stage 4 (plan) — the REQ table said "a `code_db_sync` `completed` row",
which is the status, not the outcome.

**Root cause.** A REQ verified by a status field inherits every defect of whatever writes
that field.

**Fix, by grade.** Procedural for this run, structural for the next: REQ rows now name the
artefact. Recorded as S-06.
