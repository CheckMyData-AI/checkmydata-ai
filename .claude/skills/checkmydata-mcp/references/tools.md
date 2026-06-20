# `checkmydata_*` tool reference

All tools require an authenticated principal. All responses are
JSON-encoded strings; errors are `{"error": "..."}`. List tools accept
`offset`, `limit`, and `response_format: "json" | "markdown"`.

---

## `checkmydata_ping`

Health-check. **Call this first when wiring a new client.**

**Args:** none.
**Returns:**
```json
{"ok": true, "principal": {"user_id": "..."}, "version": 1}
```

---

## `checkmydata_list_projects`

Projects the authenticated user can access.

**Args:** `offset?: int = 0`, `limit?: int = 20`, `response_format?: "json" | "markdown"`.
**Returns (json):**
```json
{
  "total": 3, "count": 3, "offset": 0,
  "items": [{"id": "...", "name": "...", "description": "..."}],
  "has_more": false, "next_offset": null,
  "projects": [...]  // back-compat alias
}
```

---

## `checkmydata_list_connections`

Database connections in a project.

**Args:** `project_id: str`, plus pagination + response_format.
**Returns:** paginated list with `{id, name, db_type, source_type, is_active}`.

---

## `checkmydata_get_schema`

Indexed tables for a connection.

**Args:** `connection_id: str`, plus pagination (default `limit=50`) +
response_format.
**Returns:** paginated list with `{name, schema, columns, row_count, description}`.
Returns `{"error": "No schema index found"}` if the connection has not been
indexed.

---

## `checkmydata_query_database`

Natural-language → SQL → results, via the full orchestrator pipeline.

**Args:**
- `project_id: str`
- `question: str`
- `connection_id?: str` (defaults to the project's first connection)

**Returns (JSON):**
```json
{
  "answer": "…",
  "response_type": "data",
  "query": "SELECT ...",
  "query_explanation": "…",
  "results": {"columns": [...], "rows": [...], "row_count": 100, "execution_time_ms": 42},
  "viz_type": "bar",
  "viz_config": {...},
  "sources": [{"source_path": "...", "doc_type": "..."}]
}
```

Always shows the orchestrator's natural-language answer first, then the
SQL. Use `viz_config` only when `viz_type != "text"`.

---

## `checkmydata_search_codebase`

Code / docs / ORM / architecture question, no DB connection required.

**Args:** `project_id: str`, `question: str`.
**Returns:** same shape as `checkmydata_query_database` minus SQL fields.

---

## `checkmydata_execute_raw_query`

Raw SQL passthrough. Requires `is_read_only=True` on the connection;
otherwise returns `{"error": "Raw query execution is only allowed on
read-only connections"}`. SQL is also passed through `SafetyGuard(READ_ONLY)`
which blocks anything that looks mutating.

**Args:** `connection_id: str`, `query: str`.
**Returns:** `{columns, rows, row_count, execution_time_ms, error}`.

---

## Resources

| URI                                  | Returns                                                   |
|--------------------------------------|-----------------------------------------------------------|
| `project://{project_id}/schema`      | Aggregated schema across all connections in the project   |
| `project://{project_id}/rules`       | Project-level custom business rules                       |
| `project://{project_id}/knowledge`   | Knowledge-base status `{document_count, status}`          |

Resources use the same auth + tenancy gate as tools.
