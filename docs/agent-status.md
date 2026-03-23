# Agent Status

## Current Cycle

| Field | Value |
|-------|-------|
| Cycle | Cycle 6 — Reliability & Security Hardening |
| Started | 2026-03-23 |
| Status | Complete |
| Tasks Planned | 5 |
| Tasks Completed | 5 |

## Health Summary

| Check | Status | Details |
|-------|--------|---------|
| Frontend TypeScript | PASS | 0 errors |
| Frontend ESLint | PASS | 0 warnings |
| Frontend Tests (Vitest) | PASS | 346/346 |
| Frontend Build | PASS | All routes compiled |
| Backend Ruff Lint | PASS | 0 violations |
| Backend Ruff Format | PASS | 416 files formatted |
| Backend Mypy | PASS | 0 errors |
| Backend Unit Tests | PASS | 2482/2482 |
| Backend Integration Tests | PASS | 410/410 |
| Backend Coverage (unit-only) | 72.00% | CI threshold: 72% |
| CI Pipeline | GREEN | All checks pass |

## Changes This Cycle

5 reliability and security fixes:

1. **SSE subscriber leak (P0)** — Wrapped entire SSE generator in `try/finally` to guarantee `tracker.unsubscribe()` and `agent_limiter.release()` even on client disconnect. Previously, subscriber cleanup was spread across 4 branches with gaps when the client dropped the connection.
2. **WebSocket agent_limiter bypass (P0)** — Applied `agent_limiter.acquire/release` to the WebSocket chat handler. Previously only the REST `/ask/stream` endpoint enforced per-user rate limits; WebSocket was uncapped.
3. **WebSocket message length cap (P1)** — Added 20,000 char limit to WebSocket messages, matching the REST `ChatRequest.message` `Field(max_length=20000)` validation.
4. **Markdown link XSS prevention (P1)** — Sanitized `href` in ChatMessage and SQLExplainer markdown renderers to only allow `http://` and `https://` schemes, blocking `javascript:` and other dangerous URIs.
5. **Dashboard load race condition (P1)** — Replaced shared `mountedRef` boolean with a monotonic request counter (`requestIdRef`) so that stale responses from slow API calls are discarded when the route `id` changes quickly.

Additional: 4 new unit tests (retry_strategy EXPLAIN_WARNING, LLMError.user_message, chunker no-boundary split) to maintain 72% coverage.

## Known Issues (Remaining)

1. **`notes.md` credentials** — Still on disk. User should rotate.
2. **Mypy untyped functions** — 23 `annotation-unchecked` notes across connector and LLM modules. Non-blocking.
3. **Dead code** — `exploration_engine.py` line 326 (`positive_count` in summary) is unreachable. Consider removing.
4. **Dead code** — `cli_output_parser.py` line 38 (`if not all_rows` after non-empty csv.reader) is unreachable.
5. **Health /modules endpoint** — Unauthenticated, calls live LLM. Should require auth or be simplified.
6. **Unbounded query params** — Several endpoints accept large `limit`/`offset` without strict bounds (notifications, insights).
7. **Metrics keys unbounded** — MetricsMiddleware creates per-path entries; UUID paths cause slow growth.

## Next Cycle Priorities

1. Protect `/api/health/modules` (add auth or remove live LLM call)
2. Clamp query param bounds (limit/offset) across API routes
3. Cap MetricsMiddleware path cardinality
4. Browser-based flow testing (onboarding, chat, insights)
5. Continue coverage improvement toward 75% target
