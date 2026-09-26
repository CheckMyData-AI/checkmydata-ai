# Retrospective — standing instructions and run stamps

**Standing instructions bind the next run.** Held to ten; each is pruned when its three
retirement triggers fire (the defect class has a guard, the code it describes is gone, or
two runs pass without it applying).

| # | Instruction | Born | Retires when |
|---|---|---|---|
| S-01 | A test fixture for an LLM tool call must mirror a **model**, not the tool schema. A fixture that hands back exactly what the schema declares proves the parser reads its own documentation. | PRJ-01 (four nights of production failure behind 8 698 green tests) | a codebase-wide coercion layer exists (B-01) and its own tests use model-shaped input |
| S-02 | SQL composed for a driver must be validated by **that driver's parser** in a test — and the parser proves **syntax, not meaning**. Check the identifiers against the schema in the same test, or the next error is simply a different error. | PRJ-01 (#344's `LIKE 'sym:%'`, then `doc_id` behind it) | B-03 makes it codebase-wide and B-02 runs the suite against Postgres |
| S-03 | When a defect is invisible at the call site that causes it, the regression lock is an **AST guard**, not an assertion about behaviour. Both guards written in PRJ-01 found something the grep for the same thing had missed. | PRJ-01 | never — this is a technique, not a patch |
| S-04 | Before pushing to `main`, check `indexing_runs` for a run in flight — **and for one that will have STARTED by the time the release lands**. A deploy arrives ~20 min after the merge (CI), so "nothing is running now" is the wrong question when a cron fires inside that window. `daily_knowledge_sync_hour` and `analytics_collect` hours are the ones to subtract. Run the check as its **own command**, not in the same line as the push — a result that arrives with the push cannot stop it. | 2026-09-14, refined 2026-09-15 after a merge at 21:54 UTC deployed at 22:20 into a nightly that began at 22:00 | the deploy pipeline refuses to restart a dyno holding a running job |
| S-05 | Write an assertion from the **contract** — the schema, the model, the migration — never from the code under test. An assertion copied out of the implementation passes by construction and locks in whatever that implementation got wrong. | PRJ-01 (`assert "doc_id LIKE" in sql`, which proved the escaping fixed while vouching for a column that has never existed) | never — this is how a test earns its authority |
| S-06 | Verify a fix on the **artefact it was supposed to produce**, not on the bookkeeping around it. A run row can say `failed` while the job it describes completed. | PRJ-01 (R6: the row read `failed: stale run reaped`, the log read `completed … tables=300, 619.54s`) | PRJ-02 makes the status trustworthy |
| S-07 | A watch whose window includes history will fire on history. Scope a monitor to the run you started — by start time or id — and put the elapsed seconds outside the change-detection key, or it emits on every poll. | PRJ-01 (a 6-hour window raised a false alarm on the previous night's failure) | never — tooling hygiene |

| S-08 | Lint locally with **CI's exact scope and order**: `ruff format --check app/ tests/`, then `ruff check app/ tests/`. Running it over `app/` alone is running a different check — and the narrower one passes on a tree CI rejects in sixty seconds. | 2026-09-14 (three errors in a test file CI caught and a local `ruff check app/` could not) | the lint scope stops being two trees |
| S-09 | A validation must **gate** the write, not accompany it. A check that raises after `&&` has already run the next command protects nothing — **and a validation in a separate command protects nothing either.** Broken twice in two days, in two syntaxes: a `&&` chain on 2026-09-14, then on 2026-09-15 a `python3 - <<'PY'` heredoc whose anchor assert raised while the `git add && git commit` on the NEXT LINE ran regardless and committed without the changelog entry the script existed to write. The shell does not care that the previous command failed unless you make it. Put the write inside the validated block, or print a sentinel the next command greps for. | 2026-09-14, again 2026-09-15 | never — this is the shape, not the instance |
| S-10 | **A guard's written justification is a claim, and it needs its own check.** Two shipped on 2026-09-15 with reasons that one CI run disproved: a 40-byte floor on "a file too small to hold a schema", justified by "the shortest real Laravel migration measures 232 bytes" — and `CREATE TABLE t1 (id INT);` is 25 bytes and complete; and a test refusing to skip on "a test that passes on an unset-up tree would have passed against the defect" — which the SHAPE rule beside it already caught on any tree, while CI has no `backend/.venv` at all. Both reasons were plausible prose and neither was measured. Before writing *because X*, find the smallest legitimate case that contradicts X. | 2026-09-15, again 2026-09-17 (B-14: a model probe that built its own context and skipped the batch path recommended the model that, on the real pipeline, declined the tool 88 times) | when a guard ships whose justification was derived rather than asserted |
| S-11 | **Status rows in `docs/evidence/loop-queue.md` are edited on `main` in a consolidation commit, never in a feature branch.** Every branch that touched the table conflicted with the next merge — the rows are adjacent — and each conflict cost a rebase and a full CI run; the CHANGELOG `[Unreleased]` heading has the same shape. Feature branches carry code, tests and the docs of what they change. | 2026-09-23 (five conflicts in one merge train: #410 twice, #414, #415) | never — this is the shape of a shared ledger |
| S-12 | **Before a push, run CI's whole backend gate locally: `ruff format --check`, `ruff check`, `mypy app/`, and the FULL unit suite — not the tests next to the change.** Three CI failures in one afternoon were each invisible to the targeted run: a file formatted after its last edit (S-08 again), a `var-annotated` only mypy sees, and six source-inspection guards reading a function whose body had moved. A guard that reads source by NAME breaks on a refactor that keeps every behaviour; that is the price of the guard, and only the full suite pays it before CI does. Also S-09, a third time: a heredoc's failing assert did not stop the `git commit` on the next line. | 2026-09-23 (#415 twice, #416 twice) | CI runs these in under a minute locally |
| S-13 | **A unit test that needs an HTTP answer builds `TestClient(app)` without `with`.** The context manager runs the app lifespan — reconciles, cron loops, process-wide singletons — and what it leaves behind breaks tests that run after it, in the full suite only. One CORS test did that to 27 tests on 2026-09-26, and the first symptom read as an unrelated flake in `test_main_cron` that I nearly filed as pre-existing (#430 carries the correction). Middleware answers without the lifespan. And a test that passes alone and fails in the full run is ordering until proven otherwise: run the suspect file first, then the failing ones, before blaming either. | 2026-09-26 (#431) | when a test genuinely needs the lifespan — then as an integration test with its own teardown |

## Run stamps

| Run | Commit | Diverged? |
|---|---|---|
| PRJ-01 production hotfix wave | `259cfea5` … `23fd0f24` | yes — four entries below |
| PRJ-02 + the audit wave (MCP, coercion class, settings, interface) | `e981b73d` … `fb154271` | yes — two entries below |

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

### 5. Linted the wrong tree

**Symptom.** PR #377 failed CI on three lint errors — two long lines and an unused
import, all in a test file — after a local run I had called clean.

**Surfaced at** stage 7 (deploy). **Owned by** stage 6 (tests), which is where the
parity command is supposed to be run.

**Root cause.** I ran `ruff check app/`. CI runs `ruff format --check app/ tests/` and
then `ruff check app/ tests/`. A narrower scope is not a weaker version of the same
check; it is a different check that cannot see the files I had just written.
`CLAUDE.md` records this exact trap costing two CI cycles in one afternoon, which is
how I knew to look for it and not enough to stop me causing it.

**Fix, by grade.** Procedural, recorded as S-08. There is a `make lint` that does it
correctly; the reason I did not use it is that its `$(VENV)` path resolves from the
repository root and I was inside `backend/`. That is worth fixing in the Makefile, and
it is on the board rather than in this run.

### 6. The check that ran after the commit

**Symptom.** Conflict markers reached a commit on `fix/close-the-coercion-class`.

**Surfaced at** stage 7, one command later. **Owned by** stage 5.

**Root cause.** The resolution script asserted its result and the shell chain behind it
was `python3 - <<PY ... PY; git add ... && git commit`. The assertion failed, the script
exited non-zero, and the `git add` ran anyway because it was a new statement rather than
a continuation. A guard placed after the action it is meant to prevent is decoration.

**Fix, by grade.** Structural: the resolver is a file now (`/tmp/resolve_changelog.py`
in this run, and it belongs in `scripts/`), it validates **before** `write_text`, and it
exits non-zero so the `&&` chain behind it stops. It has since refused to write twice,
and was right both times — the `## [Unreleased]` heading sits *above* the conflict in
this file, so a resolver that adds one produces two.

