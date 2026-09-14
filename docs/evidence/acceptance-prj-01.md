# PRJ-01 — acceptance (task-pipeline stage 10)

Run: 2026-09-13 → 2026-09-14. Branch `fix/production-hotfix-wave` → PR #369 → v409;
follow-ups #370 → v410 and #372. Standard: **Proof of Done** — every row carries the
command, file or measurement that proves it.

## 1. The ladder walk, first

Each REQ walked bottom-up, checking the seam at every step. It found two things the REQ
table could not, because a comparison needs two sides and an absence has one:

| Found | Where the ladder led | Became |
|---|---|---|
| A **third** site rebuilding `AgentContext.extra` — built into a local variable first, so the grep that found the other two missed it | R4's change → the guard that replaced the grep | fixed in #369; the guard is now what counts the sites |
| A **sixth** field of R1's class, in a module the outage never touched: `db_index_validator` writes `summary_text` and `recommendations`, both schema-declared `string`, into `Text` columns, uncoerced | R1's contract → "what else is on the other side of this seam" | #372, plus `as_text` extracted to `app/llm/tool_args.py` |
| `AgentContext` is the 8th most connected node in the repository (191 edges) and `SYSTEM_ARCHITECTURE.md` §2.3 described `extra` only by what it contains, never by the property that makes it work | stage 9, graph against docs | documented in this branch |

## 2. The coverage table

| REQ | Requirement | Verified | Evidence |
|---|---|---|---|
| R1 | object-valued tool-call args coerced before `Text` columns | **production** | `code_db_sync` wrote 300 rows at 02:17:44 UTC, 19 with `required_filters_json`, 31 with `column_value_mappings_json`; `DataError` count in 200 log lines: **0**. First successful `store_sync` since 2026-09-09 |
| R2 | pgvector's `kind` filter escapes its literal percent | **superseded by R2b** | correct, and it revealed a second defect in the same clause |
| R2b | that clause names `id`, the column the table has | **production** | symbol chunks 0 → **42 341** (`Upserted 42341 of 42341`); total chunks 5 333 → 47 865. Zero since 2026-09-11 |
| R3 | the transports pass `total_duration_ms=None` | **CI + partial production** | `test_trace_duration_is_the_request.py`; two production requests measured at 93.3 s and 469.6 s. **Not fully closed**: both were driven through `ConversationalAgent` directly, and the trace is written by the HTTP route, so the value's path into `request_traces` is still unmeasured |
| R4 | `AgentResponse.exposed_learning_ids` carries sub-agent writes | **production** | a real request returned `exposed=30`. It was `[]` on every request the product ever served |
| R5 | no future change may rebuild `AgentContext.extra` | **CI** | the guard found a site the grep missed, on the day it was written |
| R6 | production: the code↔DB map updates again | **production** | as R1; `run_code_db_sync completed … tables=300`, `619.54s` |
| R7 | production: a full rebuild reaches `pipeline_end` | **production** | `completed`, `pipeline_end: Indexed 10377 files, 740 schemas`, **4 663 s** against 12 039 s cold — `generate_docs` regenerated **24 of 782** documents, the rest reused by `content_hash` |
| R8 | suite green, coverage ≥ 80% | **yes** | 8 740 passed, 8 skipped, 1 xfailed; `coverage report --fail-under=80` → 82.03%; `mypy` clean over 414 files |

**The night's own verdict, unplanned and the strongest of them**: the 04:00 nightly ran
green end to end for the first time in weeks — `daily_sync` 2 478 s, `index_repo` 48 s,
`db_index` 1 840 s, `code_db_sync` 535 s, all `completed`. Before this deploy, 7 of 17
`daily_sync` runs failed.

## 3. The measurement that nearly lied

R6's run row reads `failed: stale run reaped`. The same job's log reads
`run_code_db_sync completed … tables=300` and `619.54s ←`. **Measured on the run row the
verdict would have been "the fix does not work".** R6 is measured on the artefact — did
the map move — and that choice is the only reason it reads verified.

Which is also the sharpest argument for PRJ-02: the product cannot currently tell a
successful run from a failed one in its own table, and `/sync-history`, the UI and the
nightly report all read the status.

## 4. What this run found that it was not sent to find

| # | Finding | Severity | Home |
|---|---|---|---|
| 1 | A second defect in the same clause as R2, hidden behind it — symbol search had been dead for three days and no error said so, because each fix produced a different error | P0 | #370, shipped |
| 2 | The code↔DB map lost **86% of its `matched` rows** to the 2026-09-10 model switch: 138 → 19, `unknown` 13 → 132, on an unchanged DB side. Invisible while the write was failing, because the old good map stayed in place | **P0, needs an operator decision** | board B-06 |
| 3 | The reaper kills live runs deterministically: measured at 319 s elapsed with **302 s** since the `IndexingRun` beat and **11 s** since the `CodeDbSyncSummary` beat — the pipeline beats correctly, into the row nobody reads | P1 | PRJ-02, evidence in `scratchpad/prj02-live-measurement.txt` |
| 4 | One chat request took **469.6 s** against a documented 180 s ceiling; a simpler one took 93.3 s | P1 | PRJ-03 |
| 5 | A sixth field of R1's class, not yet failed | P1 | #372, shipped |
| 6 | ~130 stale remote branches | P3 | board B-07 |

## 5. Ledgers at close

- **Board**: 7 rows, of which B-06 is P0 and awaiting an operator decision.
- **Verification**: 8 rows — 6 verified in production, 1 in CI, **R3 partially open** and
  named as such rather than ticked.
- **Carry-over**: PRJ-14 (codebase-wide guard, Postgres in CI, SQL compile check),
  PRJ-03 (`_wf_*` → `RequestState`), and the 56 audit findings already sequenced.

## 6. What is NOT done

R3 is not fully verified: no request has yet travelled the HTTP route on this release, so
nothing has measured the duration's path into `request_traces`. It is a row in the
verification ledger reading `partial`, not a tick.
