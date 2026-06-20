---
name: checkmydata-mcp
description: Connect to and use the CheckMyData.ai MCP server — natural-language SQL, codebase Q&A, schema inspection — bound to a per-user token. Use when the user asks to "connect Claude/Cursor to CheckMyData", "use the CheckMyData MCP", "query my database via MCP", or pastes a `cmd_mcp_…` token. Also use proactively when the user mentions both an AI agent (Claude Desktop, Cursor, OpenAI Agents, custom MCP client) AND a CheckMyData project / database / token.
---

# CheckMyData.ai MCP integration

This skill teaches an agent how to **wire itself up** to the CheckMyData.ai
MCP server using a per-user token, and how to call its tools effectively.
It is portable: drop this folder into any agent runtime that supports
markdown skills (Claude Code, Codex, Copilot CLI, Gemini CLI, custom).

## When this skill applies

- The user wants to connect Claude Desktop / Cursor / any MCP client to
  CheckMyData.ai.
- The user has (or wants to mint) a `cmd_mcp_…` token.
- The user wants the agent to query databases or search the codebase via
  the MCP tools instead of going through the UI.
- The user pastes an MCP-shaped command like `checkmydata_query_database`
  and asks for help.

## Workflow

### Step 1 — Make sure a token exists

Ask the user (or check chat history) for a token shaped
`cmd_mcp_<random>`. If they don't have one, walk them through minting it:

> In the CheckMyData web app, go to **Settings → MCP Tokens → New**. Give
> it a name (e.g. *Claude Desktop*) and optional expiry. Copy the plaintext
> token immediately — it is never shown again.

If the user **lost** a token, do **not** try to recover it — instruct them
to revoke the old one and mint a fresh one.

### Step 2 — Wire the MCP server into the client

**Claude Desktop / Cursor (stdio):** Edit the client's MCP config and add
the snippet from [`references/client-configs.md`](references/client-configs.md).
The `command` and `args` assume the CheckMyData backend is checked out
locally; for hosted deployments use the `streamable-http` snippet instead.

**Remote / hosted:** Use the `streamable-http` URL the operator provides.
The same `cmd_mcp_…` token is passed via environment in the client config.

After updating the config, the user must **restart their MCP client** —
configs are read on launch.

### Step 3 — Verify with `checkmydata_ping`

The very first tool call should be `checkmydata_ping`. It returns the
resolved principal so the user can confirm:

- Auth worked
- The token mapped to *their* user id (not someone else's)
- The transport is reachable

If `checkmydata_ping` errors with `MCP token is invalid, revoked, or
expired`, the user must mint a new token. There is no recovery path — this
is the correct behavior of the auth model.

### Step 4 — Discover scope, then use the right tool

Pick the **highest-level tool that fits the question**:

| User intent                                  | Tool                              |
|----------------------------------------------|-----------------------------------|
| "What projects can I access?"                | `checkmydata_list_projects`       |
| "What databases does project X have?"        | `checkmydata_list_connections`    |
| "What's the schema of connection Y?"         | `checkmydata_get_schema`          |
| Free-form data question in natural language  | `checkmydata_query_database`      |
| Code / docs / ORM / architecture question    | `checkmydata_search_codebase`     |
| User pasted exact SQL they want run          | `checkmydata_execute_raw_query`   |

Always pass `project_id` (and `connection_id` when known) explicitly. The
server scopes results to the user's membership, so a wrong id will return
an `error` rather than silently returning another tenant's data.

### Step 5 — Render results cleanly

Every list tool supports `response_format: "markdown"` — pass it when you
want a human-readable summary instead of JSON. `query_database` always
returns JSON with `{answer, query, results, viz_type, viz_config,
sources}`; show the natural-language answer first, then the SQL on
request, then a small results table.

## Tool reference

See [`references/tools.md`](references/tools.md) for the full input/output
schema of every `checkmydata_*` tool plus example calls.

## Troubleshooting

See [`references/troubleshooting.md`](references/troubleshooting.md) for
the common errors and their root causes (auth failures, tenancy denials,
read-only guard hits, transport mismatches).

## Security boundary

This skill MUST NEVER:

- Echo or log a full `cmd_mcp_…` token. The display prefix `cmd_mcp_XXXX…`
  is fine — the rest of the secret is not.
- Suggest disabling tenancy checks "for debugging" — the user's identity
  IS the security boundary.
- Recommend pinning the legacy server-level `CHECKMYDATA_API_KEY` into a
  client config. That mode is for self-hosted single-tenant operators, not
  end users.
