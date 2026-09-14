# Verification ledger

One row per shipped REQ. `never` means the change is deployed and nobody has confirmed it
in production yet — the whole reason this file exists separately from the test suite.

| REQ | What shipped | Verified | Evidence | Date |
|---|---|---|---|---|
| PRJ-01 R1 | object-valued tool-call args coerced before the `Text` columns | pending | — | — |
| PRJ-01 R2 | pgvector's `kind` filter escapes its literal percent | pending | — | — |
| PRJ-01 R3 | the three transports pass `total_duration_ms=None` | pending | — | — |
| PRJ-01 R4 | `AgentResponse.exposed_learning_ids` carries sub-agent writes | pending | — | — |
| PRJ-01 R5 | AST guard against rebuilding `AgentContext.extra` | CI | `test_exposure_survives_the_context_copy.py` green on #369 | 2026-09-14 |
| PRJ-01 R6 | production: the code↔DB map updates again | pending | — | — |
| PRJ-01 R7 | production: a full rebuild reaches `pipeline_end` | pending | — | — |
| PRJ-01 R8 | suite green, coverage ≥ 80% | yes | 8 721 passed; `coverage report --fail-under=80` → 82.03% | 2026-09-14 |
