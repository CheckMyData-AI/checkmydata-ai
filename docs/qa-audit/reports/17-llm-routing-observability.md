# Module 17 — LLM routing & Observability — Audit Report

**Round 1** · 2026-06-24 · Scope: `llm/router.py`, `llm/retry.py`, `core/sentry.py`,
`routes/metrics.py`, `routes/logs.py`. (Adapter token-counting + TracePersistence access-scoping
deferred to R2.)

This module is **largely solid** — failover, retry semantics, and observability hygiene are
well-built. One data-governance finding and a few verify/info items.

**Positive notes (verified):**
- **Provider failover is well-behaved**: chain `openai→anthropic→openrouter` filtered by
  configured keys; per-provider retry + exponential backoff; `LLMTokenLimitError`/`LLMBillingError`
  **skip to the next provider** without burning retries; non-retryable / stop-fallback errors
  break; terminal `LLMAllProvidersFailedError` (non-retryable per CLAUDE.md) (`router.py:235-284`).
- **Provider health tracking** with TTL-based recovery (obs 19371).
- **Sentry hygiene is thorough**: `send_default_pii=False`; `before_send=scrub_event` drops
  request `data`/`cookies`/`headers`/`query_string`/`env`, keeps only the opaque user `id`, and
  `scrub_text`-redacts exception values, log messages, and breadcrumb messages
  (`core/sentry.py:50-81`).
- **Metrics are admin-gated**: both `/api/metrics` and `/api/metrics/prometheus` require
  `require_admin` (`metrics.py:44/95`).

Severity: 🔴 Critical · 🟠 High · 🟡 Medium · 🟢 Low · ⚪ Info

---

## F-LLM-01 — 🟡 Medium — Silent cross-provider fallback can route customer DB data to a provider the user/project didn't choose

**Type:** Data governance / compliance
**Location:** `llm/router.py:75-86` (`_get_fallback_chain` builds the chain from all configured
keys), `:244-279` (`complete` falls through the chain on failure, incl. to **openrouter**).

**Description.** `preferred_provider` is treated as a *preference*, not a constraint. When the
preferred provider errors, `complete()` silently falls through to the next configured provider —
potentially **OpenRouter**, which proxies prompts to third-party model hosts. The prompts contain
the customer's **DB schema, sampled rows, and business rules**. A project that selected a specific
provider for data-residency/compliance reasons can have that data silently sent elsewhere on a
transient failure (only when multiple provider keys are configured — with a single key the chain
is length-1 and there's no leak).

**Impact.** Customer data can reach an unintended LLM provider/host, a governance/compliance gap
for a product that handles customer database contents.

**Proposed fix.** Add a per-project/connection "allowed providers" (or "no fallback") policy;
respect it in `_get_fallback_chain` so fallback never leaves the allowed set. At minimum, make
cross-provider fallback opt-in and log/emit a metric when it occurs so it's auditable.

---

## F-LLM-02 — 🟢 Low — Any unexpected exception marks a whole provider unhealthy

**Type:** Robustness
**Location:** `router.py:275-279` (`except Exception: … mark_unhealthy(provider)`).

**Description.** A single unexpected error (e.g. a response-parsing edge case, not a real outage)
evicts the entire provider from rotation, shifting all traffic to fallback until the TTL recovers
it. The TTL recovery (obs 19371) bounds the impact, but a benign bug could flap the primary
provider.

**Proposed fix.** Distinguish "provider outage" from "unexpected local error"; only
`mark_unhealthy` on errors indicative of the provider being down (5xx/timeout/connection), not on
arbitrary exceptions.

---

## F-LLM-03 — ⚪ Info — Verify `_SECRET_PATTERNS` covers DSNs/passwords that leak via `QueryResult.error`

**Type:** Verification (cross-ref F-CONN)
**Location:** `core/sentry.py:39-47` (`scrub_text` / `_SECRET_PATTERNS`).

**Description.** `scrub_event` correctly routes exception values and log messages through
`scrub_text`, and the code comment notes connection strings can appear there. But the actual
redaction depends on `_SECRET_PATTERNS`. Connectors surface `QueryResult.error=str(e)` and asyncpg
errors can echo DSNs (`postgresql://user:pass@host`), and templates use `PGPASSWORD`/`MYSQL_PWD`.
Confirm the patterns redact: `scheme://user:pass@`, `PGPASSWORD=/MYSQL_PWD=`, `Bearer <jwt>`,
`cmd_mcp_…` tokens, and Fernet keys.

**Proposed fix.** Add/confirm patterns for the above; add a unit test feeding a DSN-bearing
exception to `scrub_text` and asserting the password is `[redacted]`.

---

## F-LLM-04 — ⚪ Info — Admin-JWT-gated `/metrics/prometheus` complicates standard scraping

**Type:** Operational
**Location:** `routes/metrics.py:95` (`require_admin`).

**Description.** Requiring an admin **user JWT** for the Prometheus endpoint means a standard
Prometheus scraper can't pull it without an admin token. Secure, but note the operational
implication (a static scrape token / internal-only path is the usual pattern).

**Proposed fix.** If scraping is needed, support a dedicated scrape token (separate from user
JWTs) or bind the endpoint to an internal network, keeping it out of the public surface.

---

## Test gaps (⚪ Info)

- No test that fallback respects a provider-restriction policy (F-LLM-01) — feature absent.
- No test that `scrub_text` redacts a DSN/password in an exception value (F-LLM-03).
- (Positive coverage worth locking in: token-limit error on provider A → provider B is attempted;
  all-fail → `LLMAllProvidersFailedError`.)

## Summary

| id | sev | one-line |
|----|-----|----------|
| F-LLM-01 | 🟡 | Silent cross-provider fallback can send customer data to an unintended provider |
| F-LLM-02 | 🟢 | Any unexpected exception evicts a whole provider (flap risk) |
| F-LLM-03 | ⚪ | Verify Sentry `_SECRET_PATTERNS` redacts DSNs/passwords (cross-ref F-CONN) |
| F-LLM-04 | ⚪ | Prometheus endpoint admin-JWT-gated → scraping friction |

**Next-round focus:** `TracePersistenceService` — are `input_preview`/`output_preview` spans (which
embed prompt/SQL/data snippets) access-scoped to the project, and could an admin/cross-project read
leak tenant data? `routes/logs.py` exposure scoping; adapter-level token counting accuracy (feeds
the budget gate, F-MCP-01/F-SQL-02); `health_monitor` route auth.
