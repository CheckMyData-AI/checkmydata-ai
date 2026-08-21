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
| 🟡 Medium | 7 |
| 🟢 Low | 42 |
| ⚪ Info | 9 |

*Counted 2026-08-21, not estimated: 58 open rows and 48 struck
through, by `grep -c '^| F-'` / `grep -c '^| ~~F-'` over this file. The `~` figures this
replaced had drifted — the tally is now derived from the rows it summarises.*

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
5. ~~**Stored prompt-injection / memory poisoning**~~ — **ALL 5 CLOSED 2026-08-20.**
   F-LEARN-01 was already screened by `_contains_instruction_shaped_text`; F-LEARN-06 (the
   override PATCH) and F-LEARN-02 (the non-ASCII proxy) closed this pass. F-SQL-01 turned
   out to be closed already, by the right mechanism: content you cannot refuse is
   neutralised in the PROMPT, not screened at ingest. Finding that reframed the fix —
   the defence existed, was written once in `sql_prompt.py`, and had never reached the
   other nine agent prompts. **Six surfaces the board never listed were hardened in the
   same pass**: third-party MCP tool output, retrieved repository file contents, commit
   messages and diffs (forgeable, F-GIT-06), vendor analytics rows, sub-agent output, and
   the columns/values being charted. `prompts/untrusted_data.py` builds the section and
   requires its sources to be NAMED — "some content may be untrusted" is advice, "the
   commit messages below are attacker-controllable" is actionable — and
   `test_untrusted_data_sections.py` is a ratchet so the tenth prompt cannot skip it.
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
| ~~F-PROJ-02~~ | 🟢 | **CLOSED 2026-08-20.** `get_role` and `get_roles_bulk` now honour `Project.owner_id`, which `_accessible_filter` already calls "the single source of truth for the access rule" and which `can_access` already used — so this aligned the readers with a rule the code declares rather than adding a fourth guard. Access is **not widened**: `can_access` already admitted the owner; only the *role* now agrees with the access already granted. Every mutation path was verified closed first (`remove_member` and `update_member_role` both refuse an owner, and `accept_invite` returns an existing member untouched instead of overwriting its role), so the reachable exposure was the partial-creation state — the project and the owner's member row commit separately (`projects.py:186-189`, and `add_member` commits on its own), and a failure between them locked the owner out permanently, with no transfer path (F-PROJ-10) to recover. Tests: `test_owner_role_consistency.py` (9). |
| ~~F-PROJ-03~~ | ✅ | ~~`accept_invite` commits inside `begin_nested()` → 500 on idempotent re-accept~~ — **the symptom does not reproduce; the fragility behind it was real. Corrected and fixed 2026-08-20.** Measured on SQLAlchemy 2.0.51 + aiosqlite: no 500. `test_does_not_duplicate_if_already_member` has always passed, and a direct reproduction (`async with s.begin_nested(): insert; await s.commit()`) raised nothing and persisted the row — a `commit()` inside an open SAVEPOINT deactivates the savepoint transaction, which exits quietly. The bookkeeping lives in `SessionTransaction`, shared across dialects, so Postgres does not differ. **What was real:** the savepoint bought nothing — the early return committed inside it and the normal path committed after it, so no rollback path existed for it to provide, and a savepoint that never rolls back reads as a guarantee — and committing inside an open one works by accident of this library version, so a stricter SQLAlchemy would have produced the 500 the board already believed in. Now one transaction committed once, with the `IntegrityError` retry that was always the real concurrency guard. Evidence: `tests/unit/test_invite_service.py::TestAcceptIsOneTransaction` (4), four plants. |
| ~~F-PROJ-04~~ | 🟢 | **CLOSED 2026-08-20.** `project_invites.expires_at` (migration `c2d3e4f5a6b7`, verified up and down on a fresh database) plus `invite_expiry_days` (14). The two acceptance paths behave differently on purpose: the interactive one returns **410** with a sentence a person can act on, while `auto_accept_for_user` **skips** — it runs inside registration, and raising there would fail somebody's sign-up over a stranger's forgotten invitation, which is worse than the bug. NULL `expires_at` is read as `created_at + invite_expiry_days` rather than "never", so the policy reaches every row that predates the column — precisely the stale invites this is about — without a backfill inventing values. Note F-PROJ-01's email verification does **not** cover this: a re-registered address verifies fine, because verification proves control of the mailbox today, not that the invite was meant for whoever holds it now. Tests: `test_invite_expiry.py` (8). |
| ~~F-PROJ-05~~ | ✅ | ~~Fire-and-forget `asyncio.create_task` sync-now → silent task death~~ — **half of it was already fixed; the other half was in three places the row does not mention. 2026-08-21.** The named route (`sync-now`) already used `spawn_tracked`, which holds a strong reference and logs failures at `error`, so the "silent" part was closed before the row was read. What remained is retention at the sites that launch work from a request and return: `batch.py:107`, `data_investigations.py:157`, `chat_feedback.py:487` — each assigned a task to a local, attached a done-callback and returned, leaving only asyncio's weak reference. **A done-callback is bookkeeping, not a lifetime.** All three now use `spawn_tracked`. Ratchet: an AST sweep asks whether the assigned name is used for anything besides `add_done_callback` inside its function — the first version scanned a 25-line text window and produced two false positives (`chat.py` awaits and cancels its tasks 30 and 130 lines later, which is structured concurrency). Evidence: `tests/unit/test_task_queue_no_silent_relocation.py::TestFireAndForgetTasksAreHeld`, three plants. |
| ~~F-SCHED-04b~~ | ✅ | **My own fix was incomplete, and the test I wrote for it could not tell.** F-SCHED-04 declared `allow_in_process=False` at three heavy `enqueue` sites and asserted exactly those three by name. An AST sweep found **three more**: `projects.py:600` (manual sync-now), `runs.py:173` (a repo-index retry) and `main.py:790` — the daily-sync cron loop, which runs *inside the web dyno*, so a broken Redis put the entire daily sync (repo index + DB index + code↔DB sync) in the process serving requests. A test written from the list of things you changed cannot tell you what you missed. Replaced with a sweep derived from the code, plus a guard against it matching nothing and passing by vacuity. `main.py`'s `coro_factory` still runs when there is no Redis — the refusal only applies when Redis is configured and the enqueue throws — and the comment there says so, because that is where the next reader will doubt it. |
| F-PROJ-06 | 🟡 | Commit-then-await-email → partial-success 500s / confusing 409 |
| F-PROJ-07 | 🟢 | Service role methods don't validate role strings |
| F-PROJ-08 | 🟢 | `InviteCreate.role` advertises `owner` but route rejects it |
| F-PROJ-09 | ⚪ | `revoke_invite` ignores `_user_id`; authz only at route |
| F-PROJ-10 | 🟡 | No ownership transfer / co-owner → owner departure strands workspace |
| F-PROJ-11 | 🟢 | `add_member` upsert not `IntegrityError`-guarded → concurrent add 500 |
| F-PROJ-12 | 🟢 | No self-service "leave project" |
| F-PROJ-13 | 🟢 | `list_members`/`list_invites` no pagination cap |
| ~~F-PROJ-14~~ | 🟢 | **CLOSED 2026-08-20** by the same change — `get_roles_bulk` feeds the project list, so the divergence landed on the first screen a locked-out owner would look at. |
| ~~F-PROJ-15~~ | 🟢 | **CLOSED 2026-08-20** by the same orchestrator section, which names the project name, description and overview explicitly. |

### 03 — Connections & Connectors
| ID | Sev | Issue |
|---|---|---|
| ~~F-CONN-04~~ | ✅ | ~~Arbitrary `db_host`/`db_port` (+SSH) → internal-network reach (SSRF)~~ — **fixed 2026-08-20, and the obvious guard was the wrong one.** `validate_repo_url` refuses every non-public address by default, which is right for a git remote and wrong here: most deployments reach their database at `10.x`, `192.168.x` or `127.0.0.1`, so the same default would break the product for the majority to protect the minority running it multi-tenant — and a guard that breaks the normal case gets turned off, after which it protects nobody. So: **cloud metadata endpoints refused on every deployment** (`169.254.169.254`, `169.254.170.2`, `fd00:ec2::254`, `metadata.google.internal`, by name *and* by resolved address — no database lives there and what does hands out credentials for the account), **private addresses refused only under `CONNECTION_ALLOW_PRIVATE_HOSTS=false`** (default `true`). Every resolved address is checked, a host that cannot be resolved is accepted with a log line by default and refused only under `CONNECTION_ALLOW_PRIVATE_HOSTS=false` — the first version refused it in both modes and `test_database_connection_still_creates_with_its_defaults` went 422 on `db.internal` within the hour, which is the "guard that breaks the normal case" failure this fix has a written section about; a literal costs no DNS lookup, and the check runs off the event loop. Applied to `db_host`, `ssh_host` and a DSN's host, on **create and PATCH**. Evidence: `tests/unit/test_connection_host_guard.py` (28) + `tests/integration/test_connection_host_ssrf.py` (3), seven plants. |
| F-CONN-05 | 🟡 | Fernet encryption has no key rotation/versioning |
| F-CONN-06 | 🟢 | `_dict_to_positional` regex mis-handles `::type` casts / `:param` in literals |
| F-CONN-07 | 🟢 | Pool `min_size=1` per cached connector → remote connection exhaustion |
| ~~F-CONN-08~~ | 🟢 | **CLOSED 2026-08-20** (PR #184). `safe_error()` from `app/core/redaction.py` at all six connector sites and both service sites; a ratchet test fails if `error=str(e)` returns. Note the premise was half wrong — a real asyncpg failure carries no password (`[Errno 8] nodename nor servname provided`); the leak needs something to wrap the error with a DSN or command line. Recorded as defence in depth, since the secret is present in the layer by construction (`ssh_exec.py:_config_vars`). |
| F-CONN-09 | 🟢 | Agent connector cache FIFO/instance-scoped |

### 04 — SSH Tunnel & Keys
| ID | Sev | Issue |
|---|---|---|
| ~~F-SSH-01~~ | ✅ | ~~TOFU host-key verify fails *open* when known_hosts not writable~~ — **fixed 2026-08-20.** `ssh_known_hosts.py` answered an unwritable file by setting `known_hosts=None` and connecting anyway — for that connection and every later one — so the policy turned itself off and logged about it. The module's own closing branch says an unrecognised policy "must never silently disable verification"; two branches above, that is what happened. Fail-closed would break every connection on a read-only filesystem to protect a promise the operator never made, so the pin moves into process memory instead: the first connect to a host is unverified (which is what trust-on-first-use *is*) and every later connect is checked against the key that first one presented, raising `HostKeyChangedError` and aborting on a mismatch. Where the file is writable but the disk does not survive a restart (AUD-0819-06) that was already the guarantee, so nothing is downgraded. A host presenting no readable key is **not** recorded — remembering it would assert a check that cannot happen. Evidence: `tests/unit/test_ssh_tofu_memory_pin.py` (8), four plants. |
| ~~F-SSH-02~~ | ✅ | ~~ClickHouse exec template leaks DB password on remote command line~~ — **fixed 2026-08-20, and the finding under-stated it twice.** (1) **All three engines**, not ClickHouse alone: `PGPASSWORD=`, `MYSQL_PWD=` and `CLICKHOUSE_PASSWORD=` were interpolated into the command string, `asyncssh.run()` sends it as an SSH exec request, and sshd runs it as `sh -c "<command>"` — so the secret sat in that process's argv, readable by any user on the remote host via `ps` for the query's duration. (2) **The ClickHouse template never authenticated.** A command-prefix assignment does not affect `"$VAR"` on the same line: measured, `sh -c 'FOO="secret" printf "[%s]" "$FOO"'` prints `[]`, and with `FOO=leaked` in the environment it prints `[leaked]` — so `--password "$CLICKHOUSE_PASSWORD"` passed an empty string, or somebody else's. Fixed: the password travels on the channel's stdin (`IFS= read -r DBPASS`), templates set the client's variable from `"$DBPASS"` as an environment assignment, `--password` is gone, a newline in a password is refused rather than silently truncated by `read -r`, and the nine introspection call sites that built commands by hand now route through `_build_command`. A custom `ssh_command_template` keeps the old behaviour with a warning. Evidence: `tests/unit/test_ssh_exec_password_off_argv.py` (24), six plants. |
| F-SSH-03 | 🟢 | Pre-command allowlist has a global kill-switch (re-enables RCE) |
| F-SSH-04 | 🟢 | `db_port` template var not shell-escaped |
| F-SSH-05 | 🟢 | TOFU check-then-pin not atomic (concurrent first-connect race) |
| F-SSH-07 | 🟢 | Auto-reconnect re-runs command → double-executes non-idempotent ops |
| F-SSH-09 | 🟢 | `_locks`/per-key state grows unboundedly |

### 05 — Chat & Orchestration
| ID | Sev | Issue |
|---|---|---|
| ~~F-CHAT-01~~ | 🟢 | **CLOSED 2026-08-20.** Access is re-checked per **message**, not per connection — a socket lives as long as the tab, so a connect-time check left a removed member querying the project's database until they reloaded. Authorization belongs to the action, and a message is the action: one indexed query against messages that arrive seconds to minutes apart. A revoked member is told and closed with 4003 rather than silently ignored. **Found alongside:** the gate carried its own raw-SQL copy of `owner_id OR member` — a fourth copy of a rule whose helper docstring names *this very call site* as a user of the single source of truth. Now `can_access`. Tests: `test_ws_authz_revalidation.py` (4), the re-check watched failing with the guard disabled. |
| ~~F-CHAT-02~~ | ✅ | **Fixed 2026-08-20** — `ChatService.get_or_create_empty_session` reuses this `(project, connection, user)`'s empty session instead of writing a row per connect, and the WS route calls it (`chat.py:1554`). A session with messages in it is never handed back: resuming a stranger's conversation because it shares a triple would be far worse than the row it saves. Lazy creation was ruled out by the protocol — `session_created` promises an id at connect time. Evidence: `tests/unit/test_ws_relay_and_orphans.py` (5 of 9), six plants. **Correction 2026-08-20 (later):** the impact recorded below is wrong. `grep -rln "WebSocket\|session_created" frontend/src/` is **empty** — the product's own UI speaks SSE (`src/lib/api/chat.ts:150` → `/chat/ask/stream`) and never opens this endpoint, so a tab reload creates no session here. The finding stands for third-party clients of the documented WS API (`API.md:206`), and their orphans do reach the session list, but "ten tab reloads leave ten orphans" is not something this code can do. **Original evidence, 2026-08-20:** `_chat_svc.create_session` is called **before** the `while True:` receive loop (`chat.py:1545`), unconditionally, so every connect writes a row even when no message is ever sent — ten tab reloads leave ten orphans, and they pollute the session list the user reads (SCN-048), not only the table. The protocol constrains the fix: `session_created` is sent immediately after, so the client expects an id at connect time. Reusing an existing empty session for the same `(project, connection, user)` bounds orphans to one per triple **and** preserves the contract exactly; creating lazily on first message would not. |
| ~~F-CHAT-03~~ | ✅ | **Fixed 2026-08-20** — the relay polls and continues instead of exiting on quiet, with `ws_event_relay_poll_seconds` (0.5) and an overall `ws_event_relay_timeout_seconds` (900) ceiling; the hardcoded 60 is gone. Extracted to `relay_workflow_events` so "survives a gap, still ends at the deadline" is testable without a WebSocket handshake — neither half was reachable through the endpoint in a unit test. The shape is the SSE relay's, twenty lines away, so the two transports no longer disagree about what silence means. Evidence: `tests/unit/test_ws_relay_and_orphans.py` (4 of 9). **Correction 2026-08-20 (later):** "the reasoning panel goes quiet" is wrong — the panel is fed by SSE, and the **SSE relay is already correct**: `chat.py:1032-1043` polls on a 0.5 s timeout, emits a heartbeat every 20 s, holds `stream_timeout_seconds` as the overall deadline and *continues* rather than exiting on a gap. The broken relay is the WebSocket one, which no first-party client opens. The fix is to make it match the correct implementation already in the same file. **Original evidence, 2026-08-20:** `chat.py:1478` — `await asyncio.wait_for(queue.get(), timeout=60)`, a hardcoded 60 s with no setting beside it, while `ws_idle_timeout_seconds` exists for the receive side. A step that legitimately exceeds a minute (a large `ast_parse`, a slow warehouse query) stops the relay while the run continues, so the reasoning panel goes quiet and the answer arrives with no trace of how — which reads as a hang. |
| F-CHAT-04 | 🟢 | WS uses connection config captured once; stale after mid-session edits |
| F-CHAT-05 | ⚪ | ~51 silent exception handlers mask errors (cross-cutting) |
| F-CHAT-06 | 🟢 | WS `receive_json` no explicit payload cap (mitigated: 20K model cap; uvicorn 16MB frame) |
| F-CHAT-08 | 🟢 | `fatal` parallel stage doesn't cancel in-flight siblings |

### 06 — SQL Agent & Query Execution
| ID | Sev | Issue |
|---|---|---|
| ~~F-SQL-01~~ | 🟢 | **CLOSED — verified 2026-08-20, and it was already in place.** `sql_prompt.py` has carried an UNTRUSTED-DATA section naming query results, row values and table/column comments since the earlier remediation. This is the right treatment for content that cannot be refused — a table's comment is part of the schema whatever it says — so no ingest screen was ever the answer here. The section is now built from the shared module instead of a local literal. |
| ~~F-SQL-02~~ | ✅ | ~~`row_count` returned-vs-total ambiguity → inaccurate counts~~ — **fixed 2026-08-21, and the ambiguity was a label that lied.** `QueryResult.row_count` is set by every connector to `len(data)` **after** the row cap and the byte cap: rows *returned*. The formatter the model reads said `f"Total rows: {results.row_count}"` (`result_handler.py:36`), so a query matching fifty thousand rows against a thousand-row cap produced "Total rows: 1000" — and where truncation was detected the banner above it said "capped at 1000 rows (the database has more)", contradicting it in the same prompt, with the mislabelled line reading like the fact. **The two consumers already disagreed**, which is what located it: `answer_validator.py:94` wrote "rows returned". An agent told it has the total states a total, and the user cannot see it counted a page — `vision.md` §7, not wording. Now "Rows returned: N", with "(partial — see the notice above)" appended when truncated so the count line and the banner say the same thing. **Three producers, not one.** Fixing the one I found and asserting completeness is the mistake this session has made three times — three of six heavy `enqueue` sites, two of five rules callers — so an AST sweep ran before the row was closed and found `viz_agent._summarize_results` (what the chart layer reasons over: a caption carrying a total it does not have is a wrong number in a picture nobody re-checks) and `tool_dispatcher` (the enrichment summary, where a model may compute a share from it). All three now say "Rows returned", with a partial marker when truncated. Evidence: `tests/unit/test_result_label_honesty.py` (12) including a sweep that forbids any f-string labelling `row_count` as a total, three plants — one per producer, plus one that showed the assertion only forbade the wrong label instead of requiring the right marker. |
| F-SQL-03 | 🟡 | Multiplicative retry blow-up (replans × iterations × repairs) |
| F-SQL-05 | 🟢 | `_try_repair` no-op `error_classify` tracker span |
| F-SQL-07 | 🟢 | EXPLAIN validation asymmetric across dialects |

### 07 — Knowledge & Indexing
| ID | Sev | Issue |
|---|---|---|
| F-KNOW-04 | 🟢 | Passphrase-stripped private key briefly on disk during clone (planned: `mkdtemp(0700)` + signal-scrub) |
| F-KNOW-06 | 🟢 | `pickle.load` for BM25 is a latent RCE primitive (swap to safe format **before** F-KNOW-07) |
| F-KNOW-07 | 🟡 | BM25 snapshots on local ephemeral disk → hybrid silently dense-only in prod (needs shared storage; add `load()`-miss metric first) |
| ~~F-KNOW-08~~ | ✅ | ~~Git clone dir not removed on project delete → orphaned source on disk~~ — **shipped in #194 and this row was left open; struck 2026-08-21 after checking by content, not by memory.** `cleanup_project_artifacts` removed the BM25 snapshot and the Chroma collection and not the clone at `{repo_clone_base_dir}/{project_id}`. Ephemeral on Heroku, permanent on a persistent volume: somebody who deletes a project has asked for their code to stop being here, which makes it retention before housekeeping. The dangerous part was the fix — an `rmtree` on a path built from an identifier — so the resolved path must be a direct child of the base directory or nothing. **My first version of that guard was wrong**: it checked `is_symlink()` on the *resolved* path, which is always False by construction, so a symlink at a sibling project resolved to a legitimate-looking path inside the tree and `rmtree` followed it into that project's real source; the check now runs on the named path before resolving. Verified in main: `shutil.rmtree` present in `indexing_artifacts.py`, 10 tests in `tests/unit/test_clone_cleanup_on_delete.py`. |
| ~~F-KNOW-09~~ | 🟢 | **Restated 2026-08-19 (AUD-0819-16) — the original finding is stale.** The site moved to `pipeline_runner.py:1526` and the tasks **are** collected and awaited (`asyncio.gather(*tasks, return_exceptions=True)` at `:1531`), so nothing is GC'd mid-flight. **Restated again 2026-08-20 — half of the restatement was also wrong.** (a) The fan-out is **not** unbounded: `ast_parse_concurrency` defaults to 4 and `_parse_one` holds the semaphore around the work, so four files parse at once; the 8,541 task objects cost ~7 MiB measured. (b) The real residual — `return_exceptions=True` results never inspected — is **FIXED**: exceptions raised outside `_parse_one`'s own handler are now counted, logged with their cause, and named in the stage event so the count reaches the run journal. Covered by `tests/unit/knowledge/test_ast_parse_swallowed_errors.py`. |

### 08 — GitAgent (live Git)
| ID | Sev | Issue |
|---|---|---|
| ~~F-GIT-01~~ | ✅ | ~~Option injection via unvalidated rev/sha → `show`/`diff --output=` arbitrary write~~ — **proven, then fixed 2026-08-20.** Not suspected: measured against a scratch repo, `diff("--output=<path>", "HEAD")` turned `victim.txt` from `IMPORTANT ORIGINAL CONTENT` into the diff text, and `show("--output=<path>")` wrote 216 bytes to the same file. Any file the process can write — on a dyno that includes the app's own source, which is RCE at next boot. Reachable from chat: `git_agent.py:373/375/382/408` pass `args["sha"]`/`["a_sha"]`/`["b_sha"]`/`["commit_sha"]` straight from the model's tool call. Fixed with `GitInspector._safe_rev` (no leading dash + a revision charset) applied at all five rev entry points, and `UnsafeRevError` distinguished from `InvalidRefError` so *refused* never reads as *git disagreed*. The original PoC now raises and the file is intact. Evidence: `tests/unit/test_git_inspector_rev_injection.py` (32). |
| ~~F-GIT-08~~ | ✅ | **Found next door while fixing F-GIT-01**: `UpdateRepoRequest.branch` had **no validator** while `AddRepoRequest.branch` called `validate_git_ref` — and the branch reaches `repo.git.checkout(branch)` and `Repo.clone_from(branch=…)` as argv. Same option-injection class, same create-guarded/PATCH-free shape as the connection routes. **Fixed 2026-08-20** (`app/api/routes/repos.py:876-889`). Evidence: `TestTheSameGapNextDoor` (3). |
| ~~F-CONN-09~~ | ✅ | **Found by sweeping the shape rather than the instance** (2026-08-20). Three fields in two days were guarded on create and free on PATCH — `db_type`, `db_name`, `branch` — so an AST sweep of all 109 `BaseModel` classes under `app/api/routes/` compared every `Create`/`Update` pair field by field. Three more, all on `ConnectionUpdate`: **`mcp_env` unbounded** (create caps 50 entries / 255-char keys / 4096-char values; `update()` encrypts and stores whatever arrives into a Text column and hands it to a spawned MCP subprocess), **`connection_string` unstripped** (a DSN's trailing newline reached `encrypt()`), and `name` (covered downstream — harmless, and indistinguishable from the other two by reading either model). Fixed structurally: `_ConnectionFieldRules` is a base both models inherit. Ratchet: `tests/unit/test_create_update_validator_parity.py`, whose allow-list takes a reason rather than an entry. |
| F-GIT-02 | 🟢 | `git_agent_auto_pull` does network fetch + tree update (inherits F-KNOW-02 risk) |
| F-GIT-03 | 🟢 | `except (TimeoutError, Exception)` over-broad on auto-pull |
| F-GIT-04 | 🟢 | Freshness warning detects only "ahead", not "behind/diverged" |
| F-GIT-05 | 🟢 | `list_releases` scans all tags then output-caps (unbounded scan) |
| F-GIT-06 | ⚪ | `review_signals` trailers are forgeable commit text presented as review data |

### 09 — Data Validation / Investigations / DataGate
| ID | Sev | Issue |
|---|---|---|
| ~~F-DG-01~~ | 🟢 | **CLOSED — verified 2026-08-20, already fixed.** `data_gate.py:384` reads `isinstance(val, (int, float, Decimal))`, matching the W0 note in `CLAUDE.md`. The row predates that work. |
| ~~F-DG-02~~ | 🟢 | **CLOSED — verified 2026-08-20, already fixed.** `_check_value_ranges` scans the **whole** in-memory result by default (`qr.rows if scan_cap <= 0`), with the reason written at the call site: "missing even one defeats the gate". The checks that genuinely do sample now say so in their own message ("based on sample only"), which is the other half of the finding. |
| ~~F-DG-03~~ | 🟢 | **CLOSED — verified 2026-08-20, engineered against deliberately.** `_PERCENT_BOUNDED_KEYWORDS` is documented as "only tokens that are *unambiguously* a 0..100 share" and **enumerates the false positives it excludes** — retention, churn and utilization, because NRR exceeds 100%, net churn goes negative and CPU utilization exceeds 100%. A delta/change token demotes a percent column to `rate`, so `pct_growth` is not hard-bounded. The fuzzy-classification-drives-hard-fail concern is exactly what that discipline addresses. |
| ~~F-DG-04~~ | 🟢 | **CLOSED 2026-08-20 — the one of the four that was genuinely open.** Measured: `tuple([1, {"a": 1}]) in set()` raises `TypeError: unhashable type: 'dict'`, so a Postgres `json`/`jsonb` or array column, a Mongo document or an aggregated array took down the gate — and DataGate sits on the answer path, so a good query failed the whole answer. A check that breaks what it is checking is worse than no check. `_hashable()` recurses rather than falling back to `repr`, so rows whose JSON differs only deep inside still count as different and identical JSON still counts as duplicate; a dict is keyed on sorted items so key order does not invent a difference. Tests: `test_data_gate_unhashable_rows.py` (12), including that the check keeps *detecting* and not merely surviving. |
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
| ~~F-RULE-02~~ | 🟢 | **CLOSED 2026-08-20.** The orchestrator prompt now carries a named UNTRUSTED-DATA section listing custom rules and stored learnings among the things that are data rather than instructions (`prompts/untrusted_data.py`, applied in `orchestrator_prompt.py`). Rules are editor-authored, so the exposure was one project member directing another's agent. |
| ~~F-RULE-03~~ | ✅ | ~~`rules_to_context` no budget/size truncation (overflow/cost)~~ — **fixed 2026-08-21, and CLAUDE.md's claim was true at two call sites of five.** Rule text goes straight into an LLM prompt and its size is bounded by nothing the code controls: files an operator drops in `rules/` plus rows a user adds through `manage_custom_rules`. Measured: `orchestrator.py:605` capped at 2000, `sql_agent.py:1991` at 3000 — unrelated magic numbers — while `sql_agent.py:710` (the `get_custom_rules` tool), `sql_agent.py:1974` (repair) and `code_db_sync_pipeline.py:509` had **no cap at all**. Both existing caps sliced the joined string, cutting the last rule mid-sentence and reporting `"... (truncated)"`, which tells the model something was removed and not what — so it could not tell the user its answer may ignore rules they wrote (`vision.md` §7). The budget now lives in `rules_to_context` (`RULES_CONTEXT_MAX_CHARS`, default 3000): **whole rules are dropped, never half of one**, and the notice carries a count. A single rule larger than the whole budget — the case a pre-existing test caught and my design had missed — is cut and **named**, pointing at the setting to raise, because that is the only one of the three bad options the agent can report. Evidence: `tests/unit/test_rules_context_budget.py` (12), three plants. |
| F-RULE-04 | 🟢 | Filesystem rule loading reads any matching-suffix file incl. symlinks |

### 12 — Visualizations & Dashboards
| ID | Sev | Issue |
|---|---|---|
| ~~F-VIZ-04~~ | 🟢 | **CLOSED 2026-08-20, per format rather than with one hammer.** Measured first: `openpyxl` writes a `=`-leading string as `data_type='f'` — a real formula — while `+`, `-`, `@` come out as strings. So **XLSX** forces the cell to text and the value survives byte for byte, while **CSV**, which has no types, must prefix. **JSON is deliberately untouched** — no formula semantics in the format, so altering it would corrupt data for every consumer to protect none. Headers are covered too: column names come from the query. The rule exempts numbers and single characters, and that exemption is the substance — a blanket OWASP character list prefixes every negative number, turning `-1500.00` into `'-1500.00` and breaking a financial export for every downstream consumer, which is a worse bug than the one being fixed. Tests: `test_export_formula_injection.py` (49), including a class devoted to numeric fidelity. |
| F-VIZ-01 | 🟡 | Dashboard cards are stale data snapshots, no freshness signal |
| ~~F-VIZ-02~~ | ✅ | ~~`cards_json` stored verbatim → stored-XSS vector (downgraded: frontend renders escaped React children; residual is unvalidated storage)~~ — **fixed 2026-08-21, and the residual was quieter than "unvalidated storage" suggests.** `parseCards` is `try { JSON.parse(json) } catch { return [] }`, so a malformed string — or valid JSON of the wrong shape — renders as an **empty dashboard**. Dashboards are shared by default, so one bad write shows everyone else a page with nothing on it and no sign anything is wrong. Now validated at the write boundary against the contract the consumer declares (`frontend/src/lib/api/types.ts:502`): array of objects, `note_id` a non-empty string, `viz_config` an optional object, `refresh_interval` an optional number, at most 200 cards — a bound on *work*, since the viewer issues one note fetch per card and the 500 KB byte cap allows ~30 000 of them. `viz_config`'s interior is deliberately not inspected: the viewer treats it as opaque, so validating it would invent a contract nobody wrote. Rules live on a shared `_DashboardCardRules` base so create and PATCH cannot drift. **Writes only** — a legacy row still reads as it always did, because making it fail to load would turn a cosmetic problem into an outage (the F-EXP-06 lesson pointed the other way). Evidence: `tests/unit/test_dashboard_cards_validation.py` (20), six plants. |
| F-VIZ-03 | 🟢 | No server-side JSON/structure/size validation of `cards_json` |

### 13 — Schedules, Batch & Worker
| ID | Sev | Issue |
|---|---|---|
| ~~F-SCHED-07~~ | 🟢 | **CLOSED 2026-08-20.** `BatchService._claim_batch` takes the run claim in one atomic UPDATE, so a retried job that loses the race returns without touching results. The claim is deliberately **stale-aware** — it also takes a `running` row whose attempt began longer ago than ARQ could have kept it alive (`batch_stale_claim_seconds`, matched to the job ceiling) — because a claim on `pending` alone would have stranded every crashed batch forever: the stale-run reaper covers `indexing_runs` and has **no knowledge of `batch_queries`**. New column `batch_queries.started_at` (migration `b1c2d3e4f5a6`, verified up and down on a fresh database); `created_at` could not serve, since a batch may sit `pending` for a long time. Tests: `test_batch_claim_idempotency.py` (8). |
| ~~F-SCHED-01~~ | 🟢 | **CLOSED 2026-08-20 — and Medium understates it.** The loop ran every due schedule with no membership check, so one created by somebody since removed kept querying that project's database on a cron with nobody at the keyboard. Not merely wasted compute: the loop evaluates alert conditions and writes `Notification(user_id=schedule.user_id, body=alert["message"])`, and the alert body carries values from the query — so a removed member **kept receiving the project's data**, indefinitely. Access is now verified per run, before the connector is touched, via `MembershipService.can_access` rather than a fifth copy of the predicate. The schedule is **paused, not deleted** (`is_active=False` already excludes it from `get_due_schedules`), and the reason is written to its run history, because a schedule that simply stops reads as a bug. Tests: `test_schedule_access_revocation.py` (7), including one asserting the loop calls it **before** `get_connector` — a method nobody calls is not a fix. |
| F-SCHED-03 | 🟡 | `_stale_run` NULL-heartbeat immediate-reap race (mitigated by heartbeat beacon) |
| ~~F-SCHED-04~~ | ✅ | ~~ARQ enqueue failure silently runs heavy jobs in-process on web dyno~~ — **fixed 2026-08-20.** Two situations were collapsed into one warning. With no `REDIS_URL`, in-process **is** the mode and the module says so. With Redis configured, an `enqueue_job` that throws means Redis is broken — and the code logged a warning and ran the job here anyway. For `run_repo_index` that is the pipeline measured at ~1 GB peak, executing inside the dyno that serves user requests: an outage with extra steps, traceable to one line at a level nobody alerts on. Now the two are separated — no Redis → `INFO`, unchanged; Redis configured and failing → `ERROR`; and `allow_in_process=False` lets a call site say that running here is not a substitute, returning `None` so the caller surfaces a retryable failure. Declared at the three heavy sites (`run_repo_index`, `run_db_index`, `run_code_db_sync`), all of which already gate on `is_arq_active()` and so reach the fallback only on this exact fault. The fallback itself is kept: for light work a Redis blip should not lose the job. Evidence: `tests/unit/test_task_queue_no_silent_relocation.py` (8), four plants. |
| F-SCHED-05 | 🟢 | Fallback dedup per-process; no cross-process single-flight without Redis |
| F-SCHED-06 | 🟢 | No min-interval / cost guard on schedules |

### 14 — Billing & Entitlements
| ID | Sev | Issue |
|---|---|---|
| ~~F-BILL-02~~ | ✅ | ~~Connection/project quota check count-then-compare → TOCTOU bypass~~ — **fixed 2026-08-21.** `SELECT COUNT(…)`, compare, and then the *caller* inserted: two concurrent requests both counted `N-1`, both passed, both inserted, and a plan allowing one connection ended up with two. Creation is rate-limited to 10/minute, which bounds how far it goes and does not stop it. Fixed with a row lock on the owner (`SELECT … FOR UPDATE` on `users`) taken **before** the count — quota checks for one user serialise, different users never contend, and no counter is introduced that could drift out of step with the rows it counts. **Honest about scope:** `FOR UPDATE` is a Postgres guarantee and SQLite's driver accepts the clause and ignores it; production is Postgres, and SQLite dev is single-writer where the interleaving cannot happen — so the guard is real where the race is real and inert where it cannot occur. A lock failure logs at warning and lets the check proceed rather than turning a quota question into a 500. An unlimited plan returns before the lock, because serialising a decision already made is contention bought for nothing. Evidence: `tests/unit/test_quota_toctou.py` (11), five plants — one of which showed the breadth assertion could not see `except Exception` narrowed to `except SystemExit`, now fixed. |
| ~~F-BILL-07~~ | ✅ | ~~`demo_setup` bypasses quota gate (route-level, not service-level)~~ — **fixed 2026-08-20**. `enforce_project_quota` + `enforce_connection_quota` now run before either row is created and a breach answers 402 with the same payload every other route sends (`app/api/routes/demo.py:148-155`). Rate-limited to 3/minute, the gap minted three projects and three connections a minute against a plan nobody was charged for. Evidence: `tests/integration/test_demo_routes.py::test_a_project_quota_breach_answers_402`, `::test_a_connection_quota_breach_answers_402`. |
| ~~F-BILL-01~~ | ✅ | ~~`_resolve_plan_id` trusts stale `metadata.plan_id` over live price~~ — **fixed 2026-08-21, and it was wrong in both directions.** Stripe's `metadata` is written once, when our Checkout session creates the subscription, and **does not change when the price on that subscription changes**. The resolver read metadata first and returned immediately, so a customer moving plans through the Customer Portal kept the plan they originally bought: **downgrade Team → Pro means they pay Pro and keep Team's limits; upgrade Pro → Team means they pay Team and keep Pro's.** Both are money. The price is what Stripe actually charges, so the price is now the authority. Metadata is consulted for exactly one situation — the price is real and no catalog row matches it, i.e. the catalog is behind Stripe — because returning `None` there leaves `sub.plan_id` untouched and a paying customer silently keeps whatever they had. That fallback warns, naming both the price and the metadata plan, since a stale catalog otherwise surfaces only as somebody's wrong entitlement. Evidence: `tests/unit/test_plan_resolves_from_price.py` (8) including an AST check that the price is read before metadata — the old version returned on line one, so any correct price-matching below it was unreachable — and three plants. |
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
| ~~F-LLM-01~~ | ✅ | ~~Silent cross-provider fallback can send customer data to an unintended provider~~ — **fixed 2026-08-20.** The messages the router retries with are the user's question, their schema and their query results, so a transient 503 at one vendor sent that content to another with nothing naming where it went — the existing line reports that a provider *failed*, not where the request was sent next. Now: crossing a provider boundary logs at WARNING naming both vendors and what was sent, on **both** fallback loops (the streaming path walks its own copy and would otherwise have kept the old behaviour); and `LLM_ALLOW_PROVIDER_FALLBACK=false` makes the choice binding, ending the chain so the caller still raises `LLMAllProvidersFailedError` carrying the real outage rather than the setting. Default stays **on** — same argument as the connection-host guard: turning it off for everyone trades resilience for a guarantee most deployments never asked for, and a control that breaks the normal case gets switched off and then protects nobody. Evidence: `tests/unit/test_llm_provider_fallback_disclosure.py` (6), four plants. |
| F-LLM-05 | 🟢 | `health_monitor /reconnect` mutation defaults to viewer role (should be editor) |
| F-LLM-02 | 🟢 | Any unexpected exception evicts a whole provider (flap risk) |
| F-LLM-03 | ⚪ | Sentry scrubber redacts DSN/secret but only on Sentry egress; F-CONN-08 leak (API resp + logs) bypasses it |
| F-LLM-04 | ⚪ | Prometheus endpoint admin-JWT-gated → scraping friction |

### 18 — Semantic / Graph / Temporal / Exploration / Models / Demo
| ID | Sev | Issue |
|---|---|---|
| ~~F-EXP-01~~ | ✅ | ~~Demo project uses `:memory:` SQLite, no seeding → empty/misleading~~ — **fixed 2026-08-20**. The demo now points at a per-user file under `DEMO_DB_DIR` seeded with `customers` (5) and `orders` (8), re-seeded when the file is gone because the dyno filesystem is ephemeral (`app/api/routes/demo.py:47-114`). This was a broken promise, not a rough edge: SCN-003's expected result said "demo path sets up sample data" and the button offers to load it, and a first-run user got an empty database. **The 2026-07-19 audit passed SCN-003 on its affordances** — button, toasts — without reading its expected result. Evidence: `tests/unit/test_demo_data.py` (12), `tests/integration/test_demo_routes.py::test_the_demo_connection_points_at_a_database_with_rows_in_it`, which opens the file and counts rows. |
| ~~F-EXP-02~~ | ✅ | ~~Demo connection created writable, against read-only default~~ — **fixed 2026-08-20**. `is_read_only=True` (`app/api/routes/demo.py:176`); vision.md §7 #1. Evidence: `tests/integration/test_demo_routes.py::test_the_demo_connection_is_read_only`. |
| ~~F-EXP-03~~ | ✅ | ~~`demo_setup` creates real quota-counting Project+Connection, no dedup~~ — **fixed 2026-08-20**. A second call returns the existing demo (`app/api/routes/demo.py:128-146`). Worth naming: `test_demo_setup_twice_creates_two_projects` asserted `p1 != p2` — **the suite held the defect in place as the contract**, which is harder to dislodge than the code, because the next reader takes it for a decision. It is now `test_demo_setup_twice_reuses_one_project` (`tests/integration/test_edge_cases.py:13-38`). |
| ~~F-EXP-05~~ | ✅ | **Found while fixing the four above, and larger than all of them**: `db_type="sqlite"` had **no entry in `ADAPTER_REGISTRY`**, so `get_adapter("database", "sqlite")` raised `ValueError: Unsupported adapter: sqlite` — the demo produced a connection the product could not open, and the first question a new user asked it failed. Seeding sample data behind it (F-EXP-01) closes nothing on its own. **Fixed 2026-08-20**: `app/connectors/sqlite.py` (file-backed, `mode=ro` driver-enforced read-only, PRAGMA introspection with FKs/indexes/views, `:memory:` refused, missing file refused rather than created) registered as `sqlite`. Evidence: `tests/unit/test_sqlite_connector.py` (21), `tests/unit/test_demo_data.py::TestTheDemoDatabaseIsQueryableThroughTheProduct`. |
| ~~F-EXP-06~~ | ✅ | **Found by the post-deploy check for the demo work, not by a test** (2026-08-20). Production held one connection with `db_type='sqlite'` and `db_name=':memory:'`, created 2026-06-05: `SELECT db_type, db_name, COUNT(*) FROM connections WHERE db_type='sqlite' GROUP BY 1,2` → `sqlite | :memory: | 1`. Before the demo work it failed with `Unsupported adapter: sqlite`; after it the new connector **refuses** `:memory:` at connect — a better error for the same empty screen. So F-EXP-01's promise held for connections created after the fix and **not** for the ones created before it, which is the half of a fix a test suite cannot see. **Fixed** by migration `d3e4f5a6b7c8`: rewrites `db_name` to `./data/demo/demo_<owner>.db` and flips `is_read_only`, after which the already-deployed `repair_demo_db_if_missing` in `to_config` seeds the file on the next config build — self-completing, no operator step, no user action. `downgrade` restores the path and deliberately does **not** hand back write access. Verified up and down on a fresh database with two control rows. Evidence: `tests/unit/test_alembic.py::test_legacy_demo_connections_are_pointed_at_a_real_file`, four plants. |
| ~~F-AUTH-16~~ | ✅ | **Found through a CI failure that reported every test passing** (2026-08-21). `handleSessionExpired` fired `void import("@/stores/auth-store").then(logout)` and set `window.location.href` on the **next synchronous line**. The browser starts unloading immediately, so the `.then` may never run — and the only part of `logout()` that outlives a navigation is `storage.removeItem("auth_user")`, the profile kept for instant UI paint. A session expires, the user lands on `/login`, and the app still holds their profile against a cookie the server has already rejected. It surfaced as `EnvironmentTeardownError: Cannot load '/src/lib/api/index.ts' … after the environment was torn down` — 683 tests passing, runner exiting 1; the test file had already grown a one-macrotask `afterEach` to paper over it, enough on a laptop and not on a CI runner. **Fixed**: the teardown is synchronous, the dynamic import is gone (the in-memory store dies with the document anyway, so importing it to mutate memory before leaving was work that could only fail to happen), each `removeItem` guarded so Safari private browsing cannot trap somebody on a dead page, and the `afterEach` workaround removed so the regression cannot hide behind it. Frontend suite now 688 passed / exit 0. Evidence: `src/__tests__/session-expiry-clears-auth.test.ts` (5), three plants; SCN-011 updated. |
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
