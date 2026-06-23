# MCP Protocol-Polish — Batched Implementation Plan

> Autonomous batched execution. Each batch: TDD → ruff/mypy → suite → commit → merge `main` → push (deploy) → verify prod logs → next. Spec: `docs/superpowers/specs/2026-06-23-mcp-protocol-polish-design.md`.

**Global constraints:** ruff `E F I N W UP`, line 100, format+check clean; mypy clean (touched files); `mcp==1.27.2`; no regression to ~250 MCP/budget/usage tests; tenancy + fail-closed auth unchanged; coverage ≥72% at the end.

Commands run from `backend/` via `.venv/bin/...`. Prod: app `checkmydata-api`, base `https://checkmydata-api-990b0bcf28ab.herokuapp.com`.

---

## Batch B1 — Error contract (F6: `isError`)

**Files:** `app/mcp_server/tools.py`, `app/mcp_server/resources.py`, `app/mcp_server/server.py`, tests.

**Behaviour:** actionable failures raise `ToolError` (→ FastMCP `isError=true`) instead of returning a normal result whose body is `{"error":…}`.

- **B1.1 — verify the FastMCP convention (TDD spike).** Write a test that registers a tool raising `ToolError("boom")`, calls it through the server, asserts the `CallToolResult.isError is True` and the message is in content. Confirm the exact call path (`mcp.call_tool` or low-level). Lock the convention.
- **B1.2 — `_with_principal` propagates errors as `ToolError`.** Auth failure → `raise ToolError(str(exc))`; rate-limit rejection → `raise ToolError(rejection)`; unexpected `Exception` → `logger.exception` then `raise ToolError("Internal tool error")`. Keep agent-limiter acquire before `try`, release in `finally`. Return type stays the tool's normal value on success.
- **B1.3 — tools raise instead of return-error-json.** In `tools.py` replace each `return json.dumps({"error": msg})` (access denied, project/connection not found, no connections, no schema index, not-read-only, safety block, raw-query failure) with `raise ToolError(msg)`. Success paths unchanged (still return the JSON string for now — structured output is B2).
- **B1.4 — resources raise.** In `resources.py` `_denied`/error returns → `raise ToolError(msg)`.
- **B1.5 — update existing tests** that asserted `json.loads(out)["error"]` to instead assert `pytest.raises(ToolError)` (or the server-level isError result). Keep cross-tenant-deny coverage intact (now via raised ToolError).
- **DoD:** suite green, ruff/mypy clean. **Release:** merge→push→deploy→verify (`/mcp` 401, health 200, boot clean). Update CHANGELOG `[Unreleased]`.

---

## Batch B2 — Structured output (F5: `structuredContent` + `outputSchema`)

**Files:** `app/mcp_server/server.py` (tool registrations), `app/mcp_server/tools.py`, tests.

- **B2.1 — verify convention (TDD spike).** Register a tool with `structured_output=True` returning a `dict`; call it; assert `CallToolResult.structuredContent` is the dict and `outputSchema` is present on the tool listing. Decide the return convention (dict vs Pydantic model) from what the SDK actually emits.
- **B2.2 — typed return models.** Add Pydantic result models (or `TypedDict`/`dict`) for the JSON tools: `ping`, `list_projects`, `list_connections`, `get_schema`, `query_database`, `execute_raw_query`. Tools return the object; `_with_principal`/registration carry the typed return so FastMCP emits `outputSchema`.
- **B2.3 — preserve `response_format`.** For `list_projects/list_connections/get_schema`, `response_format="markdown"` keeps returning a text (markdown) result (no structuredContent); `"json"` returns the structured object. Document that markdown is a presentation mode.
- **B2.4 — `_with_principal` return type** widened from `str` to the structured value / text; serialization handled by FastMCP. Adjust signature + tests.
- **DoD + Release** as B1. CHANGELOG.

---

## Batch B3 — Cleanups + minors (F9 + polish)

**Files:** `app/mcp_server/tools.py`, `app/mcp_server/resources.py`, `app/mcp_server/server.py`, `app/mcp_server/asgi.py`, `app/mcp_server/auth.py`, `app/mcp_server/__main__.py`, `app/services/trace_persistence_service.py`, `tests/unit/test_config_mcp_mount.py`, tests.

- **B3.1 — `is_active` default connection.** In `query_database`, when no `connection_id`, pick `next((c for c in connections if getattr(c, "is_active", True)), connections[0])`. Test: inactive-first list → active chosen.
- **B3.2 — resource pagination.** `resources.get_project_schema` gains `offset:int=0, limit:int=50` with `has_more`/`next_offset`; register on the resource (or a paginated variant). Test: >limit tables → paged.
- **B3.3 — sse deprecation.** `__main__.py` help text marks `sse` deprecated (keep accepted for back-compat); no behaviour change. Test: argparse still accepts; help string contains "deprecated".
- **B3.4 — typed principal.** `Principal = TypedDict("Principal", {"user_id": str, "email": str})` in `runtime.py`; annotate `authenticate`/`_resolve_principal`/`current_principal`/`_with_principal`. mypy clean.
- **B3.5 — quiet userless-sync trace warning.** In `trace_persistence_service`, the "skipping initial persist … empty project_id/user_id" log → `debug` when context is a known sync/userless workflow (gate on empty user_id for sync run types), so prod logs stay clean. Test: warning not emitted for userless sync; still informative at debug.
- **B3.6 — `test_config_mcp_mount` robustness.** Instantiate a fresh `Settings()` (not the module singleton) and assert defaults; resilient to env.
- **DoD + Release** as B1.

---

## Final acceptance (after B3 deployed)

1. `cd backend && .venv/bin/pytest tests/unit tests/integration --cov=app -q` then `.venv/bin/coverage report --fail-under=72` → green.
2. `.venv/bin/ruff format --check app/ tests/ && .venv/bin/ruff check app/ tests/ && .venv/bin/mypy app/ --ignore-missing-imports` → clean.
3. Prod: latest release deployed; `/api/health`=200; `/mcp/` no-auth=401; dyno logs clean (no tracebacks); boot `MCP server mounted at /mcp`.
4. CHANGELOG `[Unreleased]` covers F5/F6/F9; wiki `concepts/mcp-server.md` refreshed (protocol-polish shipped).
5. If any prod log regression → fix forward + redeploy until green.
