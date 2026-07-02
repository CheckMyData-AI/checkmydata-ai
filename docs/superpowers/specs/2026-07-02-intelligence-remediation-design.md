# Intelligence & Data-Correctness Remediation — Master Design (roadmap spec)

**Date:** 2026-07-02 · **Source of findings:** `docs/INTELLIGENCE_AUDIT_2026-07.md` (6-lens
code+prod audit; ~120 findings; prod-validated on 195 `request_traces`).

**Purpose.** Sequence and lock contracts for remediating the *intelligence/data-correctness*
defects (not the already-closed security/reliability track). One master spec (this file) +
`writing-plans` will produce detailed TDD plans for **W0 + W1…W6**. Crit/High/Med findings →
individual TDD tasks; Low findings → per-wave grouped cleanup batch.

**Structure decision (approved):** master roadmap + full plans for all six waves. To keep late
waves from going stale, **all cross-cutting contracts are locked here first** and a sequential
**Wave 0 (Foundations)** implements them before parallel waves consume them.

**Feature-flag posture (approved):** *flip-after-fix under eval gate* — each flag flips to
default-ON only after its correctness fix lands and the retrieval-eval/benchmark passes
(`reranker_enabled`, `context_planner_enabled` at end of W2; `code_graph_enabled`,
`lineage_enabled` at end of W6). No flag flips before its fix.

---

## 1. Verified external facts (Context7, 2026-07-02) — grounding the contracts

- **ChromaDB** default embedding function = `DefaultEmbeddingFunction` → ONNX `all-MiniLM-L6-v2`
  (**256-token** window; longer input truncated). Custom EF is set via
  `create_collection(embedding_function=ef)` and auto-resolved on `get_collection`. **Changing
  the EF/model requires re-embedding** (clone/reindex the collection). → validates `CODEIDX-C1`;
  constrains the W2 fix to include a reindex/migration.
- **sentence-transformers** exposes `model.max_seq_length` (reads tokenizer, falls back to
  `max_position_embeddings`). 512-token embedding models exist (`BAAI/bge-base-en-v1.5`,
  `intfloat/e5-base-v2`). `CrossEncoder("cross-encoder/ms-marco-MiniLM-L6-v2").rank(query, docs)`
  returns sorted `{corpus_id, score}` (use `.rank()` — fixes the manual-sort/sign assumption
  `RET-R14`). `.predict(pairs)` for raw scores.
- **GitPython** `repo.is_ancestor(ancestor_rev, rev) -> bool` and `repo.merge_base(a, b) -> [Commit]`
  are available → `SYNC-L3` ahead/behind/diverged is implementable precisely; `iter_commits("a..b")`
  counts one direction.

---

## 2. Locked shared contracts (Wave 0 builds these; later waves consume them)

> These are the frozen interfaces. Implementers must not redefine them; changes require a spec
> amendment. Signatures are Python 3.12 + SQLAlchemy 2.0 async.

### C-A — `truncated` propagation
- `QueryResult.truncated: bool` is authoritative. New helper in `app/connectors/base.py`:
  ```python
  def derive_result(base: QueryResult, rows: list[tuple], *,
                    extra_truncation: bool = False, columns: list[str] | None = None,
                    **overrides) -> QueryResult:
      """Carry-forward constructor: truncated = base.truncated or extra_truncation."""
  ```
- **All** derived results use it: `data_processor.aggregate_data/filter_data/cohort_window`,
  the two enrichment paths, any future transform.
- Consumers must read `.truncated`: `response_builder.build_synthesis_messages` and every summary
  path inject a `PARTIAL DATA: query capped at N rows — totals are incomplete` line when true.

### C-B/C-C — unified post-result validation (`app/agents/result_validation.py`, NEW)
Removes the F-ARCH-3 divergence by giving both execution paths one gate. Authoritative signatures
(as locked by W0 against the real collaborators — `AgentResultValidator` + the free function
`sql_results_reconcile`; the names `SqlResultGate`/`SqlResultReconciliation` do **not** exist):
```python
@dataclass
class ResultDirective:
    action: Literal["accept", "warn", "requery", "block"]
    reason: str
    hints: list[str] = field(default_factory=list)   # e.g. repair guidance

class ResultValidation:
    def __init__(self, data_gate: DataGate, result_gate: AgentResultValidator, *,
                 reconcile: Callable[[Sequence[Any]], bool] = sql_results_reconcile) -> None: ...
    def evaluate(self, qr: QueryResult, *, question: str, sql: str,
                 truncated: bool | None = None) -> ResultDirective: ...   # SYNC — no AgentContext
```
- `evaluate` is **synchronous** (DataGate + `AgentResultValidator` are sync) and reads only the
  result — no `AgentContext`; pass `truncated=` to override `qr.truncated`, never a context object.
- Composes: `DataGate` hard-checks (**Decimal-aware**, **`qr.truncated`-aware** — closes
  `DATA-07/DATA-12`), the `AgentResultValidator` result-quality gate, zero-rows re-query +
  `sql_results_reconcile` reconciliation.
- Invoked by **both** the flat loop (`orchestrator._run_tool_loop` post-dispatch) and the pipeline
  (`stage_executor._run_sql_stage`) — closes `ORCH-A01`, `DATA-06`.
- `AnswerQualityGate` (thin wrapper over `AnswerValidator`) likewise invoked by both flat-loop and
  `response_builder.build_pipeline_response` — closes `ORCH-A02`. It takes the validator directly
  and returns a `ResultDirective` (not an `AnswerValidationResult`):
```python
class AnswerQualityGate:
    def __init__(self, validator: AnswerValidator) -> None: ...
    async def evaluate(self, *, question: str, answer: str, sql_summaries=None,
                       preferred_provider=None, model=None) -> ResultDirective: ...   # ASYNC
```

### C-D — schema-capture surface
- Extend models (`app/models/db_index.py`) + `SchemaInfo`/`ColumnInfo` (`app/connectors/base.py`):
  ```python
  # ColumnInfo (add):
  enum_labels: list[str] | None = None      # authoritative enum domain
  check_constraints: list[str] = field(default_factory=list)
  is_sort_key: bool = False                  # ClickHouse ORDER BY / PK
  distinct_values: list[str] | None = None
  distinct_count: int | None = None
  null_rate: float | None = None
  numeric_format: str | None = None
  # SchemaInfo (add):
  object_kind: Literal["table", "view", "matview"] = "table"
  ```
- **Dialect-aware capture contract:** the db-index pipeline, distinct builder, and ProbeService
  MUST route through connector methods, never a raw SQL string for non-SQL dialects:
  ```python
  async def sample_data(self, table: str, limit: int) -> QueryResult: ...
  async def distinct_values(self, table: str, column: str, limit: int) -> list[str]: ...
  async def approx_stats(self, table: str, column: str) -> ColumnStats: ...  # distinct_count/null_rate/min/max
  ```
  Mongo overrides these with native `find`/`distinct`/`$group` — closes `DBIDX-D1/D2/D3`.
- Alembic migration adds the new `DbIndex`/`db_index` JSON columns; back-compat default = empty.

### C-E — retrieval & embedding
- Config (`app/config.py`): `chroma_embedding_model` (default → a 512-ctx model, e.g.
  `BAAI/bge-base-en-v1.5`), `embedder_max_tokens` (default = model window). Changing the model
  triggers a full re-embed (reindex path); a startup check warns on chunk/window mismatch.
- Chunking sizes to the **real tokenizer window**, not `chars/4`:
  ```python
  def chunk_document(text: str, *, max_tokens: int, tokenizer) -> list[Chunk]: ...
  ```
- **Raw-code embedding path** (new): symbol-level chunks from AST spans with metadata
  `{path, symbol, language, start_line, end_line, kind}` (closes `CODEIDX-C3`).
- **ContextPack → runtime** behind `context_planner_enabled`: orchestrator calls
  `build_context_pack(...)`; its `rag_chunks` go through `HybridRetriever` (not dense-only —
  closes `RET-R2`); packing enforces `token_budget` by greedy fill on `relevance × confidence`
  (closes `RET-R3`); the rendered prompt block includes provenance per artifact
  `[{source} @ {commit_sha} · {indexed_at} · conf={confidence}]` (closes `RET-R8`).
- **Degradation signal:** when a retrieval leg returns 0 while the other has hits, emit
  `WorkflowTracker` event `retrieval_degraded{leg, reason}` + metric `retrieval_degraded_total`
  (closes `RET-R4`).
- **Reranker** uses `CrossEncoder.rank(query, docs)` (sorted result; no sign assumption).

### C-F — freshness + required-filter guard
- `app/knowledge/git_tracker.py`:
  ```python
  class GitFreshness(Enum): FRESH="fresh"; AHEAD="ahead"; BEHIND="behind"; DIVERGED="diverged"
  def classify_freshness(repo, indexed_sha: str, branch: str) -> tuple[GitFreshness, int, int]:
      # uses repo.is_ancestor + merge_base + iter_commits count → (state, ahead, behind)
  ```
  Optional `git fetch`/compare vs `origin/<branch>` behind a flag. Closes `SYNC-L3`.
- `app/core/required_filter_guard.py` becomes **data-driven** from `required_filters_json`
  (parse `col = val` / `col IS NULL`), replacing the 2-key hardcode. **Satisfiability rule:** if a
  required filter cannot be satisfied by the generated SQL after `k` attempts, **DEGRADE to a
  warning surfaced to the user — never hard-fail the answer.** Closes `SYNC-L1` (prod incident:
  a legitimate revenue query was blocked to death). Guard emits metric `filter_guard_degrade_total`.
- **Deterministic drift:** `code_db_sync` computes `code_cols ∖ db_cols` and `db_cols ∖ code_cols`
  set-diff (both sets already in memory) → factual `mismatch` list, not LLM self-report. Closes `SYNC-L5`.

### C-G — observability
- `RequestTrace` (+ `MetricsCollector`) gains `route`, `complexity`, `estimated_queries`, written
  from `route_result` (closes `ORCH-A03`). Alembic migration for the 3 columns.
- Termination: `max_orchestrator_iterations` → realistic default (**20**); wrap-up gated on
  `iteration > 0 AND ≥1 successful data-retrieval` (closes `ORCH-T01/T02`); a no-tool-call turn with
  zero data on a data route re-prompts once (closes `ORCH-T03`).
- New metrics: `retrieval_degraded_total`, `datagate_block_total`, `filter_guard_degrade_total`.

---

## 3. Wave map (findings → wave). IDs per `docs/INTELLIGENCE_AUDIT_2026-07.md`.

### W0 — Foundations (sequential, first; unblocks all)
Implements C-A, C-B/C-C skeleton + wiring points, C-D model + migration + connector method
signatures, C-E embedding metadata + degradation event scaffold, C-G trace/metric columns +
migration. **Decomposition** of hotspot files so parallel waves don't collide: extract from
`sql_agent.py` (2052 LOC) a `schema_context_builder` and a `result_handler`; extract the touched
phases of `orchestrator.py` (`_run_tool_loop`) into named helpers (partial `ORCH-A04`). Plumbing +
contract tests only; no behavior change. **Also lands here:** verify the 5 "needs-validation"
inferences (audit §10) with a failing test each before their fix wave runs.

### W1 — Wrong-number correctness (Crit/High + prod #1)
`DATA-01/02/04` (truncated propagation via C-A), `DATA-03` (SQL-prompt correctness rules),
`DATA-06/07/12` (DataGate via C-B/C-C), `DATA-09` (chart null≠0), `DATA-05` (phone E.164),
**`SYNC-L1`** (required-filter guard satisfiable/data-driven via C-F — elevated to Critical).
Low batch: `DATA-14/15/18/19/20/21/22`. Owns: `data_processor.py`, `data_gate.py`, `chart.py`,
`phone_country_service.py`, `sql_prompt.py`, `required_filter_guard.py`, `answer_validator.py`
(DATA-16 scope), `investigation_agent.py` (DATA-17).

### W2 — Embedding & retrieval (Crit/High)
`CODEIDX-C1/C2` (chunk↔window + tokenizer), `CODEIDX-C3` (raw-code embedding path via C-E),
`RET-R1/R2/R3/R8` (ContextPack runtime), `RET-R4/R5` (degradation + relevance floor),
`RET-R9/R10` + `DBIDX-D7` (FK-aware schema retrieval — **depends on W4 capture**). End of wave:
flip `reranker_enabled` + `context_planner_enabled` under retrieval-eval gate. Low batch:
`RET-R11..R17`, `CODEIDX-C10..C14,C18-C21`. Owns: `chunker.py`, `vector_store.py`,
`hybrid_retriever.py`, `reranker.py`, `context_loader.py`, `context_pack.py`,
`knowledge_catalog_service.py`, `context_planner.py`, `schema_retriever.py` (shared w/ W4 — sequence).

### W3 — Orchestrator (High; prod-hot: 24% fail, step-limit, token-bloat)
`ORCH-T01/T02/T03` (termination via C-G), `ORCH-A03` (routing metrics via C-G), token-bloat
`ORCH-PR01/CP01/CP02`, `ORCH-R01` (non-DB pipeline), then `ORCH-A01/A02` (unify gates via C-B/C-C).
Precondition: W0 helper extraction. Low batch: `ORCH-A05/V01/V02/PR03/PR04/CP02`. Owns:
`orchestrator.py`, `router.py`, `adaptive_planner.py`, `stage_executor.py`, `query_planner.py`,
prompt builders, `response_builder.py` (pipeline-answer gate).

### W4 — DB schema completeness (Crit/High)
`DBIDX-D1/D2/D3` (Mongo via C-D methods), `D4` (CH sort/PK), `D5` (enum/CHECK), `D6` (views),
`D8` (comments+indexes on default context path), `D9` (stats), `D10` (completeness validator),
`D11` (Mongo infer), `D12` (schema-cache bust), `D13` (dead SchemaIndexer resolve), `D14`
(reltuples<0). Low batch: `D15/D16/D17/D18`. Owns: `connectors/*.py`, `db_index_pipeline.py`,
`schema_indexer.py`, `db_index_validator.py`, `probe_service.py`, `db_index_service.py`,
`sql_agent.py` render (via W0-extracted `schema_context_builder`).

### W5 — Trust signals (High/Med)
`SYNC-L2` (deterministic matching), `L3` (freshness via C-F), `L5` (drift set-diff via C-F),
`L6/L7` (schema-qualified keying), `L8` (false-alarm gate), `L9` (op-kind word-boundary). Low batch:
`L11/L12/L13/L14`. Owns: `code_db_sync_pipeline.py`, `code_db_sync_analyzer.py`, `graph_db_bridge.py`,
`git_tracker.py`, `knowledge_freshness_service.py`, `entity_extractor.py` (sync-relevant regions —
sequence w/ W6).

### W6 — Code-graph correctness + flag flips (Med)
`CODEIDX-C4/C7/C17` (incremental-graph truth + checkpoint gating), `C5/C6/C8/C9` (coverage),
`C15/C16` (enum/table-name heuristics). End of wave: flip `code_graph_enabled` + `lineage_enabled`
under a graph-quality benchmark. Owns: `ast_parser.py`, `code_graph.py`, `code_graph_service.py`,
`entity_extractor.py` (extraction regions), `pipeline_runner.py` (graph stages), `code_clustering.py`.

---

## 4. Dependency graph & parallel groups

```
W0 (sequential, first)
 ├─ Group G1 (parallel): W1 · W4
 ├─ Group G2 (parallel, after W4): W2 (RET-R9/DBIDX-D7 need W4 capture) · W6
 └─ Group G3 (parallel, after W0): W3 · W5
```
Hard edges: **everything → W0**; **W2.R9/DBIDX-D7 → W4** (retrieval doc needs captured
distinct-values/FK); **W1.DATA-06 → W0.ResultValidation**; **W3.A01/A02 → W0.ResultValidation**.
G1 and G3 may run concurrently (disjoint files after W0). Exact per-task file ownership is produced
by `writing-plans`.

## 5. File-ownership conflicts (resolved by W0 extraction + sequencing)
- `sql_agent.py`: split in W0 → `schema_context_builder` (W4) + `result_handler` (W1) + core (W3
  wiring only). No two waves edit the same extracted module.
- `orchestrator.py`: W3 only (after W0 helper extraction).
- `schema_retriever.py`: W4 lands capture → W2 consumes (sequence, not parallel).
- `entity_extractor.py`: W5 (usage/table-ref regex regions) vs W6 (symbol/enum extraction regions)
  — different functions; `writing-plans` assigns per-function ownership, else sequence.

## Cross-wave ownership & migrations
- **`orchestrator.py` is W3-owned.** W2's ContextPack runtime wiring (`RET-R1`) must NOT edit
  `orchestrator.py` in parallel with W3. It enters through a `ContextLoader.assemble_knowledge_block`
  seam (W2-owned file) and is **sequenced after / coordinated with W3**, never concurrent — the
  orchestrator only ever calls that seam.
- **`context_planner.py` is split by concern:** W3 owns the `CP01` cue-precision fix (word-boundary
  matching); W2 owns `CP02` runtime invocation (hot-path pruning behind `context_planner_enabled`).
  Land W3's precision fix before W2 touches invocation, or coordinate — no concurrent edits.
- **All C-D `DbIndex` columns are W0-owned — including `column_stats_json`.** W0 ships every new
  `DbIndex`/`db_index` JSON column (back-compat empty defaults) in its migration; **W4 only
  populates** them at capture time and ships **no migration** for those columns.
- **Alembic single-head discipline.** W0 ships **two** migrations and W5 ships **one**. Migrations
  are created **sequentially at execution time**: each re-checks the current head (`alembic heads`)
  before `--autogenerate` and sets its `down_revision` to that head, so the chain stays
  single-headed. Current head at planning time: **`760604aa1803`**.

## 6. Definition of Done (per task and per wave)
- Per task: TDD (failing test → minimal fix → green), conventional commit, docs updated in the same
  change (CLAUDE.md, `API.md`, feature flags, `.env.example` where touched).
- Per wave "done": `make check` (ruff format+check, mypy, unit+integration, coverage **≥72%**) +
  retrieval-eval gate (`test_retrieval_eval.py` + `test_reranker.py`) + frontend `tsc`/eslint/vitest
  where FE touched; flag flips gated on their eval/benchmark.
- Error/degradation: honest degradation, no silent swallow; structured logs without secret leakage.

## 7. Handoff
Isolated git worktree per group (`superpowers:using-git-worktrees`), then
`superpowers:subagent-driven-development` executing parallel groups with non-overlapping file
ownership and sequential glue tasks between groups. Two-stage review per task (spec compliance,
then code quality).

## 8. Risks / needs-validation (confirm-with-test in W0 before the owning wave)
- `CODEIDX-C1` embedder window (confirmed 256 via Context7; assert `max_seq_length` on the shipped
  chromadb ONNX model in a test).
- `DATA-13` cohort tz/window off-by-one; `DATA-05` phone national-format collisions;
  `RET-R5` exact cosine-distance→similarity; `CODEIDX-C4` whether `save_incremental` re-resolves
  CALLS server-side. Each gets a failing characterization test in W0.
- Changing the embedding model (C-E) forces a prod reindex — schedule + document the reindex/migration.
- Prod evidence is 1 day post-v190 (n=195); re-pull before/after each wave to measure impact
  (failure rate, step_limit_reached, avg tokens/duration, filter_guard_degrade).
