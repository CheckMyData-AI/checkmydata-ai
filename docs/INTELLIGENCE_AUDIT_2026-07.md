# Intelligence & Data-Correctness Audit — 2026-07

**Scope:** the *quality/intelligence* dimension the prior audits did **not** cover —
how the orchestrator reasons and creates tasks, how code and DB are indexed, how
code↔DB sync + freshness work, how retrieval assembles context, and whether the user
gets a **correct, traceable** answer. This is deliberately **not** a security/IDOR/auth
audit (see `docs/qa-audit/issues.md`, `docs/ORCHESTRATOR_AUDIT_2026-06.md`,
`docs/AUDIT_REMEDIATION_PLAN_2026-06.md` for the security + reliability track, largely
closed in R1/R2/R5 + orchestrator follow-ups).

**Method:** six parallel specialist reviews (AI/agent architect + prompt engineer,
ML/data engineer ×2 for indexing + retrieval, data engineer for schema + sync, data
scientist + QA for acquisition + presentation). Every finding is grounded in code read,
quoted, and cited `file:line`. Findings tagged with a stable per-subsystem ID.

> **Runtime evidence (prod, read-only, authorized):** `request_traces` (195 rows, ~1 day
> post-v190), `error_log`, `query_failures`. Findings below are code-grounded **and** where
> noted validated against this prod sample. Local `agent.db`/`logs/` were empty/stale.

### Prod validation (2026-07-01 sample, n=195 traces)

| Signal | Value | Validates |
|---|---|---|
| Failed requests | **47/195 = 24%** | High user-facing failure rate. |
| `step_limit_reached` | 9 · `error` 14 · `clarification_request` 5 | Termination pressure (ORCH-T01/T02/T03). |
| `steps_used` avg **1.1**, max 7 (cap=100) | — | **ORCH-T01 confirmed**: step budget is a dead termination signal. |
| avg tokens/request | **164,230** | Context bloat → cost (ORCH-PR01, CP01/CP02). |
| avg duration 116s, **max 360s** | — | Wall-clock-dominated termination; slow UX. |
| avg db_queries **9.0**, llm_calls 7.3 | — | Heavy per-request query fan-out. |
| `pipeline_complete` | **1** vs sql_result 56 / text 80 | Complex pipeline rarely taken → flat-loop quality nets dominate; complex Q under-served (ORCH-R01). Divergence (A01/A02) hits few but the hardest requests. |
| `error_log` "Stale: pipeline_end never received" | occ **7** | Requests dying without terminal event (reliability). |
| **Only `query_failures` row** | Q="подсчитай доход за 1-29 июня 2026" (mysql), 3 attempts → **failed**, err=`required_filter_guard: missing purchases.deleted_at, purchases.was_handled` | **SYNC-L1 confirmed, and worse**: the 2-column hardcoded guard *blocked a legitimate revenue query to death*. The guard both under-enforces elsewhere (L1) **and** over-blocks here. Elevate SYNC-L1 to **Critical** and add "guard must be satisfiable / degrade to warn" to its fix. |

---

## 0. Bottom line (the meta-pattern)

The product advertises a deep intelligence stack (hybrid RAG, code graph, lineage,
context packs with provenance, data gates, answer validation). In the **default prod
configuration and on the most-traveled code path, much of it is inert or divergent**:

1. **Dual execution paths diverge.** SQL-quality re-query gate, reconciliation, the
   final AnswerValidator, and viz selection exist **only on the unified flat loop**; the
   complex multi-stage pipeline bypasses them. Which path a question takes is a routing
   decision — so **the same question gets different correctness assurance by coin-flip**
   (F-ARCH-3 made concrete: `ORCH-A01/A02`).
2. **The best RAG layer is dead code at runtime.** `ContextPack`/`KnowledgeCatalog`/
   `ContextPlanner` (provenance, trust, budget-aware packing) is only called by a
   read-only Health UI route; the agent uses a thin `load_relevant_knowledge` (3 chunks,
   400-char slices, source-path only) (`RET-R1/R2/R3/R8`).
3. **Advertised code intelligence is OFF by default.** `code_graph_enabled=off`,
   `lineage_enabled=off`, `reranker_enabled=off`, `context_planner_enabled=off`. The
   default path is materially weaker than the docs imply (`F-ARCH-6`, corroborated across
   `CODEIDX`, `RET`, `SYNC`).
4. **Embedding is quietly truncating.** Chunks target 1500 tokens but the default embedder
   (`all-MiniLM-L6-v2`) truncates at ~256 tokens → **~80% of each large chunk never enters
   its vector** (`CODEIDX-C1/C2`). Raw code is never embedded, only LLM schema prose
   (`CODEIDX-C3`).
5. **Confidently-wrong-number hazards** in acquisition/presentation (truncation→aggregation
   leak, no JOIN-grain guidance, DataGate skips `Decimal`, charts render nulls as zeros).
   For a data product this is the highest-severity class — it violates vision invariant #3
   ("every answer traceable/correct").
6. **"Mandatory" code↔DB filters aren't enforced.** The hard guard covers only 2 hardcoded
   columns; every other "ALWAYS add WHERE" filter is advisory prompt-text (`SYNC-L1`).
7. **MongoDB indexing is broken**; ClickHouse is thin. Mongo sample/distinct/probe emit SQL
   into a JSON parser → all fail (`DBIDX-D1/D2/D3`).

Severity roll-up (this audit only): **Critical 5 · High 21 · Medium ~38 · Low ~30.**

---

## 1. Cross-cutting themes (fix once, close many)

### T1 — Path divergence: unify the two execution paths
The flat unified loop accreted quality nets inline that the pipeline never received.
- `ORCH-A01` (High): result-quality gate + reconciliation run only in the flat loop, not
  in `stage_executor._run_sql_stage`.
- `ORCH-A02` (High): AnswerValidator runs on flat-loop answers, not on pipeline final
  answers — a `pipeline_complete` can ship a vague non-answer with a green check.
- `ORCH-P02`/`ORCH-PR-*`: the two prompt builders teach **incompatible** param
  conventions for the same enrichment (`cohort_window`).
- **Fix:** extract the SQL-result gate + reconciliation + AnswerValidator into shared
  components invoked by *both* paths. Precondition: decompose the 2808-LOC
  `orchestrator.py` god-file (`ORCH-A04`) so the divergence stops recurring.

### T2 — Dead / off-by-default intelligence: make it real or delete it
- `RET-R1/R2/R3/R8`: wire `ContextPack` into the orchestrator behind
  `context_planner_enabled` (with hybrid retrieval for its chunks, real token-budget
  packing, provenance rendered into the prompt) **or delete the layer and stop documenting
  it as the assembly path**.
- `F-ARCH-6`: decide per feature (code_graph / lineage / reranker) — promote to default-on
  with an eval gate, or document as opt-in. Today the shipped product ≠ the documented one.

### T3 — Embedding & retrieval precision
- `CODEIDX-C1/C2` (Critical): chunk-size vs embedder-window mismatch silently truncates
  ~80% of large chunks. Ship a 512+-token embedding model **or** size chunks to the real
  window using a tokenizer (not `chars/4`).
- `CODEIDX-C3` (Critical for code-Q&A): embed raw code symbols (AST spans already exist),
  not only LLM schema prose.
- `RET-R4` (Med): emit a metric/`degraded` event when a retrieval leg returns 0 (BM25
  snapshot missing on Heroku → silent dense-only).
- `RET-R5` (Med): relevance floor is near-zero (cosine sim ≈0.2); tighten and validate
  against `test_retrieval_eval.py`.
- `RET-R9` + `DBIDX-D7` (Med/High): schema retrieval is FK/join-blind — expand retrieved
  set one FK hop before the 15-table cap; splice distinct-values + numeric-format notes
  into the BM25 schema doc.

### T4 — Confidently-wrong-number hazards (highest business risk)
See §4. Truncation→aggregation leak, missing SQL-correctness guidance, DataGate blind
spots, enrichment misclassification, misleading charts.

### T5 — Trust signals that can lie
- `SYNC-L1` (High): "mandatory" required-filters enforced for only 2 hardcoded columns.
- `SYNC-L3` (High): freshness reads local HEAD only, ahead-only → can report **false-fresh**
  when the clone is behind/diverged.
- `SYNC-L5` (Med): code↔DB drift status is LLM-self-reported; no deterministic set-diff,
  so the user-facing `mismatch_count` is an opinion, not a fact.
- `ORCH-A03` (Med): routing complexity logged as `"unknown"` → mis-routes are unmeasurable.

### T6 — Cross-dialect parity
- `DBIDX-D1/D2/D3` (Critical): MongoDB enrichment/probe fully broken (SQL into JSON parser).
- `DBIDX-D4` (High): ClickHouse omits sorting/primary key (its join/order backbone).
- `DBIDX-D5/D6` (High): no enum-label / CHECK-constraint capture; views never indexed.

---

## 2. Findings — Orchestrator reasoning & task creation (`ORCH-*`)

| ID | Sev | file:line | Problem | Fix |
|---|---|---|---|---|
| ORCH-R01 | High | `orchestrator.py:589` | Multi-stage pipeline gated on `has_connection`; complex **knowledge/Git** questions silently drop to flat loop. | Gate on any data source (`has_connection or has_kb or has_repo or has_mcp`). |
| ORCH-R02 | High | `orchestrator.py:544-625`, `803-888` | `route_result.route` computed + logged but **never used**; full toolset always offered. | Narrow tools/bias prompt by route, or drop `route` from schema. |
| ORCH-R03 | Med | `router.py:42-54,187` | `estimated_queries` (single uncalibrated LLM int) is the only lever to the pipeline (`>=3`); under-estimation → complex Q on flat loop. | OR-in a cheap heuristic; log estimated-vs-actual to calibrate. |
| ORCH-R04 | Med | `orchestrator.py:536-543,1932` | Planner-fallback hardcodes `route=explore, complexity=moderate` → one bad JSON permanently downgrades a complex turn. | Preserve original `complexity` across fallback re-entry. |
| ORCH-P01 | High | `adaptive_planner.py:329-347`, `stage_validator.py:113-136` | Validation criteria (`expected_columns`/`min_rows`) are dead/no-op on text-producing stages, but the planner prompt invites them. | Scope validation to data stages; validate text stages on non-empty summary. |
| ORCH-P02 | Med | planner vs orchestrator prompt | Same op (`cohort_window`) documented with **different param envelopes** across the two paths. | Unify one param convention; accept both during transition. |
| ORCH-P03 | Med | `planner_prompt.py:11` | No lower guard: pipeline can emit a trivial 1-2 stage plan that loses flat-loop features (viz, follow-ups, result-gate). | Bounce ≤2-data-stage plans back to the unified loop. |
| ORCH-RP01 | Med | `adaptive_planner.py`, `orchestrator.py:2288` | `degraded` stages neither carried nor re-run on replan → redoes work / loses usable results. | Treat `degraded` as carry-over-eligible. |
| ORCH-RP02 | Med | `orchestrator.py:2547` | Pipeline learnings store **stage_id where tool name expected** → memory polluted. | Store `failed_stage.tool`. |
| ORCH-T01 | High | `orchestrator.py:1061,1105`; `config.py:254` | `max_orchestrator_iterations=100` makes the step lever inert; termination is wall-clock/context-fill only → long non-converging loops or clipped thorough ones. | Realistic step cap (12-20) / "no new data in N iters" wrap-up. |
| ORCH-T02 | Med | `orchestrator.py:1109-1169` | Large schema/rules payload can trip context-fill wrap-up at iter 0-1 → synthesize with **zero data**. | Gate wrap-up on iter>0 AND ≥1 successful retrieval; exclude static prompt tokens. |
| ORCH-T03 | Med | `orchestrator.py:1240-1254` | Terminates on first no-tool-call turn; a "let me think…" text turn ships a non-answer. | Re-prompt once when no data gathered on a data route. |
| ORCH-A01 | High | `stage_executor.py:576-624` vs `orchestrator.py:1444-1475` | Result-quality gate + reconciliation only on flat path. | Shared component for both paths. |
| ORCH-A02 | High | `orchestrator.py:1592` vs `response_builder.py:78-104` | AnswerValidator not run on pipeline final answers. | Run it on pipeline `final_answer` too. |
| ORCH-A03 | Med | `orchestrator.py:1749,2027` | `complexity` never written to `context.extra` → metrics log `"unknown"`; routing quality unmeasurable. | Record route/complexity/estimated_queries. |
| ORCH-A04 | Med | `orchestrator.py` (2808 LOC; `_run_tool_loop` ~950 LOC) | God-file hides the A01/A02 divergences and duplicated logic. | Extract phases (BudgetController, ToolBatchExecutor, Viz, ContinuationBuilder) with tests. |
| ORCH-A05 | Low | `orchestrator.py:1916-1934` | Planner-fallback rebuilds `AgentContext` field-by-field (13 fields) → new fields silently dropped on that branch. | `dataclasses.replace(...)`. |
| ORCH-CP01 | Med | `context_planner.py:96-154` | Naive substring cue match (`"code"`↔"country code", `"drop"`↔"drop-off") → spurious category loading, defeats its own token-saving purpose. | Word-boundary/tokenized matching; drop over-broad cues. |
| ORCH-CP02 | Low | `orchestrator.py:803-888` | ContextPlanner not invoked on the hot unified path; all categories eager-loaded. | Invoke it (or document where pruning actually happens). |
| ORCH-PR01-04 | Low-Med | `orchestrator_prompt.py` | Instruction stated 3× (budget waste); prompt/docstring still describes orchestrator as a *router* (stale post unified-loop); intermediate analysis stage lacks language-mirroring. | Consolidate; update self-description; add language caveat. |
| ORCH-V02 | Med | `stage_executor.py:434-538` | Per-stage retries compound (execute ×2 → validation-retry ×2 → data-gate-retry ×2 ≈ 7×) before replan; deadline checked only between batches. | Share one retry budget per stage; check deadline inside retry loops. |

**Top 3:** ORCH-A01/A02 (unify quality gates) · ORCH-T01+A03 (live step budget + real routing metrics) · ORCH-R01 (pipeline for non-DB complex Q).

---

## 3. Findings — Code indexing (`CODEIDX-*`)

*Reframe: the vector store embeds LLM-generated schema **documentation**, not code. AST
symbols feed only the (default-off) graph, never retrieval.*

| ID | Sev | file:line | Problem | Fix |
|---|---|---|---|---|
| CODEIDX-C1 | **Crit** | `chunker.py:10-12` + `vector_store.py:16` | `MAX_CHUNK_TOKENS=1500` vs default embedder 256-token window → ~80% of large chunks truncated pre-vector, invisibly. | Long-context embed model, or size chunks to the real window. |
| CODEIDX-C2 | **Crit** | `chunker.py:12` | `APPROX_CHARS_PER_TOKEN=4` under-counts code (~3) → "fitting" chunks overflow, compounding C1. | Use a real tokenizer. |
| CODEIDX-C3 | **Crit** (code-Q&A) | `pipeline_runner.py:1056`, `doc_generator.py` | Only LLM prose embedded; raw source truncated at 12k chars before the LLM; symbol bodies never retrievable. | Add a raw-symbol embedding path using AST spans + metadata. |
| CODEIDX-C4 | High | `pipeline_runner.py:1541`, `code_graph_service.py:167` | Incremental merge misses new cross-file edges from **unchanged** callers → graph drifts while looking complete. | Re-parse reverse-dependency set / recompute cross-file edges globally. |
| CODEIDX-C5 | Med | `ast_parser.py:177-300` | No symbols for module vars/consts, arrow-function React components, exports → TS/JS coverage much thinner than it appears. | Add `variable_declarator`(arrow/fn) + `export_statement`. |
| CODEIDX-C6 | Med | `code_graph.py:386-425` | EXTENDS parsed from a 200-char signature string, single-match only → inheritance undercounted. | Extract heritage from AST nodes. |
| CODEIDX-C7 | Med | `ast_parser.py:361-363` | UID includes line number → inserting a line above marks untouched symbols "new", drops inbound edges (compounds C4). | Drop `line` from identity; store as attribute. |
| CODEIDX-C8 | Med | `entity_extractor.py:189-335,592` | ORM extraction is per-ORM regex; misses SQLAlchemy 2.0 `Mapped[...]`, multi-line defs; failures `continue` silently → shaky input to the embedded doc (C3). | Drive column/FK extraction from AST where available; log extraction yield. |
| CODEIDX-C9 | Med | `pipeline_runner.py:1351` | tests/generated/dist not excluded from the graph; `_MAX_SYMBOLS` then evicts real symbols by slice order. | One shared ignore set; prune by degree not slice. |
| CODEIDX-C15 | Med | `entity_extractor.py:1111` | Enum→column fuzzy substring attaches wrong value-sets → LLM documents **wrong allowed values**. | Match via type annotation / FK-to-enum; low-confidence otherwise. |
| CODEIDX-C16 | Med | `entity_extractor.py:1127` | Table-name pluralization blindly appends `"s"` (`Person→persons`) → wrong table keys in metadata + cross-ref. | Use inflector / cross-check against live table names. |
| CODEIDX-C17 | Med | `pipeline_runner.py:532,1573` | `graph_build` checkpointed complete even when it threw → resume skips it, graph stays stale while run reports "completed". | Gate checkpoint on real success (mirror bm25/clustering). |
| CODEIDX-C10-C14, C18-C21 | Low | (chunk overlap byte-suffix, boundary regex Python/MD-only, file_splitter silent truncation, method heuristic Python-only, cross-lang import false edges, embed batch not isolated, BM25/Chroma divergence, Louvain over-merge, cluster staleness) | Robustness/coverage. | See per-finding notes in the subsystem review. |

**Top 3:** C1+C2 (embedding truncation) · C3 (embed raw code) · C4+C7+C17 (truth-preserving incremental graph).

---

## 4. Findings — Data acquisition & presentation (`DATA-*`) — the wrong-number engine

| ID | Sev | file:line | Problem | How it misleads | Fix |
|---|---|---|---|---|---|
| DATA-01 | **Crit** | `data_processor.py:335,424,653` | `aggregate/filter/cohort_window` build `QueryResult` **omitting `truncated=`** (defaults False). | Aggregating a 10k-capped set → total presented as full-population, `truncated` now hidden. | Propagate `truncated`; refuse in-memory sum/count over truncated input. |
| DATA-02 | **Crit** | `tool_dispatcher.py:616` | Prompt calls a capped/truncated set "the complete dataset." | LLM aggregates a sample as the whole. | Check `truncated`; never call truncated "complete." |
| DATA-03 | High | `sql_prompt.py:93-105` | **Zero** guidance on JOIN grain/fan-out, COUNT vs COUNT(DISTINCT), integer division, %-base, NULL-in-aggregate. | Classic fan-out double-count, `count/total`→0, silently NULL-skipping AVG. | Add explicit correctness rules (aggregate-before-join, `*1.0`, `NULLIF`, state the base). |
| DATA-04 | High | `response_builder.py:248-257` | Synthesis summary uses `row_count` only; `truncated` never referenced anywhere in synthesis. | Pipeline final answer states truncated totals as complete. | Inject "PARTIAL DATA" line when any stage truncated. |
| DATA-05 | High | `phone_country_service.py:285` | Digit prefix-match with no E.164 requirement; 1-char prefixes. | National-format numbers misclassified to wrong country (`"7…"`→Russia). | Require `+`/country code; else Unknown + confidence. |
| DATA-06 | High | `data_gate.py` vs `sql_agent.py:450` | DataGate hard checks run **only on the pipeline path**, not the single-query path. | 150% conversion / negative count from a one-shot query is not blocked. | Run DataGate (or fold into PostValidator) on `_handle_execute_query` too. |
| DATA-07 | High | `data_gate.py:336,371` | Numeric predicate excludes `Decimal`. | Every hard check silently skipped for currency/rate columns — where impossible values live. | Add `Decimal` to the predicate. |
| DATA-08 | Med | `data_sanity_checker.py:181` | Any `*rate*` column expected to sum to ~100. | Spurious "sums to X%" on independent ratios (conversion/bounce/win rate). | Only apply to classifier-marked share-of-total breakdowns. |
| DATA-09 | Med | `chart.py:174-187,231` | `_safe_numeric` NULL/unparseable→0; missing pivot cells→0. | "0 sales in region X" when truth is "no data". | Use null (chart gap) for missing/NULL. |
| DATA-10 | Med | `query_repair.py:15`, `validation_loop.py:452` | Repair prompt allows semantic-preserving hacks; only textual-identity guard. | "Fix" via blind DISTINCT / column-drop → runs but subtly wrong. | Forbid papering-over; diff result-shape/measure semantics. |
| DATA-11 | Med | `data_processor.py:364` | In-memory sum/avg via `float()`; avg denominator = parseable count only. | Decimal precision loss on money; avg over silently different base. | `Decimal`/`fsum`; report values-used count. |
| DATA-12 | Med | `data_gate.py:451` | Truncation inferred by round-number heuristic; ignores authoritative `qr.truncated`. | Byte-capped truncation missed; legit `LIMIT 100` false-flagged. | Check `qr.truncated` first. |
| DATA-13 | Med | `data_processor.py:484,625` | `_parse_date` drops tz; cohort window inclusive both ends. | tz-mix shifts window a day; "7-day" spans 8 calendar days. | Normalize UTC; half-open `[start, start+window)`. |
| DATA-16 | Low-Med | `answer_validator.py:57-135` | Judges only "does text address question" from answer + SQL summaries; no numbers/`truncated`. | Rubber-stamps a confidently-wrong number. | Scope honestly as completeness gate, or feed it row_count/truncated. |
| DATA-17 | Low-Med | `investigation_agent.py:187` | Diagnostics open a fresh connector (not the read-only pooled path); 15-row cap, no truncation note. | "Corrected" query reasons from a truncated sample, then stored as a learning → propagates error. | Route diagnostics through ValidationLoop/SafetyGuard; surface truncation. |
| DATA-14,15,18-22 | Low | (range-scan only on sample, reconciliation exact-round bucketing, COUNT semantics doc, duplicate/null-rate false signals, unformatted numbers, small-fan-out cartesian miss) | Robustness / presentation. | See per-finding notes. |

**Top 3:** DATA-01+02+04 (truncation→aggregation leak) · DATA-03+06 (SQL-correctness prompt + hard gate on both paths) · DATA-07+12 (DataGate Decimal + authoritative truncation).

---

## 5. Findings — Retrieval & context assembly (`RET-*`)

| ID | Sev | file:line | Problem | Fix |
|---|---|---|---|---|
| RET-R1 | High | `context_loader.py:87-133`, `projects.py:444` | `build_context_pack` (provenance/trust/budget) never called by the agent runtime — only a read-only UI route. `context_planner_enabled=False`. | Wire into orchestrator behind the flag, or delete + stop documenting. |
| RET-R2 | High | `knowledge_catalog_service.py:444` | Pack's `_rag_artifacts` uses **dense-only** ChromaDB, bypassing HybridRetriever. | Route through HybridRetriever. |
| RET-R3 | High | `knowledge_catalog_service.py:197`, `context_pack.py:76` | `token_budget` recorded but **never enforced**; no global most-relevant-first ordering. | Real greedy packing by relevance×confidence. |
| RET-R4 | Med | `hybrid_retriever.py:118` | BM25 leg returns `[]` on missing snapshot (ephemeral Heroku disk) → silent dense-only, **no signal**. | Emit `degraded` event + `bm25_snapshot_missing` metric. |
| RET-R5 | Med | `config.py:267`, `hybrid_retriever.py:184` | `chroma_max_distance=0.8` ≈ cosine sim 0.2; `hybrid_min_score=0.01` below a rank-30 contribution → almost no relevance floor. | Tighten to ~0.35-0.45 distance; validate against retrieval eval. |
| RET-R6 | Med | `config.py:475` | `reranker_enabled=False`; RRF ranks on arithmetic alone → precision@k loss. | Ship quantized cross-encoder; default on for hybrid (bounded 30 cands). |
| RET-R7 | Med | `context_loader.py:349-396` | n_results=3, 400-char mid-chunk slice, `break` on first overflow (drops later high-value chunks), no dedup. | Rank-then-pack to a token budget; boundary-aware truncation; dedup. |
| RET-R8 | Med | `context_loader.py:389` | Prompt line is `[source_path] snippet` only; provenance/trust/freshness never reach the LLM. | Render commit/indexed_at/confidence per chunk. |
| RET-R9 | Med | `schema_retriever.py:75-110` | Schema BM25 doc has **no FK/relationships**; join/bridge tables with no lexical overlap under-retrieved. | Expand retrieved set one FK hop before `max_tables`. |
| RET-R10 | Med | `sql_agent.py:1151-1177` | Safety-net = all `relevance>=2` tables appended; on small DB dominates the 15-slot budget with noise. | Relevance floor on safety-net; reserve slots for retrieved. |
| RET-R11-R17 | Low | (fusion pool shrink when caller max_results small, empty-corpus BM25 quirk, `distance=None` bypasses floor, reranker sign assumption, no cross-source conflict resolution, schema freshness not checked at query, 1024-token BM25 doc cap) | Robustness. | See per-finding notes. |

**Top 3:** R1+R2+R3+R8 (resolve the ContextPack dead-path) · R4+R5 (observe dense-only degradation + tighten floor) · R9+R10 (FK/join awareness).

---

## 6. Findings — DB schema indexing (`DBIDX-*`)

*Reframe: raw columns/types/PK/FK are re-introspected **live** at query time (300s TTL);
`DbIndex` persists only LLM text + samples + distinct values. Correctness at query time
depends on live introspection; relevance/routing depends on the persisted index.*

| ID | Sev | file:line | Problem | Fix |
|---|---|---|---|---|
| DBIDX-D1 | **Crit** | `db_index_pipeline.py:61-87,382` | Sampler emits SQL string; Mongo `execute_query` does `json.loads` → **every Mongo sample fails**. | Branch on `db_type` / use `connector.sample_data`. |
| DBIDX-D2 | **Crit** | `db_index_pipeline.py:213-234` | Same break for distinct/enum capture on Mongo → no categorical values → wrong WHERE filters. | Mongo `distinct`/`$group`. |
| DBIDX-D3 | High | `probe_service.py:112` | Same SQL-into-JSON break → Mongo data probes fail. | Dialect-aware / `sample_data`. |
| DBIDX-D4 | High | `clickhouse.py:176-224` | No PK/sorting-key extraction; `is_primary_key` never set. | Read `system.tables.sorting_key`/`primary_key`. |
| DBIDX-D5 | High | `db_index_validator.py`, `models/db_index.py` | No enum-label / CHECK-constraint capture (PG reports `USER-DEFINED`, not labels). | Read `pg_enum` + `pg_constraint contype='c'`. |
| DBIDX-D6 | High | `postgres.py:223`, `mysql.py:220` | `table_type='BASE TABLE'` → **views/matviews never indexed**; analysts querying views get no schema. | Include VIEW/MATERIALIZED VIEW. |
| DBIDX-D7 | High | `schema_retriever.py:75-110` | BM25 doc omits distinct-values + numeric-format notes; value-level questions (`status='shipped'`) don't match. | Splice distinct values + numeric notes. |
| DBIDX-D8 | Med | `sql_agent.py:1945` | Default multi-table context drops **column comments + indexes** (rendered only on on-demand detail path). | Add comment + index lines to `_format_table_context`. |
| DBIDX-D9 | Med | `db_index_pipeline.py:158-234` | No true cardinality/null-rate/min-max persisted; enum detection from ≤3 samples. | Bounded `COUNT(DISTINCT)`/`MIN`/`MAX`/null-count per candidate. |
| DBIDX-D10 | Med | `db_index_validator.py:26-100` | Misnamed — it's LLM enrichment, not a completeness validator; never checks FK targets exist / columns non-empty. | Add deterministic completeness gate. |
| DBIDX-D11 | Med | `mongodb.py:275-290` | Schema from 5 docs, top-level fields only, type = first-seen. | Larger sample, `$type` union, nested paths. |
| DBIDX-D12 | Med | `sql_agent.py:1312` | 300s schema cache with no invalidation on re-index/DDL → references dropped/renamed columns for up to 5 min. | Bust cache on `run_db_index` complete / schema-change insight. |
| DBIDX-D14 | Med | `postgres.py:354` | `reltuples=-1` (never ANALYZEd) clamped to `row_count=0` → LLM told "empty table, skip." | Treat `<0` as unknown; bounded COUNT fallback. |
| DBIDX-D13 | Med | `schema_indexer.py` | The **Mongo-aware** `SchemaIndexer` (would avoid D1/D2/D8) is dead — referenced only by its test. | Route pipeline through it, or delete. |
| DBIDX-D15-D18 | Low | (unbounded per-table LLM calls on huge schemas, unbounded columns-per-table in prompt, CH/Mongo latest-record freshness, distinct-value truncation unmarked) | Cost/robustness. | See per-finding notes. |

**Cross-dialect verdict:** Postgres ≈ MySQL (complete) ≫ ClickHouse (no sort/PK) ≫ **MongoDB (enrichment broken)**. SQL correctness is markedly worse on CH/Mongo.

**Top 3:** D1+D2+D3 (fix Mongo end-to-end) · D4+D5+D6 (enum/CHECK/CH-keys/views) · D7+D8 (retrieval + render fidelity).

---

## 7. Findings — Code↔DB sync & freshness (`SYNC-*`)

*The LLM per-table sync notes DO run in prod and ARE consumed by the SQL agent. Only the
graph-derived endpoint→table lineage (`graph_db_bridge`, M5) is dead-by-default
(`lineage_enabled=off`).*

| ID | Sev | file:line | Problem | Fix |
|---|---|---|---|---|
| SYNC-L1 | High | `core/required_filter_guard.py:15-73` | Hard guard enforces only 2 hardcoded columns (`was_handled`, `deleted_at`); every other "ALWAYS add WHERE" filter is prompt-only. | Data-driven guard from `required_filters_json`, or stop asserting mandatoriness. |
| SYNC-L2 | High | `entity_extractor.py:184-187,700` | Table refs + read/write via regex over ±100-char window → false positives (comments/CTEs/literals), wrong read/write attribution. | Prefer AST/graph usage; strip comments/literals; statement-scope window. |
| SYNC-L3 | High | `git_tracker.py:195`, `knowledge_freshness_service.py:237` | `count_commits_ahead` walks local `from_sha..HEAD`, no fetch, ahead-only → **false-fresh** when behind/diverged. | `merge-base --is-ancestor` + bidirectional; compare vs `origin/<branch>`. |
| SYNC-L4 | Med | `entity_extractor.py:1127` | Model→table blindly appends `"s"` → wrong `table_name` → entity fails to match real table (spurious code_only + db_only). | Try {name, name+"s", inflected} vs DB set first. |
| SYNC-L5 | Med | `code_db_sync_analyzer.py:20-131` | `sync_status` fully LLM-self-reported; no deterministic column set-diff. `mismatch_count` is an opinion. | Compute code∖db / db∖code set-diff from data in hand; feed as facts. |
| SYNC-L6 | Med | `code_db_sync_pipeline.py:507-523` | Code↔DB join on bare lowercased name → same-name tables in different schemas cross-contaminate context. | Match on `(schema, table)` when known. |
| SYNC-L7 | Med | `sql_agent.py:1542-1553` vs `code_db_sync_service.py:65` | Inconsistent keying: some prompt paths key on qualified name, agent asks by bare name → guidance silently not applied. | Apply bare-suffix aliasing uniformly. |
| SYNC-L8 | Med | `knowledge_freshness_service.py:199-213` | Code-graph "empty" warning fires on `code_graph_enabled` even if lineage/clustering unused → false alarm injected into every answer. | Gate on `lineage_enabled or clustering_enabled`. |
| SYNC-L9 | Med | `graph_db_bridge.py:101-234` | Read/write op-kind is verb-prefix guess; HTTP `"get" in dec` substring-matches unrelated decorators. | Word-boundary; tag name-inferred op-kind as low-confidence. |
| SYNC-L10 | Med | `pipeline_runner.py:653-676`, `config.py:487` | Endpoint→table lineage dead-by-default; but implied by "traceable answer" claims. | Enable by default if graph is built anyway, or stop implying it. |
| SYNC-L11-L14 | Low | (float-conf coercion→3, fabricated BFS `depth=`, enum substring link, single-connection/fixed-24h freshness) | Calibration/robustness. | See per-finding notes. |

**Top 3:** L1 (enforce or stop claiming mandatory filters) · L3 (ahead/behind/diverged freshness) · L2+L5 (deterministic matching + drift set-diff).

---

## 8. What's genuinely good (protect — do not regress)

- Router **fallback discipline** (every failure → safe default, robust JSON extraction).
- **Replan oscillation guard** (semantic plan fingerprint + dangling-dep pre-check) — real, not cosmetic.
- **Reconciliation guard against false self-correction** (stops "my earlier query under-counted" hallucination).
- **Empty result = truthful answer** ("zero is the truth") + repair identity guard.
- **Truncation banner on the single-query tool-loop path** is correctly worded (the gap is the *other* paths — DATA-01/02/04).
- AST layer is **honest about failure** (typed ParseErrors, counted/logged, size/binary/minified gates).
- CALLS resolution is **confidence-tiered** with stdlib blocklist + dangling-edge pruning.
- Graph **rehydrated from Postgres** before M5/M6 (avoids empty-graph trap); bm25/clustering checkpoint only on success.
- **RRF is textbook-correct** (`1/(60+rank)`, correct union/merge); per-leg 5s timeout + graceful degradation; code-aware tokenizer; atomic versioned BM25 snapshots.
- Postgres/MySQL introspection is **complete + bulk-efficient**; incremental re-index via fingerprint is correct; stale-entry purge exists; partial/failed samples honestly surfaced as `completed_partial`.
- Sync notes are **actually consumed** by the SQL agent (not dead telemetry); confidence-tiered enforcement; all-fallback overwrite guard; schema-ambiguity flagged.
- DataGate epoch-unit (s vs ms) detection; token-based (not substring) column classification.

---

## 9. Recommended remediation waves

Grouped by shared root-cause/file-set so each ships as one branch/PR (mirrors the existing
release cadence). Ordered by **severity × leverage**, wrong-number hazards first.

- **W1 — Wrong-number correctness (Critical/High).** DATA-01/02/04 (truncation→aggregation),
  DATA-03 (SQL-correctness prompt), DATA-06/07/12 (DataGate on both paths + Decimal +
  authoritative truncation), DATA-09 (chart nulls), DATA-05 (phone). Files:
  `data_processor.py`, `data_gate.py`, `sql_prompt.py`, `response_builder.py`,
  `tool_dispatcher.py`, `chart.py`, `phone_country_service.py`.
- **W2 — Embedding & retrieval (Critical/High).** CODEIDX-C1/C2/C3 (embedding truncation +
  raw-code path), RET-R1/R2/R3/R8 (ContextPack dead-path), RET-R4/R5 (degradation signal +
  floor), RET-R9 + DBIDX-D7 (FK-aware schema retrieval).
- **W3 — Path unification (High).** ORCH-A01/A02 (shared quality gates), ORCH-A03 (routing
  metrics), ORCH-T01/T02/T03 (termination), ORCH-R01 (non-DB pipeline). Precondition:
  ORCH-A04 god-file decomposition (characterization tests first).
- **W4 — DB schema completeness (Critical/High).** DBIDX-D1/D2/D3 (Mongo), D4 (CH keys),
  D5 (enum/CHECK), D6 (views), D8 (comments/indexes on default path), D13 (dead SchemaIndexer).
- **W5 — Trust signals (High/Med).** SYNC-L1 (filter enforcement), L3 (freshness
  ahead/behind/diverged), L2+L5 (deterministic matching + drift set-diff), L8 (false alarm).
- **W6 — Code-graph correctness + feature-flag decisions (Med).** CODEIDX-C4/C7/C17
  (incremental graph truth), C5/C8/C9 (coverage), F-ARCH-6 (default-on decisions with eval
  gates).

Each wave follows the repo's per-release cycle (deep study → spec locking contracts →
docs → TDD plan → subagent execution → `make check` + coverage ≥72% → deploy → post-deploy
prod check). No fix ships without a failing test first (systematic-debugging Phase 4).

---

## 10. Open / needs-validation

- **Prod runtime evidence** (authorization required): validate W1 hazards against
  `query_failures` (error_type distribution, repair-attempt histories) and `error_log`,
  and check `request_traces` for actual replan/retry/termination distributions and route
  vs complexity to quantify ORCH-T01/A03.
- **Unverified inferences to confirm with a test before fixing:** CODEIDX-C1 (exact
  `all-MiniLM-L6-v2` `max_seq_length` in the shipped chromadb), DATA-13 (cohort tz/window
  off-by-one), DATA-05 (phone national-format collisions), RET-R5 (exact cosine-distance
  semantics), CODEIDX-C4 (whether `save_incremental` re-resolves CALLS server-side).
