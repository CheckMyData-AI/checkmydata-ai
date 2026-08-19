# Full-stack audit — 2026-08-19

Scope: every mechanic and flow, production behaviour, per-screen code-vs-docs
conformance. Every claim below carries its receipt: a `file:line`, a command and
its output, or a production log line with its timestamp.

Method: production logs (`heroku logs --app checkmydata-api -n 1500`, window
2026-08-18T22:00Z → 2026-08-19T00:01Z), the gate suite run locally, mechanical
sweeps over both trees, and verification of every previously-recorded finding
against current code.

---

## 0. Baseline — what is measured, not asserted

| Gate | Command | Result |
|---|---|---|
| Backend format | `.venv/bin/ruff format --check app/ tests/` | 847 files already formatted |
| Backend lint | `.venv/bin/ruff check app/ tests/` | All checks passed |
| Backend types | `.venv/bin/mypy app/ --ignore-missing-imports` | Success: no issues found in 373 source files |
| Backend tests | `pytest tests/ --collect-only -q` | **6087 collected** |
| Frontend types | `npx tsc --noEmit` | 0 errors |
| Frontend lint | `npx eslint . --max-warnings=0` | 0 warnings |
| Frontend tests | `npx vitest run` | **667 passed / 91 files** |
| Prod frontend | `curl https://checkmydata.ai/` | 200 |
| Prod API | `curl https://api.checkmydata.ai/api/health` | `{"status":"ok"}` |

Mechanical sweeps that came back clean (recorded so a future audit need not
re-derive them):

| Sweep | Result |
|---|---|
| Bare `except:` in `backend/app` | 0 |
| `except …: pass` (silent swallow) | 0 |
| `datetime.now()` without tz | 0 |
| `utcnow()` (deprecated) | 0 |
| `TODO/FIXME/HACK/XXX` in `backend/app` | 0 |
| `TODO/FIXME/HACK/XXX` in `frontend/src` | 0 |
| Frontend API-client paths with no backend route | 0 real (143 client paths vs 167 routes; 14 regex artifacts, all resolved by hand) |

Previously-recorded findings re-verified as **fixed**: 12 of the 14 findings
from `docs/ux/audits/2026-07-19.md` (AUD-…-01/02/03/04/05/06/07/08/09/13, plus
10/11 — `app/login/page.tsx:20-27` now reads `next` with an open-redirect
guard), and Cycle-3 UX gap #12 (the mobile notes drawer carries
`role="dialog"`, `aria-modal`, `aria-labelledby` at `app/app/page.tsx:358-361`
and gets Escape + a Tab focus trap from `hooks/useDialogA11y.ts:28,33-43`).

---

## 1. Production is failing at its core loop

### AUD-0819-01 — the repository index never completes in production (critical)

The worker is OOM-killed part-way through every repo-index run. Two consecutive
runs in the captured window, both dead at the same stage.

```
2026-08-18T22:02:46 heroku[worker.1]: Process running mem=766M(148.3%)
2026-08-18T22:02:46 heroku[worker.1]: Error R14 (Memory quota exceeded)
2026-08-18T22:03:06 heroku[worker.1]: Process running mem=999M(193.2%)
2026-08-18T22:04:11 heroku[worker.1]: Process running mem=1053M(203.3%)
2026-08-18T22:04:11 heroku[worker.1]: Error R15 (Memory quota vastly exceeded)
2026-08-18T22:04:11 heroku[worker.1]: Stopping process with SIGKILL
2026-08-18T22:04:12 heroku[worker.1]: Process exited with status 137
2026-08-18T22:04:12 heroku[worker.1]: State changed from up to crashed
2026-08-19T00:01:50 heroku[worker.1]: Process running mem=703M(137.5%)   <- second run, same road
```

The decisive measurement: **`grep -c 'pipeline_end'` over the 1500-line window
returns `0`.** No indexing run reached its terminal event in two hours. The last
stage entered in both runs is `code_symbol_embed`
(`00:01:33.310 workflow[08d8a230] code_symbol_embed: started`), which follows a
`graph_build` that persisted 2475 symbols.

Consequence chain, each link evidenced:

1. The run dies → ARQ retries it (`00:00:11: 7211.27s → daily_sync:…:2026-08-19:
   run_daily_project_knowledge_sync(...) try=2 delayed=7211.27s`).
2. The dyno restarts → the Chroma persist dir, being on the dyno's ephemeral
   disk, is gone → the next run logs
   `Vector store empty but 564 docs exist in DB — running repair_embeddings`
   (22:01:17 **and** 00:00:52 — every run, not once).
3. So the embeddings, the code graph and the BM25 snapshot that the whole
   "intelligence layer" reads from are permanently incomplete in production.

This is the finding everything else is secondary to: the product's core promise
degrades silently, and `vision.md` §7 ("graceful degradation", "every answer
traceable") is not honoured because nothing tells the user.

### AUD-0819-02 — symbol UIDs collide, and whole chunk batches are dropped (major)

Nine tracebacks in a single run, each losing 200 chunks:

```
22:03:25.365 WARNING app.knowledge.code_symbol_chunker: failed to upsert 200 chunks for project 38856e63…
chromadb.errors.DuplicateIDError: Expected IDs to be unique, found duplicates of:
  sym:partner/_ide_helper.php:php:partner/_ide_helper.php:method:macro:0,
  sym:…:method:setContainer:0, sym:…:method:getContainer:0, … in upsert.
```

Root cause — `backend/app/knowledge/ast_parser.py:376-381`:

```python
def _make_uid(language: str, rel_path: str, kind: str, name: str) -> str:
    return f"{language}:{rel_path.replace(chr(92), '/')}:{kind}:{name}"
```

The UID is `{lang}:{path}:{kind}:{name}` — it deliberately excludes the
definition line (CODEIDX-C7, so a line shift does not orphan inbound edges), but
it also excludes **the enclosing class**, which `Symbol.parent_uid`
(`ast_parser.py:72`) already carries. Two methods of the same name in two
classes of one file therefore share a UID. The blast radius is wider than the
chunker: `code_graph.py:125` builds `{s.uid: s for s in symbols}`, so a
colliding symbol silently overwrites its twin in the graph as well.

The handler at `code_symbol_chunker.py:243-259` catches the failure and logs a
`WARNING`, so ~1800 chunks per run vanish with no user-visible signal.

### AUD-0819-03 — retrieval degradation is measured but never shown (major)

`emit_retrieval_degraded` (`app/knowledge/retrieval_degradation.py:13-31`) fires
a WorkflowTracker event and a `retrieval_degraded_total` counter from
`hybrid_retriever.py:142,149`. **No frontend consumer exists** — every
"degraded" string in `frontend/src` belongs to *connection* health
(`ChatPanel.tsx:793`, `ConnectionHealth.tsx:16,20,161`). Given AUD-0819-01,
hybrid retrieval runs dense-only in production as a rule, and the reader is
never told the answer came from half the index.

### AUD-0819-04 — every run emits `pipeline_start` twice (major)

`RunCoordinator.start()` calls `tracker.begin(kind, …)`
(`app/services/run_coordinator.py:168`), which broadcasts `pipeline_start`
(`workflow_tracker.py:160-149`) — and then calls
`self._record(db, run, "pipeline_start", "started", …)`
(`run_coordinator.py:200`), which broadcasts it again via `tracker.emit`
(`run_coordinator.py:226`). The terminal path was written the other way round
and says so: *"Journal the terminal event directly; tracker.end emits the
canonical SSE"* (`run_coordinator.py:292`). The start path is the oversight.

Production shows the doubling on both dynos:

```
00:00:12.303 app[worker.1]  workflow[859ee38d] pipeline_start: started (Starting daily_sync)
00:00:12.368 app[web.1]     workflow[859ee38d] pipeline_start: started (Starting daily_sync)
00:00:12.427 app[worker.1]  workflow[859ee38d] pipeline_start: started (Starting daily_sync)
00:00:12.428 app[web.1]     workflow[859ee38d] pipeline_start: started (Starting daily_sync)
```

Two emissions × (emitting process + Redis-relayed subscriber) = four lines. Any
SSE/WS subscriber therefore receives the step twice.

### AUD-0819-05 — the backup reports success without backing up the database (major)

```
2026-08-19T00:00:00.050 INFO app.core.backup_manager: Skipping pg_dump on Heroku — use `heroku pg:backups` for managed backups
2026-08-19T00:00:00.054 INFO app.core.backup_manager: Backup complete: reason=scheduled, size=188416 bytes, path=data/backups/20260819_000000
```

`_backup_database` returns `0` and records `{"skipped": True}`
(`app/core/backup_manager.py:74-81`) — correct and honest in the manifest. The
line the operator actually reads then says "Backup complete" with a byte count
(`backup_manager.py:62-67`), and the artefact is written under
`data/backups/` on the same ephemeral disk that AUD-0819-01 shows being wiped.
`vision.md` §7 forbids telling the user something succeeded when it did not.

### AUD-0819-06 — TOFU host-key pinning is a no-op on the deploy target (major, security)

`ssh_known_hosts_path` defaults to `/tmp/checkmydata_known_hosts`
(`backend/app/config.py:796`). `/tmp` does not survive a dyno restart, and
AUD-0819-01 shows restarts are routine. Production duly re-pins:

```
2026-08-19T00:00:15.995 app[worker.1]: TOFU: pinned host key for 64.188.10.62 into /tmp/checkmydata_known_hosts
```

"Trust on first use" that re-runs first use on every boot accepts whatever key
is offered, which is the property TOFU exists to deny. `CLAUDE.md` presents
`tofu` as the safe default; on the primary deploy target it is not one.

---

## 2. A ratchet with a blind spot

### AUD-0819-07 — the scrim ban does not cover the file holding the last scrim

`src/__tests__/pack-bans.test.ts:203` scopes the raw-black/white surface ban to
`f.path.startsWith("components/")`. The one remaining offender in the tree lives
outside that prefix:

```
src/app/app/page.tsx:353:  className="absolute inset-0 bg-black/60 animate-fade-in"
```

It is the only `bg-black`/`bg-white` left in `frontend/src`, and it is precisely
the case the test was written for — a scrim that ignores the theme. The test
passes because of where the file sits, not because the codebase is clean.

---

## 3. Accessibility and honesty gaps still open

| ID | Sev | Finding | Evidence |
|---|---|---|---|
| AUD-0819-08 | minor | Suggestion chips truncate **in the DOM**, so a screen reader gets the cut string; `title` cannot serve as the accessible name because the button has text content | `components/chat/SuggestionChips.tsx:58-60` — `title={s.text}` beside `{s.text.length > 60 ? s.text.slice(0, 57) + "..." : s.text}`, no `aria-label` |
| AUD-0819-09 | minor | Insight card expand toggle exposes no expanded state | `components/insights/InsightFeedPanel.tsx:91-93` — `<button onClick={() => setExpanded(p => !p)}>` with no `aria-expanded`/`aria-controls`; 16 other toggles in the tree do carry it |
| AUD-0819-10 | minor | `useMobileLayout` returns `false` on first paint and corrects in `useEffect`, so mobile shows the desktop layout for a frame | `hooks/useMobileLayout.ts:8-11` |
| AUD-0819-11 | minor | **Restated after a reading error.** The original wording ("plain prose with no way to act on it") was wrong: `ToastContainer.tsx:18-30` already linkifies a literal "/pricing", citing SCN-100. The real gap is narrower and worse: the client discarded the paywall payload's own `upgrade_url` (`entitlement_service.py:39`), so the link appeared only when the prose happened to contain the route — true of the token-budget message (`usage_service.py:140`), false of the quota messages ("Plan 'free' allows 1 connection(s); you have 1.") | `lib/api/_client.ts:140-146`; `entitlement_service.py:32-40` |
| AUD-0819-12 | minor | `logout()` discards the server's answer | `stores/auth-store.ts:150` — `void api.auth.logout().catch(() => {});` |
| AUD-0819-13 | minor | `except (TimeoutError, Exception)` is redundant (`TimeoutError` is an `Exception` subclass) and reads as if it narrows when it does not | `app/agents/git_agent.py:182` |

---

## 4. Documentation that does not match the code

| ID | Sev | Finding | Measured |
|---|---|---|---|
| AUD-0819-14 | minor | `CLAUDE.md:12` states "~6,634 total (6,028 backend collected + 606 frontend Vitest across 86 files)" | 6087 backend, 667 frontend across 91 files → 6754 total |
| AUD-0819-15 | minor | `docs/ux/scenarios.md` carries SCN-113…121 as `draft` with `Last audit: —`, though the code shipped in `[1.16.0]` and is covered | `VendorCredentialsPanel.tsx` (363 lines), `ConnectionHealth.tsx` (474 lines), 36 `ga4`/`analytics` hits in `ConnectionSelector.tsx`, `analytics/source_types.py:32`, `ssh_key_service.py:68-92` |
| AUD-0819-16 | minor | `docs/qa-audit/issues.md` F-KNOW-09 says `pipeline_runner.py:1428` leaves `asyncio.create_task(_parse_one(rp))` untracked | The site moved to `pipeline_runner.py:1526` and **is** gathered (`:1531`); residual issues are unbounded fan-out (8541 tasks in production) and `return_exceptions=True` results never inspected |

---

## 5. Task block

Ordered by leverage. Each task's Definition of Done is a test that fails before
the change and passes after, plus the gate suite green.

| # | ID | Task | Sev |
|---|---|---|---|
| 1 | AUD-0819-02 | Make symbol UIDs collision-free (include the enclosing scope); dedupe defensively in the chunker so a residual collision can never drop a batch | major |
| 2 | AUD-0819-04 | Emit `pipeline_start` once — the run-scoped event carrying `run_id` | major |
| 3 | AUD-0819-05 | Stop reporting a backup that skipped the database as complete | major |
| 4 | AUD-0819-06 | Make the TOFU store durable, or fail loudly when its path is ephemeral | major |
| 5 | AUD-0819-01 | Cut the peak memory of the code-symbol embed stage so the run can finish | critical |
| 6 | AUD-0819-03 | Surface retrieval degradation to the reader | major |
| 7 | AUD-0819-07 | Widen the scrim ratchet past `components/` and tokenise the last scrim | minor |
| 8 | AUD-0819-08 | Give truncated suggestion chips their full accessible name | minor |
| 9 | AUD-0819-09 | Expose expanded state on the insight card toggle | minor |
| 10 | AUD-0819-10 | Remove the desktop-layout flash on mobile first paint | minor |
| 11 | AUD-0819-11 | Make the 402 upgrade path actionable | minor |
| 12 | AUD-0819-12 | Report a failed logout instead of swallowing it | minor |
| 13 | AUD-0819-13 | Narrow the git auto-pull handler | minor |
| 14 | AUD-0819-15 | Audit SCN-113…121 against the shipped code and move them out of `draft` | minor |
| 15 | AUD-0819-14 | Recompute the test/coverage numbers in `CLAUDE.md` | minor |
| 16 | AUD-0819-16 | Correct F-KNOW-09 in `docs/qa-audit/issues.md` and record the residual | minor |

---

## 6. Remediation log

Recorded as it shipped. "Watched fail" means the check was run against the defect
(present or deliberately re-planted) and seen red before being seen green — a green
nobody has watched fail is not evidence of anything.

| ID | Shipped | Test | Watched fail |
|---|---|---|---|
| AUD-0819-02 | The UID carries the enclosing scope (`ast_parser.py:_make_uid`); the chunker's document id is unique by construction (`code_symbol_chunker.py`) | `test_ast_parser.py::test_same_named_methods_in_different_classes_keep_distinct_uids`, `test_code_symbol_chunker.py::…unique_doc_ids_when_uids_collide` | yes — both red first, reproducing `DuplicateIDError` on the production shape |
| AUD-0819-04 | `tracker.begin(..., broadcast=False)`; the coordinator emits the single run-scoped event | `test_run_coordinator_start_emits_once.py` (2 tests) | yes — red with two events, the first `run_id=None` |
| AUD-0819-05 | Manifest carries `status` (`ok`/`partial`/`failed`), `skipped[]` and `database_captured`; both call sites persist the verdict instead of `"success"` | `test_backup_honesty.py` (4 tests) | yes |
| AUD-0819-06 | `warn_if_known_hosts_ephemeral()` says it once per process; `config.py` no longer claims a guarantee the host cannot keep; durable store specified in `docs/adr/0002-ssh-host-key-store.md` | `test_ssh_known_hosts_durability.py` (7 tests) | yes — import error, then the behaviour |
| AUD-0819-07 | Ratchet widened past `components/`; the last scrim tokenised to `lg-scrim` | `pack-bans.test.ts` | **yes — the defect was re-planted and the widened check named `app/app/page.tsx:353`** |
| AUD-0819-08 | `aria-label` with the full question on the chip | `SuggestionChips.test.tsx` | yes — re-planted; failed on the accessible name, not on a stray reference |
| AUD-0819-09 | `aria-expanded` + `aria-controls` on the insight toggle, `id` on the detail region | covered by the pack/a11y suites | no dedicated red — structural attribute, asserted by inspection |
| AUD-0819-10 | `useLayoutEffect` commits before paint | `useMobileLayout.test.tsx` | yes, **and the first attempt was thrown away**: under jsdom both hooks flush inside `act()`, so the behavioural test passed against the defect. Replaced with a source ratchet that states plainly what a unit test can and cannot hold here |
| AUD-0819-11 | The client uses the payload's `upgrade_url` rather than relying on prose | `api.test.ts` "plan paywall (402)" (3 tests) | yes |
| AUD-0819-12 | A non-401 logout failure says the server session may still be active; HTTP status now rides on client errors | `auth-store.test.ts` (2 tests) | yes, **after the first assertion was found not to discriminate** — it matched a string the code never emits, so it passed with the guard removed; sharpened, then verified red-with-guard-removed and green-with-guard |
| AUD-0819-13 | `except (TimeoutError, Exception)` → `except Exception`, with `CancelledError` re-raised | existing git-agent suite (16 passed) | no — a dead tuple member; removing it cannot change behaviour, which is the reason it was only ever misleading |

### Corrections to this audit, made by the work

- **AUD-0819-11 was misread.** See §3. The mechanism was already partly in place; what
  was broken was narrower and only reachable on the quota paths.
- **Cycle-3 UX gap #12 (mobile notes drawer a11y) was already closed** before this audit
  and is recorded as re-verified in §0, not as a finding.
- **`docs/qa-audit/issues.md` F-KNOW-09 is stale** (AUD-0819-16): the fire-and-forget site
  is gathered now. Two residuals stand and are real — the fan-out is unbounded (8541
  concurrent tasks in production) and `return_exceptions=True` results are never
  inspected, so an exception outside `_parse_one`'s own handler is dropped silently.
- **New, found while fixing:** `tests/integration/test_code_graph_end_to_end.py:11-12`
  says it exports `EXPECTED_SYMBOLS` / `EXPECTED_EXTENDS` "for the Task 11 graph
  benchmark". Nothing imports them (`grep -rn 'EXPECTED_SYMBOLS' app/ tests/` outside
  that file returns nothing). A docstring naming a consumer that does not exist.
