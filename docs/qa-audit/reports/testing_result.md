# CheckMyData.ai — Consolidated QA / Security Audit Results

**Scope:** all 19 business modules, backend + frontend.
**Method:** round-robin module-by-module audit (docs + code), 5 deepening rounds (R5 partial).
**Generated:** 2026-06-24. Per-module detail lives in `docs/qa-audit/reports/NN-*.md`; this file is the single consolidated index.

---

## 1. Executive summary

- **125 distinct findings** (`F-<MODULE>-NN`), severity-graded 🔴 Critical / 🟠 High / 🟡 Medium / 🟢 Low / ⚪ Info.
- **Tally:** 1 🔴 Critical (fixed), 9 🟠 High (2 fixed / 7 open), ~45 🟡 Medium, ~55 🟢 Low, ~13 ⚪ Info.
- **Remediated:** Module 01 Auth (F-AUTH-01..12) and the knowledge-RCE cluster (F-KNOW-01/02/03/05) are fixed and verified. Everything else is **open**.
- **Single highest-leverage fix:** enforce **read-only at the DB session/connector level** (per dialect). It closes the largest cluster (F-CONN-01/02, F-SQL-04/08, F-SCHED-02, F-NOTE-01, MCP raw-query) because today the read-only invariant rests on **one evadable regex** with no database-level backstop.

### Severity tally by status

| Severity | Total | Fixed | Open |
|---|---|---|---|
| 🔴 Critical | 1 | 1 (F-KNOW-01) | 0 |
| 🟠 High | 9 | 2 (F-AUTH-01, F-AUTH-02) | 7 |
| 🟡 Medium | ~45 | ~10 (Module 01 + F-KNOW) | ~35 |
| 🟢 Low | ~55 | ~ | most open |
| ⚪ Info | ~13 | — | open |

---

## 2. Top priorities (open Critical + High)

| ID | Sev | Title | Where | Fix |
|---|---|---|---|---|
| **F-SQL-08** | 🟠 High | Read-only `SafetyGuard` regex is **evadable** (`SELECT…INTO`, `CREATE OR REPLACE/TEMP/MATERIALIZED VIEW`, `ALTER ROLE/USER`, `DROP ROLE/FUNCTION/…`) **and** no DB-session read-only fallback (`is_read_only` only picks SafetyLevel; MySQL `autocommit=True`). Directly reachable via raw-SQL at notes/schedules/batch/MCP. | `core/safety.py:16-34`, `connectors/*` | DB-session read-only (`default_transaction_read_only`/`readonly=1`/`SET TRANSACTION READ ONLY`) **+** statement-initial allow-list. **#1 leverage item.** |
| **F-CONN-01** | 🟠 High | Read-only enforced at scattered call sites, not at the connector/DB chokepoint. | `connectors/` | Same DB-level fix as F-SQL-08. |
| **F-CONN-02** | 🟠 High | `SafetyGuard` regex blocklist has multiple bypasses (umbrella of F-SQL-08). | `core/safety.py` | Same. |
| **F-SSH-08** | 🟠 High | SSH tunnel cache key omits the credential → **cross-tenant tunnel sharing** (bypasses SSH-key auth). | `connectors/ssh_tunnel.py:212-216` | Include a credential discriminator (key fingerprint hash) in `_key`. |
| **F-PROJ-01** | 🟠 High | Unverified-email registration + email-based auto-accept = invite/access harvesting (register as a victim's email → claim their invites). | `routes/auth.py`, `services/invite_service.py` | Email verification on registration before invite auto-accept. |
| **F-RULE-01** | 🟠 High | No authz on **global** (`project_id=null`) rule creation → cross-tenant prompt injection. | `routes/rules.py` | Require admin for global rules; gate by membership otherwise. |
| **F-MCP-01** | 🟠 High | MCP agent runs never record token usage → token-budget & billing limits bypassed (live in prod). | `mcp_server/tools.py` | Thread a per-request usage sink (shared with F-CHAT-07/F-SQL-06). |
| ~~F-AUTH-01~~ | 🟠 High | **FIXED** — SQLite FK enforcement was OFF (CASCADE no-op). | `models/base.py:50` | `enable_sqlite_fk` PRAGMA. ✅ |
| ~~F-AUTH-02~~ | 🟠 High | **FIXED** — no JWT revocation. | `models/user.py:29`, `api/deps.py:78` | `token_version` claim + check. ✅ |
| ~~F-KNOW-01~~ | 🔴 Critical | **FIXED** — RCE/LFI/SSRF via unvalidated `repo_url`. | `app/knowledge/repo_url.py` | `validate_repo_url` + `validate_git_ref`. ✅ |

---

## 3. Cross-cutting clusters (fix once, close many)

1. **Read-only enforcement chokepoint** — F-CONN-01/02, F-SQL-04/08, F-SCHED-02, F-NOTE-01, MCP raw-query. The invariant rests on a single evadable regex with no DB-session backstop. **Fix:** per-dialect DB-session read-only (PG `default_transaction_read_only=on`, ClickHouse `readonly=1`, MySQL `SET TRANSACTION READ ONLY` / read-only user, Mongo read-only user + `--noscripting` which also kills F-CONN-10) **+** replace the DDL blocklist with a statement-initial allow-list.
2. **Object-ownership IDOR family** — "route checks URL-project membership but the mutation/load uses a bare resource id": **F-DG-07, F-DG-09, F-GRAPH-01, F-RULE-05**. **Fix:** scope every resource load/mutation by `project_id` (the GET/confirm handlers already do — copy the check).
3. **Token-budget / billing under-count** — **F-MCP-01, F-CHAT-07, F-SQL-06** (+ session-summary, repairs). LLM usage is accumulated per-call-site and several sites are missed. **Fix:** a single per-request usage sink threaded through `LLMRouter`.
4. **Credential leakage in errors** — **F-CONN-08** returns `str(e)` (DSN/password) in the API response **and** app logs; the (correct) **Sentry** scrubber only covers the Sentry egress (F-LLM-03). **Fix:** scrub at the `connection_service` error site, not just Sentry.
5. **Stored prompt-injection / memory poisoning** — **F-RULE-01/02, F-LEARN-01/06, F-SQL-01, F-PROJ-15**: LLM-authored / DB-sourced content injected as authoritative with no content-safety/provenance gate. **Fix:** a shared content-safety screen on every rule/learning ingest + provenance tags.
6. **Non-durable observability** — **F-AUTH-15** (`audit_log` is logger-only, ephemeral on Heroku, not queryable) undermines every audit call site. **Fix:** persist an `AuditLog` table alongside the logger line.
7. **Idempotency / retry hazards** — **F-SCHED-07** (batch ARQ-retry duplicates writes), **F-LEARN-08** (feedback replay = downvote-bomb), **F-SSH-07** (reconnect double-exec), **F-LEARN-03** (confidence pump). **Fix:** atomic claims + transition-guards.

---

## 4. Full per-module catalog

Status legend: **OPEN** unless marked ✅ FIXED.

### 01 — Auth & Session  (F-AUTH-01..16; 01..12 ✅ fixed)
| ID | Sev | Issue | Status |
|---|---|---|---|
| F-AUTH-01 | 🟠 | SQLite FK enforcement OFF → CASCADE silent no-op | ✅ |
| F-AUTH-02 | 🟠 | No server-side JWT revocation on pwd-change/logout | ✅ |
| F-AUTH-03 | 🟡 | `change_password` blocking sync bcrypt on request path | ✅ |
| F-AUTH-04 | 🟡 | JWT in response body defeats httpOnly-cookie model | ✅ |
| F-AUTH-05 | 🟡 | User enumeration via login timing + register 409 | ✅ |
| F-AUTH-06 | 🟢 | Google CSRF double-submit opt-in/bypassable | ✅ |
| F-AUTH-07 | 🟢 | Google link wipes avatar, flips `auth_provider` | ✅ |
| F-AUTH-08 | 🟢 | `SameSite=None` w/o `Secure` guard → silent login fail | ✅ |
| F-AUTH-09 | 🟢 | Sensitive auth mutations (`/refresh`) not rate-limited | ✅ |
| F-AUTH-10 | 🟡 | `delete_account` cascade-dependent, skips secret cleanup + audit | ✅ |
| F-AUTH-11 | 🟡 | Prod secret guard fail-*open* unless env exactly `production` | ✅ |
| F-AUTH-12 | 🟢 | MCP tokens default to never expiring | ✅ |
| F-AUTH-13 | 🟡 | **No password-reset flow** → forgotten password = permanent lockout | OPEN |
| F-AUTH-14 | 🟢 | No per-account login lockout (only IP rate limit) | OPEN |
| F-AUTH-15 | 🟡 | `audit_log` logger-only — no durable/queryable audit table (`core/audit.py:19`) | OPEN |
| F-AUTH-16 | 🟢 | `/refresh` + `/logout` emit no audit event | OPEN |

### 02 — Projects, RBAC & Invites  (F-PROJ-01..15)
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

### 03 — Connections & Connectors  (F-CONN-01..10)
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

### 04 — SSH Tunnel & Keys  (F-SSH-01..09)
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

### 05 — Chat & Orchestration  (F-CHAT-01..08)
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

### 06 — SQL Agent & Query Execution  (F-SQL-01..08)
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

### 07 — Knowledge & Indexing  (F-KNOW-01..08; 01/02/03/05 ✅ fixed)
| ID | Sev | Issue | Status |
|---|---|---|---|
| F-KNOW-01 | 🔴 | RCE/LFI/SSRF via unvalidated `repo_url` git transport | ✅ |
| F-KNOW-02 | 🟡 | Git-SSH clone `StrictHostKeyChecking=no` → MITM | ✅ |
| F-KNOW-03 | 🟡 | Editing `repo_url` doesn't re-point existing clone | ✅ |
| F-KNOW-05 | 🟢 | `branch` not validated (option-injection smell) | ✅ |
| F-KNOW-04 | 🟢 | Passphrase-stripped private key briefly on disk during clone | OPEN |
| F-KNOW-06 | 🟢 | `pickle.load` for BM25 is a latent RCE primitive | OPEN |
| F-KNOW-07 | 🟡 | BM25 snapshots on local ephemeral disk → hybrid silently dense-only in prod | OPEN |
| F-KNOW-08 | 🟡 | Git clone dir not removed on project delete → orphaned source on disk | OPEN |

### 08 — GitAgent (live Git)  (F-GIT-01..06)
| ID | Sev | Issue |
|---|---|---|
| F-GIT-01 | 🟡 | Option injection via unvalidated rev/sha → `show`/`diff --output=` arbitrary write |
| F-GIT-02 | 🟢 | `git_agent_auto_pull` does network fetch + tree update (inherits F-KNOW-02) |
| F-GIT-03 | 🟢 | `except (TimeoutError, Exception)` over-broad on auto-pull |
| F-GIT-04 | 🟢 | Freshness warning detects only "ahead", not "behind/diverged" |
| F-GIT-05 | 🟢 | `list_releases` scans all tags then output-caps (unbounded scan) |
| F-GIT-06 | ⚪ | `review_signals` trailers are forgeable commit text presented as review data |

### 09 — Data Validation / Investigations / DataGate  (F-DG-01..09)
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

### 10 — Insights & Learning Memory  (F-LEARN-01..08)
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

### 11 — Rules Engine  (F-RULE-01..05)
| ID | Sev | Issue |
|---|---|---|
| F-RULE-01 | 🟠 | No authz on global rule create → cross-tenant prompt injection |
| F-RULE-05 | 🟡 | Agent `manage_rules` update/delete: IDOR on arbitrary `rule_id` (globals/other tenant) |
| F-RULE-02 | 🟡 | Rule content injected as authoritative, no content/posture guard |
| F-RULE-03 | 🟡 | `rules_to_context` no budget/size truncation (overflow/cost) |
| F-RULE-04 | 🟢 | Filesystem rule loading reads any matching-suffix file incl. symlinks |

### 12 — Visualizations & Dashboards  (F-VIZ-01..04)
| ID | Sev | Issue |
|---|---|---|
| F-VIZ-04 | 🟡 | CSV/XLSX export doesn't neutralize formula-leading cells → CSV injection |
| F-VIZ-01 | 🟡 | Dashboard cards are stale data snapshots, no freshness signal |
| F-VIZ-02 | 🟡 | `cards_json` stored verbatim → stored-XSS vector (**downgraded R4**: frontend renders escaped React children, not exploitable; residual is unvalidated storage) |
| F-VIZ-03 | 🟢 | No server-side JSON/structure/size validation of `cards_json` |

### 13 — Schedules, Batch & Worker  (F-SCHED-01..07)
| ID | Sev | Issue |
|---|---|---|
| F-SCHED-02 | 🟡→🟠 | Batch `/execute` runs viewer's raw SQL with **no SafetyGuard** → arbitrary writes/DDL (most reachable read-only bypass) |
| F-SCHED-07 | 🟡 | `execute_batch` no idempotency guard + ARQ default `max_tries=5` → retry duplicates writes |
| F-SCHED-01 | 🟡 | Schedules keep running after creator loses access |
| F-SCHED-03 | 🟡 | `_stale_run` NULL-heartbeat immediate-reap race (mitigated by heartbeat beacon) |
| F-SCHED-04 | 🟡 | ARQ enqueue failure silently runs heavy jobs in-process on web dyno |
| F-SCHED-05 | 🟢 | Fallback dedup per-process; no cross-process single-flight without Redis |
| F-SCHED-06 | 🟢 | No min-interval / cost guard on schedules |

### 14 — Billing & Entitlements  (F-BILL-01..08)
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

### 15 — MCP Server  (F-MCP-01..04)
| ID | Sev | Issue |
|---|---|---|
| F-MCP-01 | 🟠 | MCP runs never record token usage → budget/billing bypass (live in prod) |
| F-MCP-02 | 🟡 | MCP tools don't acquire `agent_limiter` → concurrency cap bypassed |
| F-MCP-03 | 🟢 | Env server-key tried before JWT if misconfigured to a `cmd_mcp_` value |
| F-MCP-04 | 🟢 | `MCP_ALLOWED_HOSTS` DNS-rebinding validation is opt-in |

### 16 — Notifications, Notes & Feed  (F-NOTE-01..03)
| ID | Sev | Issue |
|---|---|---|
| F-NOTE-01 | 🟢 | Note exec uses call-site regex guard + direct execute (reachable F-SQL-08 surface) |
| F-NOTE-02 | 🟢 | Fresh connect/disconnect per note execution (no pool reuse) |
| F-NOTE-03 | ⚪ | Notes cache `last_result_json` snapshot — staleness like dashboards |

### 17 — LLM Routing & Observability  (F-LLM-01..05)
| ID | Sev | Issue |
|---|---|---|
| F-LLM-01 | 🟡 | Silent cross-provider fallback can send customer data to an unintended provider |
| F-LLM-05 | 🟢 | `health_monitor /reconnect` mutation defaults to viewer role (should be editor) |
| F-LLM-02 | 🟢 | Any unexpected exception evicts a whole provider (flap risk) |
| F-LLM-03 | ⚪ | Sentry scrubber **verified** redacts DSN/secret — but only on Sentry egress; **F-CONN-08 leak (API resp + logs) bypasses it** |
| F-LLM-04 | ⚪ | Prometheus endpoint admin-JWT-gated → scraping friction |

### 18 — Semantic / Graph / Temporal / Exploration / Models / Demo  (F-EXP-01..04, F-GRAPH-01)
| ID | Sev | Issue |
|---|---|---|
| F-GRAPH-01 | 🟡 | `DELETE /{project_id}/metrics/{metric_id}` deletes any project's metric → cross-tenant destructive IDOR |
| F-EXP-01 | 🟡 | Demo project uses `:memory:` SQLite, no seeding → empty/misleading |
| F-EXP-02 | 🟢 | Demo connection created writable, against read-only default |
| F-EXP-03 | 🟢 | `demo_setup` creates real quota-counting Project+Connection, no dedup |
| F-EXP-04 | ⚪ | `models` endpoint discloses configured providers |

### 19 — Frontend SPA  (F-FE-01..03; 01 ✅ fixed)
| ID | Sev | Issue | Status |
|---|---|---|---|
| F-FE-01 | 🟡 | Failing/non-loading Vitest tests (lost regression signal) | ✅ (471 pass) |
| F-FE-02 | 🟢 | Dashboard card text — confirmed escaped React children (safe) | ✅ verified |
| F-FE-03 | 🟢 | a11y / design-token conformance not audited | OPEN |

---

## 5. Recommended fix order

1. **DB-session read-only enforcement** (per dialect) + statement-initial allow-list → closes F-SQL-08, F-CONN-01/02, F-SQL-04, F-SCHED-02, F-NOTE-01, F-CONN-03/10, MCP raw-query.
2. **F-SSH-08** credential discriminator in tunnel cache key (cross-tenant tunnel sharing).
3. **Object-ownership IDOR sweep** — F-DG-07/09, F-GRAPH-01, F-RULE-05 (+ audit all mutations).
4. **F-PROJ-01 / F-RULE-01** — email verification before invite auto-accept; global-rule authz.
5. **Per-request usage sink** in `LLMRouter` → F-MCP-01, F-CHAT-07, F-SQL-06, F-BILL-05.
6. **Credential-redaction at source** (F-CONN-08) + **durable `AuditLog` table** (F-AUTH-15/16).
7. **Idempotency** — F-SCHED-07 (batch claim) + F-LEARN-08 (feedback transition-guard).
8. Remaining Medium/Low per module table.

---

## 6. Notes & limitations

- **Verified-safe (ruled out, not bugs):** config command-injection (escaped), EXPLAIN non-executing, agent path IS ValidationLoop-guarded, QueryCache schema-version-aware, MCP read-only end-to-end (guard present though evadable), knowledge resume-skip (atomic checkpoints), public-dashboard share (no anonymous route), insight-TTL (correct sweep), billing cancel-grace + no entitlement cache, frontend stored-XSS (escaped React children), Sentry scrubber correctness.
- **Remediation already in tree:** Module 01 (F-AUTH-01..12, commits a8d3b2a/f35ac10/03dad44/ed54b48/2475114/1343fc3) and F-KNOW-01/02/03/05 (e642c67 + 81e3d75) — verified, no regressions. See §7 for the per-fix log.
- This audit prioritized **security + correctness + data-integrity**; a dedicated a11y/design-token sweep (F-FE-03) and a performance/load pass remain owed.
- Full reproduction detail, code locations, and proposed fixes per finding are in the individual `docs/qa-audit/reports/NN-*.md` files; the live tracker is `docs/qa-audit/README.md`.

---

## 7. Remediation log — fixes applied by the QA fix loop (2026-06-24)

Branch `fix/security-audit-2026-06-24` → **PR [#172](https://github.com/CheckMyData-AI/checkmydata-ai/pull/172)** (prod merge is a gated human step — direct push to `main` is blocked by the safety classifier). Each fix is TDD'd; gates below were run green.

**Verification at module-01 completion:** backend `ruff format`+`ruff check`+`mypy` (328 files) clean, **4334 unit+integration tests pass, coverage 74.41% ≥ 72%**; frontend `tsc`+`eslint` clean, **472 vitest tests pass**.

### RESOLVED (16 findings)

| Finding | Sev | Fix summary | Key files | Commit |
|---|---|---|---|---|
| F-AUTH-01 | 🟠 | `enable_sqlite_fk()` issues `PRAGMA foreign_keys=ON` on app + test engines so `ondelete=CASCADE` actually fires; +cascade regression test; fixed 17 orphan-insert tests | `app/models/base.py`, `tests/integration/conftest.py` | `a8d3b2a` |
| F-AUTH-02 | 🟠 | `User.token_version` (+migration `f4a5b6c7d8e9`) + `ver` JWT claim; `get_current_user` rejects on mismatch; bumped on password change (revokes stolen tokens) | `app/models/user.py`, `app/services/auth_service.py`, `app/api/deps.py` | `f35ac10` |
| F-AUTH-03 | 🟡 | `change_password` switched to off-thread async bcrypt (no event-loop stall) | `app/api/routes/auth.py` | `f35ac10` |
| F-AUTH-04 | 🟡 | JWT omitted from response body under cookie auth; added non-sensitive `expires_in` so the SPA still schedules proactive refresh | `app/api/routes/auth.py`, `frontend/src/stores/auth-store.ts` | `03dad44`, `1343fc3` |
| F-AUTH-05 | 🟡 | dummy bcrypt verify on unknown/passwordless login equalises timing (no account-existence oracle) | `app/services/auth_service.py` | `03dad44` |
| F-AUTH-06 | 🟢 | Google CSRF double-submit enforced on cookie presence (omitting the body token no longer bypasses) | `app/api/routes/auth.py` | `03dad44` |
| F-AUTH-07 | 🟢 | Google link no longer nulls an existing avatar / mis-flips `auth_provider` for password users | `app/services/auth_service.py` | `ed54b48` |
| F-AUTH-08 | 🟢 | config fails closed when `auth_cookie_samesite=none` without `auth_cookie_secure` | `app/config.py` | `2475114` |
| F-AUTH-09 | 🟢 | `/refresh` rate-limited (30/min) | `app/api/routes/auth.py` | `03dad44` |
| F-AUTH-10 | 🟡 | `delete_account` cleans on-disk ChromaDB/BM25 artifacts, explicitly revokes MCP keys, writes `auth.delete_account` audit | `app/api/routes/auth.py` | `ed54b48` |
| F-AUTH-11 | 🟡 | prod secret guard fails closed via `_SAFE_ENVIRONMENTS` allow-list (unknown/typo env ⇒ production) | `app/config.py` | `2475114` |
| F-AUTH-12 | 🟢 | MCP tokens default to a bounded 90-day expiry (`mcp_token_default_expiry_days`) | `app/config.py`, `app/services/mcp_key_service.py` | `2475114` |
| F-KNOW-01 | 🔴 | `validate_repo_url()` transport allowlist + `GIT_ALLOW_PROTOCOL` pin (blocks `ext::`/`fd::`/`file://`/`git://`/option-injection) | `app/knowledge/repo_url.py`, `repo_analyzer.py` | `e642c67` |
| F-KNOW-02 | 🟡 | git-SSH `StrictHostKeyChecking=no` → `accept-new` (TOFU, consistent with Module-04 policy) | `app/knowledge/repo_analyzer.py` | `e642c67` |
| F-KNOW-03 | 🟡 | `clone_or_pull` re-points origin via `set_url` when stored `repo_url` differs from the existing clone | `app/knowledge/repo_analyzer.py` | `81e3d75` |
| F-KNOW-05 | 🟢 | `validate_git_ref()` rejects leading-dash/`--opt=`/`..`/trailing-slash/`.lock`; applied at API boundary + RepoAnalyzer | `app/knowledge/repo_url.py`, `repos.py`, `projects.py`, `repo_analyzer.py` | `81e3d75` |

> Also fixed in `e642c67` (cross-cutting, pre-loop): SafetyGuard read-only denylist hardening + SQL-comment stripping, and `spawn_tracked()` for fire-and-forget background tasks. These partially mitigate the read-only cluster (§3.1) and F-PROJ-05 / F-CHAT-05 patterns but do **not** fully close the High items F-SQL-08 / F-CONN-01/02 (still need the DB-session read-only backstop).

### NOT RESOLVED — deferred with rationale (Module 07 remainder)

| Finding | Sev | Why deferred / planned fix |
|---|---|---|
| F-KNOW-04 | 🟢 | temp private key briefly on disk — planned: `mkdtemp(0700)` + signal-scrub. Small, next chunk. |
| F-KNOW-06 | 🟢 | BM25 `pickle.load` latent RCE — must swap to a safe format **before** F-KNOW-07; needs back-compat (old `.pkl` → miss+rebuild). |
| F-KNOW-07 | 🟡 | BM25 snapshots on ephemeral per-dyno disk → hybrid silently dense-only in prod. Full fix = shared object storage (new dep/config/deploy) → architecture decision, tracked for backlog; observability (log on `load()` miss) to land first. |
| F-KNOW-08 | 🟡 | clone dir not removed on project delete (orphaned source) — ties to the `indexing_artifacts` cleanup path. |

### NOT RESOLVED — all other modules (open)

Everything in the §4 catalog not marked ✅ above is **OPEN** — notably the High items **F-SQL-08, F-CONN-01/02, F-SSH-08, F-PROJ-01, F-RULE-01, F-MCP-01**. Recommended order in §5; the single highest-leverage item remains **DB-session read-only enforcement** (closes the largest cluster).

### Loop status

Module 01 (Auth) **complete & verified**; Module 07 (Knowledge) **partially complete** (4/8 fixed, 4 deferred). The autonomous loop was **stopped here by user request** after finishing the in-flight Module-07 fix and writing this consolidated result.
