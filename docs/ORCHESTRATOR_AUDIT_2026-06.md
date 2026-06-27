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

## Remaining (tracked follow-ups)

Lower-severity or larger-design items deliberately deferred from this release; none are
security/data-loss blockers.

### High (deferred — design risk)
- **`direct` mis-route has no recovery.** A question wrongly routed `direct` answers with no
  tools/traceability. Fix needs a router-prompt hardening + a "needs data" re-route escape;
  deferred to avoid a half-baked heuristic. (router.py / orchestrator `_run_direct_response`)
- **MCP `isError` not surfaced.** `MCPClientAdapter.call_tool` returns `str` and ignores the
  SDK `result.isError`, so a tool-level error is indistinguishable from data. Needs an
  `mcp_client.py` contract change (structured result). The new timeout already prevents hangs.

### Medium
- Compounded retry ceiling (per-stage × validation × data-gate × replan) — add a per-pipeline
  wall-clock/dispatch budget in `StageExecutor.execute`.
- Unified-loop wall-clock only checked at iteration top — thread `remaining_wall_seconds` into
  all sub-agent handlers (only SQL gets it today).
- `process_data` reads `bucket[-1]` with no ordering guarantee in a sequential batch.
- Large tool results enter context uncondensed (cap only on later trim).
- Empty-result repair loop can re-run an equivalent query (no identity guard) and reports a
  valid-empty as a failure.
- Transient DB connection errors classified non-retryable in `ValidationLoop`.
- Dynamic per-query timeout not threaded into `connector.execute_query` (static 30s used).
- DataGate value-range hard check scans only the first 50 in-memory rows.
- Router runs on the user's premium model (`router_model` config is dead); `estimated_queries`
  unused contract drift.
- Pipeline resume has no idempotency guard against duplicate concurrent runs; resume reads
  sample-only rows as if full.
- Replan can repeat a near-identical failing plan (no plan fingerprint/oscillation guard).
- Auto-investigate trigger false-positive surface (`row_count==0` on the synthesis path);
  add a budget-enforcement flag (`auto_investigate_budget_enforcement_enabled`).
- Source attribution collected only for `search_knowledge` (not entity/Git/MCP).

### Low
- `_extract_json` brittle on trailing text / nested JSON; router `max_tokens=200` truncation.
- `_stream_tokens` event churn; `_ended_workflows`/`_workflow_owners` unbounded in cross-process.
- Cross-stage / business-rule checks fail open (warn-only) — document or strengthen.
- `_ensure_validation_criteria` mislabels `process_data.min_rows`; `build_context_for_stage`
  unbounded dependency serialization.
- Reconciliation `_parse_number` accepts non-finite floats.
- WS endpoint has no SlowAPI rate limit / idle timeout; WS path omits pipeline-action plumbing.
