# ADR-0006 — Buy before build: `codebase-memory-mcp` for code intelligence, DuckDB for compute, Vanna not adopted

**Status:** accepted 2026-09-14 · **Amends:** ADR-0005 §5 (the waves) · **Question:** which
ready-made components shorten the path to Goal #1 without trading one class of failure
for another.

Every claim below was measured on this machine on 2026-09-14 unless it cites a source.

---

## 1. Decision

1. **Adopt `codebase-memory-mcp` (CBM) as the code-intelligence engine** behind the repo
   index: AST parse, code graph, symbol/structural search, change detection and
   architecture summary. It replaces our `ast_parse`, `graph_build`, `code_symbol_embed`
   and `bm25_build` steps and removes `generate_docs` from the critical path.
2. **Keep what CBM does not do and what is the product's real asset:** the DB index, the
   code↔DB map (`code_db_sync`), per-connection learnings, freshness. These read CBM's
   graph instead of ours.
3. **Adopt DuckDB for in-request compute** — already decided in ADR-0005 §3.3; restated
   here as the second "buy".
4. **Do not adopt Vanna 2.0 as the SQL engine.** Borrow its one good idea (verified
   question→SQL pairs as retrieval), which ADR-0005 §3.5 already plans.
5. **Do not migrate the orchestrator to an agent framework** (LangGraph, PydanticAI
   graphs). Extracting seams from 3 721 lines with 43 test files is faster than a
   framework rewrite and keeps the tests.

---

## 2. Evidence for CBM

### 2.1 What it is

Single static C binary (MIT), tree-sitter over 162 grammars with hybrid LSP resolution for
Python/TS/JS/PHP/Go/Java/C#/Rust and others, SQLite graph on local disk, optional bundled
embeddings, 15 MCP tools, CLI mode (`codebase-memory-mcp cli --json <tool> <json>`),
Linux amd64/arm64 static and "portable" release assets, SLSA provenance
([repo](https://github.com/DeusData/codebase-memory-mcp)). Installed here at
`~/.local/bin/codebase-memory-mcp` **v0.10.8** (release 2026-08-19), provenance verified per
`~/.config/agentgateway/servers.yaml`.

### 2.2 Measured here

| Repository | Files | Time | Nodes / edges | Notable |
|---|---|---|---|---|
| `checkmydata-ai` (Python + TS) | 1 724 | **25.6 s** | 26 481 / 140 173 | 24 edge types incl. `CALLS`, `IMPORTS`, `TESTS`, `HTTP_CALLS`, `INHERITS`, `RAISES`, `FILE_CHANGES_WITH`; 461 `Route`, 22 `EnvVar` nodes |
| `nicegram-api` (Laravel 13, PHP) | 1 483 PHP | **22.3 s** | 9 571 / 30 917 | 197 routes with method+path, 288 `EnvVar`, migrations grouped as a package, `Schema::create` found by `search_code` in 4 migration `up()` bodies |

Against our own pipeline on `esim-php` (9 981 files, PHP): full rebuild **12 039–12 329 s**,
of which `generate_docs` ≈ 9 375 s and `code_symbol_embed` 2 260–2 582 s; our graph
25 695 symbols / 68 263 edges. CBM's `search_code` answered a structural question in 754 ms
(`search_code` for `heartbeat_at` returned the five right methods with line ranges);
`search_graph` ran BM25 (semantic mode did not engage in CLI without
`CBM_SEMANTIC_ENABLED`); `get_architecture` returned a package/route/entry-point summary
that our `project_summary` needs an LLM call to approximate.

### 2.3 What it does not do (and we keep)

- **Code↔DB table mapping.** `WRITES` edges are *variable* writes, not table writes; an
  `INHERITS → Model` query returned 0 rows (the parent is an unresolved vendor symbol).
  Our `tables_declared_in_migration`, `is_plausible_table_name` and `resolve_sync_status`
  stay, fed by CBM's `search_code`/`query_graph` instead of our AST.
- **DB schema index, learnings, freshness, custom rules** — ours.
- **LLM prose per file.** We stop generating it. The "knows the product" property comes
  from the graph + the map + the DB index, and the knowledge agent reads code **on demand**
  through `get_code_snippet`/`trace_path` with the graph as the index. One LLM-written
  project summary remains.

### 2.4 Known failure mode, and the mitigations we ship with it

The binary refused to start here with *"a pre-coordination or unverified CBM generation is
active"* while **no process was running** — stale lock files in `/tmp/cbm-daemon-<uid>/`
left by a hard-killed process on 2026-09-12. Recovery was `rm -rf /tmp/cbm-daemon-$(id -u)`
(backed up first). This is the same defect that made the machine's gateway entry fail with
HTTP 500 for days. It is tracked upstream as
[#1760](https://github.com/DeusData/codebase-memory-mcp/issues/1760),
[#2162](https://github.com/DeusData/codebase-memory-mcp/issues/2162) and
[#2178](https://github.com/DeusData/codebase-memory-mcp/issues/2178), and the maintainers'
own workaround is a fresh `CBM_RUNTIME_DIR`.

So in the product: **`CBM_RUNTIME_DIR` is a per-boot directory** (a dyno's filesystem is
fresh at every start anyway, and a stale lock cannot survive it); the sidecar is started
with `CBM_MEM_BUDGET_MB` sized to the dyno (the default is a fraction of RAM — 24 GB here;
on Standard-2X it must be ~300), `CBM_ALLOWED_ROOT` = the clone directory, `CBM_CACHE_DIR`
on the dyno disk, `--ui=false`, `auto_watch=false` (our pipeline decides when to index);
a health probe (`index_status`) before use, and a single retry that recreates the runtime
dir. The version is **pinned** and `gh attestation verify` runs in the image build, exactly
as `servers.yaml` documents for this machine. Semantic search stays off until its memory is
measured on the dyno; BM25 over the graph is what we measured.

---

## 3. Integration design

```
worker / web dyno
  └─ CBM sidecar: `codebase-memory-mcp` (stdio MCP), spawned at boot by the process that needs it,
       env: CBM_RUNTIME_DIR=/tmp/cbm-$BOOT_ID  CBM_MEM_BUDGET_MB=…  CBM_ALLOWED_ROOT=$REPO_CLONE_BASE_DIR
       client: app/connectors/mcp_client.py (already speaks stdio)     ← no new transport code

repo index (pipeline_runner) becomes:
  clone_or_pull → cbm.index_repository(repo_path) → code_db_sync (reads cbm.search_code / query_graph)
               → project_summary (1 LLM call, from cbm.get_architecture) → record_index
  (ast_parse, graph_build, code_symbol_embed, bm25_build, generate_docs, enrich_docs: deleted behind a flag)

knowledge agent `search_codebase` → cbm.search_graph → cbm.get_code_snippet / trace_path
freshness                          → cbm.detect_changes (+ our git AHEAD/BEHIND)
```

- **Persistence.** The graph lives on the dyno's disk and is rebuilt at boot in ~30 s
  for a repo of `esim-php`'s size — the same shape as `bm25_local_reconcile`. Optionally
  the compressed `graph.db.zst` is stored in Postgres per project and restored on boot, so
  a cold start does not need the clone first; decided by measurement in wave 0.5.
- **Flag.** `code_intel_backend = cbm | native`, default `native` until the parity gate
  passes, then `cbm`; the native steps are deleted one release later. `graph_extraction
  schema` bumps stop forcing full rebuilds — a CBM re-index *is* a full rebuild and costs
  30 s.
- **Tenancy.** One CBM project per product project, named by project id; every tool call
  passes `project` explicitly (the upstream README warns queries without it return the
  wrong project).
- **What disappears with the hours-long rebuild:** the orphan/reap/ceiling/requeue class
  for `index_repo` (audit S-04, S-06, S-10, S-11, S-14 become moot), the vector-store
  fingerprint dance for code chunks (schema embeddings for DB retrieval remain), and
  ~1.7–2.0 M tokens per rebuild.

---

## 4. Vanna 2.0 — evaluated, not adopted

Vanna 2.0 (late 2025, MIT) is a rewrite into a user-aware agent framework with a training
store of DDL, documentation and question→SQL pairs, DataFrame results and Plotly charts,
many connectors ([Bytebase overview](https://www.bytebase.com/blog/top-text-to-sql-query-tools/),
[a local walkthrough](https://themenonlab.blog/blog/text-to-sql-open-source-local)). It
overlaps almost exactly with what `SQLAgent` + `ValidationLoop` + `SafetyGuard` +
`ContextPack` + per-connection learnings already are, and it brings its own agent loop.
Adopting it would be a second orchestrator inside the first — the divergence the audit
found between Path A and Path B, multiplied. What it does well, retrieval over verified
SQL pairs, is ADR-0005 §3.5 and costs two tables and a retriever. **Optional 1-day spike**,
off the critical path: run Vanna on the golden set to get an external baseline for D1.

---

## 5. The shortened plan (amends ADR-0005 §5)

| Wave | Before (ADR-0005) | Now | Days |
|---|---|---|---|
| 0 | PRJ-01 hotfix, PRJ-14 guards, PRJ-02 liveness | **unchanged** — the pgvector fix is still needed until CBM lands, and the sync fix is needed regardless | 3 |
| **0.5 (new)** | — | **CBM sidecar** behind `code_intel_backend`, repo index reduced to four steps, `search_codebase` on CBM, code↔DB sync reading CBM; parity gate on `esim-php` in staging: symbol count within ±10% of our 25 695, map row count ≥ ours, full index < 120 s | 5 |
| 1 | deadline, trace truth, golden set | unchanged | 9 |
| 2 | Artifact, `compute_sql`, Numbers Gate, MCP artefacts | unchanged | 12 |
| 3 | one executor, verified-query memory, eval gate | unchanged, minus `search_codebase` rework (done in 0.5) | 12 |
| index track | PRJ-06 pipeline DAG (L), PRJ-07 scheduling (M) | **PRJ-06 shrinks to S** (a four-step pipeline needs no DAG runner); PRJ-07 unchanged | 8 → 3 |

Chat track ≈ 41 days → **~36 with 0.5 included**, index track ≈ 10 → **~5**, and the
product's most expensive, most fragile job (a 3.4 h rebuild) becomes a 30 s step. Wave 0.5
runs **in parallel with wave 1** (disjoint files) and must not start before wave 0's
rebuild has finished (a deploy kills a running rebuild).

---

## 6. Consequences and risks

- **A binary dependency in the image.** Mitigated by MIT licence, pinned version,
  provenance verification in the build, the `native` fallback flag for one release, and
  the fact that its output is a SQLite file we can read directly if the binary ever goes
  away.
- **PHP resolution quality on `esim-php` is unmeasured** — the Laravel repo here measured
  well, but the parity gate in wave 0.5 exists because "measured well elsewhere" is not a
  measurement.
- **Semantic search off** at first; structural + BM25 search is what was measured. If the
  golden set shows retrieval misses, enable `CBM_SEMANTIC_ENABLED` and measure memory.
- **The machine's own gateway entry still times out** after the lock cleanup (the gateway
  spawns its own instance and may hold a stale one); that is `~/.config/agentgateway`, not
  this repository, and is recorded here only so nobody reads it as evidence against the
  binary.
