# Troubleshooting CheckMyData MCP connections

Every error below is what the **tool** returns — not an HTTP error. Tool
errors come back as `{"error": "..."}` so the LLM can recover gracefully.

---

## `MCP token is invalid, revoked, or expired`

The `cmd_mcp_…` token doesn't match a live record. Three possibilities,
indistinguishable by design:

- The token was revoked in **Settings → MCP Tokens**.
- The token's `expires_at` has passed.
- The token never existed (typo).

**Fix:** mint a new token. Never paste the old one back.

---

## `MCP authentication required: configure CHECKMYDATA_API_KEY or provide a token`

The client started without any credential. Check the MCP server's
`env.CHECKMYDATA_API_KEY` in the client config.

---

## `Access denied to project '...'`

The principal resolved fine, but they aren't a member of that project.
Either:

- They're using a token from the wrong account.
- They were removed from the project on the web app.

**Fix:** call `checkmydata_list_projects` to see which projects this
principal can actually access.

---

## `Connection '...' not found`

Either the connection id doesn't exist or it belongs to a different
project than the one passed. The server checks both — call
`checkmydata_list_connections` with the right `project_id` to find the
correct id.

---

## `Raw query execution is only allowed on read-only connections`

The connection wasn't marked `is_read_only=True`. The MCP raw-SQL tool
will not run against a connection that could write. **Fix:** in
Settings → Connections → Edit, toggle "read-only" on. Or use
`checkmydata_query_database` which goes through the orchestrator and is
always safe.

---

## `MCP server is disabled`

The server was started with `MCP_ENABLED` unset. Set `MCP_ENABLED=true`
in the client config's `env`.

---

## "Connecting to checkmydata…" hangs in Claude Desktop

Check the client log (`~/Library/Logs/Claude/mcp*.log` on macOS). Most
common causes:

- `cwd` in the config doesn't point at the backend directory (the server
  can't import `app.mcp_server`).
- Missing Python virtualenv. Use the absolute path to the backend's
  `.venv/bin/python` as `command`.
- The backend can't reach Postgres / SQLite — every tool call opens a
  session.

---

## Debugging logs

Run the server manually with verbose logging:

```bash
MCP_ENABLED=true \
CHECKMYDATA_API_KEY=cmd_mcp_… \
python -m app.mcp_server --log-level DEBUG
```

Grep targets:

| Pattern                            | What it tells you                            |
|------------------------------------|----------------------------------------------|
| `MCP auth: personal token .* resolved` | Token accepted, user id at end of line     |
| `MCP auth: personal token lookup failed` | Token rejected (unknown/revoked/expired) |
| `MCP tool .* starting`             | Tool call started, user id at end of line    |
| `MCP tool .* ok`                   | Tool call returned normally                  |
| `MCP tool .* crashed`              | Tool raised — full traceback in same record  |
| `MCP key issued`                   | Token CRUD: new token minted                 |
| `MCP key revoked`                  | Token CRUD: revoke succeeded                 |
