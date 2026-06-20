# MCP client config snippets

Pick the snippet that matches the user's client. The token always goes in
`CHECKMYDATA_API_KEY` (or the client-specific equivalent). **Never paste
a plaintext token into this file or quote it in chat output.**

---

## Claude Desktop (macOS / Linux / Windows)

File:
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Linux: `~/.config/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

### Local backend (stdio)

```json
{
  "mcpServers": {
    "checkmydata": {
      "command": "python",
      "args": ["-m", "app.mcp_server"],
      "env": {
        "MCP_ENABLED": "true",
        "CHECKMYDATA_API_KEY": "cmd_mcp_PASTE_YOUR_TOKEN_HERE",
        "DATABASE_URL": "sqlite+aiosqlite:///./backend/data/agent.db"
      },
      "cwd": "/absolute/path/to/checkmydata-ai/backend"
    }
  }
}
```

### Hosted backend (streamable HTTP)

```json
{
  "mcpServers": {
    "checkmydata": {
      "url": "https://YOUR-HOST/mcp",
      "headers": {
        "Authorization": "Bearer cmd_mcp_PASTE_YOUR_TOKEN_HERE"
      }
    }
  }
}
```

After saving, **fully quit and reopen Claude Desktop** — the config is
read once on launch.

---

## Cursor

`File → Preferences → Cursor Settings → MCP → Add new MCP server`. Same
JSON shape as Claude Desktop. The Cursor settings file lives at
`~/.cursor/mcp.json`.

---

## OpenAI Agents SDK (Python)

```python
from agents import Agent, MCPServerStdio

server = MCPServerStdio(
    "checkmydata",
    command="python",
    args=["-m", "app.mcp_server"],
    env={
        "MCP_ENABLED": "true",
        "CHECKMYDATA_API_KEY": "cmd_mcp_PASTE_YOUR_TOKEN_HERE",
    },
    cwd="/absolute/path/to/checkmydata-ai/backend",
)
agent = Agent(name="my-agent", mcp_servers=[server])
```

---

## Generic stdio MCP client

```bash
MCP_ENABLED=true \
CHECKMYDATA_API_KEY=cmd_mcp_PASTE_YOUR_TOKEN_HERE \
python -m app.mcp_server
```

Add `--log-level DEBUG` for verbose auth and tool-call logs.
