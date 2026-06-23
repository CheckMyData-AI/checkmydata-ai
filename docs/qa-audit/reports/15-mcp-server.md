# Module 15 — MCP Server — Audit Report

**Round 1** · 2026-06-24 · Scope: `mcp_server/{auth,asgi,tools,resources,server,runtime}.py`,
`services/mcp_key_service.py` (scanned). Context: MCP HTTP mount is **live in production**
(obs 20559) and was the subject of a prior comprehensive audit (S1417).

Documented contract (CLAUDE.md "MCP server"): per-user `cmd_mcp_` tokens resolved by SHA-256
hash; revoked/expired token never falls through to the server key; mounted transport resolves the
bearer **per request** to a principal in a `ContextVar`; MCP tools run the shared **token-budget
gate** *and* acquire **`agent_limiter`** slots; tools/resources share principal + ownership checks.

**Positive notes (verified — auth & isolation are well-built):**
- **Per-request principal isolation is correct**: a *pure ASGI* middleware (deliberately not
  `BaseHTTPMiddleware`, which would drop the ContextVar) sets `runtime.current_principal` and
  **resets it in `finally`** per request (`asgi.py:59-77`) — no cross-request principal bleed.
- `cmd_mcp_` tokens **never** fall through to the server key (`auth.py:156-162`); an invalid JWT
  **raises** (never returns None) so it can't fall through either (`:123-137,164-165`); server-key
  uses `hmac.compare_digest` (`:105`).
- The mounted multi-tenant transport effectively **does not honor the env server key** (a
  server-key value presented as a bearer is routed to JWT validation → 401), which is the correct
  posture for multi-tenant.
- **Per-tool authorization is enforced**: `_require_project_access` → `MembershipService.can_access`
  (`tools.py:71-73`), `_require_connection_access` checks the connection's project
  (`:76-81`), and connection-to-project scoping is verified (`:273`).

Severity: 🔴 Critical · 🟠 High · 🟡 Medium · 🟢 Low · ⚪ Info

---

## F-MCP-01 — 🟠 High — MCP agent runs never record token usage → token-budget & billing limits bypassed

**Type:** Security / billing (control bypass)
**Location:** `mcp_server/tools.py:281` & `:338` call `check_token_budget` (the **gate**) but there
is **no usage-recording call** anywhere in `tools.py`; token usage is written **only** in
`api/routes/chat.py` (confirmed app-wide: recording sites are `chat.py` + `usage_service.py`; the
orchestrator/agent does **not** record internally).

**Description.** The chat route both (a) checks the token budget *and* (b) records the run's
`token_usage` into `TokenUsage` afterward (`chat.py`). The MCP `ask`/`search_codebase` tools
replicate only the **check** — they invoke the agent (consuming LLM tokens) but never record the
consumption. Because `check_token_budget` reads the `TokenUsage` ledger that MCP never increments,
**the budget gate is inert for MCP**: a user can run unlimited token-consuming queries through an
MCP token without ever accruing usage, hitting their daily/monthly token limit, or being billed
for entitlement token caps.

**Impact.** Token-budget and billing-entitlement bypass via the MCP entry point — a real
cost/revenue leak, and it's **live in production** (MCP mount enabled, obs 20559). Contradicts the
CLAUDE.md claim that MCP tools run the shared budget gate (the gate runs but is toothless without
recording).

**Proposed fix.** After each MCP agent run, record the returned `token_usage` via the same
`UsageService` path the chat route uses (ideally move record-usage into a shared helper invoked by
both the chat route and the MCP tools, so entry points can't diverge). Add a test: run an MCP
`ask`, assert a `TokenUsage` row was written and the budget reflects it.

---

## F-MCP-02 — 🟡 Medium — MCP tools don't acquire `agent_limiter` slots → per-user concurrency cap bypassed

**Type:** Reliability / cost (doc↔code mismatch)
**Location:** `mcp_server/tools.py` (no `agent_limiter` usage — confirmed by search); contrast
`api/routes/chat.py:1464` which acquires/releases an `agent_limiter` slot per agent run.

**Description.** CLAUDE.md states MCP agent tools "acquire `agent_limiter` concurrency slots", but
`tools.py` never does. The per-user concurrency cap that bounds simultaneous agent runs on the
chat path is therefore not enforced for MCP, so a user with an MCP token can launch unbounded
concurrent agent runs.

**Impact.** Resource/cost DoS lever via MCP (parallel agent runs), bypassing the chat path's
concurrency protection.

**Proposed fix.** Acquire/release an `agent_limiter` slot around the MCP agent invocation (same
shared helper as F-MCP-01), returning a clear "too many concurrent requests" error when the slot
can't be acquired.

---

## F-MCP-03 — 🟢 Low — `authenticate` tries the env server-key *before* the JWT when `CHECKMYDATA_API_KEY` is misconfigured to a `cmd_mcp_` value

**Type:** Hardening (edge misconfiguration)
**Location:** `auth.py:155-159` (`candidate_key = api_key or _get_api_key()`; if it starts with
`cmd_mcp_` the personal-token path runs first).

**Description.** On the JWT branch (`authenticate(token=…, api_key=None)`), `candidate_key` becomes
the env `CHECKMYDATA_API_KEY`. If an operator misconfigures that env var to a `cmd_mcp_`-prefixed
value, the personal-token lookup for the **env** key runs before the request's JWT is considered,
resolving to whoever owns that token. Requires a clear operator misconfiguration, so low severity.

**Proposed fix.** Validate at startup that `CHECKMYDATA_API_KEY` does **not** start with
`cmd_mcp_`; on the mounted transport, ignore the env server-key entirely (only honor per-request
credentials).

---

## F-MCP-04 — 🟢 Low — DNS-rebinding Host validation (`MCP_ALLOWED_HOSTS`) is opt-in

**Type:** Hardening
**Location:** mount config (`MCP_ALLOWED_HOSTS` per CLAUDE.md, default off).

**Description.** The mounted transport's Host validation that mitigates DNS-rebinding is opt-in. In
a browser-adjacent deployment this leaves a rebinding vector unless explicitly configured.

**Proposed fix.** Default `MCP_ALLOWED_HOSTS` to the deployment's known hosts when the mount is
enabled, or warn loudly when unset.

---

## Test gaps (⚪ Info)

- No test that an MCP `ask` **records** `TokenUsage` and that the budget gate then reflects it
  (F-MCP-01) — highest-value regression test.
- No test that concurrent MCP agent runs are bounded by `agent_limiter` (F-MCP-02).
- (Positive coverage worth locking in: `test_mcp_asgi_auth.py` should assert principal reset
  across sequential requests and no fall-through from invalid JWT / revoked `cmd_mcp_` token.)

## Summary

| id | sev | one-line |
|----|-----|----------|
| F-MCP-01 | 🟠 | MCP runs never record token usage → budget/billing limits bypassed (live in prod) |
| F-MCP-02 | 🟡 | MCP tools don't acquire `agent_limiter` → concurrency cap bypassed (doc mismatch) |
| F-MCP-03 | 🟢 | Env server-key tried before JWT if misconfigured to a `cmd_mcp_` value |
| F-MCP-04 | 🟢 | `MCP_ALLOWED_HOSTS` DNS-rebinding validation is opt-in |

**Next-round focus:** `resources.py` ownership parity with tools; `mcp_key_service` token
generation entropy + hashing + expiry handling; per-tool result/row caps vs the double-truncation
note (obs 18985); rate-limiting of MCP token minting (`/api/auth/mcp-tokens`); whether MCP `ask`
honours the connection read-only posture end-to-end.
