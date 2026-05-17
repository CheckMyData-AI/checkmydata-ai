# Code-Intelligence Rollout Playbook (M1–M6)

> **Audience:** the operator flipping `code_graph_enabled`,
> `hybrid_retrieval_enabled`, `schema_retrieval_enabled`, `lineage_enabled`,
> and `clustering_enabled` from `False` to `True` in production.
>
> **Status:** v129 (commit `b13f530`) ships every milestone shipped but every
> flag still defaults to `False`. This document is the exact step list to
> safely enable them, observe metrics for the prescribed soak, and — once
> all five flags are healthy in production — the cleanup PR that deletes
> the now-unreachable legacy branches.

---

## 1. Flag inventory + canary criteria

Each flag is independent. Each must complete its **own** 2-week soak with
clean metrics before the next one is enabled. The sequence below is the
order the plan prescribes (lowest-risk → highest-risk paired with
"requires its predecessor's data"):

| # | Flag | Adds | Soak |
|---|------|------|------|
| 1 | `code_graph_enabled` | M1 AST + M2 graph build | 2 weeks |
| 2 | `hybrid_retrieval_enabled` | M3 BM25 + RRF in `KnowledgeAgent` | 2 weeks |
| 3 | `schema_retrieval_enabled` | M4 question-aware schema retrieval in `SQLAgent` | 2 weeks |
| 4 | `lineage_enabled` | M5 graph_callers in entity context | 2 weeks |
| 5 | `clustering_enabled` | M6 Louvain clusters + `get_tables_in_cluster` tool | 2 weeks |

`cluster_llm_label_enabled` already defaults to `True` and is gated by
`clustering_enabled`. It does not need its own soak.

---

## 2. Per-flag procedure

### 2.1 `code_graph_enabled` (M1 + M2)

**What it turns on:** `ast_parse` and `graph_build` pipeline steps. Writes
to `code_graph_symbols` and `code_graph_edges`.

**Pre-flip:**

```bash
heroku config:get DATABASE_URL -a checkmydata-api | \
  xargs -I{} psql {} -c "SELECT COUNT(*) FROM code_graph_symbols, COUNT(*) FROM code_graph_edges;"
# Expect: 0 rows (or rows from prior tests). Migration is already applied.
```

**Flip:**

```bash
heroku config:set CODE_GRAPH_ENABLED=true -a checkmydata-api
heroku ps:restart -a checkmydata-api
```

**Smoke (within 5 min of the next user-triggered index):**

```bash
heroku logs -a checkmydata-api --tail | grep -E "ast_parse|graph_build"
# Expect lines like:
#   ast_parse: project=<id> files=N symbols=N parse_errors=N
#   graph_build: project=<id> symbols=N edges=N
```

```bash
curl -sH "Authorization: Bearer $ADMIN_TOKEN" \
  https://checkmydata-api-990b0bcf28ab.herokuapp.com/api/metrics | \
  jq '.code_graph'
# Expect: { "code_graph_symbols_total": N>0,
#           "code_graph_edges_total":   N>0,
#           "code_graph_builds_total":  N>=1 }
```

**Soak (14 days) — daily check:**

| Metric | Healthy range | Alarm |
|--------|---------------|-------|
| `code_graph_builds_total` growth/day | ≥ 1 per active project that re-indexes | 0 over 48 h on a project that pushed code |
| Pipeline `graph_build` step p95 duration | < 60 s on repos ≤ 10k symbols | > 120 s or step failure rate > 1 % |
| Postgres `code_graph_*` table size | Linear with repo size | Unbounded growth on a single project |
| Dyno RSS | < 80 % of `Standard-1X` 512 MB | Sustained > 90 % during index |

**Rollback:** `heroku config:set CODE_GRAPH_ENABLED=false && heroku ps:restart`.
The pipeline silently skips M1+M2 next run; persisted rows stay but become
read-only (no consumer reads them when this flag is off).

---

### 2.2 `hybrid_retrieval_enabled` (M3)

**Prerequisite:** `code_graph_enabled=true` is not required, but a
`bm25_build` step needs to have run at least once for each project — which
only happens with `hybrid_retrieval_enabled=true`. Cold projects degrade
gracefully to dense-only via `_dense_only_search` (see §4).

**Flip:**

```bash
heroku config:set HYBRID_RETRIEVAL_ENABLED=true -a checkmydata-api
heroku ps:restart -a checkmydata-api
```

**Smoke:** trigger a knowledge query in the UI; in logs look for the
`hybrid_search` path:

```bash
heroku logs -a checkmydata-api --tail | grep -E "bm25_build|hybrid_search|HybridRetriever"
```

**Soak — daily check:**

| Metric | Healthy | Alarm |
|--------|---------|-------|
| `_hybrid_search` returning empty → falling back to dense | < 5 % of queries | > 25 % (BM25 not building) |
| RRF score distribution | Long-tail decay | All zeros (tokenizer broken) |
| `bm25_build` step duration | < 30 s for ≤ 5k chunks | > 120 s |
| `./data/bm25/*.pkl` disk usage | < 100 MB per project | Unbounded |

**Rollback:** flip flag off → `_handle_search_knowledge` reverts to
dense-only. The `.pkl` files stay on disk but are not read.

---

### 2.3 `schema_retrieval_enabled` (M4)

**Prerequisite:** at least one indexing run after `CODE_GRAPH_ENABLED=true`
so the `schema_embed` step has materialised the per-connection BM25 schema
snapshot. Without it the SQL agent falls back to the legacy
`relevance_score >= 2` safety net (which is preserved on purpose — see
§4).

**Flip:**

```bash
heroku config:set SCHEMA_RETRIEVAL_ENABLED=true -a checkmydata-api
heroku ps:restart -a checkmydata-api
```

**Smoke:** ask an analytical question whose answer requires a specific
table; in logs:

```bash
heroku logs -a checkmydata-api --tail | grep -E "schema_retriever|_retrieve_tables_for_question"
```

**Soak — daily check:**

| Metric | Healthy | Alarm |
|--------|---------|-------|
| % SQL queries that get a focused context (≤ 5 tables) | ↑ vs pre-flip | Flat or ↓ |
| `relevant_tables` count per `_build_query_context` | Median ≤ 5 | Median == `sql_agent_max_context_tables` (retriever returning everything) |
| Operator-reported "wrong table" incidents | ↓ vs pre-flip | ↑ |

**Rollback:** flip flag off → `_retrieve_tables_for_question` no longer
runs; the safety-net `relevance_score >= 2` path serves results alone.

---

### 2.4 `lineage_enabled` (M5)

**Prerequisite:** `code_graph_enabled=true` for ≥ 1 indexing run per
project (the `graph_db_bridge` step needs `state.code_graph` populated).
The rehydrate-from-DB fallback in `pipeline_runner._run_steps` covers
incremental indexing.

**Flip:**

```bash
heroku config:set LINEAGE_ENABLED=true -a checkmydata-api
heroku ps:restart -a checkmydata-api
```

**Smoke:** open an entity in the knowledge UI; the response should
contain a "Code lineage (top callers)" section. Backend log:

```bash
heroku logs -a checkmydata-api --tail | grep -E "graph_db_bridge|graph_callers"
```

API smoke:

```bash
curl -sH "Authorization: Bearer $ADMIN_TOKEN" \
  https://checkmydata-api-990b0bcf28ab.herokuapp.com/api/metrics | \
  jq '.code_graph.code_graph_lineage_refs_total'
# Expect: > 0 after the next indexing run
```

**Soak — daily check:**

| Metric | Healthy | Alarm |
|--------|---------|-------|
| `code_graph_lineage_refs_total` growth | ↑ with every successful index | Flat (bridge step never running) |
| Sampled `graph_callers` quality | Endpoint kinds + op kinds correct on 5 random spot-checks | Random / wrong endpoints |
| `code_db_sync_analyzer` `required_filters` precision | ↑ vs pre-flip | No change or ↓ |

**Rollback:** flip flag off → `KnowledgeAgent._format_entity_detail` and
`SQLAgent` lineage-block rendering both skip; persisted `graph_callers`
remain in `project_caches.knowledge_json` but are not surfaced.

---

### 2.5 `clustering_enabled` (M6)

**Prerequisite:** `code_graph_enabled=true` for ≥ 1 successful indexing
run.

**Flip:**

```bash
heroku config:set CLUSTERING_ENABLED=true -a checkmydata-api
heroku ps:restart -a checkmydata-api
```

(`cluster_llm_label_enabled` is already `true`; the LLM label step
gracefully degrades to `"Cluster N"` on router failure.)

**Smoke:**

```bash
heroku logs -a checkmydata-api --tail | grep -E "graph_clustering|cluster_label"
```

Then in the chat UI, ask: *"List the tables in the auth cluster"*. The
SQL agent should call `get_tables_in_cluster`.

**Soak — daily check:**

| Metric | Healthy | Alarm |
|--------|---------|-------|
| `code_graph_clusters_total` per project | 3–30 typical | 1 (everything in one community) or > 100 (over-segmented) |
| `cluster_llm_label_enabled` LLM failure rate | < 5 % (defaults to "Cluster N") | > 25 % |
| `get_tables_in_cluster` tool invocations | > 0 / week after operator-led demo | 0 (LLM never picks the tool) |

**Rollback:** flip flag off → `graph_clustering` pipeline step skips and
the SQL agent's `has_clusters` flag drops the tool from the available
list.

---

## 3. Operator quick-reference

```bash
# Verify the live config (production)
heroku config -a checkmydata-api | grep -E "CODE_GRAPH|HYBRID|SCHEMA_RETRIEVAL|LINEAGE|CLUSTERING"

# Single-command health snapshot
curl -sH "Authorization: Bearer $ADMIN_TOKEN" \
  https://checkmydata-api-990b0bcf28ab.herokuapp.com/api/metrics | \
  jq '{ active_workflows, code_graph, recent_errors: [.orchestrator_recent[] | select(.error != null)] }'

# Roll back ALL five flags in one command (panic button)
heroku config:set \
  CODE_GRAPH_ENABLED=false \
  HYBRID_RETRIEVAL_ENABLED=false \
  SCHEMA_RETRIEVAL_ENABLED=false \
  LINEAGE_ENABLED=false \
  CLUSTERING_ENABLED=false \
  -a checkmydata-api && \
heroku ps:restart -a checkmydata-api
```

---

## 4. The cleanup PR — what it deletes, what it keeps

After **all five flags** have completed their 2-week soaks in production,
a separate PR flips defaults to `True` in `backend/app/config.py` and
deletes the now-unreachable legacy branches. Below is the precise list.

### 4.1 Default flips

`backend/app/config.py`:

```diff
- code_graph_enabled: bool = False
+ code_graph_enabled: bool = True
- hybrid_retrieval_enabled: bool = False
+ hybrid_retrieval_enabled: bool = True
- schema_retrieval_enabled: bool = False
+ schema_retrieval_enabled: bool = True
- lineage_enabled: bool = False
+ lineage_enabled: bool = True
- clustering_enabled: bool = False
+ clustering_enabled: bool = True
```

### 4.2 Flag-gate removals (the actual cleanup)

| File | Site | What collapses |
|------|------|----------------|
| `pipeline_runner.py:406` | `if settings.code_graph_enabled and state.repo_dir is not None:` | Drop the flag conjunct; still gated by `repo_dir is not None`. |
| `pipeline_runner.py:548–551` | Pre-M5/M6 rehydrate guard | Drop flag conjuncts; keep the `state.code_graph is None` guard. |
| `pipeline_runner.py:573` | `if settings.lineage_enabled and …` | Drop flag conjunct. |
| `pipeline_runner.py:636` | `if settings.clustering_enabled …` | Drop flag conjunct. |
| `pipeline_runner.py:956` | `if settings.hybrid_retrieval_enabled:` | Drop the whole `if`; bm25_build always runs. |
| `db_index_pipeline.py:642` | `if _settings.schema_retrieval_enabled:` | Drop the `if`; schema_embed always runs. |
| `sql_agent.py:1131` | `if settings.schema_retrieval_enabled:` | Drop the `if`; always call `_retrieve_tables_for_question`. |
| `sql_agent.py:1887` | `if graph_callers and settings.lineage_enabled:` | Drop `settings.lineage_enabled` conjunct; keep `graph_callers` truthiness check. |
| `knowledge_agent.py:262–270` | `if settings.hybrid_retrieval_enabled: … else: _dense_only_search(…)` | Drop the legacy `else` branch only; **keep** the `_dense_only_search` fallback at line 372 (it's the BM25-missing safety net, not legacy). |
| `knowledge_agent.py:488` | `if graph_callers and settings.lineage_enabled:` | Drop the flag conjunct. |
| `knowledge_freshness_service.py:114` | `if settings.code_graph_enabled:` | Drop the `if`; always evaluate code-graph freshness. |

### 4.3 Prompt-builder kwargs to remove

The kwargs below are no longer needed once defaults flip to `True`; the
prompt sections become unconditional.

- `backend/app/agents/prompts/sql_prompt.py`:
  `lineage_enabled`, `schema_retrieval_enabled`, `has_code_clusters` →
  remove kwarg, render sections unconditionally.
- `backend/app/agents/prompts/knowledge_prompt.py`:
  `hybrid_retrieval_enabled`, `lineage_enabled` → same.

Update call sites in `sql_agent.py` and `knowledge_agent.py` accordingly.

### 4.4 What the cleanup PR must **not** delete

- `_dense_only_search` in `knowledge_agent.py` — it's the documented
  fallback when the BM25 snapshot is missing (cold project, corrupt
  snapshot, etc.), and `_hybrid_search` already calls it on empty
  results. Removing it would break the safety net.
- `relevance_score`-based safety net in `sql_agent._build_query_context`
  (the `safety_net = [...]` block before the `for entry in retrieved +
  safety_net:` loop). It's load-bearing on the union path, not legacy.
- The five flags themselves (`code_graph_enabled`, etc.) — they stay in
  `config.py` so an operator can still kill the feature without a code
  deploy. Default just changes from `False` to `True`.
- Tunables: `code_graph_max_symbols`, `ast_parse_concurrency`,
  `ast_max_file_bytes`, `bm25_data_dir`, `hybrid_rrf_k`,
  `hybrid_min_score`, `hybrid_k`, `sql_agent_max_context_tables`,
  `lineage_max_depth`. These are not "legacy code paths" — they're
  operational knobs.

### 4.5 Tests to update in the cleanup PR

Tests that assert flag-off behaviour will need either deletion or
inversion:

- `tests/unit/test_knowledge_agent.py` — legacy dense-only path assertions.
- `tests/unit/test_sql_agent.py` — `schema_retrieval_enabled=False` paths.
- `tests/integration/test_indexing_e2e.py` —
  `test_sql_prompt_surfaces_lineage_cluster_and_schema_retrieval` and
  `test_knowledge_prompt_surfaces_hybrid_and_lineage` currently assert
  both flag-on and flag-off rendering; the flag-off assertions become
  vacuous and should be deleted.
- `tests/unit/test_knowledge_freshness_service.py` — flag-off freshness
  path.

---

## 5. Status tracking

| Flag | Flipped (date) | Soak ends (date) | Health | Cleaned up |
|------|----------------|------------------|--------|------------|
| `code_graph_enabled` | _pending_ | — | — | ☐ |
| `hybrid_retrieval_enabled` | _pending_ | — | — | ☐ |
| `schema_retrieval_enabled` | _pending_ | — | — | ☐ |
| `lineage_enabled` | _pending_ | — | — | ☐ |
| `clustering_enabled` | _pending_ | — | — | ☐ |

Update this table as each soak completes.
