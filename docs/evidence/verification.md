# Verification ledger

One row per shipped REQ. `never`/`pending` means the change is deployed and nobody has
confirmed it in production yet — the whole reason this file exists separately from the
test suite.

| REQ | What shipped | Verified | Evidence | Date |
|---|---|---|---|---|
| PRJ-01 R1 | object-valued tool-call args coerced before the `Text` columns | **yes** | production v409: `code_db_sync` wrote 300 rows at 02:17:44 UTC with 19 non-empty `required_filters_json` and 31 non-empty `column_value_mappings_json`; `DataError` count in the worker log over 200 lines: 0. First successful `store_sync` since 2026-09-09 | 2026-09-14 |
| PRJ-01 R2 | pgvector's `kind` filter escapes its literal percent | **superseded** | the escape was correct and revealed a second defect in the same clause — see R2b | 2026-09-14 |
| PRJ-01 R2b | that clause names `id`, the column the table actually has | **yes** | `acceptance-prj-01.md` R2b: symbol chunks 0 → 42 341. Re-read 2026-09-23 on v444: `doc_embeddings` by `metadata->>'kind'` — method 24 208, class 18 182, enum 364, function 215, interface 201 | 2026-09-14 |
| PRJ-01 R3 | the three transports pass `total_duration_ms=None` | CI | `test_trace_duration_is_the_request.py`; no production chat traffic since 2026-09-05 to measure against | 2026-09-14 |
| PRJ-01 R4 | `AgentResponse.exposed_learning_ids` carries sub-agent writes | CI | `test_exposure_survives_the_context_copy.py`; needs a real chat request to confirm in production | 2026-09-14 |
| PRJ-01 R5 | AST guard against rebuilding `AgentContext.extra` | **yes** | the guard found a third rebuild site the grep for it had missed (`orchestrator.py:2753`) | 2026-09-14 |
| PRJ-01 R6 | production: the code↔DB map updates again | **yes** | as R1; worker log `run_code_db_sync completed: connection=0a9360ea tables=300 matched=17`, `619.54s` | 2026-09-14 |
| PRJ-01 R7 | production: a full rebuild reaches `pipeline_end` | **yes** | `acceptance-prj-01.md` R7: `pipeline_end: Indexed 10377 files, 740 schemas`, 4 663 s. This row was never updated when the acceptance doc was (found by the 2026-09-23 audit) | 2026-09-14 |
| PRJ-01 R8 | suite green, coverage ≥ 80% | **yes** | 8 721 passed; `coverage report --fail-under=80` → 82.03% | 2026-09-14 |

## The measurement that nearly lied

R6's run row reads `failed: stale run reaped`. Measured on the run row, the verdict would
have been "the fix does not work". The worker log for the same job says
`run_code_db_sync completed … tables=300` and `619.54s ←`: the reap is bookkeeping, the
process kept working and stored its result. **R6 is measured on the artefact — did the map
move — not on the run's status**, and that choice is the only reason the row above reads
`yes`.

That is also the sharpest argument for PRJ-02: the product currently cannot tell a
successful run from a failed one in its own table. `/sync-history`, the UI and the nightly
report all read the status.
