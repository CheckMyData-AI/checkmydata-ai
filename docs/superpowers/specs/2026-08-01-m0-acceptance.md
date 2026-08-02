# Acceptance — m0-ga4-spine

Program: analytics data sources (GA4 · App Store Connect · Google Play).
Module 1 of 3. Merge commit `6290f6c` on `main`. Version `1.16.0`.

**Status: complete and merged locally; NOT deployed.** `git push origin main` was
blocked by the harness safety classifier — correctly, since it is an outward,
irreversible production action. One operator action closes it (see *Human step*).

## Gate results (the eight named preconditions from brief D10)

| # | Gate | Result |
|---|---|---|
| 1 | `ruff format --check app/ tests/` | 831 files already formatted |
| 2 | `ruff check app/ tests/` | All checks passed |
| 3 | `mypy app/ --ignore-missing-imports` | Success — 371 source files |
| 4 | backend `pytest tests/` | **6025 passed**, 5 skipped, 1 xfailed |
| 5 | combined coverage | **78.66 %** (gate 72 %) |
| 6 | `tsc --noEmit` | clean |
| 7 | `eslint . --max-warnings=0` | clean |
| 8 | `vitest run` | **606 passed** (86 files) |

Baseline before this work: 5439 backend / 546 frontend. Net new: **+586 backend,
+60 frontend**. The analytics surface alone is 309 tests.

## REQ coverage

Every row's evidence is a test that was **seen failing first** — each build task
reported its pre-implementation failure message, and the load-bearing guarantees
were additionally re-broken by planted defect and observed to fail.

| REQ | Status | Evidence |
|---|---|---|
| 001 source_type + nullable DB columns | **verified** | `tests/unit/models/test_connection_analytics.py` (22); alembic up→down→up over a seeded legacy row |
| 002 owner-scoped credentials, never serialised | **verified** | `test_vendor_credential_service.py`, `test_vendor_credentials_api.py` (31); planted NULL-owner union → 2 failures |
| 003 GA4 adapter, typed errors, no retry on auth | **verified** | `test_ga4_adapter.py`; retry now on the **production** path (M3 fix) — 11 tests failed when the budget was forced to 1 |
| 004 AnalyticsPipeline registered | **verified** | `test_pipeline_registry_resolves_ga4` |
| 005 journal watermark = expected − done | **verified** | `test_journal.py` (26); a naive `max(period)` implementation fails exactly 4 of them, including the hole case |
| 006 fact tables, natural-key upsert | **verified** | migration + `test_ga4_upsert_respects_natural_key` |
| 007 ARQ job + hourly wave + in-process fallback | **verified** | `test_analytics_cron.py`; emptying the in-process path fails 2 |
| 008 ok/partial/failed exit contract | **verified** | `test_outcome.py` (8); collapsing partial→failed fails 7 across 3 files |
| 009 AnalyticsAgent + gated tool | **verified** | `test_analytics_agent.py`, `test_analytics_tool_gating.py`, `test_orchestrator_analytics_wiring.py` — the last counts call sites so a future MCP-only wiring is caught |
| 010 DataGate · truncation · freshness · quality gate | **verified** | `test_analytics_agent.py`; **four** distinct coverage states, each planted-defect tested |
| 011 charting | **verified** | `test_analytics_viz.py` (9) — *was dead code; closed during review (M1)* |
| 012 UI | **verified** | `GA4ConnectionForm`, `VendorCredentialsPanel`, `CollectionStatusRow`, `AnalyticsConnectionEdit`, `SidebarVendorCredentials` specs |
| 013 scenarios traced | **verified** | SCN-113…119 + `tests/unit/docs/test_ux_scenarios.py` (6), which was proven to fail on an orphan body and a bogus path |
| 014 vision §8 + ADR-0001 | **verified** | `vision.md` diff is one bullet; `docs/adr/0001-external-report-cache.md` |
| 015 retention | **verified** | raw never written; journal prune wired into the maintenance cron; cascade proven in the e2e |
| 027 docs | **verified** | `API.md`, `CHANGELOG.md` `[1.16.0]`, `CLAUDE.md`, `docs/ANALYTICS_SOURCES.md`, `README.md` |
| 028 coverage ≥ 72 % | **verified** | 78.66 % |

**15 of 15 module REQs verified, plus both program-level rows.** None partial,
none deferred, none dropped.

## What the review caught after every gate was green

The adversarial pass ran against a branch where all eight gates already passed.
It found 1 BLOCKER, 5 HIGH and 9 MEDIUM. All were fixed before merge.

| # | Finding | Why it mattered |
|---|---|---|
| B1 | Two-step PATCH attached another tenant's vendor credential; `/collect` then decrypted and used it | Cross-tenant data theft. Reproduced end to end by the reviewer |
| H2 | Account deletion deadlocked (`users→credentials` CASCADE vs `connections→credential` RESTRICT) | A data-subject deletion request that can never succeed |
| H3 | Connect failures journalled nothing → UI read `never_collected`, no error, forever | The most likely failure for a new connection was indistinguishable from "nothing has happened yet" |
| H4 | The agent could answer with **zero tool calls** — fabricated numbers, no caveat, validator passed | The exact failure the module exists to prevent |
| H5 | Sentry captured frame locals, shipping the decrypted service-account key off-box — plus, pre-existing, `db_password` and `ssh_key_content` | Secret exfiltration to a third party |
| H6 | Editing a connection's source type reported success while corrupting the row | Silent data corruption behind a green toast |
| M1 | REQ-011 charting was never wired — `AnalyticsResult.rows` read by nothing | An unmet requirement that all gates passed over |
| M3 | The retry path was dead code; a single 429 failed a period | An unmet requirement with a full test suite behind it |

Two further bugs were found by the tests themselves: the e2e caught a
vendor-truncated period being reported as a complete measurement, and the docs
pass caught the `_connect` sentinel contradicting its own documented contract
(whose fix then exposed a second-order status bug, also fixed).

**The lesson worth recording: eight green gates were not evidence.** Every one of
these shipped green. What found them was an adversarial pass, an end-to-end test
that crossed seams no unit test crossed, and a documentation pass forced to read
the code rather than the spec.

## Carry-over

20 rows in `2026-08-01-analytics-sources-carryover.md`. Two need the operator's eye:

- **C13 — `ssh_key_id` has the identical shape of bug as B1**, pre-existing on
  `main`: no ownership check on create/update, and `to_config` runs without
  `user_id` on the chat/SSE/WS paths, so a tenant who learns another tenant's SSH
  key id can have the server tunnel with someone else's private key. Not
  introduced here and not fixed here — it touches ~6 shared call sites, and
  folding that into an already-validated branch at the last minute was the wrong
  trade. **Recommended as the next piece of work.**
- **C20 — the push is blocked**, so nothing is deployed yet.

## Human step — the only one

```bash
git push origin main
```

That triggers CI (`ci.yml`) and, on success, the production deploy
(`deploy.yml` → `checkmydata-api` + `checkmydata-web`). Once it is pushed, stage 8
verification is: watch the two workflows, then

```bash
heroku logs -a checkmydata-api --tail | grep -E "alembic|Application startup"
curl -s https://api.checkmydata.ai/api/health
```

Migration `a7b8c9d0e1f2` runs from the `Procfile` before the web dyno boots.
Collection stays off until `ANALYTICS_COLLECT_ENABLED=true` is set on the app —
deliberately, per the house rule that ingestion automation ships off.
