# MCP Server — Remote-Ready Hardening (Design Spec)

- **Date:** 2026-06-22
- **Branch:** `feat/mcp-remote-hardening`
- **Status:** Approved design → ready for `writing-plans`
- **Audit source:** see findings F1–F9 below (derived from full read of `backend/app/mcp_server/`).
- **Locked decisions:** Deployment = **remote multi-tenant HTTP**; Architecture = **ASGI-mount into FastAPI**; Scope = **remote-ready bundle** (F1, F2, F3, F4, F7, F8). Protocol polish (F5, F6, F9) is explicitly out of scope (separate spec).

---

## 1. Problem statement

The MCP server (`backend/app/mcp_server/`) exposes CheckMyData's agent as MCP tools. It is well-built for the **stdio / per-user-process** case (good token hygiene, tenancy gates, annotations, pagination), but cannot safely serve the **remote multi-tenant HTTP** mode it advertises:

| # | Sev | Finding (verified in code) |
|---|---|---|
| **F1** | 🔴 Critical | `_with_principal` calls `auth.authenticate()` with **no args** (`server.py:48`); `authenticate()` reads creds **only from `os.environ`** (`auth.py:154`). The per-request `Authorization` header is never read → on `streamable-http`/`sse` every client is authenticated as the same env-bound user. |
| **F2** | 🟠 High | MCP `query_database`/`search_codebase` call `orchestrator.run()` directly with **no token-budget / entitlement gate** (`chat.py:72-103` has the gate; MCP has none). LLM spend bypasses plan limits. |
| **F3** | 🟠 High | No rate-limit or agent-concurrency gate on the MCP tool surface (chat uses `agent_limiter` + slowapi; MCP uses neither). |
| **F4** | 🟠 High | `app.state.trace_persistence_service` is set inside FastAPI **lifespan** (`main.py:152`); the standalone MCP process never runs lifespan → `_get_trace_svc()` is always `None` (`tools.py:79`) → MCP request traces are never persisted. |
| **F7** | 🟡 Med | `pyproject.toml:35` pins `mcp>=1.2.0` (installed `1.27.2`); FastMCP API changed substantially across that range. |
| **F8** | 🟡 Med | Auth tests only patch `os.environ` — structurally cannot catch F1; no per-request multi-token test. |

**Out of scope (separate spec):** F5 (`outputSchema`/`structuredContent`), F6 (`isError`), F9 (`is_active` default, resource pagination, drop `sse` default).

---

## 2. Goals / non-goals

**Goals**
- G1 — Per-request principal on HTTP transport: two clients with two tokens resolve to two users.
- G2 — Token-budget/entitlement gate on MCP agent tools, reusing the chat gate.
- G3 — Rate-limit + concurrency on the MCP tool surface.
- G4 — MCP request traces actually persist (`RequestTrace`/`TraceSpan`).
- G5 — Exact `mcp` pin; no CI-coverage regression (≥ 72%).
- G6 — **No regression** to the stdio/per-user-process path or tenancy cross-project denial.

**Non-goals**
- Not rebuilding the server. Auth core (`authenticate`, token model, tenancy gates) is reused as-is.
- Not implementing OAuth 2.1 Authorization Server / `/.well-known` metadata (opaque `cmd_mcp_` tokens are introspected directly).
- Not the P2 protocol-polish items.

---

## 3. Architecture

FastMCP is mounted as an ASGI sub-app inside the existing FastAPI app (`backend/app/main.py`), under `settings.mcp_mount_path` (default `/mcp`), gated by `settings.mcp_enabled`. The standalone `python -m app.mcp_server` (stdio) entry point is **retained unchanged** and shares the same `create_mcp_server()` + auth core.

```
Remote (HTTP):
  client A (Bearer cmd_mcp_A) ─┐
  client B (Bearer cmd_mcp_B) ─┼─► FastAPI app  /mcp (mounted Starlette)
                               │     └─ McpAuthMiddleware ─► authenticate(api_key=bearer)
                               │           └─ set current_principal (ContextVar) | 401
                               │                 └─ FastMCP tool ─► _with_principal reads ContextVar
                               │                       └─ budget gate ─► concurrency ─► orchestrator
Local (stdio):
  python -m app.mcp_server ─► same tools ─► _with_principal falls back to os.environ (current behaviour)
```

- Transport mode: `stateless_http=True, json_response=True` (horizontal scale, no sticky sessions).
- FastAPI lifespan extended with `async with mcp.session_manager.run(): yield` (required — otherwise streamable sessions don't start; verified against SDK docs).
- `streamable_http_app()` returns a `starlette.applications.Starlette` (verified, mcp 1.27.2) → we attach `McpAuthMiddleware` via `.add_middleware(...)` before mounting.
- DNS-rebinding / Origin guard: pass `TransportSecuritySettings` with allowed hosts/origins for the deploy domain.

---

## 4. Component contracts (locked)

### 4.1 Per-request principal (F1 → G1)

**New: `app/mcp_server/principal.py`**
```python
from contextvars import ContextVar
# Principal dict shape: {"user_id": str, "email": str} — same shape authenticate() returns.
current_principal: ContextVar[dict | None] = ContextVar("mcp_current_principal", default=None)
```

**New: `app/mcp_server/asgi.py`** — builds the mounted, middleware-wrapped app.
```python
def build_mounted_mcp_app() -> Starlette:
    """Return the FastMCP streamable-http Starlette app with McpAuthMiddleware attached.
    Used by main.py to Mount under settings.mcp_mount_path."""
```
- `McpAuthMiddleware` — **pure ASGI middleware** (NOT Starlette `BaseHTTPMiddleware`, which runs the downstream app in a separate anyio task and breaks ContextVar propagation to the endpoint). It reads `Authorization: Bearer <tok>` (or `X-API-Key`) from the ASGI `scope`; calls `auth.authenticate(api_key=tok)`; on success sets `current_principal` then `await app(scope, receive, send)` **in the same task** (so the ContextVar is visible downstream); on `MCPAuthError` short-circuits with `401` JSON `{"error": ...}` + `WWW-Authenticate: Bearer`.

**Changed: `app/mcp_server/auth.py`**
- `authenticate(api_key=None, token=None)` already accepts explicit creds — **unchanged**. The middleware passes the per-request token; env-fallback path is preserved for stdio.

**Changed: `app/mcp_server/server.py` `_with_principal`**
```python
async def _with_principal(run, *, tool_name=None) -> str:
    principal = current_principal.get()           # HTTP path (middleware-set)
    if principal is None:
        try:
            principal = await auth.authenticate()  # stdio fallback (env)
        except auth.MCPAuthError as exc:
            return json.dumps({"error": str(exc)})
    ... # rate-limit + run, unchanged downstream
```

### 4.2 Token-budget gate (F2 → G2)

**Changed: `app/services/usage_service.py`** — extract chat's `_check_token_budget` into a reusable method:
```python
class UsageService:
    async def check_token_budget(self, db, user_id: str) -> str | None:
        """Return an error string if the user's token budget is exhausted, else None.
        Resolves plan entitlements (EntitlementService.effective_token_limits) with
        config fallback; budget *checks* fail-open, *breaches* block."""
```
- **Changed: `chat.py`** — `_check_token_budget` becomes a thin delegate to `UsageService.check_token_budget` (behaviour identical; no contract change for chat).
- **Changed: `app/mcp_server/tools.py`** — `query_database` and `search_codebase` call `check_token_budget(session, user_id)` **after** access check and **before** `orchestrator.run()`; on non-None return `{"error": <msg with upgrade hint>}` and do **not** start the agent.

### 4.3 Rate-limit + concurrency (F3 → G3)

- **Concurrency:** wrap the agent-invoking tools (`query_database`, `search_codebase`, `execute_raw_query`) with `app.core.agent_limiter` (same pool as chat) so MCP shares the global agent-slot budget.
- **Rate-limit (per-user):** slowapi `limiter` is route-decorator + remote-address keyed → not applicable to the mounted ASGI sub-app. Introduce a **per-principal** token-bucket check in `_with_principal` keyed on `user_id`, backed by the existing rate-limit backend (Redis with in-memory fallback). New config `mcp_rate_limit_per_minute` (default conservative, e.g. 30). On exceed → `{"error": "rate limit exceeded, retry in …"}`.

### 4.4 Observability / trace (F4 → G4)

- Under ASGI-mount the FastAPI lifespan runs, so `app.state.trace_persistence_service` is populated. Replace the fragile `import app.main` reach-through in `tools.py:_get_trace_svc` with access via the request/app state (the mounted app shares the parent's `app.state`). stdio path degrades explicitly (returns `None`, logged once) rather than silently.
- `finalize_trace(...)` calls in `query_database`/`search_codebase` are unchanged but now actually fire on the HTTP path.

### 4.5 Dependency + config (F7 → G5)

- `pyproject.toml`: `mcp>=1.2.0` → `mcp==1.27.2` (exact pin, matching the ruff/mypy convention).
- `app/config.py` + `backend/.env.example`: add
  - `mcp_mount_enabled: bool = False` — gates the **HTTP mount** specifically, kept distinct from `mcp_enabled` so enabling the stdio MCP surface does NOT auto-expose the remote HTTP endpoint (safer default; the mount requires both `mcp_enabled` and `mcp_mount_enabled`).
  - `mcp_mount_path: str = "/mcp"`
  - `mcp_rate_limit_per_minute: int = 30`
- `main.py`: conditional mount of `build_mounted_mcp_app()` + lifespan `session_manager.run()`, all behind the flag (no behaviour change when off).

---

## 5. Auth wiring decision (resolved)

Custom **Starlette `McpAuthMiddleware` + `ContextVar`**, NOT FastMCP's built-in `token_verifier`/`AuthSettings`. Rationale:
- Our tokens are opaque `cmd_mcp_` keys, not OAuth tokens; `AuthSettings` would pull in issuer/resource metadata + `/.well-known` endpoints we don't need.
- `streamable_http_app()` is a Starlette app with `.add_middleware` (verified) → middleware is the least-invasive seam and reuses `authenticate()` verbatim.
- ContextVar set in upstream ASGI middleware is visible to the downstream tool coroutine (standard request-scoped pattern).

---

## 6. File ownership (parallelizable boundaries)

| File | Change | Type |
|---|---|---|
| `app/mcp_server/principal.py` | **new** ContextVar | parallel-safe |
| `app/mcp_server/asgi.py` | **new** mounted-app builder + `McpAuthMiddleware` | depends: principal |
| `app/mcp_server/auth.py` | no logic change (confirm `authenticate` signature) | parallel-safe |
| `app/mcp_server/server.py` | `_with_principal` reads ContextVar + rate-limit hook | depends: principal |
| `app/mcp_server/tools.py` | budget gate + concurrency + trace-svc access | depends: usage helper |
| `app/services/usage_service.py` | extract `check_token_budget` | parallel-safe |
| `app/api/routes/chat.py` | delegate to shared helper | depends: usage helper |
| `app/main.py` | conditional mount + lifespan (glue, sequential) | depends: asgi |
| `app/config.py`, `backend/.env.example`, `pyproject.toml` | config + pin | parallel-safe |
| `tests/unit/test_mcp_asgi_auth.py` (new), `test_mcp_server.py` | F8 tests | last |

---

## 7. Testing (F8 → G6)

- **Per-request auth (the F1 regression test):** mount via `httpx.ASGITransport`, issue two `cmd_mcp_` tokens for two users, call `checkmydata_ping`/`list_projects` with each `Authorization` header → assert two distinct `user_id`s; missing/invalid token → 401.
- **Budget deny:** stub budget exhausted → `query_database` returns upgrade-hint error and `orchestrator.run` is **not** awaited.
- **Rate-limit:** N+1 calls in the window for one principal → error.
- **Trace:** mounted `query_database` → `trace_svc.finalize_trace` invoked (mocked).
- **Regression:** stdio/env path still resolves principal; cross-project tenancy denial unchanged; existing ~82 MCP tests stay green.
- Coverage stays ≥ 72% (combined gate).

---

## 8. Definition of Done

- [ ] Two tokens → two principals over HTTP (test green).
- [ ] MCP agent tools enforce token budget (test green); chat behaviour unchanged.
- [ ] Per-user rate-limit + agent-concurrency applied to MCP tools (test green).
- [ ] MCP request traces persist under mount (test green); stdio degrades explicitly.
- [ ] `mcp==1.27.2` pinned; flag-gated mount (off by default) wired in `main.py` + lifespan.
- [ ] stdio path + tenancy denial regression-green; CI green; coverage ≥ 72%.
- [ ] `ruff format`/`ruff check`/`mypy` clean.

---

## 9. Risks

- **R1 — ContextVar propagation** across the middleware → FastMCP-tool boundary. The Starlette `BaseHTTPMiddleware` gotcha (separate anyio task drops the ContextVar) is avoided by using pure ASGI middleware (§4.1). Mitigation: explicit test in §7; fallback is `scope`-based principal passing.
- **R2 — `session_manager.run()` lifespan interaction** with existing lifespan startup ordering. Mitigation: nest inside current lifespan; keep mount behind flag so default boot is unchanged.
- **R3 — Stateless mode** assumes no server-push; our tools are request/response only → compatible.
