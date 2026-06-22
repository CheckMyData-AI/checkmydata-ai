# MCP Server Remote-Ready Hardening — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the MCP server safe for remote multi-tenant HTTP by mounting it into FastAPI with per-request auth, token-budget enforcement, rate-limiting, and working trace persistence — without regressing the stdio path.

**Architecture:** FastMCP is mounted as an ASGI sub-app inside the existing FastAPI app under `/mcp` (flag-gated). A pure-ASGI auth middleware resolves the per-request bearer token to a principal stored in a `ContextVar`; tools read that instead of `os.environ`. The agent-invoking tools reuse the existing `agent_limiter` (per-user concurrency + hourly cap) and the chat token-budget gate. Trace persistence is wired through a module-level runtime holder populated by the FastAPI lifespan.

**Tech Stack:** Python 3.12, FastAPI, Starlette, `mcp` (FastMCP) `==1.27.2`, SQLAlchemy 2.0 async, pytest (`asyncio_mode=auto`), httpx (ASGITransport for the integration test).

## Global Constraints

- `mcp` dependency MUST be pinned exactly to `==1.27.2` (no range) — CI reproducibility convention, same as ruff/mypy.
- Line length 100; ruff rules `E F I N W UP`; `ruff format` clean; `mypy app/ --ignore-missing-imports` clean.
- Async everywhere — no sync I/O on the request path.
- New env vars MUST be added to `app/config.py` (with the existing typed-default style) AND `backend/.env.example`.
- The HTTP mount requires BOTH `settings.mcp_enabled` AND `settings.mcp_mount_enabled` (default `False`); when off, app boot is byte-for-byte unchanged.
- No regression: stdio principal resolution (env token) and cross-project tenancy denial stay green; existing ~82 MCP tests stay green.
- Combined unit+integration coverage gate stays ≥ 72%.
- Commands run from `backend/` using `.venv/bin/...`. `asyncio_mode="auto"` — no `@pytest.mark.asyncio`.

---

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `backend/pyproject.toml` | pin `mcp==1.27.2` | T1 |
| `backend/app/config.py` | `mcp_mount_enabled`, `mcp_mount_path` settings | T1 |
| `backend/.env.example` | document new env vars | T1 |
| `backend/app/mcp_server/runtime.py` (new) | `current_principal` ContextVar + trace-service holder | T2 |
| `backend/app/services/usage_service.py` | `check_token_budget(db, user_id) -> str | None` | T3 |
| `backend/app/api/routes/chat.py` | delegate `_check_token_budget` to the shared helper | T3 |
| `backend/app/mcp_server/server.py` | `_with_principal` reads ContextVar + `limited` agent-limiter | T4 |
| `backend/app/mcp_server/tools.py` | budget gate in agent tools + trace svc via runtime holder | T5 |
| `backend/app/mcp_server/asgi.py` (new) | `get_mcp_instance`, `McpAuthMiddleware`, `build_mounted_mcp_app` | T6 |
| `backend/app/main.py` | conditional mount + lifespan `session_manager.run()` + `set_trace_service` | T7 |
| `backend/tests/unit/test_mcp_asgi_auth.py` (new) | two-token isolation, 401, budget-deny, rate-limit | T8 |
| `backend/tests/unit/test_mcp_server.py` | regression additions | T8 |

## Dependency Graph / Parallel Groups

- **Group A (parallel):** T1, T2, T3
- **Group B (parallel):** T4 `depends:[T2]`, T5 `depends:[T2,T3]`
- **Group C:** T6 `depends:[T2,T4]`
- **Group D:** T7 `depends:[T1,T6]`
- **Group E:** T8 `depends:[T4,T5,T6,T7]`

## Plan-time refinements vs spec (intentional)

1. **F3 reuses `agent_limiter`** (`app/core/agent_limiter.py`) which already does per-user concurrency + hourly cap (Redis + in-memory fallback). The spec's proposed new `mcp_rate_limit_per_minute` token-bucket is therefore dropped (YAGNI). MCP inherits `max_concurrent_agent_calls` / `max_agent_calls_per_hour`.
2. **F4 uses a module-level runtime holder** (`runtime.set_trace_service` / `get_trace_service`) populated by the lifespan, NOT `request.app.state` — the mounted sub-app is a separate Starlette app with its own `state`, so the parent's `app.state` is not visible to tools. This also removes the fragile `import app.main` reach-through in `tools.py`.

---

### Task 1: Pin dependency + add mount config

**Files:**
- Modify: `backend/pyproject.toml` (the `mcp>=1.2.0` line)
- Modify: `backend/app/config.py` (after `mcp_api_key_user_id` at ~line 523)
- Modify: `backend/.env.example`
- Test: `backend/tests/unit/test_config_mcp_mount.py` (new)

**Interfaces:**
- Produces: `settings.mcp_mount_enabled: bool` (default `False`), `settings.mcp_mount_path: str` (default `"/mcp"`).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_config_mcp_mount.py
from app.config import settings


def test_mcp_mount_defaults_off():
    assert settings.mcp_mount_enabled is False
    assert settings.mcp_mount_path == "/mcp"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_config_mcp_mount.py -v`
Expected: FAIL with `AttributeError: 'Settings' object has no attribute 'mcp_mount_enabled'`

- [ ] **Step 3: Pin the dependency**

In `backend/pyproject.toml`, change the dependency line from:
```toml
    "mcp>=1.2.0",
```
to:
```toml
    "mcp==1.27.2",
```

- [ ] **Step 4: Add the settings**

In `backend/app/config.py`, immediately after the `mcp_api_key_user_id: str = ""` line, add:
```python
    # MCP HTTP mount (remote multi-tenant). Gated SEPARATELY from mcp_enabled so
    # turning on the stdio MCP surface does not auto-expose the remote HTTP
    # endpoint. The mount requires BOTH mcp_enabled and mcp_mount_enabled.
    mcp_mount_enabled: bool = False
    mcp_mount_path: str = "/mcp"
```

- [ ] **Step 5: Document env vars**

In `backend/.env.example`, near the existing `MCP_ENABLED` entry, add:
```bash
# Mount the MCP server as an HTTP endpoint inside the API process (remote
# multi-tenant). Requires MCP_ENABLED=true as well. Off by default.
MCP_MOUNT_ENABLED=false
MCP_MOUNT_PATH=/mcp
```

- [ ] **Step 6: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_config_mcp_mount.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/pyproject.toml backend/app/config.py backend/.env.example backend/tests/unit/test_config_mcp_mount.py
git commit -m "feat(mcp): pin mcp==1.27.2 and add HTTP-mount config flags"
```

---

### Task 2: Runtime module — principal ContextVar + trace holder

**Files:**
- Create: `backend/app/mcp_server/runtime.py`
- Test: `backend/tests/unit/test_mcp_runtime.py` (new)

**Interfaces:**
- Produces:
  - `current_principal: ContextVar[dict | None]` (default `None`); principal dict shape `{"user_id": str, "email": str}`.
  - `set_trace_service(svc: object | None) -> None`
  - `get_trace_service() -> object | None`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_mcp_runtime.py
from app.mcp_server import runtime


def test_current_principal_defaults_none():
    assert runtime.current_principal.get() is None


def test_principal_set_and_reset():
    token = runtime.current_principal.set({"user_id": "u1", "email": "a@b.c"})
    try:
        assert runtime.current_principal.get()["user_id"] == "u1"
    finally:
        runtime.current_principal.reset(token)
    assert runtime.current_principal.get() is None


def test_trace_service_holder():
    assert runtime.get_trace_service() is None
    sentinel = object()
    runtime.set_trace_service(sentinel)
    try:
        assert runtime.get_trace_service() is sentinel
    finally:
        runtime.set_trace_service(None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_mcp_runtime.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.mcp_server.runtime'`

- [ ] **Step 3: Write the implementation**

```python
# backend/app/mcp_server/runtime.py
"""Request-scoped runtime state for the MCP server.

``current_principal`` carries the authenticated principal resolved by the
HTTP auth middleware so tools read identity from the request context rather
than a process-wide env var (multi-tenant safety). ``*_trace_service`` is a
module-level holder the FastAPI lifespan populates when the MCP app is
mounted, so tools can persist traces without reaching into ``app.main``.
"""

from __future__ import annotations

from contextvars import ContextVar

# Principal dict shape: {"user_id": str, "email": str}.
current_principal: ContextVar[dict | None] = ContextVar("mcp_current_principal", default=None)

_trace_service: object | None = None


def set_trace_service(svc: object | None) -> None:
    global _trace_service  # noqa: PLW0603
    _trace_service = svc


def get_trace_service() -> object | None:
    return _trace_service
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_mcp_runtime.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/mcp_server/runtime.py backend/tests/unit/test_mcp_runtime.py
git commit -m "feat(mcp): add runtime principal ContextVar + trace-service holder"
```

---

### Task 3: Shared token-budget helper + chat delegation

**Files:**
- Modify: `backend/app/services/usage_service.py` (add method to `UsageService`)
- Modify: `backend/app/api/routes/chat.py:72-103` (delegate)
- Test: `backend/tests/unit/test_usage_budget_helper.py` (new)

**Interfaces:**
- Consumes: `UsageService.check_budget(db, user_id, *, daily_limit, monthly_limit) -> dict` (raises `BudgetExceededError`); `EntitlementService().effective_token_limits(db, user_id) -> tuple[int, int]`.
- Produces: `UsageService.check_token_budget(db, user_id) -> str | None` (error string when exhausted, `None` when allowed; fail-open on infra error).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_usage_budget_helper.py
from unittest.mock import AsyncMock, patch

from app.services.usage_service import BudgetExceededError, UsageService


async def test_returns_none_when_within_budget():
    svc = UsageService()
    db = AsyncMock()
    with (
        patch(
            "app.services.entitlement_service.EntitlementService.effective_token_limits",
            new=AsyncMock(return_value=(1000, 0)),
        ),
        patch.object(svc, "check_budget", new=AsyncMock(return_value={"allowed": True})),
    ):
        assert await svc.check_token_budget(db, "u1") is None


async def test_returns_message_when_budget_exceeded():
    svc = UsageService()
    db = AsyncMock()
    with (
        patch(
            "app.services.entitlement_service.EntitlementService.effective_token_limits",
            new=AsyncMock(return_value=(1000, 0)),
        ),
        patch.object(
            svc,
            "check_budget",
            new=AsyncMock(side_effect=BudgetExceededError("Daily token budget exceeded", used=1000, limit=1000)),
        ),
    ):
        msg = await svc.check_token_budget(db, "u1")
        assert msg is not None and "/pricing" in msg


async def test_unlimited_limits_short_circuit():
    svc = UsageService()
    db = AsyncMock()
    with patch(
        "app.services.entitlement_service.EntitlementService.effective_token_limits",
        new=AsyncMock(return_value=(0, 0)),
    ):
        assert await svc.check_token_budget(db, "u1") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_usage_budget_helper.py -v`
Expected: FAIL with `AttributeError: 'UsageService' object has no attribute 'check_token_budget'`

- [ ] **Step 3: Add the method to `UsageService`**

In `backend/app/services/usage_service.py`, add this method to the `UsageService` class (after `check_budget`):
```python
    async def check_token_budget(self, db: AsyncSession, user_id: str) -> str | None:
        """Return an error message when the user's token budget is exhausted,
        else ``None``. Budget *checks* fail open (infra error must not take the
        agent down); budget *breaches* always block. Limits come from plan
        entitlements with a config fallback — the strictest non-zero wins.
        """
        try:
            from app.services.entitlement_service import EntitlementService

            daily, monthly = await EntitlementService().effective_token_limits(db, user_id)
        except Exception:
            logger.warning("Entitlement lookup failed; using config limits", exc_info=True)
            from app.config import settings

            daily = settings.user_daily_token_limit
            monthly = settings.user_monthly_token_limit
        if not daily and not monthly:
            return None
        try:
            await self.check_budget(db, user_id, daily_limit=daily, monthly_limit=monthly)
        except BudgetExceededError as exc:
            logger.warning("Token budget exceeded for user=%s: %s", user_id[:8], exc)
            return str(exc) + " — upgrade your plan at /pricing to continue."
        except Exception:
            logger.warning("Token budget check failed; allowing request", exc_info=True)
        return None
```

- [ ] **Step 4: Rewire chat.py to delegate**

In `backend/app/api/routes/chat.py`, replace the body of `_check_token_budget` (lines ~72-103) with a delegate:
```python
async def _check_token_budget(db: AsyncSession, user_id: str) -> str | None:
    """F-FIN-1: enforce per-user token budgets before running the agent.

    Thin delegate to the shared helper so the MCP surface enforces the same
    gate. Returns an error message when exhausted, ``None`` to proceed.
    """
    return await _usage_svc.check_token_budget(db, user_id)
```

- [ ] **Step 5: Run tests (helper + chat budget regression)**

Run: `.venv/bin/pytest tests/unit/test_usage_budget_helper.py tests/unit -k "budget" -v`
Expected: PASS (new helper tests + existing chat budget tests green)

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/usage_service.py backend/app/api/routes/chat.py backend/tests/unit/test_usage_budget_helper.py
git commit -m "refactor(usage): extract shared check_token_budget; chat delegates"
```

---

### Task 4: `_with_principal` reads ContextVar + agent-limiter on agent tools

**Files:**
- Modify: `backend/app/mcp_server/server.py` (`_with_principal`, tool registrations)
- Test: `backend/tests/unit/test_mcp_with_principal.py` (new)

**Interfaces:**
- Consumes: `runtime.current_principal`; `auth.authenticate()`; `app.core.agent_limiter.agent_limiter.acquire(user_id)->str|None` / `.release(user_id)`.
- Produces: `_with_principal(run, *, tool_name=None, limited=False) -> str` — resolves principal from ContextVar (HTTP) then env (stdio); when `limited=True`, acquires an agent slot keyed on the principal's `user_id` and releases it after, returning a JSON error if the limiter rejects.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_mcp_with_principal.py
import json
from unittest.mock import AsyncMock, patch

from app.mcp_server import runtime, server


async def test_with_principal_prefers_contextvar():
    token = runtime.current_principal.set({"user_id": "ctx-user", "email": ""})
    try:
        captured = {}

        async def run(p):
            captured["uid"] = p["user_id"]
            return "ok"

        # authenticate() must NOT be consulted when a ContextVar principal exists.
        with patch("app.mcp_server.auth.authenticate", new=AsyncMock(side_effect=AssertionError)):
            out = await server._with_principal(run, tool_name="t")
        assert out == "ok"
        assert captured["uid"] == "ctx-user"
    finally:
        runtime.current_principal.reset(token)


async def test_with_principal_falls_back_to_env_auth():
    runtime.current_principal.set(None)
    with patch(
        "app.mcp_server.auth.authenticate",
        new=AsyncMock(return_value={"user_id": "env-user", "email": ""}),
    ):
        out = await server._with_principal(AsyncMock(return_value="ran"), tool_name="t")
    assert out == "ran"


async def test_limited_rejected_when_limiter_blocks():
    runtime.current_principal.set({"user_id": "u1", "email": ""})
    with patch(
        "app.core.agent_limiter.agent_limiter.acquire",
        new=AsyncMock(return_value="Too many concurrent requests"),
    ):
        out = await server._with_principal(AsyncMock(return_value="x"), tool_name="t", limited=True)
    assert json.loads(out)["error"].startswith("Too many concurrent")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_mcp_with_principal.py -v`
Expected: FAIL (`_with_principal` has no `limited` kwarg / does not read ContextVar)

- [ ] **Step 3: Rewrite `_with_principal`**

In `backend/app/mcp_server/server.py`, add imports at top:
```python
from app.core.agent_limiter import agent_limiter
from app.mcp_server import runtime
```
Replace the existing `_with_principal` with:
```python
async def _with_principal(
    run: Callable[[dict], Awaitable[str]],
    *,
    tool_name: str | None = None,
    limited: bool = False,
) -> str:
    """Resolve the caller's identity, then run a tool bound to that principal.

    Identity comes from the request-scoped ContextVar set by the HTTP auth
    middleware; absent that (stdio), we fall back to env-based ``authenticate``.
    When ``limited`` is set the call is gated by the per-user agent limiter
    (shared with chat) for concurrency + hourly caps.
    """
    name = tool_name or getattr(run, "__name__", "anonymous-tool")
    principal = runtime.current_principal.get()
    if principal is None:
        try:
            principal = await auth.authenticate()
        except auth.MCPAuthError as exc:
            logger.warning("MCP tool %s rejected: auth failed (%s)", name, exc)
            return json.dumps({"error": str(exc)})

    user_id = principal.get("user_id") or ""
    if limited:
        rejection = await agent_limiter.acquire(user_id)
        if rejection:
            logger.info("MCP tool %s rate-limited (user=%s)", name, user_id)
            return json.dumps({"error": rejection})

    logger.info("MCP tool %s starting (user=%s)", name, user_id)
    try:
        result = await run(principal)
    except Exception:
        logger.exception("MCP tool %s crashed", name)
        return json.dumps({"error": "Internal tool error"})
    finally:
        if limited:
            await agent_limiter.release(user_id)
    logger.info("MCP tool %s ok (user=%s)", name, user_id)
    return result
```

- [ ] **Step 4: Mark the agent-invoking tools `limited=True`**

In `backend/app/mcp_server/server.py`, update the three agent tools' wrappers to pass `limited=True`:
```python
    async def checkmydata_query_database(
        project_id: str,
        question: str,
        connection_id: str | None = None,
    ) -> str:
        return await _with_principal(
            lambda p: tools.query_database(p, project_id, question, connection_id),
            tool_name="checkmydata_query_database",
            limited=True,
        )
```
```python
    async def checkmydata_search_codebase(project_id: str, question: str) -> str:
        return await _with_principal(
            lambda p: tools.search_codebase(p, project_id, question),
            tool_name="checkmydata_search_codebase",
            limited=True,
        )
```
```python
    async def checkmydata_execute_raw_query(connection_id: str, query: str) -> str:
        return await _with_principal(
            lambda p: tools.execute_raw_query(p, connection_id, query),
            tool_name="checkmydata_execute_raw_query",
            limited=True,
        )
```
(Leave `ping`, `list_projects`, `list_connections`, `get_schema`, and the three resources without `limited` — cheap metadata reads.)

- [ ] **Step 5: Run tests**

Run: `.venv/bin/pytest tests/unit/test_mcp_with_principal.py tests/unit/test_mcp_server.py -v`
Expected: PASS (new tests + existing 40 MCP server tests green)

- [ ] **Step 6: Commit**

```bash
git add backend/app/mcp_server/server.py backend/tests/unit/test_mcp_with_principal.py
git commit -m "feat(mcp): _with_principal reads ContextVar + agent-limiter on agent tools"
```

---

### Task 5: Budget gate in agent tools + trace via runtime holder

**Files:**
- Modify: `backend/app/mcp_server/tools.py` (`query_database`, `search_codebase`, `_get_trace_svc`)
- Test: `backend/tests/unit/test_mcp_tools_budget.py` (new)

**Interfaces:**
- Consumes: `UsageService.check_token_budget(db, user_id) -> str | None`; `runtime.get_trace_service()`.
- Produces: agent tools return `{"error": <budget msg>}` and do NOT run the orchestrator when budget is exhausted.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_mcp_tools_budget.py
import json
from unittest.mock import AsyncMock, MagicMock, patch

from app.mcp_server import tools


async def test_query_database_blocks_when_budget_exhausted():
    principal = {"user_id": "u1", "email": ""}
    project = MagicMock(id="p1", name="Proj")

    with (
        patch.object(tools._project_svc, "get", new=AsyncMock(return_value=project)),
        patch.object(tools, "_require_project_access", new=AsyncMock(return_value=None)),
        patch.object(
            tools._connection_svc, "list_by_project", new=AsyncMock(return_value=[MagicMock(id="c1")])
        ),
        patch.object(
            tools._usage_svc,
            "check_token_budget",
            new=AsyncMock(return_value="Daily token budget exceeded — upgrade your plan at /pricing to continue."),
        ),
        patch.object(tools, "_make_orchestrator") as make_orch,
    ):
        out = await tools.query_database(principal, "p1", "how many users?")

    payload = json.loads(out)
    assert "/pricing" in payload["error"]
    make_orch.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_mcp_tools_budget.py -v`
Expected: FAIL (orchestrator is called; no budget gate yet)

- [ ] **Step 3: Add the module-level usage service**

In `backend/app/mcp_server/tools.py`, add to the existing service singletons block (near `_project_svc = ProjectService()`):
```python
from app.services.usage_service import UsageService

_usage_svc = UsageService()
```

- [ ] **Step 4: Insert the budget gate**

In `query_database`, inside the `async with async_session_factory() as session:` block, after the connection is resolved and BEFORE `config = await _connection_svc.to_config(...)`, add:
```python
        budget_error = await _usage_svc.check_token_budget(session, user_id)
        if budget_error:
            return json.dumps({"error": budget_error})
```
In `search_codebase`, inside its `async with async_session_factory() as session:` block, after the access check and BEFORE the session closes, add:
```python
        budget_error = await _usage_svc.check_token_budget(session, user_id)
        if budget_error:
            return json.dumps({"error": budget_error})
```

- [ ] **Step 5: Replace `_get_trace_svc` with the runtime holder**

In `backend/app/mcp_server/tools.py`, replace the `_get_trace_svc` function with:
```python
def _get_trace_svc():
    """Trace persistence service, populated by the FastAPI lifespan when the
    MCP app is mounted. Returns ``None`` in standalone/stdio mode (traces are
    then skipped explicitly rather than via a fragile app.main reach-through)."""
    from app.mcp_server import runtime

    return runtime.get_trace_service()
```

- [ ] **Step 6: Run tests**

Run: `.venv/bin/pytest tests/unit/test_mcp_tools_budget.py tests/unit/test_mcp_server.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/mcp_server/tools.py backend/tests/unit/test_mcp_tools_budget.py
git commit -m "feat(mcp): token-budget gate on agent tools; trace via runtime holder"
```

---

### Task 6: ASGI mount builder + auth middleware

**Files:**
- Create: `backend/app/mcp_server/asgi.py`
- Test: `backend/tests/unit/test_mcp_asgi_app.py` (new)

**Interfaces:**
- Consumes: `create_mcp_server()`; `auth.authenticate`, `auth.MCPAuthError`; `mcp_key_service.TOKEN_PREFIX`; `runtime.current_principal`.
- Produces:
  - `get_mcp_instance() -> FastMCP` (singleton; same instance used for mount + lifespan `session_manager`).
  - `build_mounted_mcp_app() -> Starlette` (streamable-http app wrapped with `McpAuthMiddleware`).
  - `McpAuthMiddleware` (pure ASGI): 401s requests with no/invalid bearer; sets `current_principal` for valid ones.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_mcp_asgi_app.py
from unittest.mock import AsyncMock, patch

import httpx

from app.mcp_server.asgi import McpAuthMiddleware, get_mcp_instance


def test_get_mcp_instance_is_singleton():
    assert get_mcp_instance() is get_mcp_instance()


async def _ok_app(scope, receive, send):
    # Minimal ASGI echo of the resolved principal user_id.
    from app.mcp_server import runtime

    principal = runtime.current_principal.get()
    body = (principal or {}).get("user_id", "none").encode()
    await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"text/plain")]})
    await send({"type": "http.response.body", "body": body})


async def test_missing_bearer_is_401():
    app = McpAuthMiddleware(_ok_app)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        r = await client.post("/mcp")
    assert r.status_code == 401
    assert r.headers.get("www-authenticate") == "Bearer"


async def test_valid_bearer_sets_principal():
    app = McpAuthMiddleware(_ok_app)
    transport = httpx.ASGITransport(app=app)
    with patch(
        "app.mcp_server.asgi._resolve_principal",
        new=AsyncMock(return_value={"user_id": "tok-user", "email": ""}),
    ):
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            r = await client.post("/mcp", headers={"Authorization": "Bearer cmd_mcp_abc"})
    assert r.status_code == 200
    assert r.text == "tok-user"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_mcp_asgi_app.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.mcp_server.asgi'`

- [ ] **Step 3: Write the implementation**

```python
# backend/app/mcp_server/asgi.py
"""ASGI mount + per-request auth for the MCP server (remote multi-tenant).

The FastMCP streamable-http app is a Starlette app; we wrap it with a pure
ASGI middleware (NOT BaseHTTPMiddleware — that runs the inner app in a
separate anyio task and would drop the ContextVar) that resolves the bearer
token to a principal and stores it in ``runtime.current_principal`` for the
duration of the request.
"""

from __future__ import annotations

import json
import logging

from starlette.applications import Starlette
from starlette.datastructures import Headers

from app.mcp_server import auth, runtime
from app.mcp_server.server import create_mcp_server
from app.services.mcp_key_service import TOKEN_PREFIX

logger = logging.getLogger(__name__)

_mcp_instance = None


def get_mcp_instance():
    """Return the process-wide FastMCP instance (same one used for the mount
    and the lifespan session manager)."""
    global _mcp_instance  # noqa: PLW0603
    if _mcp_instance is None:
        _mcp_instance = create_mcp_server()
    return _mcp_instance


async def _resolve_principal(token: str | None) -> dict:
    """Resolve a bearer token to a principal, raising MCPAuthError on failure."""
    if not token:
        raise auth.MCPAuthError("MCP authentication required: missing bearer token")
    if token.startswith(TOKEN_PREFIX):
        return await auth.authenticate(api_key=token)
    return await auth.authenticate(token=token)


def _extract_token(headers: Headers) -> str | None:
    authz = headers.get("authorization")
    if authz and authz.lower().startswith("bearer "):
        return authz[7:].strip()
    return headers.get("x-api-key")


class McpAuthMiddleware:
    """Pure ASGI middleware: bearer token -> current_principal, or 401."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        try:
            principal = await _resolve_principal(_extract_token(headers))
        except auth.MCPAuthError as exc:
            await self._unauthorized(send, str(exc))
            return
        token = runtime.current_principal.set(principal)
        try:
            await self.app(scope, receive, send)
        finally:
            runtime.current_principal.reset(token)

    @staticmethod
    async def _unauthorized(send, message: str) -> None:
        body = json.dumps({"error": message}).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"www-authenticate", b"Bearer"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


def build_mounted_mcp_app() -> Starlette:
    """Return the streamable-http Starlette app wrapped with auth middleware."""
    mcp = get_mcp_instance()
    app = mcp.streamable_http_app()
    app.add_middleware(McpAuthMiddleware)
    return app
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/pytest tests/unit/test_mcp_asgi_app.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/mcp_server/asgi.py backend/tests/unit/test_mcp_asgi_app.py
git commit -m "feat(mcp): ASGI mount builder + pure-ASGI bearer auth middleware"
```

---

### Task 7: Mount into FastAPI + lifespan wiring

**Files:**
- Modify: `backend/app/main.py` (lifespan + mount after `app = FastAPI(...)`)
- Test: `backend/tests/unit/test_mcp_mount_wiring.py` (new)

**Interfaces:**
- Consumes: `build_mounted_mcp_app()`, `get_mcp_instance()`, `runtime.set_trace_service`.
- Produces: when `settings.mcp_enabled and settings.mcp_mount_enabled`, a `/mcp` route exists on `app` and the lifespan runs the MCP `session_manager` + publishes the trace service to `runtime`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_mcp_mount_wiring.py
import importlib
from unittest.mock import patch


def _routes_contain_mcp(app) -> bool:
    return any(getattr(r, "path", "").startswith("/mcp") for r in app.routes)


def test_mount_absent_when_flag_off():
    import app.main as main_mod

    with patch.object(main_mod.settings, "mcp_mount_enabled", False):
        importlib.reload(main_mod)
    assert not _routes_contain_mcp(main_mod.app)
    importlib.reload(main_mod)  # restore default module state


def test_mount_present_when_flags_on():
    import app.main as main_mod

    with patch.object(main_mod.settings, "mcp_enabled", True), patch.object(
        main_mod.settings, "mcp_mount_enabled", True
    ):
        importlib.reload(main_mod)
        assert _routes_contain_mcp(main_mod.app)
    importlib.reload(main_mod)  # restore default module state
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_mcp_mount_wiring.py -v`
Expected: FAIL (`test_mount_present_when_flags_on` — no `/mcp` route)

- [ ] **Step 3: Publish the trace service in the lifespan**

In `backend/app/main.py`, immediately after the existing line `app.state.trace_persistence_service = _trace_svc` (~line 152), add:
```python
    from app.mcp_server import runtime as _mcp_runtime

    _mcp_runtime.set_trace_service(_trace_svc)
```

- [ ] **Step 4: Run the MCP session manager inside the lifespan**

In `backend/app/main.py`, wrap the `yield` so the MCP session manager runs when mounted. Replace the bare `yield` (~line 161) with:
```python
    from contextlib import AsyncExitStack

    async with AsyncExitStack() as _mcp_stack:
        if settings.mcp_enabled and settings.mcp_mount_enabled:
            from app.mcp_server.asgi import get_mcp_instance

            await _mcp_stack.enter_async_context(get_mcp_instance().session_manager.run())
        yield
```
(The existing post-yield cleanup — `await _trace_svc.stop()` etc. — stays exactly where it is, after this block.)

- [ ] **Step 5: Mount the app**

In `backend/app/main.py`, after `app.state.limiter = limiter` (~line 267), add:
```python
if settings.mcp_enabled and settings.mcp_mount_enabled:
    from app.mcp_server.asgi import build_mounted_mcp_app

    app.mount(settings.mcp_mount_path, build_mounted_mcp_app())
    logger.info("MCP server mounted at %s", settings.mcp_mount_path)
```

- [ ] **Step 6: Run tests**

Run: `.venv/bin/pytest tests/unit/test_mcp_mount_wiring.py -v`
Expected: PASS (2 passed)

- [ ] **Step 7: Commit**

```bash
git add backend/app/main.py backend/tests/unit/test_mcp_mount_wiring.py
git commit -m "feat(mcp): mount MCP app into FastAPI + lifespan session manager/trace wiring"
```

---

### Task 8: End-to-end multi-tenant integration test

**Files:**
- Create: `backend/tests/unit/test_mcp_asgi_auth.py`
- Test: itself

**Interfaces:**
- Consumes: `build_mounted_mcp_app()` / `McpAuthMiddleware`, `auth.authenticate`, the tool layer.

This task proves the F1 fix end-to-end: two different bearer tokens resolve to two different principals through the real mounted middleware (the gap the env-patching tests structurally cannot catch).

- [ ] **Step 1: Write the test**

```python
# backend/tests/unit/test_mcp_asgi_auth.py
"""F1 regression: per-request principal isolation over the HTTP mount.

Drives McpAuthMiddleware with two different tokens and asserts each request
sees its own principal — something the env-var-based auth tests cannot prove.
"""

from unittest.mock import AsyncMock, patch

import httpx

from app.mcp_server import runtime
from app.mcp_server.asgi import McpAuthMiddleware


async def _echo_principal_app(scope, receive, send):
    principal = runtime.current_principal.get()
    body = (principal or {}).get("user_id", "none").encode()
    await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"text/plain")]})
    await send({"type": "http.response.body", "body": body})


def _fake_authenticate(*, api_key=None, token=None):
    # Map token suffix -> user id, mimicking per-user cmd_mcp_ resolution.
    mapping = {"cmd_mcp_AAA": "user-a", "cmd_mcp_BBB": "user-b"}
    cred = api_key or token
    if cred in mapping:
        return {"user_id": mapping[cred], "email": ""}
    from app.mcp_server.auth import MCPAuthError

    raise MCPAuthError("MCP token is invalid, revoked, or expired")


async def test_two_tokens_resolve_to_two_principals():
    app = McpAuthMiddleware(_echo_principal_app)
    transport = httpx.ASGITransport(app=app)
    with patch("app.mcp_server.asgi.auth.authenticate", new=AsyncMock(side_effect=_fake_authenticate)):
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            ra = await client.post("/mcp", headers={"Authorization": "Bearer cmd_mcp_AAA"})
            rb = await client.post("/mcp", headers={"Authorization": "Bearer cmd_mcp_BBB"})
    assert ra.text == "user-a"
    assert rb.text == "user-b"


async def test_invalid_token_is_401_and_leaves_no_principal():
    app = McpAuthMiddleware(_echo_principal_app)
    transport = httpx.ASGITransport(app=app)
    with patch("app.mcp_server.asgi.auth.authenticate", new=AsyncMock(side_effect=_fake_authenticate)):
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            r = await client.post("/mcp", headers={"Authorization": "Bearer cmd_mcp_NOPE"})
    assert r.status_code == 401
    # ContextVar must be clean after the request (no leakage across requests).
    assert runtime.current_principal.get() is None
```

- [ ] **Step 2: Run the test**

Run: `.venv/bin/pytest tests/unit/test_mcp_asgi_auth.py -v`
Expected: PASS (2 passed)

- [ ] **Step 3: Full MCP regression + lint + type + format**

Run:
```bash
.venv/bin/pytest tests/unit -k "mcp or budget or usage" -v
.venv/bin/ruff format app/ tests/
.venv/bin/ruff check app/ tests/
.venv/bin/mypy app/ --ignore-missing-imports
```
Expected: all green; ruff/format/mypy clean.

- [ ] **Step 4: Coverage gate check**

Run: `.venv/bin/pytest tests/unit tests/integration --cov=app --cov-report=term-missing -q` then `.venv/bin/coverage report --fail-under=72`
Expected: combined coverage ≥ 72%.

- [ ] **Step 5: Commit**

```bash
git add backend/tests/unit/test_mcp_asgi_auth.py
git commit -m "test(mcp): per-request principal isolation over HTTP mount (F1 regression)"
```

---

## Self-Review

**Spec coverage:**
- F1 (per-request auth) → T2 (ContextVar), T4 (`_with_principal` reads it), T6 (middleware), T8 (proof). ✅
- F2 (budget gate) → T3 (shared helper), T5 (wired into agent tools). ✅
- F3 (rate-limit/concurrency) → T4 (`agent_limiter` on agent tools). ✅
- F4 (trace persistence) → T2 (holder), T5 (`_get_trace_svc`), T7 (lifespan publishes). ✅
- F7 (pin) → T1. ✅
- F8 (tests) → T8 + per-task tests. ✅
- G6 (no regression) → existing `test_mcp_server.py` rerun in T4/T5; stdio fallback covered in T4. ✅

**Placeholder scan:** none — every code/test step has concrete content.

**Type consistency:** `check_token_budget(db, user_id) -> str | None` consistent T3↔T5; `_with_principal(..., limited=False)` consistent T4↔(server tools); `current_principal` / `get_trace_service` / `set_trace_service` consistent T2↔T4↔T5↔T7; `get_mcp_instance` / `build_mounted_mcp_app` / `McpAuthMiddleware` / `_resolve_principal` consistent T6↔T7↔T8.

## Manual / human steps (post-merge, optional)

- Smoke-test against a running instance with `MCP_ENABLED=true MCP_MOUNT_ENABLED=true` using two real `cmd_mcp_` tokens (curl the `/mcp` initialize + a tool call) to confirm end-to-end multi-tenant behaviour beyond the ASGITransport test.
- Update `docs/MCP_SERVER.md` "Transports" section to document the mounted HTTP endpoint and per-request bearer auth (doc-only; can be folded into the implementation branch or a follow-up).
