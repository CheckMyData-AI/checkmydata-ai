# Audit — the work of 2026-09-15 … 2026-09-18, production, and documentation drift (2026-09-23)

**Question asked:** what was done in the last days, where the plan is going, how ready each
delivered task is; review the code, the errors and production logs; find and fix every place
the documentation disagrees with the code; build the prioritised backlog.

**How it was measured.** `main` = `origin/main` = `92e3ba24`, deployed as Heroku **v444**
(web and worker Standard-2X, both `up` since the 2026-09-22 ~21:51 UTC platform cycle).
Production figures are SQL against the live Supabase database and `heroku ps/releases/logs`,
taken 2026-09-23 09:30–11:30 UTC. The diff reviewed is `ce1b9f35..92e3ba24` (174 files,
+13 585/−2 122). Two independent code readings (orchestrator/traces/GA4; connections, security
and frontend) and one documentation reading ran in parallel; every finding below was either
reproduced by its reader (**CONFIRMED**, stated how) or re-read at its lines by this audit
before being ranked. Findings not substantiated were dropped.

## 1. Where the plan stands

The plan is `docs/evidence/loop-queue.md` (the loop's state, single source for status):
fourteen projects from `docs/audits/2026-09-13-connections-sync-orchestrator-audit.md`,
sequenced by ADR-0005/0006/0007, delivered one per iteration with a verification iteration
after every three.

| Row | What | State on 2026-09-23 | Evidence |
|---|---|---|---|
| T01 | B-14 background model | done | prod A/B, #392/#393 |
| T02, T02b | PRJ-03 request deadline | done | #394/#396, v433/v435 |
| T03, T03b | PRJ-04 trace truth | done | #395/#397; today **4 traces / 4 workflows** in 8 days, no `Stale:` since 2026-09-16 |
| V1 | verify T01–T03b | done | live answer, #398 |
| T00-mem | web memory | merged (#400 v439, #402 v441) — **not closed** | idle web 478–483 MB on 1 GiB (log-runtime-metrics, 318 samples); `chromadb` + eager drivers still open |
| T04 | Track D1 thumbs-down → investigation | merged (#401 v440, #403 v441) — production proof owed | §3.3 below: three defects in the modal |
| T05 | PRJ-08 connection layer | merged (#404 v442) — **8 of 15 C-rows only partially closed** | §3.2 |
| T06 | PRJ-10 GA4 | done at schema/route level (v443); A-rows proven by fixture only — no GA4 connection exists in production | §3.4: two defects undo A-01/A-02 at the read side |
| V2 … V6, T07 … T18 | | todo | |

The code-level CI state of `main` is green (`CI` + `Deploy to Heroku` succeeded on
`92e3ba24`, 2026-09-18 18:25 UTC).

## 2. Production (v444)

| Check | Result | How |
|---|---|---|
| Nightly sync, 8 nights | **32 of 32 runs `completed`**, 0 failed/reaped | `indexing_runs` since 2026-09-15 by kind/status |
| Nightly durations | `daily_sync` 2 352–3 136 s (≤ 44% of the 7 200 s budget); `db_index` 1 573–1 828 s; `code_db_sync` 569–1 057 s; `index_repo` 67–430 s | same, `finished_at − started_at` |
| Schema index | 217 tables, 211 with column statistics, last 2026-09-22 22:31 UTC | `db_index` |
| Symbol vectors | method 24 208, class 18 182, enum 364, function 215, interface 201 | `doc_embeddings` by `metadata->>'kind'` |
| Error catalog | nothing new since 2026-09-17; **6 rows still `open`** that PRJ-01…04 fixed (reaps 09-14, `doc_id` 09-14, 14× `Stale:` 09-16, 2× `AgentFatalError` 09-17) | `error_log` |
| Last 2 h of logs (1 500 lines) | 0 ERROR/CRITICAL/R14/R15/H12/H15; 6× `H27` (client closed an MCP GET); MCP per-user token auth resolving | `heroku logs -n 1500` |
| Memory | web idle **478–483 MB**; worker idle RSS **722 MB** (845 MB total) of 1 GiB, swap 0 | runtime-metrics lines |
| Alembic | `e1f2a3b4c5d7` = repository head | `alembic_version`, `alembic heads` |
| Config drift | clean; 10 `DELIBERATE` entries | `make config-drift` |
| Health | `{"status":"ok"}` | `GET https://api.checkmydata.ai/api/health` |
| Chat traffic | **4 traces in 8 days**, none since 2026-09-18 | `request_traces` |
| LLM spend | ~1.72 M tokens/night, all background, `deepseek/deepseek-v4-flash-0731` | `token_usage` |

**Cost finding (O-1).** The background model's price per million tokens went from
$0.06–0.10 (2026-09-17…19) to **$0.35** on 2026-09-21 and 2026-09-22 for the same model and
the same ~1.72 M tokens — $0.10–0.18/night became **$0.61/night**. The accounting is right:
the live OpenRouter catalogue now lists `deepseek/deepseek-v4-flash-0731` at $0.04 in /
**$0.64 out**, and the night is 0.82 M in / 0.90 M out. The undated `deepseek/deepseek-v4-flash`
lists $0.089 / $0.177 (≈ $0.23/night). Absolute cost is small (~$18/month); the finding is that
a dated snapshot was repriced ×6 and nothing noticed. Output exceeds input on a summarising
workload, which is worth one look at whether reasoning tokens are being paid for.

## 3. Code findings (diff `ce1b9f35..92e3ba24`)

Ranked most severe first. "Prod" says whether this deployment (MySQL through an SSH tunnel,
no GA4, no Postgres/ClickHouse/Mongo customer connection) can hit it.

### 3.1 Knowledge layer

| id | Sev | Where | Defect | Failure | Prod | Verified |
|---|---|---|---|---|---|---|
| F-K1 | **P1** | `backend/app/knowledge/db_index_validator.py:424-452` | the `and tc.arguments` guard skips a tool call with empty arguments **without advancing `tool_idx`**; calls map to tables by position | in a batch where call #2 has unparseable arguments (the adapter substitutes `{}`), call #3's description/hints/relevance are stored on table #2 and so on down the batch; the last table gets the fallback. `tool_call_truncated` only fires when no call has arguments | **yes** — every nightly `db_index` | re-read at the lines |
| F-R1 | P2 | `backend/app/connectors/base.py:549-590` (`period_total`) | period bounds passed as ISO strings | asyncpg refuses `str` for a date parameter; ClickHouse `bind_query` leaves `:period_start` unbound; SSH-exec refuses `params` — the B-09 rival-table comparison silently never produces a fact on those engines (MySQL/SQLite work) | no (MySQL) | reader ran asyncpg + `bind_query` |
| F-R2 | P2 | `backend/app/knowledge/db_index_pipeline.py` (`_comparison_ran`) | set whenever `measure_rivalries` returns, even when it measured nothing | last night's correct `MEASURED (rivalry):` caveats are stripped when every pair failed or the budget ran out before one | possible (budget) | read |

### 3.2 Connection layer (PRJ-08 residue)

| id | Sev | Where | Defect | Failure | Prod | Verified |
|---|---|---|---|---|---|---|
| F-C1 | **P1** | `ConnectionSelector.tsx:820-831` with `connections.py:963-964` | the edit form always sends `ssh_key_id`, so the C-04 "verify only the key being attached" branch always runs | a co-owner renaming a connection whose key another member uploaded still gets 404 — C-04 is not fixed end to end | yes | re-read both sides |
| F-C2 | **P1** | `ConnectionSelector.tsx:844`, `connections.py:389-395`, `exec_templates.py` | the PATCH always sends `ssh_command_template`; the C-02 validator refuses a template containing `{db_password}` | any edit to a legacy connection whose stored template carries `{db_password}` is a 422 — the validator's docstring promises to "break none of the existing ones". Also: `"$DBPASS"` in a custom client's argv passes the screen, and the help text says a custom command gets the query "as an argument" when it is piped on stdin | depends on stored template | read |
| F-C3 | P2 | `transient_errors.py:28`, `ssh_tunnel.py:437-452` | `pymysql.err.OperationalError` (also error 1045 *Access denied*) is in `TRANSIENT_CONNECT_ERRORS` | a wrong MySQL password is retried 3×, and through a tunnel `open_through` force-closes the **shared** tunnel under every other connection's live pool, then reports "via SSH tunnel" | **yes** (MySQL via tunnel) | reader checked the class hierarchy |
| F-C4 | P2 | `ssh_tunnel.py:476-490` (`cleanup_idle`), `main.py:1843-1893` | the idle sweep closes a tunnel 30 min after its last *query*; `test_connection` (the health probe) does not `touch()` it; `execute_query` has no reconnect path | after 30 idle minutes, a chat question in the ≤ 300 s before the next health pass calls `reconnect()` fails with a connection error; `sql_agent.py:1576`'s comment "the tunnel rebuilds itself" is false here | **plausible** — prod traffic is idle most of the time; reproduce before fixing | read; mitigation found in `health_monitor.check_connection` → `reconnect()` |
| F-C5 | P2 | `mongodb.py:418` → `db_index_pipeline.py:1120-1123` | an unreadable collection is left out of `schema.tables`, then `delete_stale_tables` deletes its stored index row; `SchemaInfo.unreadable` reaches only a log line | a transient permission error wipes that collection's knowledge; all failing → "completed, No tables found" | no | grep |
| F-C6 | P2 | `clickhouse.py:144-152, 261` | `_get_client()` recreate failure swallowed at DEBUG → empty `SchemaInfo` → `completed, tables: 0`; ClickHouse has no `reconnect()` | a dead tunnel is recorded as an empty database | no | grep |
| F-C7 | P2 | `ssh_tunnel.py:85`, `ssh_exec.py:219` | a wrong passphrase raises `asyncssh.KeyEncryptionError`, not `KeyImportError` | C-14 misses it: 3 retries with backoff, then "SSH tunnel reconnection failed"; SSH-exec `connect()` does not wrap key import | yes if a passphrase is wrong | reader ran `import_private_key(pem, "wrong")` |
| F-C8 | P2 | `dsn.py:40-46`, `clickhouse.py:102` | `parse_dsn` refuses a DSN without a user | a saved `clickhouse://host/db` (the engine's account is `default`) now fails on connect | no | read — product call |

C-row verdicts (reader 2, re-checked where ranked): closed — C-05, C-06 (with F-C8), C-08,
C-09, C-12, C-13, C-16. Partially closed — **C-02** (F-C2), **C-03** (F-C4), **C-04** (F-C1),
**C-07** (F-C6), **C-10** (only Postgres/MySQL go through `open_through`; F-C3), **C-11**
(F-C5), **C-14** (F-C7), **C-15** (the form still requires both key and user,
`ConnectionSelector.tsx:652, 805`). T05 is therefore not `done`.

### 3.3 Track D1 (T04)

| id | Sev | Where | Defect |
|---|---|---|---|
| F-W1 | P2 | `frontend/src/components/chat/WrongDataModal.tsx:81-98` | polling stops silently after 30 × 2 s or at the first failed request (`catch { break; }`); the modal stays on "investigating" with no timeout message and no retry — and every thumbs-down on a SQL answer now opens it |
| F-W2 | P2 | `WrongDataModal.tsx:196-209` | the `<label>`s have no `htmlFor`, the input/select no `id` or `aria-label` (repo convention; dialog role, `aria-modal`, focus trap and Escape are present) |
| F-W3 | P2 | `ReadinessGate.tsx:95-137, 220-226` | a step already running at mount shows "Running…" but polling starts only from `handleAction`, so the gate never sees it finish |

### 3.4 GA4 (T06 residue) — none reachable in production until a GA4 connection exists

| id | Sev | Where | Defect |
|---|---|---|---|
| F-G1 | **P1** | `backend/app/analytics/ga4/adapter.py:153-176` | `_is_auth_failure` treats every `GoogleAuthError` as a dead credential; `TransportError`/`TimeoutError` are subclasses, so a network blip journals the report `failed` instead of retrying, and `POST …/verify` stamps a working key `last_verify_error` — the case `verify`'s docstring promises never to do (reader confirmed by MRO and by calling it) |
| F-G2 | **P1** | `backend/app/agents/analytics_agent.py` (`_degraded_periods`, `_provisional_periods`, `query_report`) | the journal's `partial` status is read by nothing in the agent; a period where one of two properties failed is published as "collected, so the values below are real measurements" with no caveat — A-01 undone at the read side (reader confirmed by calling `_window_coverage_lines` with a `partial` status) |
| F-G3 | P2 | `backend/app/services/vendor_credential_service.py` (`verify`) | `appstore`/`googleplay` have no probe; Verify stamps the key `verified:false` with "cannot be checked yet" — contradicts "error is null exactly when the attempt succeeded" |
| F-G4 | P2 | same | `verify` does not wrap `decrypt()` (unlike `get_decrypted`) — after a key-rotation problem Verify is an unhandled 500 (PLAUSIBLE) |
| F-G5 | P3 | `backend/app/analytics/journal.py` (`prune`) | cutoff is UTC-today − horizon; the window starts at property-today − `backfill_days`; for a ≥ 400-day window west of UTC the oldest period can be pruned and re-fetched daily |

### 3.5 Traces

| id | Sev | Where | Defect |
|---|---|---|---|
| F-T1 | P2 | `backend/app/core/workflow_tracker.py:473-488`, read by `trace_persistence_service.py:269`, `run_coordinator.py:541` | `_external_rebroadcast` is a process-wide flag held across awaits; a local chat event arriving on the web dyno while a worker event is rebroadcast is dropped — a lost `pipeline_start` loses the whole trace. Pre-existing, not introduced by this diff |

## 4. Tests and gates, measured locally on `92e3ba24`

| Gate | Result |
|---|---|
| `ruff format --check` / `ruff check` | 1 149 files formatted; all checks passed (one warning: invalid `# noqa` at `tests/unit/docs/test_suppression_debt_ratchet.py:442`) |
| `mypy app/` | no issues, 420 source files |
| `pytest tests/` (one process, unit + integration together) | **9 751 passed, 2 failed**, 14 skipped, 1 xfailed, 1 769 s |
| — failure 1 | `test_ux_scenarios.py::test_stale_verifications_do_not_grow` — caused by this audit running `make ux-status`, which restamped the block: **106 of 154** scenarios are now > 30 days old against a ceiling of 95. Reverted; the rot is real (Q-1) |
| — failure 2 | `test_learnings_api.py::test_update_learning_toggle_active` — `StaleDataError` only when the unit suite runs first in the same process; the file alone is 15/15 and `tests/integration` alone is 698/698. CI runs them in separate steps, so CI cannot see it (Q-3) |
| `npx vitest run` | 811 tests; 7 timed out at 5 s while `pytest` ran beside it; the 6 files re-run alone: **56/56 pass** (Q-2) |
| `tsc --noEmit`, `eslint --max-warnings=0` | clean |
| CI on this PR (#407), 10:27 UTC | **1 failed**: `test_a_day_ends_in_the_propertys_timezone.py::test_two_properties_a_day_apart_get_different_todays` asserted exactly one calendar day between UTC+14 and UTC−11 on the real clock — true 23 hours a day, **false every day 10:00–10:59 UTC** (two days; computed for every half hour of 2026-09-23). Introduced by T06 on 2026-09-18, so any merge to `main` in that hour fails CI and skips the deploy. **Fixed in this change** (Q-4): the assertion is now 1–2 days, which still refuses the defect it guards (one clock → 0 days; verified by planting it) |

## 5. Documentation — fixed in this change

52 mismatches were reported by the documentation reading; each was re-checked against the
code before its edit (two more were found while doing so: `action_engine.py` lives in `core/`,
and schema retrieval is BM25 only). Corrected here:

- **`CLAUDE.md`** — current release `[1.17.0]` (not `[1.16.0]`); test count 10 579 =
  9 768 + 811 (measured today); the reranker no longer described as part of ContextPack;
  T00-mem's actual result; "five settings" (not four); BM25 tokens freed after load;
  `config-drift` scope and its **ten** `DELIBERATE` entries; `connection_test_timeout_seconds`
  in the flag table; the thumbs-down → `WrongDataModal` path; the dead spec link
  (`2026-07-02-…`); the 2026-09-13 audit row no longer says two P0s are live; two new rows in
  *Where to look first* (delivery queue, this audit).
- **`API.md`** — coverage note rewritten from the route diff; `/api/billing/plans` and
  `/api/billing/webhook` paths; the manual collect's own task id (ANA-10) and the lock that
  stops the overlap (A-05); `property_timezone` and the 422s; `last_verified_at` /
  `last_verify_error` in the credential example; `?project_id=` on the investigation read;
  `span_type` vocabulary; **nine routes that were missing** (`PATCH /api/chat/sessions/{id}`,
  `GET`/`DELETE …/index-db`, `GET`/`DELETE …/sync`, `GET /api/notes/{id}`,
  `GET /api/rules/{id}`, `PATCH /api/invites/{project_id}/members/{member_user_id}`).
- **`ARCHITECTURE.md`** — 40 route modules; real file names in services/models/core/
  pipelines/connectors; `.json.gz` BM25 snapshots; provisional (not failed) stale traces;
  pgvector/Chroma; `ScheduledQuery`/`ScheduleRun`; rate-limit exemptions.
- **`docs/SYSTEM_ARCHITECTURE.md`** — `max_orchestrator_iterations` default 20 (two places);
  new §2.6.0 on the one request deadline; thumbs-down → investigation; §7.6 marked removed
  (`table_resolver.py` deleted in `a0344647`); vector store section.
- **`docs/ANALYTICS_SOURCES.md`** — `partial` status; manual collect task id; window ends in
  the property's timezone; prune by period age.
- **`docs/DEPLOYMENT.md`, `INSTALLATION.md`** — coverage gate 80; the four images and the
  release verification; migrations run in the release phase, not from a `Procfile`.
- **One test, not documentation** — Q-4 above: a clock-dependent assertion that failed CI one hour a day.
- **`backend/.env.example`** — four settings deleted from `config.py` on 2026-09-14 removed.
- **`SECURITY.md`** — rate-limit exemptions; the SSH-exec shell surface (C-02/C-12).
- **`docs/KNOWLEDGE_CATALOG.md`, `docs/DOCMAP.md`, `ROADMAP.md`** — vector store; ADR count;
  status homes (loop-queue is the single source); coverage floor 80; the two "open" stale
  claims marked fixed; SQLite connector ticked; API reference.
- **Status cells** — `BACKLOG.md` 11.0 and 11.4 → `done`; `docs/evidence/verification.md`
  PRJ-01 R2b and R7 → `yes` (the acceptance doc had them, the ledger never did);
  `docs/evidence/loop-queue.md` T00-mem/T04/T05 → `merged`, with the residue rows below;
  banners on the frozen July snapshots `docs/agent-status.md` and `docs/agent-backlog.md`.

Not changed, deliberately: dated audits keep their original text (the 2026-09-13 audit is a
snapshot; `CLAUDE.md` and `DOCMAP.md` now point to the queue for status). The UX verification
block keeps its 2026-09-18 stamp — restamping it without re-auditing is what the ratchet
refuses (Q-1). The scenario counts in `CLAUDE.md` (154/142/12) were measured and are correct.

## 6. Prioritised backlog

Order = production impact first, then what blocks the next queued project, then hygiene.
IDs `T…b` are residue of a delivered row and go into `docs/evidence/loop-queue.md`; `B-…` rows
go into `docs/evidence/backlog.md`; `O-…` are operator/ops steps.

| # | id | Pri | Task | Why now | Size |
|---|---|---|---|---|---|
| 1 | **B-16** | **P1** | F-K1 — advance `tool_idx` for every `table_analysis` call, or better, map calls to tables by a `table_name` argument rather than by position; test with an empty-args call in the middle of a batch | silently mis-attributes table descriptions on every nightly `db_index` of the one real customer | S |
| 2 | **V2** | P1 | verify T00-mem, T04, T05, T06 on production (as queued), now with §3 as its checklist | four merged rows carry no production proof | S |
| 3 | **T05b** | P1 | PRJ-08 residue: F-C1 (send only changed fields on PATCH), F-C2 (legacy `{db_password}` templates saveable; screen `$DBPASS` in argv; correct the help text), F-C3 (1045 is not transient; never force-close a shared tunnel on an auth error), F-C4 (reproduce first: idle > 30 min then one question; then `touch()` from the health probe or reconnect in `execute_query`), F-C7, C-15 form residue | the production connection is MySQL through a tunnel — F-C3/F-C4 are on its path | M |
| 4 | **T04b** | P2 | F-W1 (timeout + error state + retry in the investigation modal), F-W2 (labels), F-W3 (ReadinessGate polls a step already running at mount); update SCN-052 | every thumbs-down on a SQL answer opens this modal | S |
| 5 | **T06b** | P1 before first GA4 use | F-G1 (transport/timeout errors are transient, not auth), F-G2 (`partial` periods carry a caveat and are never "real measurements"), F-G3, F-G4, F-G5 | the first real GA4 connection would hit F-G1/F-G2 at once | S–M |
| 6 | **B-17** | P2 | F-R1 + F-R2 — bind period bounds as dates (and per dialect), and set `_comparison_ran` only when at least one pair was measured | B-09's comparison is a no-op on three engines and can erase a true caveat | S |
| 7 | **O-1** | P2 (operator) | decide the background model after the ×6 reprice: measure the undated `deepseek/deepseek-v4-flash` with T01's A/B method before switching; check whether reasoning tokens are billed on background calls | $0.61/night for the same work that cost $0.10–0.18 | S |
| 8 | **B-18** | P2 | UX verification rot: re-audit ≥ 12 of the 106 scenarios older than 30 days (`/ux-audit`, oldest first — 94 date from 2026-07-19), then restamp with `make ux-status` after staging | the block cannot be regenerated honestly until then; CI will refuse it | M |
| 9 | T07 → T18 | as queued | PRJ-07 scheduling/recovery, PRJ-13 eval harness, B-02, Track D2/D3, PRJ-06, PRJ-09 (should absorb F-C5, F-C6, F-C8 and ClickHouse `reconnect()`), PRJ-05, PRJ-11/12, PRJ-16, PRJ-15 | unchanged | — |
| 10 | **B-19** | P2 | F-T1 — replace the process-wide `_external_rebroadcast` flag with per-event provenance | intermittent lost traces during indexing runs | S |
| 11 | **B-20** | P2 | cut release **1.18.0**: `[Unreleased]` holds ~4 350 lines since 1.17.0 (2026-08-31), PRJ-01…PRJ-10 included; bump `pyproject.toml`/`package.json`, tag | release history and the version the product reports are three weeks and ten projects behind | S |
| 12 | **O-2** | P3 (ops) | unset `VECTOR_STORE_BACKEND` on Heroku and delete its `DELIBERATE` entry (its own text says so; `auto` resolves to pgvector on Postgres) — a config change restarts both dynos, so outside the 04:00 UTC window and with no `indexing_runs` row running (S-04) | redundant state that reads as a decision | XS |
| 13 | **O-3** | P3 (ops) | mark the six `error_log` rows fixed by PRJ-01…04 `resolved` (`PATCH /api/logs/{project_id}/errors/{id}`) | the catalog shows six open errors that no longer happen | XS |
| 14 | **B-21** | P3 | test hygiene: Q-2 (raise the Vitest per-test timeout or remove the load sensitivity — the same GA4 form test flaked `main` on 2026-09-18), Q-3 (isolate the unit-suite state that leaks into `test_learnings_api` when run in one process), the invalid `# noqa` at `test_suppression_debt_ratchet.py:442`, `pytest-xdist` in `[dev]` (the one-process suite takes 29.5 min) | the next CI flake is already visible locally | S |
| 15 | T00-mem rest | P3 | `chromadb` import (22 MB) and eager connector drivers; worker idles at 722 MB RSS of 1 GiB | headroom, not an outage (swap 0) | M |

**Human steps** (need the operator): O-1 is a spend/quality decision; O-2 and O-3 mutate
production and are one command each once approved.

## 7. Handoff

- **Objective of this run:** audit + documentation truth + backlog. **Done:** §2–§6. **No
  application code was changed**; documentation and planning files, plus one test assertion (Q-4)
  that blocked this PR's CI.
- **Checks actually run:** listed in §2 and §4, all on `92e3ba24` / v444.
- **Decisions taken here:** `docs/evidence/loop-queue.md` is the single source for status
  (DOCMAP updated to say so); dated audits are not rewritten; the UX block is not restamped
  without a re-audit.
- **Exact next task:** B-16 (F-K1) — it is small, it corrupts production knowledge nightly,
  and it can ship before V2 without conflicting with it. Then V2, then T05b.
