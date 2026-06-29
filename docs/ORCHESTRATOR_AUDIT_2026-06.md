# Orchestrator audit & remediation — 2026-06

Multi-specialist audit of the orchestrator (command intake → routing → planning →
execution → data acquisition → validation → bad-data/replan/learning loops), with
remediation on branch `fix/orchestrator-audit-remediation-2026-06`.

Methodology: TDD (failing test first) per fix; an independent adversarial review of
the branch (whose findings were folded back in); `make smoke` startup self-check on
the revenue-by-payment-method + weekly-cohort scenario; backend suite 4635 passing at
75.39% coverage; ruff/mypy clean; frontend `tsc` clean.

## Fixed in this release

| # | Severity | Area | Finding |
|---|----------|------|---------|
| 1 | CRITICAL | DataGate | Semantic value-range gate was dead in prod (keyword-only, narrow); revived with token-based classification, bounded-percent vs loose-rate split, negative-count hard check. |
| 2 | High | chat (SSE/WS) | Cross-tenant workflow-event leak — subscriptions now scoped by `user_id`+project. |
| 3 | High | DataGate | Hard-check domain too narrow (no negative counts / impossible bounded %). |
| 4 | High | stage_executor | `process_data` scavenged an unrelated dataset when declared deps were empty. |
| 5 | High | stage_executor | Deterministic exceptions classified `transient` and retried. |
| 6 | High | mcp_source_agent | External MCP calls had no wall-clock timeout; max-iter exhaustion reported `success`. |
| 7 | High | sql_agent | Truncated results hidden from the LLM (wrong aggregates). |
| 8 | High | connectors | `row_count` semantics inconsistent across dialects (Mongo pre-cap vs SQL capped). |
| 9 | High | answer_validator | Parse failures were fail-open despite `answer_validator_fail_closed`. |
| 10 | High | query_planner | Missing `stage_id`/`description` passed validation → `KeyError` mid-planning; duplicate ids mislabeled. |
| 11 | High | orchestrator | Budget hard-stop never emitted terminal `pipeline_end`. |
| 12 | High | orchestrator | `executed_pairs[tc.id]` `KeyError` discarded the whole turn on duplicate tool-call id. |
| 13 | High | orchestrator | Generic handler leaked raw `str(exc)` (DSN/host) to the client. |
| 14 | High | orchestrator | Replan with dangling deps wasted the replan budget on a doomed plan. |
| 15 | High | history_trimmer | Mid-loop trim orphaned `tool_call`↔`tool` pairs → provider 400 lost the turn. |
| 16 | High | chat | `POST /api/chat/ask` bypassed `agent_limiter` (concurrency/hourly caps); added slot + timeout. |
| 17 | High | investigate | Auto-investigation bypassed token budget + limiter; verdict dead-ended in a DB row (now a Notification). |

## Follow-up remediation (2026-06-29)

All 21 deferred follow-ups from the section above were subsequently remediated (TDD,
one commit per finding) on branch `fix/orchestrator-audit-followups-2026-06`.

### High (were design-risk)
- **C1 — `direct` mis-route recovery.** Model-driven re-route: router prompt hardened; the
  direct LLM emits a `NEEDS_DATA_SENTINEL` (only when a data source exists) and
  `_run_direct_response` returns `None` so the caller falls through to the tool loop.
- **C2 — MCP `isError` surfaced.** `MCPClientAdapter.call_tool` now returns a structured
  `MCPToolCallResult(text, is_error)`; `McpSourceAgent` flags errored results to the LLM.

### Medium
- **B4** per-pipeline wall-clock budget in `StageExecutor.execute` (`pipeline_max_wall_seconds`).
- **B5** `remaining_wall_seconds` respected for all expensive sub-agents (dispatch-level guard).
- **A1** `process_data` batched with a fresh `query_database` is deferred (no stale `bucket[-1]`).
- **B6** hard per-result ceiling at insertion (`tool_result_insert_max_chars`).
- **A2** empty-result repair identity guard + valid-empty returned as success.
- **A3** transient connection errors retried (same-query backoff) in `ValidationLoop`.
- **B2** dynamic per-query timeout threaded into every connector's `execute_query`.
- **A5** DataGate value-range hard check scans the full in-memory result by default.
- **B1** router uses configured `router_model`; `estimated_queries` now drives `use_complex_pipeline`.
- **B7** in-process resume idempotency guard + sample-only restores flagged `truncated`.
- **B3** replan oscillation guard via plan fingerprint.
- **B8** `auto_investigate_budget_enforcement_enabled` (skip on over-budget / unresolved owner).
- **B9** entity-info lookups attributed as sources. *Carried forward:* top-level Git/MCP citation
  needs a dedicated `AgentResponse.sources` field (separate from `knowledge_sources`, which drives
  response-type) — a response-schema change, intentionally not overloaded here.

### Low
- **L1** robust `_extract_json` (`raw_decode`, nested/trailing-safe); router `max_tokens` → 512.
- **L2** `_workflow_owners` FIFO-bounded; `_stream_tokens` event count capped.
- **L3** cross-stage / business-rule checks documented as intentionally fail-open (advisory).
- **L4** `process_data` defaults `min_rows=0`; `build_context_for_stage` field-capped.
- **A4** reconciliation `_parse_number` rejects non-finite floats.
- **L5** WS idle timeout + pipeline-action plumbing (rate limiting already via `agent_limiter`).
