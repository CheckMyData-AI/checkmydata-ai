# DOCMAP — where settled things live in this repository

First written 2026-08-08 during the query-timeout pipeline run. It answers four
questions: where settled things live, what each fact's single home is, what a change
of a given type obliges, and what command proves the docs are in sync.

## Registers and single homes

**One fact, one home.** A second copy is a future contradiction, so anything below
that repeats a fact elsewhere links instead of restating.

| Fact class | Single home | Notes |
|---|---|---|
| Architecture decisions with a trade-off | `docs/adr/` | **This is the decision register.** Sequential numbering; `0001`–`0007` today (measured 2026-09-23: `ls docs/adr/`) |
| Product intent and invariants | `vision.md` | §7 invariants and §8 anti-vision are load-bearing; a conflicting feature stops until resolved |
| Agent/house conventions, commands, flags | `CLAUDE.md` | Read by every session; must not restate what a deeper doc owns |
| User-facing behaviour | `docs/ux/scenarios.md` | Hard rule in `CLAUDE.md`; checked by `tests/unit/docs/test_ux_scenarios.py` |
| Orchestrator / agent internals | `docs/SYSTEM_ARCHITECTURE.md` | The deep dive `ARCHITECTURE.md` summarises |
| API contracts | `API.md` + `backend/app/api/routes/` | Route modules are the tiebreaker |
| Release history | `CHANGELOG.md` | Keep-a-changelog style, versioned |
| Delivery queue and the status of every PRJ-xx / T-xx / V-x row | `docs/evidence/loop-queue.md` | **The single source for status** since 2026-09-17; an audit or `CLAUDE.md` links to it rather than restating a status |
| Residual board (B-xx — work outside a named project) | `docs/evidence/backlog.md` | |
| Production verification of shipped rows | `docs/evidence/verification.md`, `docs/evidence/acceptance-*.md` | |
| Product backlog and sprint history | `BACKLOG.md` | Destination for every carry-over row that outlives its run |
| Pipeline briefs, specs, plans, carry-over | `docs/superpowers/{specs,plans}/` | One dated set per run |
| What previous runs got wrong here | `docs/superpowers/retro.md` | **Created by this run**; capped at ten standing instructions |
| Operator runbooks | `docs/ANALYTICS_SOURCES.md`, `docs/DEPLOYMENT.md`, `docs/ROLLOUT_M1_M6.md` | Per-subsystem |

## Propagation matrix — what a change of type X obliges

The stage-0 source ledger names what you *read*; this names what you *owe*.

| Change type | Obliges |
|---|---|
| New/changed **config setting** | `backend/app/config.py` docstring · `backend/.env.example` · the flag table in `CLAUDE.md` · a boot-validation test if the value can be nonsensical |
| New/changed **user-visible string or behaviour** | `docs/ux/scenarios.md` (add or amend a `SCN-` row, in the **same** change) · `tests/unit/docs/test_ux_scenarios.py` stays green |
| New/changed **agent or orchestrator behaviour** | `docs/SYSTEM_ARCHITECTURE.md` · the request-lifecycle block in `CLAUDE.md` if the flow changed |
| New/changed **API route or contract** | `API.md` · route module docstring |
| **DB schema** change | Alembic migration · the model docstring · `CLAUDE.md` if a documented column set changes |
| **Hard-to-reverse decision** with a real trade-off | An ADR in `docs/adr/` (all three of: hard to reverse, surprising without context, genuine alternatives) |
| Anything **deferred** | The run's `-carryover.md` **the moment it is said**, then `BACKLOG.md` at stage 10 |
| Any **release** | `CHANGELOG.md` version entry · the "Recent work" line in `CLAUDE.md` |

## The documentation gate

Docs claims are checked by command, not by assertion — a claim nobody can run is
not documentation ([evidence-docs canon](../CLAUDE.md)).

```bash
cd backend && .venv/bin/pytest tests/unit/docs/ -q       # scenario index↔body parity, Coverage: paths resolve
```

**Ratchet floors** (a count may shrink, never grow):

| Ratchet | Floor today | Set | Owner |
|---|---|---|---|
| Unresolvable `Coverage:` paths in `docs/ux/scenarios.md` | **≤ 9** | 2026-08-01 (m0, carry-over C19) | `tests/unit/docs/test_ux_scenarios.py` |
| Backend coverage | **≥ 80%** | CI `coverage report --fail-under=80` (raised 2026-08-26) | `.github/workflows/ci.yml` |

## Known stale claims — both fixed (re-checked 2026-09-23)

Recorded here so they are fixed rather than rediscovered. Both were owed by stage 9
of the 2026-08-08 query-timeout run, and both are now corrected at their source:
`docs/SYSTEM_ARCHITECTURE.md` §error classification documents `error_type=`, and the W0
landmarks paragraph in `CLAUDE.md` carries the 2026-08-08 correction about `approach` /
`route_ms`. Kept as a record of what was wrong.

| Claim | Where | Why it is false |
|---|---|---|
| `ErrorClassifier` categorises `timeout` | `docs/SYSTEM_ARCHITECTURE.md:895` | True only for vendor-worded timeouts; the app's own `"Query timed out after Ns"` falls through to `UNKNOWN` |
| `RequestTrace` gained routing columns `approach`, `complexity`, `route_ms` | `CLAUDE.md`, W0 landmarks | Only `complexity` exists — `grep -rln "approach" backend/alembic/versions/` returns nothing |
