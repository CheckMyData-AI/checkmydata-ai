# CheckMyData.ai — Open Issues (QA / Security Audit)

**The single source of truth for unresolved findings.** Scope: all 19 business modules, backend +
frontend. Resolved findings are intentionally **not** listed here — they are done and verified in
git (see "Already fixed" below). This document tracks only what is **still open**.

> Finding id format: `F-<MODULE>-NN`. Severity: 🔴 Critical · 🟠 High · 🟡 Medium · 🟢 Low · ⚪ Info.

## Already fixed (not tracked here — for reference)

16 findings are closed and verified (backend 4334 tests green / 74.41% coverage; frontend 472
tests green), in branch `fix/security-audit-2026-06-24` → PR
[#172](https://github.com/CheckMyData-AI/checkmydata-ai/pull/172):
**Module 01 Auth** F-AUTH-01…12, and **Module 07 Knowledge** F-KNOW-01/02/03/05. Per-fix detail is
in the git history (commits `a8d3b2a`, `f35ac10`, `03dad44`, `ed54b48`, `2475114`, `1343fc3`,
`e642c67`, `81e3d75`).

This file also folds in the **2026-06-23 codebase audit** (`code-reviewer` baseline + manual
review). Its findings map as: **H1** = F-KNOW-01 (fixed); **M2** = F-KNOW-02 (fixed); **M1** =
the read-only cluster (F-SQL-08 / F-CONN-01/02, open — denylist hardened in `e642c67` but the
DB-session backstop is still owed); **M3** partially fixed (`projects.py`/`runs.py` via
`spawn_tracked`; the `pipeline_runner` site remains = F-KNOW-09); **M4/M5/L1/L2** are the
codebase-wide items in §7. Automated baseline grades: backend **B** (1,934 smells, 55 SOLID),
frontend **A** (563 smells, 7 SOLID).

---

## 1. Open severity tally

| Severity | Open |
|---|---|
| 🔴 Critical | 0 |
| 🟠 High | 7 |
| 🟡 Medium | ~39 |
| 🟢 Low | ~51 |
| ⚪ Info | ~15 |

*(Includes the 2026-06-23 codebase-audit items folded in — see §7 and the "Already fixed" mapping.)*

**Single highest-leverage fix:** enforce **read-only at the DB session/connector level** (per
dialect). It closes the largest cluster (F-CONN-01/02, F-SQL-04/08, F-SCHED-02, F-NOTE-01, MCP
raw-query) because today the read-only invariant rests on **one evadable regex** with no
database-level backstop.

---

## 2. Top priorities (open High)

| ID | Sev | Title | Where | Fix |
|---|---|---|---|---|
| **F-SQL-08** | 🟠 | Read-only `SafetyGuard` regex is **evadable** (`SELECT…INTO`, `CREATE OR REPLACE/TEMP/MATERIALIZED VIEW`, `ALTER ROLE/USER`, `DROP ROLE/FUNCTION`) **and** no DB-session read-only fallback (MySQL `autocommit=True`). Reachable via raw-SQL at notes/schedules/batch/MCP. | `core/safety.py:16-34`, `connectors/*` | DB-session read-only (`default_transaction_read_only`/`readonly=1`/`SET TRANSACTION READ ONLY`) **+** statement-initial allow-list. **#1 leverage item.** |
| **F-CONN-01** | 🟠 | Read-only enforced at scattered call sites, not at the connector/DB chokepoint. | `connectors/` | Same DB-level fix as F-SQL-08. |
| **F-CONN-02** | 🟠 | `SafetyGuard` regex blocklist has multiple bypasses (umbrella of F-SQL-08). | `core/safety.py` | Same. |
| **F-SSH-08** | 🟠 | SSH tunnel cache key omits the credential → **cross-tenant tunnel sharing** (bypasses SSH-key auth). | `connectors/ssh_tunnel.py:212-216` | Include a credential discriminator (key fingerprint hash) in `_key`. |
| **F-PROJ-01** | 🟠 | Unverified-email registration + email-based auto-accept = invite/access harvesting. | `routes/auth.py`, `services/invite_service.py` | Email verification before invite auto-accept. |
| **F-RULE-01** | 🟠 | No authz on **global** (`project_id=null`) rule creation → cross-tenant prompt injection. | `routes/rules.py` | Require admin for global rules; gate by membership otherwise. |
| **F-MCP-01** | 🟠 | MCP agent runs never record token usage → token-budget & billing limits bypassed (live in prod). | `mcp_server/tools.py` | Thread a per-request usage sink (shared with F-CHAT-07/F-SQL-06). |

---

## 3. Cross-cutting clusters (fix once, close many)

1. **Read-only enforcement chokepoint** — F-CONN-01/02, F-SQL-04/08, F-SCHED-02, F-NOTE-01, MCP
   raw-query. **Fix:** per-dialect DB-session read-only (PG `default_transaction_read_only=on`,
   ClickHouse `readonly=1`, MySQL `SET TRANSACTION READ ONLY` / read-only user, Mongo read-only
   user + `--noscripting` which also kills F-CONN-10) **+** replace the DDL blocklist with a
   statement-initial allow-list. *(Partially mitigated by `e642c67`'s denylist hardening, but the
   High items still need the DB-session backstop.)*
2. **Object-ownership IDOR family** — F-DG-07, F-DG-09, F-GRAPH-01, F-RULE-05: route checks
   URL-project membership but the mutation/load uses a bare resource id. **Fix:** scope every
   resource load/mutation by `project_id`.
3. **Token-budget / billing under-count** — F-MCP-01, F-CHAT-07, F-SQL-06 (+ session-summary,
   repairs). **Fix:** a single per-request usage sink threaded through `LLMRouter`.
4. **Credential leakage in errors** — F-CONN-08 returns `str(e)` (DSN/password) in the API response
   and logs; the Sentry scrubber only covers Sentry egress. **Fix:** scrub at the
   `connection_service` error site.
5. **Stored prompt-injection / memory poisoning** — F-RULE-01/02, F-LEARN-01/06, F-SQL-01,
   F-PROJ-15: LLM-authored / DB-sourced content injected as authoritative with no content-safety
   gate. **Fix:** shared content-safety screen on every rule/learning ingest + provenance tags.
6. **Non-durable observability** — F-AUTH-15 (`audit_log` logger-only, ephemeral on Heroku, not
   queryable). **Fix:** persist an `AuditLog` table alongside the logger line.
7. **Idempotency / retry hazards** — F-SCHED-07 (batch ARQ-retry duplicates writes), F-LEARN-08
   (feedback replay = downvote-bomb), F-SSH-07 (reconnect double-exec), F-LEARN-03 (confidence
   pump). **Fix:** atomic claims + transition-guards.

---

## 4. Open issues by module

### 01 — Auth & Session
| ID | Sev | Issue |
|---|---|---|
| F-AUTH-13 | 🟡 | No password-reset flow → forgotten password = permanent lockout |
| F-AUTH-14 | 🟢 | No per-account login lockout (only IP rate limit) |
| F-AUTH-15 | 🟡 | `audit_log` logger-only — no durable/queryable audit table (`core/audit.py:19`) |
| F-AUTH-16 | 🟢 | `/refresh` + `/logout` emit no audit event |

### 02 — Projects, RBAC & Invites
| ID | Sev | Issue |
|---|---|---|
| F-PROJ-01 | 🟠 | Unverified-email registration + auto-accept = invite/access harvesting |
| F-PROJ-02 | 🟡 | Owner tracked in two places that drift; `require_role` ignores `owner_id` |
| F-PROJ-03 | 🟡 | `accept_invite` commits inside `begin_nested()` → 500 on idempotent re-accept |
| F-PROJ-04 | 🟡 | Invites never expire; auto-accepted indefinitely |
| F-PROJ-05 | 🟡 | Fire-and-forget `asyncio.create_task` sync-now → silent task death |
| F-PROJ-06 | 🟡 | Commit-then-await-email → partial-success 500s / confusing 409 |
| F-PROJ-07 | 🟢 | Service role methods don't validate role strings |
| F-PROJ-08 | 🟢 | `InviteCreate.role` advertises `owner` but route rejects it |
| F-PROJ-09 | ⚪ | `revoke_invite` ignores `_user_id`; authz only at route |
| F-PROJ-10 | 🟡 | No ownership transfer / co-owner → owner departure strands workspace |
| F-PROJ-11 | 🟢 | `add_member` upsert not `IntegrityError`-guarded → concurrent add 500 |
| F-PROJ-12 | 🟢 | No self-service "leave project" |
| F-PROJ-13 | 🟢 | `list_members`/`list_invites` no pagination cap |
| F-PROJ-14 | 🟢 | `GET /api/projects` member-only query diverges from `can_access` |
| F-PROJ-15 | 🟢 | Project name/desc/overview injected into orchestrator prompt |

### 03 — Connections & Connectors
| ID | Sev | Issue |
|---|---|---|
| F-CONN-01 | 🟠 | Read-only enforced at scattered call sites, not at the connector/DB chokepoint |
| F-CONN-02 | 🟠 | `SafetyGuard` regex blocklist has multiple bypasses |
| F-CONN-03 | 🟡 | Mongo `$out`/`$merge` stages bypass read-only guard |
| F-CONN-04 | 🟡 | Arbitrary `db_host`/`db_port` (+SSH) → internal-network reach (SSRF) |
| F-CONN-05 | 🟡 | Fernet encryption has no key rotation/versioning |
| F-CONN-06 | 🟢 | `_dict_to_positional` regex mis-handles `::type` casts / `:param` in literals |
| F-CONN-07 | 🟢 | Pool `min_size=1` per cached connector → remote connection exhaustion |
| F-CONN-08 | 🟡 | `QueryResult.error=str(e)` unredacted → DSN/password leak to members + logs |
| F-CONN-09 | 🟢 | Agent connector cache FIFO/instance-scoped |
| F-CONN-10 | 🟡 | Mongo server-side JS (`$where`/`$function`) + write stages bypass op-level guard |

### 04 — SSH Tunnel & Keys
| ID | Sev | Issue |
|---|---|---|
| F-SSH-08 | 🟠 | Tunnel cache key omits credential → cross-tenant tunnel sharing |
| F-SSH-01 | 🟡 | TOFU host-key verify fails *open* when known_hosts not writable |
| F-SSH-02 | 🟡 | ClickHouse exec template leaks DB password on remote command line |
| F-SSH-03 | 🟢 | Pre-command allowlist has a global kill-switch (re-enables RCE) |
| F-SSH-04 | 🟢 | `db_port` template var not shell-escaped |
| F-SSH-05 | 🟢 | TOFU check-then-pin not atomic (concurrent first-connect race) |
| F-SSH-06 | 🟢 | `SshKeyService` treats `user_id IS NULL` keys as shared across tenants (latent) |
| F-SSH-07 | 🟢 | Auto-reconnect re-runs command → double-executes non-idempotent ops |
| F-SSH-09 | 🟢 | `_locks`/per-key state grows unboundedly |

### 05 — Chat & Orchestration
| ID | Sev | Issue |
|---|---|---|
| F-CHAT-01 | 🟡 | WS authz checked only at connect; revocation ineffective until disconnect |
| F-CHAT-02 | 🟡 | Empty chat_session created on every WS connect → orphan bloat |
| F-CHAT-03 | 🟡 | `_relay_events` 60s idle timeout silently kills progress on slow steps |
| F-CHAT-04 | 🟢 | WS uses connection config captured once; stale after mid-session edits |
| F-CHAT-05 | ⚪ | ~51 silent exception handlers mask errors (cross-cutting) |
| F-CHAT-06 | 🟢 | WS `receive_json` no explicit payload cap (mitigated: 20K model cap; uvicorn 16MB frame) |
| F-CHAT-07 | 🟡 | AdaptivePlanner & AnswerValidator LLM calls never counted → budget under-count |
| F-CHAT-08 | 🟢 | `fatal` parallel stage doesn't cancel in-flight siblings |

### 06 — SQL Agent & Query Execution
| ID | Sev | Issue |
|---|---|---|
| F-SQL-08 | 🟠 | Read-only guard regex evadable + no DB-session fallback (see §2) |
| F-SQL-01 | 🟡 | Indirect prompt injection via DB content (comments/sampled/distinct values) |
| F-SQL-02 | 🟡 | `row_count` returned-vs-total ambiguity → inaccurate counts |
| F-SQL-03 | 🟡 | Multiplicative retry blow-up (replans × iterations × repairs) |
| F-SQL-04 | 🟢 | Read-only guard only in ValidationLoop; sibling callers bypass |
| F-SQL-05 | 🟢 | `_try_repair` no-op `error_classify` tracker span |
| F-SQL-06 | 🟡 | Repair LLM calls entirely uncounted → biggest budget under-count |
| F-SQL-07 | 🟢 | EXPLAIN validation asymmetric across dialects |

### 07 — Knowledge & Indexing
| ID | Sev | Issue |
|---|---|---|
| F-KNOW-04 | 🟢 | Passphrase-stripped private key briefly on disk during clone (planned: `mkdtemp(0700)` + signal-scrub) |
| F-KNOW-06 | 🟢 | `pickle.load` for BM25 is a latent RCE primitive (swap to safe format **before** F-KNOW-07) |
| F-KNOW-07 | 🟡 | BM25 snapshots on local ephemeral disk → hybrid silently dense-only in prod (needs shared storage; add `load()`-miss metric first) |
| F-KNOW-08 | 🟡 | Git clone dir not removed on project delete → orphaned source on disk |
| F-KNOW-09 | 🟡 | Fire-and-forget `asyncio.create_task(_parse_one(rp))` in a loop (`pipeline_runner.py:1428`) → tasks GC'd / exceptions dropped (codebase-audit M3; `projects.py`/`runs.py` already fixed via `spawn_tracked`, this site not) |

### 08 — GitAgent (live Git)
| ID | Sev | Issue |
|---|---|---|
| F-GIT-01 | 🟡 | Option injection via unvalidated rev/sha → `show`/`diff --output=` arbitrary write |
| F-GIT-02 | 🟢 | `git_agent_auto_pull` does network fetch + tree update (inherits F-KNOW-02 risk) |
| F-GIT-03 | 🟢 | `except (TimeoutError, Exception)` over-broad on auto-pull |
| F-GIT-04 | 🟢 | Freshness warning detects only "ahead", not "behind/diverged" |
| F-GIT-05 | 🟢 | `list_releases` scans all tags then output-caps (unbounded scan) |
| F-GIT-06 | ⚪ | `review_signals` trailers are forgeable commit text presented as review data |

### 09 — Data Validation / Investigations / DataGate
| ID | Sev | Issue |
|---|---|---|
| F-DG-07 | 🟡 | `/investigate` reads chat message by id, no project check → cross-tenant leak (IDOR) |
| F-DG-09 | 🟡 | `/investigate` trusts caller `connection_id`/`session_id`/`message_id` → cross-tenant exec + leak |
| F-DG-01 | 🟡 | `Decimal` percent/date values bypass the range hard-check |
| F-DG-02 | 🟡 | Hard checks run on a sample → impossible values past window pass |
| F-DG-03 | 🟡 | Hard-FAIL keys on fuzzy name-based classification |
| F-DG-04 | 🟡 | JSON/array cell → `tuple(row)` unhashable → DataGate crashes |
| F-DG-05 | 🟢 | Percent bounds `-1..200` too lenient |
| F-DG-06 | 🟢 | Type-consistency check off-by-design at boundaries |
| F-DG-08 | 🟢 | Cross-stage/truncation checks use unreliable `row_count` |

### 10 — Insights & Learning Memory
| ID | Sev | Issue |
|---|---|---|
| F-LEARN-06 | 🟡 | Learning-override PATCH bypasses quality gate (direct-API poisoning) |
| F-LEARN-07 | 🟡 | `cross_connection_learnings_enabled` global patterns leak across **tenants** |
| F-LEARN-08 | 🟡 | Feedback not idempotent → repeated 👎 deactivates shared learnings (downvote-bomb) |
| F-LEARN-01 | 🟡 | LLM-authored lessons injected with no content-safety/provenance gate |
| F-LEARN-02 | 🟡 | Non-ASCII ratio gate silently rejects CJK/non-Latin lessons |
| F-LEARN-03 | 🟢 | Confidence pumpable to 1.0 via repeated confirm/dedup |
| F-LEARN-04 | 🟢 | Heuristic contradiction detection misses semantic conflicts |
| F-LEARN-05 | 🟢 | Token-based dedup → paraphrased duplicates bloat prompt |

### 11 — Rules Engine
| ID | Sev | Issue |
|---|---|---|
| F-RULE-01 | 🟠 | No authz on global rule create → cross-tenant prompt injection |
| F-RULE-05 | 🟡 | Agent `manage_rules` update/delete: IDOR on arbitrary `rule_id` (globals/other tenant) |
| F-RULE-02 | 🟡 | Rule content injected as authoritative, no content/posture guard |
| F-RULE-03 | 🟡 | `rules_to_context` no budget/size truncation (overflow/cost) |
| F-RULE-04 | 🟢 | Filesystem rule loading reads any matching-suffix file incl. symlinks |

### 12 — Visualizations & Dashboards
| ID | Sev | Issue |
|---|---|---|
| F-VIZ-04 | 🟡 | CSV/XLSX export doesn't neutralize formula-leading cells → CSV injection |
| F-VIZ-01 | 🟡 | Dashboard cards are stale data snapshots, no freshness signal |
| F-VIZ-02 | 🟡 | `cards_json` stored verbatim → stored-XSS vector (downgraded: frontend renders escaped React children; residual is unvalidated storage) |
| F-VIZ-03 | 🟢 | No server-side JSON/structure/size validation of `cards_json` |

### 13 — Schedules, Batch & Worker
| ID | Sev | Issue |
|---|---|---|
| F-SCHED-02 | 🟠 | Batch `/execute` runs viewer's raw SQL with **no SafetyGuard** → arbitrary writes/DDL (most reachable read-only bypass) |
| F-SCHED-07 | 🟡 | `execute_batch` no idempotency guard + ARQ default `max_tries=5` → retry duplicates writes |
| F-SCHED-01 | 🟡 | Schedules keep running after creator loses access |
| F-SCHED-03 | 🟡 | `_stale_run` NULL-heartbeat immediate-reap race (mitigated by heartbeat beacon) |
| F-SCHED-04 | 🟡 | ARQ enqueue failure silently runs heavy jobs in-process on web dyno |
| F-SCHED-05 | 🟢 | Fallback dedup per-process; no cross-process single-flight without Redis |
| F-SCHED-06 | 🟢 | No min-interval / cost guard on schedules |

### 14 — Billing & Entitlements
| ID | Sev | Issue |
|---|---|---|
| F-BILL-02 | 🟡 | Connection/project quota check count-then-compare → TOCTOU bypass |
| F-BILL-07 | 🟡 | `demo_setup` bypasses quota gate (route-level, not service-level) |
| F-BILL-01 | 🟡 | `_resolve_plan_id` trusts stale `metadata.plan_id` over live price |
| F-BILL-05 | 🟡 | Token-budget gate pre-flight only → one request overshoots budget |
| F-BILL-03 | 🟢 | `/webhook` no rate limit / body cap |
| F-BILL-06 | 🟢 | Budget windows UTC-based, not per-user timezone |
| F-BILL-08 | 🟢 | No `charge.dispute.*`/`charge.refunded` handler → chargeback ≠ revoke |
| F-BILL-04 | ⚪ | Ledger payload truncated at 64KB |

### 15 — MCP Server
| ID | Sev | Issue |
|---|---|---|
| F-MCP-01 | 🟠 | MCP runs never record token usage → budget/billing bypass (live in prod) |
| F-MCP-02 | 🟡 | MCP tools don't acquire `agent_limiter` → concurrency cap bypassed |
| F-MCP-03 | 🟢 | Env server-key tried before JWT if misconfigured to a `cmd_mcp_` value |
| F-MCP-04 | 🟢 | `MCP_ALLOWED_HOSTS` DNS-rebinding validation is opt-in |

### 16 — Notifications, Notes & Feed
| ID | Sev | Issue |
|---|---|---|
| F-NOTE-01 | 🟢 | Note exec uses call-site regex guard + direct execute (reachable F-SQL-08 surface) |
| F-NOTE-02 | 🟢 | Fresh connect/disconnect per note execution (no pool reuse) |
| F-NOTE-03 | ⚪ | Notes cache `last_result_json` snapshot — staleness like dashboards |

### 17 — LLM Routing & Observability
| ID | Sev | Issue |
|---|---|---|
| F-LLM-01 | 🟡 | Silent cross-provider fallback can send customer data to an unintended provider |
| F-LLM-05 | 🟢 | `health_monitor /reconnect` mutation defaults to viewer role (should be editor) |
| F-LLM-02 | 🟢 | Any unexpected exception evicts a whole provider (flap risk) |
| F-LLM-03 | ⚪ | Sentry scrubber redacts DSN/secret but only on Sentry egress; F-CONN-08 leak (API resp + logs) bypasses it |
| F-LLM-04 | ⚪ | Prometheus endpoint admin-JWT-gated → scraping friction |

### 18 — Semantic / Graph / Temporal / Exploration / Models / Demo
| ID | Sev | Issue |
|---|---|---|
| F-GRAPH-01 | 🟡 | `DELETE /{project_id}/metrics/{metric_id}` deletes any project's metric → cross-tenant destructive IDOR |
| F-EXP-01 | 🟡 | Demo project uses `:memory:` SQLite, no seeding → empty/misleading |
| F-EXP-02 | 🟢 | Demo connection created writable, against read-only default |
| F-EXP-03 | 🟢 | `demo_setup` creates real quota-counting Project+Connection, no dedup |
| F-EXP-04 | ⚪ | `models` endpoint discloses configured providers |

### 19 — Frontend SPA
| ID | Sev | Issue |
|---|---|---|
| F-FE-03 | 🟢 | a11y / design-token conformance not audited |
| F-FE-04 | ⚪ | `dangerouslySetInnerHTML` in marketing pages (about/contact/support/pricing) = static JSON-LD SEO schema — almost certainly safe; assert the injected object has no user input (codebase-audit L2) |

---

## 5. Recommended fix order

1. **DB-session read-only enforcement** (per dialect) + statement-initial allow-list → closes
   F-SQL-08, F-CONN-01/02, F-SQL-04, F-SCHED-02, F-NOTE-01, F-CONN-03/10, MCP raw-query.
2. **F-SSH-08** credential discriminator in tunnel cache key (cross-tenant tunnel sharing).
3. **Object-ownership IDOR sweep** — F-DG-07/09, F-GRAPH-01, F-RULE-05 (+ audit all mutations).
4. **F-PROJ-01 / F-RULE-01** — email verification before invite auto-accept; global-rule authz.
5. **Per-request usage sink** in `LLMRouter` → F-MCP-01, F-CHAT-07, F-SQL-06, F-BILL-05.
6. **Credential-redaction at source** (F-CONN-08) + **durable `AuditLog` table** (F-AUTH-15/16).
7. **Idempotency** — F-SCHED-07 (batch claim) + F-LEARN-08 (feedback transition-guard).
8. Remaining Medium/Low per module table.

---

## 6. Open questions / limitations

- **Verified-safe (ruled out, not bugs):** config command-injection (escaped), EXPLAIN
  non-executing, agent path IS ValidationLoop-guarded, QueryCache schema-version-aware, MCP
  read-only end-to-end (guard present though evadable), knowledge resume-skip (atomic checkpoints),
  public-dashboard share (no anonymous route), insight-TTL sweep, billing cancel-grace + no
  entitlement cache, frontend stored-XSS (escaped React children), Sentry scrubber correctness.
- A dedicated **a11y / design-token** sweep (F-FE-03) and a **performance / load** pass remain owed
  (not yet audited).
- Code locations and proposed fixes are summarized inline above; deeper reproduction notes for the
  fixed items live in git history.

---

## 7. Codebase-wide maintainability & tech-debt (2026-06-23 codebase audit)

Cross-cutting items that don't belong to one module. Not behavioral security bugs, but the dominant
maintainability / reliability risks.

| ID | Sev | Issue | Fix |
|---|---|---|---|
| CB-M4 | 🟢 | **God-files / long functions** (backend grade B, 1,934 smells): `agents/orchestrator.py` (2,525 LOC), `agents/sql_agent.py` (2,017), `knowledge/pipeline_runner.py` (1,769), `api/routes/chat.py` (1,724), `services/agent_learning_service.py` (1,259), `main.py` (1,248), `api/routes/connections.py` (1,199). High blast-radius, hard to test in isolation. | Decompose by responsibility (extract per-stage / per-concern modules); fold into the ongoing dashboard-rebuild altitude work. |
| CB-M5 | ⚪ | **Silent error swallowing** — 51 `except …: pass` + 516 `except Exception` across `app/`. Some benign (cache writes), but blanket swallowing in request paths (`chat.py`, `health_monitor.py`) hides real failures (vision invariant #5, honest degradation). Overlaps **F-CHAT-05**. | Narrow exception types + log at appropriate level; reserve bare `pass` for provably-benign cleanup. |
| CB-L1 | ⚪ | **Suppression debt** — 47 `# type: ignore`, 104 `# noqa` in `app/` (type-safety / lint gaps). (0 TODO/FIXME/HACK markers — clean.) | Revisit and remove suppressions where feasible; track the rest. |

**Verified-good in the codebase audit (no issue):** SQL identifier quoting (`connectors/base.py:262`
doubles quotes correctly), credential exposure (`ConnectionResponse` returns no secrets; Fernet at
rest), SSH pre-command allowlist (rejects metacharacters), frontend auth (no JWT in localStorage),
no LLM-key/secret logging, MCP read-only gating present (subject to the M1 regex robustness).
