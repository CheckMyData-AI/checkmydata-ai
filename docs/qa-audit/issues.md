# CheckMyData.ai — Open Issues (QA / Security Audit)

**The single source of truth for unresolved findings.** Scope: all 19 business modules, backend +
frontend. Resolved findings are intentionally **not** listed here — they are done and verified in
git (see "Already fixed" below). This document tracks only what is **still open**.

> Finding id format: `F-<MODULE>-NN`. Severity: 🔴 Critical · 🟠 High · 🟡 Medium · 🟢 Low · ⚪ Info.

> **Update 2026-07-24:** a full repository audit was run — see
> [`full-audit-2026-07-24/`](full-audit-2026-07-24/) (10 reports). Since the tally below was
> written, **all 3 open High findings were closed**: F-SSH-08 + F-RULE-01 by release R3
> (commit `fbf8112`, 2026-06-25, together with F-RULE-05, F-DG-07/09, F-GRAPH-01, F-SSH-06,
> F-LEARN-07) and F-PROJ-01 by the email-verification work (2026-07-19, commit `1701b46`,
> covered by `backend/tests/integration/test_auth_email_verification.py`). The tally, module
> tables, and release roadmap below have been updated to reflect this.
>
> **Remediation 2026-07-24:** the full audit's findings were remediated on branch
> `fix/audit-remediation-2026-07-24` (8 commits) — 40 FIXED / 5 PARTIAL / 99 deferred of 144.
> Per-finding status and commit mapping:
> [`full-audit-2026-07-24/11-findings-registry.md`](full-audit-2026-07-24/11-findings-registry.md).
> Notably closed: the MongoDB-connector Critical (FA-001), the git-SSRF High (FA-004), the
> AQ-1 downvote-bomb (closes **F-LEARN-08**) and AQ-7 vote-pumping (closes **F-LEARN-03**),
> plus the gitpython/mcp/pyasn1/next CVEs.

## Already fixed (not tracked here — for reference)

**31 findings closed and verified** (backend 4458 tests / 74.62% coverage; frontend 472 tests),
in branch `fix/security-audit-2026-06-24` → PR
[#172](https://github.com/CheckMyData-AI/checkmydata-ai/pull/172):
- **Module 01 Auth** F-AUTH-01…12 (commits `a8d3b2a`, `f35ac10`, `03dad44`, `ed54b48`, `2475114`, `1343fc3`).
- **Module 07 Knowledge** F-KNOW-01/02/03/05 (commits `e642c67`, `81e3d75`).
- **Release R1 — DB-level read-only enforcement** F-SQL-08, F-SQL-04, F-CONN-01, F-CONN-02, F-CONN-03,
  F-CONN-10, F-SCHED-02, F-NOTE-01 (commit `50ce7c8`): per-dialect read-only DB session (PG
  `server_settings`, MySQL `init_command`, ClickHouse `settings.readonly`, Mongo write-stage/JS
  guard) + SafetyGuard statement-initial allow-list + batch/notes call-site guards.
- **Release R2 — Usage accounting & MCP auth** F-MCP-01, F-MCP-02, F-MCP-03, F-MCP-04, F-CHAT-07,
  F-SQL-06, F-BILL-05 (commit `fda9ce5`): per-request `UsageSink` in `LLMRouter` (observed on every
  call); `DbUsageSink` persists usage + re-checks budget for **post-call hard-stop**; planner/
  validator/repair carry the sink; MCP tools build `DbUsageSink`-bound router + acquire
  `agent_limiter` for parity with chat; explicit JWT preferred over env candidate; startup warning
  for empty `MCP_ALLOWED_HOSTS`.
- **Release R5 — code↔DB sync reliability & correctness** (branch `fix/sync-remediation-2026-06-25`,
  18 TDD tasks, commits `d672486`…`fc09a20`): closes **all 22 findings of the separate 2026-06-25
  five-specialist sync-subsystem audit** (9 High, 9 Medium, 4 Low — tracked under that audit's own
  H/M/L scheme, not the `F-<MODULE>-NN` tally below). **High:** H1 daily-sync parent heartbeat
  (reaper no longer kills healthy runs), H2 batch analyses reconciled by echoed `table_name`, H3
  per-table confidence coercion, H4 all-fallback overwrite guard + confidence-gated filters, H5
  owner-attributed budget gate (429/graceful-cron), H6 PII scrub + per-connection opt-out, H7
  `is_indexed` status whitelist, H8 `IntegrityError`→409 + model index parity, H9 adopt-not-run.
  **Medium:** M1 reconciler all-connections, M2 schema-qualified table identity, M3 parent-run
  progress steps, M4 per-project schedule hour honored, M5 overview regen + worker log key, M6
  enrichment validation/deep-merge + producer reroute, M7 graph `op_kind` heuristic labelling, M8
  freshness defaults + `sync_failed`, M9 `get_index_age` NULL guard. **Low:** L1 reaper unknown-
  rowcount log, L2 prompt-header date gating, L3 child-run orphaning (covered by H1+H9), L4
  truncation markers + relevance matching. Combined suite 4560 passing, 75% coverage; ruff/mypy
  clean; alembic up/down/base clean. Spec + plan under `docs/superpowers/{specs,plans}/2026-06-25-*`.
- **Release R3 — cross-tenant isolation & IDOR** F-RULE-01, F-RULE-05, F-DG-07, F-DG-09,
  F-GRAPH-01, F-SSH-08, F-SSH-06, F-LEARN-07 (commit `fbf8112`, 2026-06-25): ownership-scoping
  sweep — global-rule creation requires admin, agent `manage_rules` scoped by project,
  `/investigate` validates message/connection/session belong to the URL project, data-graph
  metric delete scoped by project, SSH tunnel cache key carries a credential discriminator,
  `user_id IS NULL` SSH keys no longer shared across tenants, global-pattern learnings
  tenant-isolated (fail closed).
- **UX audit remediation** (2026-07-19, commits `1701b46`, `5ead515`, `b100e44`, `27104ef`,
  `68f47e4`, `e695caa`): closes **F-PROJ-01** (email verification — registration issues a
  verification email; unverified accounts no longer auto-accepted into projects; backend +
  UI, tested by `backend/tests/integration/test_auth_email_verification.py`) and **F-AUTH-13**
  (forgot/reset password flow, single-use token + `token_version` bump). Also shipped:
  decline invite, dashboard delete, batch results view, honesty sweep, logout toast.

This file also folds in the **2026-06-23 codebase audit** (`code-reviewer` baseline + manual
review). Its findings map as: **H1** = F-KNOW-01 (fixed); **M2** = F-KNOW-02 (fixed); **M1** =
the read-only cluster (F-SQL-08 / F-CONN-01/02, open — denylist hardened in `e642c67` but the
DB-session backstop is still owed); **M3** partially fixed (`projects.py`/`runs.py` via
`spawn_tracked`; the `pipeline_runner` site is gathered rather than untracked — see the
restated F-KNOW-09); **M4/M5/L1/L2** are the
codebase-wide items in §7. Automated baseline grades: backend **B** (1,934 smells, 55 SOLID),
frontend **A** (563 smells, 7 SOLID).

---

## 1. Open severity tally

| Severity | Open |
|---|---|
| 🔴 Critical | 0 |
| 🟠 High | **0** |
| 🟡 Medium | ~27 |
| 🟢 Low | ~48 |
| ⚪ Info | ~15 |

*(R1+R2 closed 4 High + 8 Medium + 3 Low. R3 (`fbf8112`) closed 2 High (F-SSH-08, F-RULE-01) +
5 Medium (F-RULE-05, F-DG-07/09, F-GRAPH-01, F-LEARN-07) + 1 Low (F-SSH-06). The 2026-07-19 UX
remediation closed the last High (F-PROJ-01) + 1 Medium (F-AUTH-13). Includes the 2026-06-23
codebase-audit items folded in — see §7 and the "Already fixed" mapping.)*

**All open High findings are closed.** The two highest-leverage items from the 2026-07-24 full
audit — the MongoDB connector motor-truthiness bug (`05-cross-db.md` B1, Critical) and SSRF
host filtering in `validate_repo_url` (`07-security.md` S-01, High) — were **FIXED** by the
2026-07-24 remediation (commits `0567e21`, `97616b7`). Within this document's own scope, the
top remaining clusters are §3 items 4–7 (credential redaction F-CONN-08, prompt-injection
gate, durable AuditLog, idempotency).

---

## 2. Top priorities (open High)

**None — all three former open High findings are CLOSED:**

| ID | Sev | Title | Status / evidence |
|---|---|---|---|
| ~~**F-SSH-08**~~ | 🟠 | SSH tunnel cache key omits the credential → cross-tenant tunnel sharing | **CLOSED** by R3 (commit `fbf8112`, 2026-06-25): `_key` now includes a credential discriminator (key fingerprint hash). |
| ~~**F-PROJ-01**~~ | 🟠 | Unverified-email registration + email-based auto-accept = invite/access harvesting | **CLOSED** by the email-verification work (2026-07-19, commit `1701b46`): registration issues a verification email; invite auto-accept requires verified email; covered by `backend/tests/integration/test_auth_email_verification.py`. |
| ~~**F-RULE-01**~~ | 🟠 | No authz on global (`project_id=null`) rule creation → cross-tenant prompt injection | **CLOSED** by R3 (commit `fbf8112`, 2026-06-25): global-rule creation requires admin; membership-gated otherwise. |

---

## 3. Cross-cutting clusters (fix once, close many)

1. ~~**Read-only enforcement chokepoint** — F-CONN-01/02, F-SQL-04/08, F-SCHED-02, F-NOTE-01,
   F-CONN-03/10.~~ **CLOSED by R1 (`50ce7c8`)**: per-dialect DB-session read-only + statement-
   initial allow-list + batch/notes call-site guards. (Hardening of the MCP raw-query path that
   reuses connectors inherits the DB-session backstop automatically.)
2. ~~**Object-ownership IDOR family** — F-DG-07, F-DG-09, F-GRAPH-01, F-RULE-05: route checks
   URL-project membership but the mutation/load uses a bare resource id.~~ **CLOSED by R3
   (`fbf8112`)**: every resource load/mutation scoped by `project_id`.
3. ~~**Token-budget / billing under-count** — F-MCP-01, F-CHAT-07, F-SQL-06.~~ **CLOSED by R2
   (`fda9ce5`)**: per-request `UsageSink` threaded through `LLMRouter`; `DbUsageSink` records every
   call + post-call budget hard-stop (also closes F-BILL-05). MCP path gets full parity with chat.
4. **Credential leakage in errors** — F-CONN-08 returns `str(e)` (DSN/password) in the API response
   and logs; the Sentry scrubber only covers Sentry egress. **Fix:** scrub at the
   `connection_service` error site.
5. **Stored prompt-injection / memory poisoning** — **3 of 5 closed 2026-08-20.**
   F-LEARN-01 was already screened by `_contains_instruction_shaped_text`; F-LEARN-06 (the
   override PATCH) and F-LEARN-02 (the non-ASCII proxy) closed this pass. **Remaining:
   F-RULE-02, F-SQL-01, F-PROJ-15 — three surfaces with no screen at all** (rule content,
   DB-sourced comments/sampled values, project name/description). One shared fix: lift the
   instruction-pattern set out of `agent_learning_service` into a module of its own and
   apply it at those three points — one pattern set, not four copies, for the same reason
   the credential scrubber was consolidated (a second copy drifts, and drifts silently).
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
| F-AUTH-14 | 🟢 | No per-account login lockout (only IP rate limit) |
| ~~F-AUTH-15~~ | 🟢 | **CLOSED, verified 2026-08-20.** The durable table exists — `app/models/audit_log.py:17` (`class AuditLog`) with migration `a7c8d9e0f1a2_r4_auth_lifecycle_audit.py`. `CLAUDE.md` already said so; this row was the stale one. |
| ~~F-AUTH-16~~ | 🟢 | **CLOSED, verified 2026-08-20.** Both emit — `auth.py:338` (`auth.refresh`) and `auth.py:365` (`auth.logout`), each carrying an explicit `# F-AUTH-16` marker. |

### 02 — Projects, RBAC & Invites
| ID | Sev | Issue |
|---|---|---|
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
| F-CONN-04 | 🟡 | Arbitrary `db_host`/`db_port` (+SSH) → internal-network reach (SSRF) |
| F-CONN-05 | 🟡 | Fernet encryption has no key rotation/versioning |
| F-CONN-06 | 🟢 | `_dict_to_positional` regex mis-handles `::type` casts / `:param` in literals |
| F-CONN-07 | 🟢 | Pool `min_size=1` per cached connector → remote connection exhaustion |
| ~~F-CONN-08~~ | 🟢 | **CLOSED 2026-08-20** (PR #184). `safe_error()` from `app/core/redaction.py` at all six connector sites and both service sites; a ratchet test fails if `error=str(e)` returns. Note the premise was half wrong — a real asyncpg failure carries no password (`[Errno 8] nodename nor servname provided`); the leak needs something to wrap the error with a DSN or command line. Recorded as defence in depth, since the secret is present in the layer by construction (`ssh_exec.py:_config_vars`). |
| F-CONN-09 | 🟢 | Agent connector cache FIFO/instance-scoped |

### 04 — SSH Tunnel & Keys
| ID | Sev | Issue |
|---|---|---|
| F-SSH-01 | 🟡 | TOFU host-key verify fails *open* when known_hosts not writable |
| F-SSH-02 | 🟡 | ClickHouse exec template leaks DB password on remote command line |
| F-SSH-03 | 🟢 | Pre-command allowlist has a global kill-switch (re-enables RCE) |
| F-SSH-04 | 🟢 | `db_port` template var not shell-escaped |
| F-SSH-05 | 🟢 | TOFU check-then-pin not atomic (concurrent first-connect race) |
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
| F-CHAT-08 | 🟢 | `fatal` parallel stage doesn't cancel in-flight siblings |

### 06 — SQL Agent & Query Execution
| ID | Sev | Issue |
|---|---|---|
| F-SQL-01 | 🟡 | Indirect prompt injection via DB content (comments/sampled/distinct values) |
| F-SQL-02 | 🟡 | `row_count` returned-vs-total ambiguity → inaccurate counts |
| F-SQL-03 | 🟡 | Multiplicative retry blow-up (replans × iterations × repairs) |
| F-SQL-05 | 🟢 | `_try_repair` no-op `error_classify` tracker span |
| F-SQL-07 | 🟢 | EXPLAIN validation asymmetric across dialects |

### 07 — Knowledge & Indexing
| ID | Sev | Issue |
|---|---|---|
| F-KNOW-04 | 🟢 | Passphrase-stripped private key briefly on disk during clone (planned: `mkdtemp(0700)` + signal-scrub) |
| F-KNOW-06 | 🟢 | `pickle.load` for BM25 is a latent RCE primitive (swap to safe format **before** F-KNOW-07) |
| F-KNOW-07 | 🟡 | BM25 snapshots on local ephemeral disk → hybrid silently dense-only in prod (needs shared storage; add `load()`-miss metric first) |
| F-KNOW-08 | 🟡 | Git clone dir not removed on project delete → orphaned source on disk |
| ~~F-KNOW-09~~ | 🟢 | **Restated 2026-08-19 (AUD-0819-16) — the original finding is stale.** The site moved to `pipeline_runner.py:1526` and the tasks **are** collected and awaited (`asyncio.gather(*tasks, return_exceptions=True)` at `:1531`), so nothing is GC'd mid-flight. **Restated again 2026-08-20 — half of the restatement was also wrong.** (a) The fan-out is **not** unbounded: `ast_parse_concurrency` defaults to 4 and `_parse_one` holds the semaphore around the work, so four files parse at once; the 8,541 task objects cost ~7 MiB measured. (b) The real residual — `return_exceptions=True` results never inspected — is **FIXED**: exceptions raised outside `_parse_one`'s own handler are now counted, logged with their cause, and named in the stage event so the count reaches the run journal. Covered by `tests/unit/knowledge/test_ast_parse_swallowed_errors.py`. |

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
| ~~F-LEARN-06~~ | 🟢 | **CLOSED 2026-08-20.** The override PATCH now runs `validate_learning_quality` + `normalize_lesson_text` before writing, and returns 422 on rejection (`connection_learnings.py`). The gate already screened instruction-shaped text on the ingest path — the check is labelled "possible prompt injection" — so the exposure was purely the asymmetry, the same shape as F-LEARN-08. Tests: `test_learnings_api.py` (4 route tests, watched failing with the gate removed). |
| ~~F-LEARN-08~~ | 🟢 | **CLOSED 2026-08-20 — and the open half was the other direction.** The 👎 path was already guarded by a per-message `learning_contradicted_at_feedback` flag (covered by `test_feedback_downvote_idempotency.py`), so the reported defect was fixed before this pass. Its twin was not: the route guarded 👍 on `learning_credited_at_validation`, set at *validation* time, so a message never credited there could be up-voted twice and bump `times_applied` twice per learning — which feeds the decay score and the ranking. Now `process_positive_feedback_learning_effects` carries the symmetric guard; `test_feedback_upvote_idempotency.py`. |
| ~~F-LEARN-01~~ | 🟢 | **CLOSED — verified 2026-08-20, already in place.** Every lesson reaching `create_learning` passes `validate_learning_quality`, whose `_contains_instruction_shaped_text` screen carries nine patterns and is labelled "possible prompt injection" (`agent_learning_service.py`). The row predates that check. |
| ~~F-LEARN-02~~ | 🟢 | **CLOSED 2026-08-20, and the rule was worse than reported.** It rejected any lesson >50% non-ASCII, so every Russian and Chinese lesson failed — while the *same request in English* passed untouched. It never caught raw user requests; it caught non-English text and was read as catching requests. Replaced by what it was reaching for: a bare-question check (language-independent) and a Unicode-aware "is this writing at all" ratio. The genuine check — compare the lesson to the question that produced it — needs the question threaded through six `create_learning` call sites and is recorded as AUD-0820-01 rather than faked with a per-language wordlist. Tests: `test_learning_gate_symmetry.py` (12). |
| F-LEARN-03 | 🟢 | Confidence pumpable to 1.0 via repeated confirm/dedup |
| F-LEARN-04 | 🟢 | Heuristic contradiction detection misses semantic conflicts |
| F-LEARN-05 | 🟢 | Token-based dedup → paraphrased duplicates bloat prompt |

### 11 — Rules Engine
| ID | Sev | Issue |
|---|---|---|
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
| ~~F-SCHED-07~~ | 🟢 | **CLOSED 2026-08-20.** `BatchService._claim_batch` takes the run claim in one atomic UPDATE, so a retried job that loses the race returns without touching results. The claim is deliberately **stale-aware** — it also takes a `running` row whose attempt began longer ago than ARQ could have kept it alive (`batch_stale_claim_seconds`, matched to the job ceiling) — because a claim on `pending` alone would have stranded every crashed batch forever: the stale-run reaper covers `indexing_runs` and has **no knowledge of `batch_queries`**. New column `batch_queries.started_at` (migration `b1c2d3e4f5a6`, verified up and down on a fresh database); `created_at` could not serve, since a batch may sit `pending` for a long time. Tests: `test_batch_claim_idempotency.py` (8). |
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
| F-BILL-03 | 🟢 | `/webhook` no rate limit / body cap |
| F-BILL-06 | 🟢 | Budget windows UTC-based, not per-user timezone |
| F-BILL-08 | 🟢 | No `charge.dispute.*`/`charge.refunded` handler → chargeback ≠ revoke |
| F-BILL-04 | ⚪ | Ledger payload truncated at 64KB |

### 15 — MCP Server
*All R2 findings closed (`fda9ce5`). Module currently has no open issues.*

### 16 — Notifications, Notes & Feed
| ID | Sev | Issue |
|---|---|---|
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
2. ~~**F-SSH-08** credential discriminator in tunnel cache key (cross-tenant tunnel sharing).~~
   **DONE — R3 (`fbf8112`).**
3. ~~**Object-ownership IDOR sweep** — F-DG-07/09, F-GRAPH-01, F-RULE-05 (+ audit all mutations).~~
   **DONE — R3 (`fbf8112`).**
4. ~~**F-PROJ-01 / F-RULE-01** — email verification before invite auto-accept; global-rule authz.~~
   **DONE — F-RULE-01 by R3 (`fbf8112`); F-PROJ-01 by email verification (`1701b46`).**
5. **Per-request usage sink** in `LLMRouter` → F-MCP-01, F-CHAT-07, F-SQL-06, F-BILL-05.
6. ~~**Credential-redaction at source** (F-CONN-08) + **durable `AuditLog` table** (F-AUTH-15/16).~~
   **DONE — redaction 2026-08-20 (`app/core/redaction.py`, `safe_error` at every connector and
   service site); the `AuditLog` table and the refresh/logout events were already shipped and
   this list was stale.**
7. ~~**Idempotency** — F-LEARN-08 (feedback transition-guard) + F-SCHED-07 (batch claim).~~
   **DONE 2026-08-20, both.** F-LEARN-08's open half turned out to be the upvote, not the
   downvote the row described; F-SCHED-07's claim had to be stale-aware because nothing
   reaps batches.
8. Remaining Medium/Low per module table **← the whole ordered list is now here.**

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

---

## 8. Release roadmap (grouped for delivery)

The open findings are grouped into **14 releases**, each bundling bugs that share a root cause,
module, or file set so they can be specced, built, and shipped **together**. One branch + PR per
release; a release is "done" only when its bugs are closed end-to-end.

### Per-release cycle (run for every release)

1. **Deep study** — read the touched code + docs (CLAUDE.md, `vision.md` §7 invariants,
   `ARCHITECTURE.md`, relevant `docs/*`); verify current external-lib APIs via Context7 **before**
   writing the spec.
2. **SPEC** — `docs/superpowers/specs/<date>-rel-NN-*-design.md`; lock shared contracts
   (types/schemas/signatures/file layout) for a zero-context implementer.
3. **DOC** — update the affected product docs (API.md, CLAUDE.md, feature flags, `.env.example`)
   as part of the same change (Definition of Done).
4. **PLAN** — `docs/superpowers/plans/<date>-rel-NN-*.md`; TDD tasks, non-overlapping file
   ownership, explicit dependency graph + parallel groups.
5. **Subagent-driven development** — execute the plan with parallel subagents where files don't
   overlap; sequential glue tasks between groups.
6. **Verify** — `make check` (ruff format+check, mypy, full unit+integration, coverage ≥ 72%) +
   frontend `tsc`/`eslint`/`vitest` when frontend is touched; review **test logs** + **linter**.
7. **Deploy** — branch → PR → merge `main` (prod auto-deploy). *(Direct push to `main` is gated by
   the safety classifier; the merge is the human approval step unless a push-to-main permission
   rule is added.)*
8. **Post-deploy** — check prod health (`/api/health`) + Heroku logs for new errors; if clean,
   **close the release's bugs** and move to the next.

### Delivery order

Ordered by **max severity × leverage** (security-critical / High-closing first). Each release lists
its bug IDs; every open finding is assigned to exactly one release.

#### Wave A — security-critical (closes all open High)

| Rel | Title | Sev | Bugs | Modules / key files | Why grouped |
|---|---|---|---|---|---|
| ~~**R1**~~ | DB-level read-only enforcement | ✅ DONE | F-SQL-08, F-SQL-04, F-CONN-01, F-CONN-02, F-CONN-03, F-CONN-10, F-SCHED-02, F-NOTE-01 | `core/safety.py`, `connectors/*`, `services/batch_service.py`, `routes/notes.py` | Closed by commit `50ce7c8` — per-dialect DB-session read-only + statement-initial allow-list + batch/notes call-site guards. **All 8 bugs closed.** |
| ~~**R2**~~ | Usage accounting & MCP auth | ✅ DONE | F-MCP-01, F-MCP-02, F-MCP-03, F-MCP-04, F-CHAT-07, F-SQL-06, F-BILL-05 | `llm/router.py`, `mcp_server/*`, `agents/*` budget sites | Closed by commit `fda9ce5` — per-request `UsageSink` in `LLMRouter` + `DbUsageSink` post-call recording & budget hard-stop + MCP parity with chat (limiter + sink) + JWT precedence + DNS-rebinding startup warning. **All 7 bugs closed.** |
| ~~**R3**~~ | Cross-tenant isolation & IDOR | ✅ DONE | F-RULE-01, F-RULE-05, F-DG-07, F-DG-09, F-GRAPH-01, F-LEARN-07, F-SSH-08, F-SSH-06 | `routes/{rules,data_investigations,data_graph}.py`, `services/agent_learning_service.py`, `connectors/ssh_tunnel.py`, `ssh_key_service.py` | Closed by commit `fbf8112` (2026-06-25) — ownership-scoping sweep + tunnel/key credential discriminator + global-rule authz. **All 8 bugs closed.** |

#### Wave B — security / correctness (Medium)

| Rel | Title | Sev | Bugs | Modules / key files | Why grouped |
|---|---|---|---|---|---|
| **R4** | Identity, auth lifecycle & durable audit | 🟠 | ~~F-PROJ-01~~, ~~F-AUTH-13~~, F-AUTH-14, F-AUTH-15, F-AUTH-16 | `routes/auth.py`, `services/{auth,invite,email}_service.py`, `core/audit.py`, new `AuditLog` model | Shared email-verification + account-security infra; durable `AuditLog` table underpins F-AUTH-15/16. *(F-PROJ-01 and F-AUTH-13 closed out-of-band by the 2026-07-19 UX remediation — R4 scope reduced to F-AUTH-14/15/16.)* |
| **R5** | Connection & SSH hardening + credential redaction | 🟡 | F-CONN-04, F-CONN-05, F-CONN-06, F-CONN-07, F-CONN-08, F-CONN-09, F-SSH-01, F-SSH-02, F-SSH-03, F-SSH-04, F-SSH-05, F-SSH-07, F-SSH-09, F-LLM-03 | `connectors/*`, `connectors/ssh_*`, `services/connection_service.py` | Same files (connectors + ssh); SSRF host-validation, key rotation, error redaction at source (F-CONN-08 + F-LLM-03), pool caps, SSH template/escape/atomicity. |
| **R6** | Memory & prompt-injection hygiene | 🟡 | F-RULE-02, F-RULE-03, F-RULE-04, F-LEARN-01, F-LEARN-02, F-LEARN-03, F-LEARN-04, F-LEARN-05, F-LEARN-06, F-LEARN-08, F-SQL-01 | `knowledge/custom_rules.py`, `services/agent_learning_service.py`, `agents/sql_agent.py` | Shared content-safety/provenance gate on every rule/learning ingest + dedup + idempotent feedback; F-SQL-01 (DB-content injection) is the upstream source. |
| **R7** | Knowledge & GitAgent hardening | 🟡 | F-KNOW-04, F-KNOW-06, F-KNOW-07, F-KNOW-08, F-KNOW-09, F-GIT-01, F-GIT-02, F-GIT-03, F-GIT-04, F-GIT-05, F-GIT-06 | `knowledge/{repo_analyzer,bm25_index,pipeline_runner}.py`, `agents/git_agent.py` | Module 07/08 ingestion + live-git; F-GIT-01 (rev option-injection → arbitrary write) is the security driver; BM25 pickle→safe format precedes shared-storage (F-KNOW-07). |
| **R8** | Schedules, batch & worker reliability | 🟡 | F-SCHED-01, F-SCHED-03, F-SCHED-04, F-SCHED-05, F-SCHED-06, F-SCHED-07 | `routes/schedules.py`, `batch.py`, `worker.py`, `core/task_queue.py` | Module 13; idempotency (F-SCHED-07 atomic claim), creator-access revocation, reap race, ARQ fallback hygiene. |
| **R9** | Billing & entitlements | 🟡 | F-BILL-01, F-BILL-02, F-BILL-03, F-BILL-04, F-BILL-06, F-BILL-07, F-BILL-08 | `routes/billing.py`, `services/entitlement_service.py`, Stripe webhooks | Module 14; plan resolution from live price, service-level quota (TOCTOU + demo bypass), webhook hardening, chargeback→revoke. |

#### Wave C — quality, correctness & tech-debt

| Rel | Title | Sev | Bugs | Modules / key files | Why grouped |
|---|---|---|---|---|---|
| **R10** | Projects, RBAC & invites lifecycle | 🟡 | F-PROJ-02, F-PROJ-03, F-PROJ-04, F-PROJ-05, F-PROJ-06, F-PROJ-07, F-PROJ-08, F-PROJ-09, F-PROJ-10, F-PROJ-11, F-PROJ-12, F-PROJ-13, F-PROJ-14, F-PROJ-15 | `routes/{projects,invites}.py`, `services/{project,invite}_service.py`, `api/deps.py` | Module 02; owner-model consistency, invite expiry/idempotency, ownership transfer, leave-project, pagination, role validation, prompt-meta sanitization. |
| **R11** | Chat/orchestration, SQL-agent quality & LLM observability | 🟡 | F-CHAT-01, F-CHAT-02, F-CHAT-03, F-CHAT-04, F-CHAT-05, F-CHAT-06, F-CHAT-08, F-SQL-02, F-SQL-03, F-SQL-05, F-SQL-07, F-LLM-01, F-LLM-02, F-LLM-04, F-LLM-05, CB-M5 | `routes/chat.py`, `agents/{orchestrator,sql_agent,stage_executor}.py`, `llm/router.py` | WS authz/lifecycle, relay timeout, agent retry/accuracy, provider-fallback governance; CB-M5 (broad excepts) lives in these request paths (overlaps F-CHAT-05). |
| **R12** | Data quality / DataGate robustness | 🟡 | F-DG-01, F-DG-02, F-DG-03, F-DG-04, F-DG-05, F-DG-06, F-DG-08 | `agents/data_gate.py`, `investigation_agent.py` | Module 09; hard-check robustness (Decimal/sample/fuzzy/JSON-cell), bounds, row_count reliability. |
| **R13** | Visualizations, dashboards, exploration & demo | 🟡 | F-VIZ-01, F-VIZ-02, F-VIZ-03, F-VIZ-04, F-EXP-01, F-EXP-02, F-EXP-03, F-EXP-04 | `routes/{visualizations,dashboards,exploration,demo}.py`, `agents/viz_agent.py` | Modules 12/18; CSV-injection neutralization, snapshot freshness, `cards_json` validation, demo seeding/read-only/dedup. |
| **R14** | Frontend polish, notes & tech-debt | 🟢 | F-FE-03, F-FE-04, F-NOTE-02, F-NOTE-03, CB-M4, CB-L1 | `frontend/src/*`, `routes/notes.py`, god-file decomposition | a11y/design-token sweep, JSON-LD assertion, note pool reuse/staleness, god-file decomposition (CB-M4), suppression-debt cleanup (CB-L1). |

**Coverage check:** R1–R14 partition all open findings (Modules 01–19 + codebase-wide CB-*).
**R1 done** (`50ce7c8`), **R2 done** (`fda9ce5`), **R3 done** (`fbf8112`); the last open High
(F-PROJ-01, R4) was closed out-of-band by the 2026-07-19 UX remediation — there are now
**0 open High**.
