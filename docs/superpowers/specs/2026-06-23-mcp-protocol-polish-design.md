# MCP Protocol-Polish & Cleanups (Design Spec)

- **Date:** 2026-06-23
- **Branch:** `feat/mcp-protocol-polish`
- **Status:** Approved (autonomous batched execution authorized by user)
- **Predecessor:** remote-hardening (`docs/superpowers/specs/2026-06-22-mcp-server-hardening-design.md`) — now live in prod (Heroku v175, `MCP_MOUNT_ENABLED=true`).
- **Execution model:** **batched** — each batch is implemented (TDD), tested, linted, committed, **merged to `main` + pushed (released/deployed)**, and **verified in prod logs** before the next batch. Autonomous, no stops.

---

## 1. Scope — "all remaining edits"

Deferred protocol-polish (F5/F6/F9) from the audit + the noted Minors, grouped into three releasable batches. Each batch leaves the MCP server fully working.

| Batch | Items | Risk |
|---|---|---|
| **B1 — error contract** | F6: tool errors signal `isError=true` (raise `ToolError`) instead of returning a normal result with an `{"error":…}` string | low/med (response-shape change, live endpoint) |
| **B2 — structured output** | F5: tools emit `structuredContent` + auto `outputSchema` (typed returns) while preserving a text rendering and the `response_format` switch | med |
| **B3 — cleanups + minors** | F9: `is_active` preference in `query_database` connection pick; pagination for the `project_schema` resource; deprecate `sse` from the default transport help/choices. Minors: typed principal (`TypedDict`), quiet the userless-sync `TracePersistence` warning, robust `test_config_mcp_mount` | low |

**Out of scope:** anything requiring a new product decision; the standalone-process auth model (unchanged); `fix/alembic-boolean-default-postgres` branch deletion (needs operator action — its content is already in `main`).

## 2. Goals / non-goals

- **G1** Each batch ships green (ruff format+check, mypy on touched files, tests) and deploys cleanly to prod (v176+), verified via logs + `/mcp` fail-closed smoke.
- **G2** No regression: existing ~250 MCP/budget/usage tests stay green; tenancy + fail-closed auth unchanged.
- **G3** Backward-compatible where feasible; where the MCP protocol mandates a shape change (isError, structuredContent), it is the correct behaviour and acceptable on a day-old, bearer-walled, near-zero-consumer endpoint.
- **Non-goal:** rewriting the tool layer; changing auth/tenancy/budget semantics.

## 3. Contracts (grounded in installed `mcp==1.27.2`)

- **F6:** `from mcp.server.fastmcp.exceptions import ToolError`. A tool that `raise ToolError(msg)` produces `CallToolResult(isError=True, content=[text=msg])`. So actionable tool failures (access denied, not found, budget exhausted, safety block, rate-limit, internal error) **raise `ToolError`** rather than `return json.dumps({"error":…})`. `_with_principal` stops swallowing into an error-string and lets `ToolError` propagate; it still wraps unexpected `Exception` → `ToolError("Internal tool error")`; the agent-limiter `finally`-release is preserved.
- **F5:** `@mcp.tool(..., structured_output=True)` + a tool returning a JSON-serialisable object (dict / Pydantic model) yields `structuredContent` and an auto-generated `outputSchema`. Tools keep returning a human-readable text rendering too (FastMCP derives `content` text from the structured value, or we provide it). The `response_format="markdown"` switch on list tools is preserved by keeping those returning text (markdown is presentation, not structured data) — structured output is applied to the JSON path. Exact return convention verified by TDD in B2.
- **F9:** `query_database` prefers an `is_active` connection when defaulting (`next((c for c in connections if c.is_active), connections[0])`). The `project_schema` resource gains `offset`/`limit` table pagination with `has_more`/`next_offset` (mirroring the tool). `__main__.py` marks `sse` deprecated in help and keeps `stdio`/`streamable-http` as the documented choices.
- **Minors:** principal dict → a `TypedDict` (`Principal{user_id:str,email:str}`) used across `auth`/`asgi`/`runtime`/`server`; `TracePersistence` "skipping initial persist … empty project_id/user_id" downgraded to `debug` when the workflow is a known userless sync (or gated on truly-empty context) so prod logs stay clean; `test_config_mcp_mount` instantiates a fresh `Settings()` instead of the module singleton.

## 4. Per-batch Definition of Done (identical shape)

1. TDD: failing test → impl → green.
2. `cd backend && .venv/bin/ruff format app/ tests/ && .venv/bin/ruff check app/ tests/ && .venv/bin/mypy app/ --ignore-missing-imports` clean (branch-touched files).
3. Full MCP suite green: `.venv/bin/pytest tests/unit -k "mcp or budget or usage" -v`.
4. Commit → `git checkout main && git merge --no-ff feat/mcp-protocol-polish` (or ff) → `git push origin main`.
5. CI green → Heroku auto-deploy → new release vN.
6. Verify: `/api/health`=200, `/mcp/` no-auth=401 (fail-closed intact), boot log `Application startup complete` + `MCP server mounted at /mcp`, no errors/tracebacks in dyno logs.
7. If logs show a regression → fix forward (same batch) before next batch.

## 5. Final acceptance (after B3)

- Full unit suite + coverage gate (`coverage report --fail-under=72`) green.
- ruff format+check, mypy clean.
- Prod release deployed, health 200, `/mcp` fail-closed, logs clean.
- CHANGELOG `[Unreleased]` updated; wiki concept page refreshed.

## 6. Risks

- **R1 — isError breaks a client parsing `{"error":…}`.** Mitigation: endpoint enabled today, bearer-walled, near-zero consumers; isError is the correct MCP contract. Document in CHANGELOG.
- **R2 — structured-output return convention** differs from assumption. Mitigation: B2 verifies the exact FastMCP convention via TDD before converting all tools; convert incrementally with the suite green.
- **R3 — per-batch prod deploy churn.** Mitigation: each batch is independently green and verified in prod before the next; fail-forward within the batch.
