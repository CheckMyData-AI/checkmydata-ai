# Loop queue — one task per iteration, verification every third

Started 2026-09-17 by the operator's `/loop`: every task goes through the full pipeline —
harvest, build, test, commit, merge to `main`, deploy, **verify on production** — and
after every three delivery iterations one iteration does nothing but check that the
previous three landed and nothing regressed.

**This file is the loop's state.** Each iteration reads it first, takes the first row
whose status is `todo`, and writes its result back before the next one starts. A row is
`done` only with production evidence in its `Proof` cell; `blocked` names what blocks it;
`merged` means on `main` and deployed, with the production proof still owed.

Standing rules the loop inherits (from `docs/evidence/retro.md`):

- S-04 — no merge while an `indexing_runs` row is running or queued, and none that would
  deploy into the 04:00 UTC nightly window.
- S-08 — lint with CI's exact scope and order, after the last edit.
- S-09 — a validation gates the write; never a separate command behind a failed one.
- S-10 — a guard's written justification needs its own check.
- Every guard is verified against a planted defect before it is trusted.

| # | Kind | Task | Source | Status | Proof |
|---|---|---|---|---|---|
| T01 | deliver | B-14 — background model on measured evidence, map quality measured on production before and after | `docs/evidence/backlog.md` B-14 | done | Prod A/B on 368 tables: v3.2 88 no-tool-call + 17 batches lost 4/5; flash 0/0. Flash kept (#392). Unplanned: PyMySQL 1.2.1 broke aiomysql import — pinned `<1.2.1` (#393), verified on v431 `import ok`. |
| T02 | deliver | PRJ-03 — one request deadline, honoured everywhere | audit §PRJ-03 | done | #394 on v433. In the production runtime `bounded(asyncio.sleep(3600))` with limit 1.0 raised `WallClockExceeded` after **1.20 s**; `localize` takes `timeout`. Baseline 30d: 6/23 traces >216 s, failed p50 283 s — the 30-day duration figure is re-read at V1. |
| T03 | deliver | PRJ-04 — trace truth and failure taxonomy | audit §PRJ-04 | done | #395 on v434: migration `d6e7f8a9b0c1` ran in the release phase; `request_traces` **177 rows / 177 workflows** (was 242/177); `ix_request_traces_workflow_id` is UNIQUE; failed `route='unknown'` (30 d) 10 → 3. One completed single row still said `Stale:` → cleared by `4030521071d4` in #396, re-checked at V1. |
| T02b | deliver | PRJ-03 remainder — client disconnect (SSE/WS) and REST `wait_for` cancel the agent task; `CancelledError` swallows in viz/localize; sub-agent deadline into `LLMRouter.complete`; dead retry wrappers | audit §PRJ-03, T02 out-of-scope | done | #396 on v435, in the production runtime: a hanging pipeline stage cut after **1.20 s** → `stage_failed`, not replannable; `localize` source has no `CancelledError` handler; cache/trace horizon 960 s; `4030521071d4` applied, completed `Stale:` rows **0**. Decided: client disconnect does not cancel (answers finish while the user is away). No dead retry wrappers exist. |
| T03b | deliver | PRJ-04 remainder — split `db_query` spans from LLM repair and learning-analyzer spans; router attempt/backoff events as spans; Logs screen renders both | audit §PRJ-04, T03 out-of-scope | done | #397 on v436; confirmed in the production runtime and on a live chat answer: `execute_query` → `db_query` **once**, `sql:tool:execute_query` → `tool_call`, `query_repair` / `sql:learning_analysis` / `orchestrator:llm_retry` → `llm_call`. |
| V1 | verify | T01–T03b landed | — | done | Live chat answer on prod (SSE, 112 events, 144 s): **one** trace row, `completed`, route `query`, 132 s < 216 s, db_query counted once, 179 rows / 179 workflows. Nightly 2026-09-16 completed on all four kinds. Found and fixed: session-less pipelines failed (#398), SCN-123 shadow (#398). Found and escalated: **web dyno was over its 512 MB quota on the first chat request** (import 294 + BM25 93 + request 138 = 525 MB measured); operator chose Standard-2X — scaled, chat answers end to end since. Memory reduction queued as T00-mem. |
| T00-mem | deliver | Web memory: 525 MB for one answer on a 512 MB dyno | V1 finding 2026-09-17 | done — V2 proof (317 MB boot); rest in B-22 / audit §6 row 15 | #400 on v439: boot steady state **353 MB** vs 387 before (tokenized corpus 58.9 MB dropped, `malloc_trim` returns 23 MB more in #402), one answer **522 MB** peak 548. Not closed: `chromadb` (22 MB) and the connector registry's eager drivers. |
| T04 | deliver | Track D1 — `WrongDataModal` on the thumbs-down path | plan Track D | done — V2 proof; residue in T04b | #401. Operator's decision 2026-09-18: investigation, not the canned message. Mounted with its first tests; SCN-052 rewritten; planting the canned sentence back fails two tests. |
| T05 | deliver | PRJ-08 — connection layer correctness | audit §PRJ-08 | done — V2 proof; residue in T05b | #404: C-02, C-03, C-04, C-05, C-06, C-07, C-08, C-09, C-10, C-11, C-12, C-13, C-14, C-15, C-16 — 28 tests, each verified against a planted defect. |
| T06 | deliver | PRJ-10 — GA4 tells the truth | audit §PRJ-10 | done | #405 + #406 on **v443**. In the production runtime: alembic head `e1f2a3b4c5d7`; `vendor_credentials` carries `last_verified_at` + `last_verify_error`; the verify route answers 401 without auth (it exists and is guarded); manifest `connect/collect_reports/summarize`; history kinds `daily_sync, analytics_collect`; statuses `ok|empty|partial|failed` with `partial` **not** done; marker `provisional:`; `PST` refused as a zone, `usd`→`USD`. **Rows A-01…A-12 themselves cannot be verified here — no GA4 connection exists on this deployment**; their acceptance is the fixture end-to-end test, and a real property stays owed to PRJ-10's own acceptance. |
| B-16 | deliver | F-K1 — batch table analysis maps tool calls to tables by position and skips an empty-args call without advancing, so later descriptions land on the wrong table | `docs/audits/2026-09-23-recent-work-audit.md` §3.1 | merged #408 — production proof owed by V3 (nightly 2026-09-23) | `tests/unit/knowledge/test_batch_table_analysis_maps_by_name.py`, 5 tests, all failing on the old code for the defect's reason |
| O-1 | deliver | Background model after the 09-21 reprice: `DEFAULT_LLM_MODEL_REASONING=off` | audit §2 | merged #414; `DEFAULT_LLM_MODEL_REASONING=off` set v449 (runtime: `off`) — first nightly is the A/B, read by V3 | runtime probe 2026-09-23: reasoning 228-505 of 867-1 089 completion tokens; off → 604-650 tokens, cost −30-40%, 3/3 tool calls, facts kept 3/3 |
| V2 | verify | T00-mem, T04–T06 landed — checklist: `docs/audits/2026-09-23-recent-work-audit.md` §3 | — | done | 2026-09-23. **T00-mem** on v445: web **317 MB** after boot (peak 403 during the BM25 rebuild, returned by `malloc_trim`), runtime-metrics 14:11–14:14 UTC — better than the 353 recorded; idle growth to ~483 MB over ~17 h queued as B-22. **T04** in the production bundle: `Report Incorrect Data` present, `getInvestigation` sends `?project_id=`; in the production runtime `get_investigation` requires `project_id`. **T05** in the production runtime (v444, one-off dyno, read-only): `redact_for_role(…, "viewer")` hides templates on all 4 connections, a new `{db_password}` template refused, `connection_test_timeout_seconds` 90; residue → T05b. **T06** as recorded. Also measured: production holds no command template, no DSN and no MCP connection. |
| T05b | deliver | PRJ-08 residue: F-C1, F-C2, F-C3, F-C4, F-C7, F-C9 (found here), C-15 | `docs/audits/2026-09-23-recent-work-audit.md` §3.2 | merged #409 (v447) — production proof owed by V3 | |
| T04b | deliver | Track D1 residue: F-W1, F-W2, F-W3 | `docs/audits/2026-09-23-recent-work-audit.md` §3.3 | merged #410 — production proof owed by V3 | |
| B-23 | deliver | Brand pack: `docs/brand/` does not exist, so every user-facing string is written without one (routing requires `/brand-init` first) — seed voice, terminology and facts from the existing interface | found by T04b | todo | |
| T06b | deliver | PRJ-10 residue: F-G1, F-G2, F-G3, F-G4, F-G5 — before the first real GA4 connection | `docs/audits/2026-09-23-recent-work-audit.md` §3.4 | merged #411 — fixture-level only; no GA4 connection in production | fixture-level only — no GA4 connection exists in production (same limit as T06) |
| T07 | deliver | PRJ-07 — scheduling and recovery that work in every deployment | audit §PRJ-07 | todo | |
| T08 | deliver | PRJ-13 — orchestrator eval harness | audit §PRJ-13 | todo | |
| T09 | deliver | B-02 — replace the integration harness's open-transaction isolation so the suite runs on PostgreSQL | backlog B-02 | todo | |
| V3 | verify | T07–T09 landed | — | todo | |
| T10 | deliver | Track D2 — `feed` / `reconciliation` / `temporal` / `exploration` as chat cards | plan Track D | todo | |
| T11 | deliver | Track D3 — `data_graph` metric catalogue as a chat card | plan Track D | todo | |
| T12 | deliver | PRJ-06 — indexing pipeline as a declared DAG with a resumable full rebuild | audit §PRJ-06 | todo | |
| V4 | verify | T10–T12 landed | — | todo | |
| T13 | deliver | PRJ-09 — connector contract and fifth-engine readiness | audit §PRJ-09 | todo | |
| T14 | deliver | PRJ-05 — one executor, one gate pipeline (phase 1) | audit §PRJ-05 | todo | |
| T15 | deliver | PRJ-11 — vendor abstraction + App Store Connect | audit §PRJ-11 | todo | |
| V5 | verify | T13–T15 landed | — | todo | |
| T16 | deliver | PRJ-12 — Google Play | audit §PRJ-12 | todo | |
| T17 | deliver | PRJ-16 — recipes: model, save-from-answer, run, MCP tools | ADR-0007 | todo | |
| T18 | deliver | PRJ-15 — workspace shell | ADR-0007 | todo | |
| V6 | verify | T16–T18 landed | — | todo | |

## Operator questions

Only questions an agent cannot answer by itself — an action that needs a person, a credential,
or a decision that is the operator's. Everything else is decided and recorded in the row.
Each loop cycle ends by stating how many are open.

| # | Opened | Question | Blocks | Status |
|---|---|---|---|---|
| Q1 | 2026-09-23 | GitHub refuses the SSH key `sergeysheleg4@gmail.com (ED25519)` since ~15:00 UTC (`Permission denied (publickey)`; `~/.ssh/config` unchanged since 2026-09-07). Pushes go over HTTPS with `gh` as a one-off credential helper, so nothing is blocked. Needs a person: check the key is still on the GitHub account | nothing | open |

## Log

One line per finished iteration, newest last.

- **T01 (2026-09-17)** — recommendation reversed by production A/B; flash kept. Found and pinned a same-day PyMySQL release that would have broken every MySQL connection on the next deploy.
- **T06 (2026-09-18)** — PRJ-10 finished: the timezone a GA4 day ends in (A-04), the four
  knobs the form promised and did not have (A-08's GA4 half), a credential that can be
  asked whether it still works, and a collection that is a run like any other. Two rules
  came out of it worth carrying: an injected clock answers for every timezone (a test that
  pins a date is stating what day it is, and a date has no time of day to convert), and a
  test that matches an expression verbatim goes stale the day a correct change adds a
  second reason — the A-01 guard is an AST check now. Two process lessons, both paid for:
  the **full** suite found five defects the targeted runs could not (a settling period was
  published as a truncation, two new steps had no label, a log line tripped the secret
  sweep, and the e2e fixture had no timezone), and CI's push-to-`main` run failed on a
  flaky test of my own that the PR run had passed — so the merge landed and the deploy
  was **skipped**, leaving production on the old release until #406 fixed the race. A
  green PR is not a green `main`.
- **Audit (2026-09-23)** — not an iteration: an operator-requested audit of T00-mem…T06, production
  (v444) and documentation. Production healthy (32/32 nightly runs, no errors since 09-17).
  T00-mem/T04/T05 relabelled `merged`: they are deployed, and none has its production proof.
  T05 is not `done` in substance either — 8 of its 15 C-rows are only partially closed.
  Queued B-16 (first: it mis-attributes table descriptions every night), T05b, T04b, T06b.
  52 documentation mismatches fixed. Full record: `docs/audits/2026-09-23-recent-work-audit.md`.
- **Cycle 1 of the operator's /loop (2026-09-23)** — shipped B-16 (#408), T05b (#409), T04b
  (#410), T06b (#411), F-E1 (#412), B-17 (#413), O-1 (#414), T07c (#417); V2 closed on
  production; ops O-1 (config `off`, v449), O-2 (`VECTOR_STORE_BACKEND` unset, v450 —
  runtime resolves `pgvector`) and O-3 (23 stale `error_log` rows resolved, safe because
  F-E1 reopens on recurrence) done. In review: T07 part 1 (#415), part 2 (#416), B-21
  (#418). Two process failures, both caught by CI, both now rules: S-11, S-12.
  **Operator questions open: 1** (Q1, non-blocking).
