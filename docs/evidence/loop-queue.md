# Loop queue — one task per iteration, verification every third

Started 2026-09-17 by the operator's `/loop`: every task goes through the full pipeline —
harvest, build, test, commit, merge to `main`, deploy, **verify on production** — and
after every three delivery iterations one iteration does nothing but check that the
previous three landed and nothing regressed.

**This file is the loop's state.** Each iteration reads it first, takes the first row
whose status is `todo`, and writes its result back before the next one starts. A row is
`done` only with production evidence in its `Proof` cell; `blocked` names what blocks it.

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
| T03 | deliver | PRJ-04 — trace truth and failure taxonomy | audit §PRJ-04 | in review | Baseline: 242 rows / 177 workflows; 10 of 12 failed traces (30 d) `route='unknown'`; 26 `Stale:` rows; 0 REST-timeout rows (id overflowed `String(36)`). |
| T02b | deliver | PRJ-03 remainder — client disconnect (SSE/WS) and REST `wait_for` cancel the agent task; `CancelledError` swallows in viz/localize; sub-agent deadline into `LLMRouter.complete`; dead retry wrappers | audit §PRJ-03, T02 out-of-scope | todo | |
| T03b | deliver | PRJ-04 remainder — split `db_query` spans from LLM repair and learning-analyzer spans; router attempt/backoff events as spans; Logs screen renders both | audit §PRJ-04, T03 out-of-scope | in review | |
| V1 | verify | T01–T03b landed: full suites, production health, nightly, chat answers a question end to end; re-audit the 5 scenarios verified 2026-08-16 that pass 30 days on regenerating the UX block (ceiling 95, would be 100); confirm no completed trace says `Stale:` after `4030521071d4` | — | todo | |
| T04 | deliver | Track D1 — `WrongDataModal` on the thumbs-down path | plan Track D | todo | |
| T05 | deliver | PRJ-08 — connection layer correctness | audit §PRJ-08 | todo | |
| T06 | deliver | PRJ-10 — GA4 tells the truth | audit §PRJ-10 | todo | |
| V2 | verify | T04–T06 landed | — | todo | |
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

## Log

One line per finished iteration, newest last.

- **T01 (2026-09-17)** — recommendation reversed by production A/B; flash kept. Found and pinned a same-day PyMySQL release that would have broken every MySQL connection on the next deploy.
