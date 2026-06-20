# CheckMyData.ai MCP Server

Connect Claude Desktop, Cursor, OpenAI Agents, or any MCP-compatible AI client
to CheckMyData.ai and let them query your databases, search your code, and
inspect schemas — scoped to **your** projects, with **your** identity.

---

## Quick start (3 steps)

1. **Mint a token.** Open the app → **Settings** → **MCP Tokens** → **New**.
   Give it a name (e.g. *Laptop*) and optional expiry. **Copy the plaintext
   token now — it is never shown again.** It looks like
   `cmd_mcp_lFv7K…iCfP`.

2. **Add the server to your client.** For Claude Desktop, edit
   `~/Library/Application Support/Claude/claude_desktop_config.json`
   (macOS / Linux) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

   ```json
   {
     "mcpServers": {
       "checkmydata": {
         "command": "python",
         "args": ["-m", "app.mcp_server"],
         "env": {
           "MCP_ENABLED": "true",
           "CHECKMYDATA_API_KEY": "cmd_mcp_PASTE_YOUR_TOKEN_HERE"
         }
       }
     }
   }
   ```

   The same snippet is rendered for you inside the *Token created* modal so
   you can copy-paste it directly.

3. **Restart your client.** The next time it lists tools, you'll see
   `checkmydata_*`:

   - `checkmydata_ping` — smoke test, returns your resolved user id
   - `checkmydata_list_projects` — projects you can access
   - `checkmydata_list_connections` — DB connections in a project
   - `checkmydata_get_schema` — indexed tables/columns for a connection
   - `checkmydata_query_database` — natural-language query → SQL + results
   - `checkmydata_search_codebase` — knowledge / code Q&A
   - `checkmydata_execute_raw_query` — read-only SQL passthrough

---

## How identity works

Every MCP call is bound to a **real CheckMyData user** before any tool runs.
There is no anonymous fallback.

```
client → MCP transport → authenticate() → tenancy gate → tool
                              │
                              ├─ cmd_mcp_… token   → DB lookup → user
                              ├─ JWT (legacy)      → AuthService → user
                              └─ legacy server key → MCP_API_KEY_USER_ID
```

- **Per-user `cmd_mcp_…` token (recommended)** — the path the UI mints.
  The plaintext is hashed (SHA-256) and stored alongside a 12-char display
  prefix; `last_used_at` is updated on every successful resolve.
- **JWT (`Authorization: Bearer`)** — for clients that already carry a
  short-lived platform JWT.
- **Server-level API key + `MCP_API_KEY_USER_ID`** — operator/single-tenant
  mode. Useful for self-hosted deployments where one platform user "owns" the
  MCP surface.

Tenancy is enforced **after** identity resolution: tools and resources
consult `MembershipService.can_access` and refuse on cross-tenant project /
connection ids. Raw SQL is additionally constrained to connections marked
`is_read_only=True` and passed through `SafetyGuard(READ_ONLY)`.

---

## CRUD API

All endpoints require the user to be signed in (JWT or session cookie).

| Method | Path                              | Description                                                                  |
|--------|-----------------------------------|------------------------------------------------------------------------------|
| POST   | `/api/auth/mcp-tokens`            | Issue a token. Body: `{"name": str, "expires_in_days": int \| null}`. Returns plaintext **once**. |
| GET    | `/api/auth/mcp-tokens`            | List tokens for the current user. Plaintext is **never** returned here.       |
| DELETE | `/api/auth/mcp-tokens/{token_id}` | Revoke a token. Returns 404 if missing, not owned, or already revoked.       |

Token shape:

```json
{
  "id": "uuid",
  "name": "Laptop",
  "token_prefix": "cmd_mcp_lFv7",
  "created_at": "2026-06-20T00:00:00+00:00",
  "last_used_at": "2026-06-20T01:23:45+00:00",
  "expires_at": null,
  "revoked_at": null
}
```

---

## Transports

```bash
# stdio (default — Claude Desktop, Cursor, local dev)
MCP_ENABLED=true CHECKMYDATA_API_KEY=cmd_mcp_... \
  python -m app.mcp_server

# streamable HTTP (remote / multi-client)
MCP_ENABLED=true CHECKMYDATA_API_KEY=cmd_mcp_... \
  python -m app.mcp_server --transport streamable-http --port 8100
```

- `stdio` — preferred for desktop / IDE clients. No HTTP, no network.
- `streamable-http` — preferred for remote / multi-client deployments.
- `sse` — legacy, kept only for older clients; prefer streamable HTTP.

---

## Operator config (single-tenant fallback)

If you self-host and want **one** key for all MCP traffic:

```bash
export MCP_ENABLED=true
export CHECKMYDATA_API_KEY=$(openssl rand -hex 32)
export MCP_API_KEY_USER_ID=<the-user-this-key-acts-as>
python -m app.mcp_server
```

This **operator** flow is independent from the per-user UI flow — both can
coexist. A `cmd_mcp_…` token always wins over the server-level key.

---

## Logging & debugging

Every step is logged so you can grep `MCP auth:` / `MCP tool` for problems.

| Logger                            | Signal                                                                  |
|-----------------------------------|-------------------------------------------------------------------------|
| `app.mcp_server.auth`             | `personal token … resolved to user …` / `lookup failed` / `JWT decode failed` |
| `app.mcp_server.server`           | `tool <name> starting`, `tool <name> ok`, `tool <name> crashed`         |
| `app.services.mcp_key_service`    | `MCP key issued`, `MCP key revoked`, `MCP key lookup: expired/revoked`  |
| `app.api.routes.mcp_tokens`       | `MCP token create: validation rejected`, `MCP token revoke: 404`        |

Plaintext tokens are **never** logged — only the 12-char display prefix and
the 8-char hash prefix. If you need a trace correlated with a user, search
on `user=<uuid>`.

To bump log level:

```bash
python -m app.mcp_server --log-level DEBUG
```

---

## Security model in one paragraph

The plaintext token is shown once at creation and **never** persisted in
plaintext — only `sha256(plaintext)`. Lookup is constant-time over the hash
and fails closed on unknown / revoked / expired keys without distinguishing
which case occurred. Tokens are scoped to the issuing user; a revoked or
expired `cmd_mcp_…` token **never** silently falls through to the operator
server-key path. Each tool call still re-checks project membership at the
service layer, so even a valid token can't reach a project the user has
been removed from.

For a deeper architectural dive see
[`SYSTEM_ARCHITECTURE.md`](SYSTEM_ARCHITECTURE.md). For the on-disk skill
you can drop into any AI agent, see
[`../.claude/skills/checkmydata-mcp/SKILL.md`](../.claude/skills/checkmydata-mcp/SKILL.md).
