# Knowledge Catalog — Artifact Schema & ContextPack Contract

> Status: **Phase 0 contract** for the Knowledge Architecture roadmap
> (`knowledge_architecture_audit` plan). This document defines the canonical
> shape of every knowledge artifact and the `ContextPack` the orchestrator
> consumes. Phase 1 implements a **read-facade** (`KnowledgeCatalogService`)
> over the existing stores — it does **not** migrate data. Existing tables and
> indexes remain the source of truth; the catalog is a unifying read layer.

## 1. Why

Today the orchestrator assembles context from 6+ independent lazy loads
(`ContextLoader`): `table_map`, `recent_learnings`, `active_insights`,
`relevant_knowledge`, `staleness_warning`, `project_overview`, `custom_rules`.
Each has its own shape, its own freshness story, and no shared provenance. The
catalog gives every artifact a **stable identity, provenance, freshness, and
confidence** so the orchestrator (and the UI) can reason about *what* it knows
and *how much to trust it* — vision invariants #2 (traceability) and #5
(graceful degradation).

## 2. Artifact model

Every knowledge artifact, regardless of store, is described by this envelope:

```jsonc
{
  "id": "table:conn_ab12::public.orders",   // stable, store-prefixed
  "type": "table",                          // see Artifact Types below
  "title": "orders",                        // human label
  "summary": "Customer orders, one row per checkout.",
  "provenance": {
    "source": "db_index",                   // which store produced it
    "source_ref": "connection:ab12cd34",    // pointer back to the row/file
    "produced_by": "DbIndexPipeline",       // pipeline/agent that wrote it
    "commit_sha": null                       // set for code/RAG artifacts
  },
  "freshness": {
    "indexed_at": "2026-06-08T20:00:00Z",
    "age_hours": 3.2,
    "stale": false,
    "ttl_hours": 24
  },
  "confidence": 0.9,                          // 0..1, source-dependent
  "payload": { /* type-specific body */ }
}
```

### Field rules

- **`id`** — globally unique, deterministic, store-prefixed (`<type>:<scope>::<local>`).
  Re-indexing the same entity MUST produce the same id (so the UI can diff).
- **`provenance.source`** — one of the store identifiers in §3.
- **`provenance.source_ref`** — enough to fetch the underlying row/file again.
- **`freshness`** — every artifact carries its own freshness; the catalog never
  reports a single global timestamp. `stale` is derived from `age_hours > ttl_hours`
  or an explicit store status (e.g. sync `stale`/`failed`).
- **`confidence`** — `1.0` for introspected facts (schema), LLM-enrichment
  confidence for generated docs, sync match confidence for lineage edges,
  learning priority-normalised for learnings.

## 3. Artifact types → backing stores

| `type`         | Backing store / model                              | Source id      | Notes |
| -------------- | -------------------------------------------------- | -------------- | ----- |
| `table`        | `db_index` (`DbIndexService`)                      | `db_index`     | one per table; payload = columns, row_estimate, llm description |
| `column`       | nested in `table.payload.columns`                  | `db_index`     | not a top-level artifact by default |
| `code_entity`  | `code_graph_symbols` + `EntityExtractor`           | `code_graph`   | ORM models, migrations, enums |
| `lineage_edge` | `code_db_sync` ⊕ `graph_db_bridge` (M5) ⊕ DataGraph | `lineage`     | code symbol → entity → table → column → metric |
| `learning`     | `agent_learnings` (`AgentLearningService`)         | `learnings`    | per-connection; confidence = priority/100 |
| `insight`      | `insights` (`InsightMemoryService`)                | `insights`     | TTL/decay applies |
| `rule`         | `CustomRulesEngine`                                | `rules`        | user-authored, confidence = 1.0 |
| `rag_chunk`    | ChromaDB per project ⊕ BM25 code snapshot          | `rag`          | payload carries `commit_sha`, `file_path`, `indexed_at` (Phase 2 temporal metadata) |
| `metric`       | `data_graph` (`DataGraphService`)                  | `data_graph`   | metric definitions + relationships |
| `sync_note`    | `code_db_sync` (`conversion_warnings`, filters)    | `code_db_sync` | attached to the relevant `table` |

## 4. `ContextPack` — the orchestrator's input

The catalog's primary read API:

```
KnowledgeCatalogService.get_context_pack(
    session, *, project_id, connection_id, question, budget_tokens
) -> ContextPack
```

`ContextPack` is a structured, citeable bundle that replaces the 6+ ad-hoc
loads. It is **budget-aware** (allocates tokens per category) and **traceable**
(every block keeps its source refs):

```jsonc
{
  "project_id": "...",
  "connection_id": "...",
  "question": "...",
  "tables": [ { Artifact(type=table) + sync_notes[] } ],
  "lineage": [ Artifact(type=lineage_edge) ],
  "learnings": [ Artifact(type=learning) ],
  "rules": [ Artifact(type=rule) ],
  "insights": [ Artifact(type=insight) ],
  "rag_chunks": [ Artifact(type=rag_chunk) ],
  "freshness": {
    "overall_stale": true,
    "warnings": [
      {
        "category": "db_index",        // db_index | sync | git | code_graph
        "severity": "warning",          // info | warning | critical
        "message": "Database index is 30h old (>24h); consider re-indexing.",
        "recommended_action": {
          "label": "Re-index database",
          "kind": "reindex_db",          // reindex_db | reindex_repo | resync | none
          "connection_id": "ab12cd34"
        }
      }
    ]
  },
  "sources_used": ["db_index", "learnings", "rag"],   // for provenance panel
  "token_budget": { "total": 8000, "allocated": { "tables": 4000, ... } }
}
```

### Construction rules

1. **Facade, not migration** — the catalog reads from `DataSourcePipeline`
   (`pipelines/database_pipeline.py`), `ContextLoader`, `KnowledgeFreshnessService`,
   and the services above. No new persistence in Phase 1.
2. **Budget-aware** — reuse `core/context_budget.py` allocation. Categories are
   trimmed (not dropped) when over budget, preserving graceful degradation.
3. **Every block carries `provenance`** so Phase 4 (`ContextPlanner`) can show
   per-block provenance in the reasoning panel.
4. **Freshness is per-artifact and aggregated** — `freshness.warnings[]` each
   carry a `recommended_action` so the UI can render one-click re-index buttons
   that call `task_queue.enqueue` (the single, consolidated execution path).

## 5. Freshness → recommended actions

`KnowledgeFreshnessService` is extended (Phase 1) to emit, per warning, a
`recommended_action`:

| Warning category | Condition                              | `recommended_action.kind` |
| ---------------- | -------------------------------------- | -------------------------- |
| `db_index`       | missing or age > TTL                   | `reindex_db`               |
| `sync`           | status in {stale, failed}              | `resync`                   |
| `git`            | N commits behind HEAD / unindexed      | `reindex_repo`             |
| `code_graph`     | empty graph while `code_graph_enabled` | `reindex_repo`             |

The legacy `warnings: list[str]` field is preserved for backward compatibility;
the structured `details: list[FreshnessWarningDetail]` is additive.

## 6. Stability & versioning

- Artifact `id` format is part of this contract — changing it is a breaking
  change and requires a UI/diff migration note.
- New artifact `type`s are additive; consumers MUST ignore unknown types.
- `ContextPack` fields are additive; never repurpose a field's meaning.
