# ADR-0005 — Goal #1: a grounded chat over an indexed project, and the Request Kernel that carries it

**Status:** accepted 2026-09-14 · **Owner:** product owner · **Supersedes nothing;
constrains everything in `ROADMAP.md` → Current Priorities until it is met.**
**Inputs:** `docs/audits/2026-09-13-connections-sync-orchestrator-audit.md` (60 findings, 14
projects), `vision.md` §7–§8, the `agent-orchestrator` doctrine (work as a graph, checker
before convergence, one budget, typed results, a durable trace under the feed).

---

## 1. The goal, fixed

> **A user connects one database and one repository. The product indexes both. In chat —
> the web interface and MCP alike — the agent answers questions about that data
> correctly, shows tables and charts, and never invents a number: every figure in an
> answer was produced by code that ran (SQL first, then a compute script over the
> results), and the model only narrates what the code produced.**

Everything else — GA4, App Store, Google Play, new engines, dashboards — is **after** this.
Not because it is unimportant, but because a product that answers wrongly about the one
source it has does not get to add a second.

### 1.1 Definition of done (measurable, all seven)

| # | Criterion | How it is measured |
|---|---|---|
| D1 | **Correctness ≥ 90%** on a golden set of ≥ 40 questions against the real `esim-php` database + repository, answers verified by the owner | eval harness (§5, wave 1) run in CI on recorded fixtures and nightly against production |
| D2 | **Zero fabricated numbers**: every numeric token in the narrated answer resolves to a cell or an aggregate of an artefact the run produced | the Numbers Gate (§3.4) rejects otherwise; the eval counts rejections and leaks |
| D3 | **Failure rate < 5%** of real requests; every failure carries `route`, `failure_kind` and a one-line cause the user can read | `request_traces` over 30 days; the audit's O-03/O-04 tests |
| D4 | **p95 latency ≤ 60 s, hard ceiling 180 s** honoured by every component, including the LLM router and every sub-agent | `total_duration_ms` (after PRJ-01 fixes it) |
| D5 | **Tables and charts** for every tabular answer, built from artefacts, never from numbers the model typed | viz node consumes artefact ids only |
| D6 | **Identical behaviour over MCP and web**: `checkmydata_query_database` returns the same artefacts, narration and caveats the web chat shows | one `run_request()` behind both; a parity test |
| D7 | **The index is alive**: repo re-index, DB index and code↔DB sync complete nightly without false failures, so the context the chat reads is at most a day old | 14 days of `indexing_runs` with zero false reaps; `KnowledgeFreshnessService` shows `fresh` |

Today, measured 2026-09-13: D1 unknown (no golden set), D2 unenforced, D3 = 35% failing,
D4 = 358 s max, D5 partial (Path A only), D6 false (MCP returns text), D7 false (sync
broken since 09-10, full rebuild broken since 09-11).

---

## 2. How the system is built today, and why it fails

The chat is three layers, each sound in isolation and each leaking at its boundary.

**Knowledge layer** — repo index (AST → code graph → generated docs → embeddings + BM25),
DB index (schema + samples + statistics), code↔DB map, learnings, insights. This is the
"database that knows the product": which tables the code writes, what `status=3` means,
which filters a query needs. It is the product's real asset and it is currently **stale
by construction**: the sync that produces the map has failed on every run since 09-10 and
any full rebuild dies in `generate_docs` (audit P0-A/B). The chat is answering from a
map four days old that the UI says is current.

**Reasoning layer** — `OrchestratorAgent` (3721 lines): one router LLM call, then either a
20-iteration tool loop (Path A) or a planned DAG of stages (Path B), or a third copy of the
tail for resume. Sub-agents (SQL, knowledge, git, MCP, analytics, viz) return
loosely-typed results consumed by `getattr`. Gates (ResultValidation, DataGate,
StageValidator, AnswerQualityGate, reconciliation) exist and are applied in **ten
different combinations** depending on the path. Numbers travel from a `QueryResult`
into the LLM's context as pipe-joined text, and the *model* writes the final figures.

**Transport layer** — REST, SSE, WS, MCP, each with its own timeout, its own finalisation,
its own cancellation story; a process-level singleton holds per-request state in eight
dicts swept by age.

Four mechanisms explain the 35% failure rate and the 358 s runs, and they are the same
four the audit named across all subsystems:

1. **The budget is advisory.** `agent_wall_clock_timeout_seconds=180` is checked at
   iteration boundaries; the LLM router has no deadline parameter (3 × 120 s + backoff =
   366 s for one call); Path B hands the SQL agent no deadline; four sub-agents accept
   none. A request is as long as its slowest unbounded call.
2. **State crosses boundaries by convention.** `replace(context, extra=…)` silently drops
   every write a sub-agent makes (`exposed_learning_ids` never reach the response);
   `TraceMeta` is not on the terminal event, so a killed run records nothing; the
   trace-buffer sweep at 300 s records live requests as failed.
3. **Truth is computed from the input.** A default route is stored as a decision; a
   reaped-then-completed run stays failed; a run's duration is the last query's time.
4. **Numbers are prose.** Rows are flattened into the prompt; the model reads, reasons and
   *types* the answer's figures. There is no mechanism that ties a number in the answer to
   a cell in a result. This is the hallucination surface, and no gate today closes it —
   `AnswerQualityGate` asks a second model whether the first looked grounded.

The reasoning layer is also over-built for the question it is asked most: 23 real requests
in 30 days, 10 of them `query/simple`. The complexity is not serving the load; it is
generating the failures.

---

## 3. Target architecture — the Request Kernel

One paragraph: **every request, from any transport, becomes a `RequestRun` that owns one
budget and one record; a `GraphExecutor` runs typed nodes whose data-bearing outputs are
`Artifacts` — tables with provenance; a `compute` node lets the model write SQL *over
artefacts* in an in-request DuckDB sandbox instead of doing arithmetic in prose; a declared
`GatePipeline` — ending in a deterministic Numbers Gate — runs at every terminal on every
path; and the answer node narrates artefacts it must cite, while viz and MCP consume the
artefacts directly.** The agent-orchestrator doctrine supplies the shape: work as a
graph, a checker before every convergence, sub-agents that return distilled typed
results, a durable trace under the feed.

```
transport (REST | SSE | WS | MCP)
   └─ run_request(question, principal, project, connection) ─► RequestRun
         ├─ Budget      one monotonic deadline, step/token/$ counters — passed to EVERY node and into LLMRouter.complete(deadline=)
         ├─ RunRecord   route, plan, artefacts, gate verdicts, failure_kind — written on the terminal event, not after it
         └─ GraphExecutor
               ├─ plan node      (router+planner: one call → static layered plan, or "incremental" for simple)
               ├─ data nodes     query_database → Artifact(table, sql, connection, executed_at, truncated)
               │                 search_codebase / analyze_git / query_mcp → Artifact(text|table, sources)
               ├─ compute node   compute_sql(artefact_ids, sql) → Artifact   [DuckDB, read-only, mem+time capped]
               ├─ checker node   per layer: usable / not usable (ResultValidation + DataGate)
               ├─ viz node       chart(artefact_id, spec) → Artifact(chart)
               ├─ answer node    narrate(artefacts) — cites artefact ids, forbidden from arithmetic
               └─ GatePipeline   [ResultValidation, DataGate, NumbersGate, AnswerQualityGate, TruncationCaveat, Reconcile, Localize]
                                 applied at every terminal: normal, budget-exhausted, error, checkpoint
```

### 3.1 `RequestRun`, `Budget`, `RunRecord`

- `Budget` is created **before routing** so the router, history summariser and retrieval
  count. Every node receives it; `LLMRouter.complete(..., deadline=)` clamps each attempt's
  HTTP timeout to `min(adapter_timeout, remaining)` and refuses to start an attempt with
  less than a floor left; total attempts across providers are capped, not per provider.
- A recoverable provider error **refunds** its step (doctrine §2); a misconfiguration
  does not spend the runaway guard.
- `RunRecord` replaces the eight `_wf_*` dicts and the age sweep. It travels on the
  `pipeline_end` event so the trace flush writes it; `workflow_id` becomes UNIQUE.
- Cancellation is real: transport timeout or client disconnect cancels the task; no node
  swallows `CancelledError`.

### 3.2 `Artifact` — the currency

```python
@dataclass(frozen=True)
class Artifact:
    id: str                      # "a1", "a2" — what the model cites
    kind: Literal["table", "text", "chart"]
    table: QueryResult | None    # columns, rows (capped), row_count, truncated
    provenance: Provenance       # sql | compute_sql | search | git — plus connection_id, executed_at, source artefact ids
    caveats: tuple[str, ...]     # truncated, partial, stale, estimated
```

`QueryResult` already is this minus the id and provenance (audit: the most connected node
in the repository, named in no document until 09-03). Every data-bearing tool returns an
`Artifact`; `search_codebase`, `analyze_git` and `query_mcp_source` populate `table`
where they have rows, so downstream nodes can compute on them (today they return prose
nothing can consume). Artefacts are **per request**, capped at `CHAT_RAW_RESULT_ROW_CAP`
rows, stored in the message metadata exactly as the bounded trace `vision.md` §8 already
permits — **not a warehouse, not queryable across requests** (§4, decision 3).

### 3.3 `compute` — script-first, in-request, sandboxed

The model must not do arithmetic in prose. It gets one tool for derived numbers:

```
compute_sql(inputs: [artefact_id], sql: str) -> Artifact
```

Inputs are loaded as read-only DuckDB tables named by artefact id (`a1`, `a2`); the SQL
is checked by the same `SafetyGuard` in read-only mode; DuckDB runs with
`memory_limit` (default 256 MB), `threads=1`, a statement timeout from the `Budget`, no
filesystem or extension access (`enable_external_access=false`). Joins, pivots,
percentages, period-over-period, cohort maths, rankings — the whole `process_data` enum
and everything it cannot express — become one closed-form tool the model already knows how
to use. Determinism is the point: the same inputs and SQL give the same artefact, and the
SQL is stored as provenance so the answer is reproducible.

Why SQL-over-artefacts and not Python: Python needs a process sandbox (subprocess,
seccomp or a remote executor), a dependency surface, and a second language for the
guard; DuckDB is one wheel, in-process, and the guard already exists. Python comes later
(§6) only if the golden set produces questions SQL cannot answer.

### 3.4 The Numbers Gate — deterministic, not a second model

After the answer node narrates, a pure function extracts every numeric token from the
text (with locale-aware formatting, percentages, currency, rounding) and resolves each to:
a cell of a cited artefact; an aggregate (`sum`, `count`, `avg`, `min`, `max`, `distinct`)
of a column of a cited artefact; or a value the compute node produced. A token that
resolves to nothing fails the gate. On failure the node is asked **once** to rewrite
citing artefacts; if it fails again, the sentence is dropped and the artefact table is
shown in its place with a caveat. The gate cannot be argued with — it is `assert`, not
opinion — and its verdicts are stored per request so the eval can count them (doctrine:
a checker that has never rejected anything is a finding).

`AnswerQualityGate` (the LLM judge) stays, **after** the Numbers Gate, for what a regex
cannot judge: did the answer address the question, did it disclose truncation.

### 3.5 The database that knows the product

The context the plan node and the SQL agent read is a `ContextPack`, and it already exists.
Two changes make it "aware of how the product is used":

- **Verified-query memory, per connection** (vision §7 #4): every answer that passed the
  gates and received no negative feedback — or received a thumbs-up — stores
  `(question, sql, artefact schema, connection_id)` as a retrievable exemplar. The SQL
  agent gets the top-k exemplars for the current question as few-shot. This is the
  learning loop the audit found dead (`exposed_learning_ids` never reaching the response)
  rebuilt on the artefact record, and written from a **contrast** where one exists (a
  failed attempt beside the one that worked — doctrine §8), never from a lone success.
- **Usage signals from the index**: the code↔DB map's `read_count`/`write_count`,
  required filters and column value mappings already say how the code uses each table;
  they are injected today but only when the map is fresh — which D7 makes true.

### 3.6 Gates as a declared pipeline

One list, applied by the executor at every terminal on every path:
`[ResultValidation, DataGate, NumbersGate, AnswerQualityGate, TruncationCaveat,
ReconcileAndScrub, Localize]`. Path A, Path B and resume cannot drift because they no
longer own tails: the executor owns the one tail. Each gate returns a typed verdict
stored on the `RunRecord`.

### 3.7 One `run_request()` behind four transports

REST, SSE, WS and MCP call the same function and differ only in how they relay events and
deliver the result. MCP's `checkmydata_query_database` returns `{narration, artefacts[],
caveats[], record_id}` — the artefacts as structured tables, which is what an MCP client
(Claude, Cursor, a script) actually wants, and which today it does not get. The web client
renders the same payload. One parity test asserts identical artefacts for the same
question through both.

### 3.8 Below the kernel: the index must be alive

D7 is a precondition, not a wish: the kernel reads the map. Audit PRJ-01 (the two P0s),
PRJ-02 (one heartbeat writer, unconditioned) and PRJ-14 (runtime-true guards) are the
first three days of this plan for that reason.

---

## 4. Decisions (and the alternatives refused)

1. **Script-first means SQL-over-artefacts in DuckDB, in the request, capped.** Refused:
   Python sandbox now (cost, second guard, second language); running compute on the
   worker (adds a queue hop to a 60 s budget); letting the model do arithmetic with a
   judge afterwards (the current state — a judge cannot see a wrong sum).
2. **Numbers are gated deterministically, then judged.** Refused: judge-only (today);
   forbidding numbers in prose entirely (users read sentences, not only tables).
3. **Artefacts are per-request and bounded; nothing here is a warehouse.** `vision.md` §8
   forbids a queryable copy of the customer's data; artefacts live in the message
   metadata under `CHAT_RAW_RESULT_ROW_CAP` exactly as the bounded trace already does, and
   `compute_sql` reads only the current request's artefacts. Refused: a session-level or
   project-level artefact store (convenient, and precisely the thing §8 says we are not).
4. **One executor, two plan shapes.** Refused: keeping Path A and Path B as separate
   executors with "parity tests" — ten divergences in 30 days say parity does not hold
   by testing.
5. **Deadline is a parameter, not a check.** Refused: more iteration-boundary checks.
6. **The strongest model goes to the plan node**, the cheap one to narration (doctrine
   §6: the planner is the bottleneck). Refused: one model for everything.
7. **Freeze**: no new sources, no new agents, no new connectors until D1–D7 are green.
   `orchestrator_auto_investigate_enabled` and `session_rotation_enabled` are turned off
   in production for the duration (both spend the owner's concurrency and the request's
   budget on work the golden set does not measure) and recorded in `DELIBERATE`.
8. **Sequence over parallelism where they share `chat.py`**: waves 1 and 2 touch the same
   files; they are ordered, not concurrent. The index track (PRJ-02/06/07) runs beside
   them because it shares nothing.

---

## 5. The plan — waves, fastest path

Effort is engineer-days; each wave is one `/task-pipeline` run or a small set of them; each
ends with a measured gate, not a merged PR.

### Wave 0 — make the index true again (days 1–3)

Audit **PRJ-01** (hotfix: `store_sync` dict→str, pgvector `%%`, `exposed_learning_ids`,
`total_duration_ms`), **PRJ-14** (runtime-true guard tests), **PRJ-02** (one `RunBeat`).
**Gate:** a hand-enqueued full rebuild of `esim-php` reaches `pipeline_end`; the next
`code_db_sync` completes; 3 nights with zero false reaps. **Ops by the engineer:** enqueue
the rebuild, watch it, record the numbers in the PR. Do not merge anything else to `main`
while it runs.

### Wave 1 — a chat that fails honestly and within budget (days 4–12)

Audit **PRJ-03** (`Budget` threaded to every node and into the router; cancellation;
`RequestState` replacing `_wf_*`) and **PRJ-04** (`RunRecord` on the terminal event,
UNIQUE `workflow_id`, WS finalisation, stale buffer above the ceiling, `failure_kind`
everywhere). Plus O-10 (SSE latches onto its own workflow id) and decision 7 (freeze
flags). **Golden set v1**: the owner writes 40 questions against `esim-php` with verified
answers; the harness records LLM fixtures for replay. **Gate:** D3 and D4 measured on the
golden set: failure < 5%, p95 ≤ 60 s, max ≤ 180 s, every failure explains itself.

### Wave 2 — script-first and the Numbers Gate (days 13–25)

`Artifact` + `Provenance`; every data tool returns one; `compute_sql` on DuckDB replacing
`process_data`; the answer node cites artefacts; **Numbers Gate**; viz consumes artefact
ids; `finish` tail extracted from `_run_tool_loop` and reused by Path B and resume (audit
PRJ-05 phases 1–3). MCP `checkmydata_query_database` returns artefacts (D6). **Gate:** D2
on the golden set — zero unresolved numeric tokens leaking past the gate; D5 — a chart or
table on every tabular answer; D6 parity test green.

### Wave 3 — one executor, verified-query memory, the eval as the release gate (days 26–40)

`GraphExecutor` with layered execution and a checker per layer; `ToolRegistry` as the
single source of truth; delete `_execute_resume` as a separate tail (PRJ-05 phases 4–5);
verified-query memory per connection (§3.5); the eval harness (audit PRJ-13) in CI on
fixtures and nightly on production traces, gating on D1/D2/D3 regressions. **Gate:** D1 ≥
90% on golden set v2 (≥ 60 questions, including compute-heavy ones); `orchestrator.py`
< 800 lines; the parity test enumerates gates from the registry.

### After Goal #1 (not before)

PRJ-06/07 (pipeline DAG, scheduling) can run beside waves 1–3 on the index track since
they share no files. PRJ-08/09 (connections), PRJ-10/11/12 (GA4, App Store, Google Play)
start only when D1–D7 are green. A Python compute node is considered only if golden set
v2 contains questions `compute_sql` cannot answer.

**Total to Goal #1:** ~40 engineer-days on the chat track, ~10 on the index track in
parallel. The first three days remove every production-visible failure in the audit.

---

## 6. What this ADR does not decide

- Which model serves the plan node versus narration (a `DEFAULT_LLM_MODEL`-style knob per
  node role; the eval decides the values).
- Whether artefacts are ever shareable between messages of one session (§8 says no today;
  revisit only with a written carve-out like ADR-0001's).
- The Python sandbox design.
- Anything about sources beyond the one database and one repository.

---

## 7. Where this is recorded

- `ROADMAP.md` → Current Priorities names Goal #1 and points here.
- The audit's fourteen projects keep their ids; this ADR sequences PRJ-01/14/02/03/04/05/13
  into waves and defers the rest.
- Each wave ships through `/task-pipeline`; user-facing behaviour (artefact rendering,
  caveats, MCP payload) updates `docs/ux/scenarios.md` in the same change.
