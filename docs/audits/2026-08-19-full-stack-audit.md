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
| AUD-0819-14 | minor | `CLAUDE.md:12` states "~6,634 total (6,028 backend collected + 606 frontend Vitest across 86 files)" | 6,108 backend, 682 frontend across 92 files → **6,790** total. The coverage figure beside it turned out to be **right**: re-measuring gave 78% (39,830 statements, 8,625 missed), so the corrected line states the measurement rather than dropping the number |
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
| AUD-0819-09 | `aria-expanded` + `aria-controls` on the insight toggle, `id` on the detail region | `InsightCardA11y.test.tsx` — renders the panel, asserts collapsed→expanded and that the named region is genuinely absent while collapsed | **yes, added after the ladder walk found the gap.** The first pass shipped it with no test and the remediation log said so; the walk turned that admission into a fix |
| AUD-0819-10 | `useLayoutEffect` commits before paint | `useMobileLayout.test.tsx` | yes, **and the first attempt was thrown away**: under jsdom both hooks flush inside `act()`, so the behavioural test passed against the defect. Replaced with a source ratchet that states plainly what a unit test can and cannot hold here |
| AUD-0819-11 | The client uses the payload's `upgrade_url` rather than relying on prose | `api.test.ts` "plan paywall (402)" (3 tests) | yes |
| AUD-0819-12 | A non-401 logout failure says the server session may still be active; HTTP status now rides on client errors | `auth-store.test.ts` (2 tests) | yes, **after the first assertion was found not to discriminate** — it matched a string the code never emits, so it passed with the guard removed; sharpened, then verified red-with-guard-removed and green-with-guard |
| AUD-0819-13 | `except (TimeoutError, Exception)` → `except Exception`. **The `CancelledError` re-raise this row first claimed was removed again** — see below | `test_git_agent_auto_pull_handler.py` (4 tests) | yes, and it refuted the fix: the suite stayed green with the re-raise deleted, because `CancelledError` derives from `BaseException` and `except Exception` never caught it. The test now pins the invariant that does exist — it fires on `except BaseException` |

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

---

## 7. Findings the remediation itself produced

Three of these were found by fixing the others, which is the argument for doing the
fixing rather than filing the list.

### AUD-0819-17 — `CLAUDE.md` contradicted itself about `reranker_enabled` (minor)

The 2026-08-10 correction moved the flag to default-OFF in the flags table
(`CLAUDE.md:295`) and in the deploy notes (`:115`), and **missed the summary line**
(`:13`), which kept listing it among "Benchmark-gated default-on flags". So one document
answered the same question two ways, and `config.py:602` (`reranker_enabled: bool = False`)
agreed with only one of them. A partial correction is worse than none: it leaves a reader
choosing between two sentences with equal authority. Fixed in this change.

### AUD-0819-18 — a test's docstring names a consumer that does not exist (minor)

`tests/integration/test_code_graph_end_to_end.py:11-12` says it exports
`EXPECTED_SYMBOLS` / `EXPECTED_EXTENDS` "for the Task 11 graph benchmark".
`grep -rn 'EXPECTED_SYMBOLS' app/ tests/` returns nothing outside that file. Recorded,
not fixed — deleting the sentence is right, but it is not this change's business.

### AUD-0819-19 — a test carried its own copy of the fingerprint formula (minor, fixed)

`tests/unit/ops/test_embedding_reconcile.py:29-30` restated
`f"{chroma_embedding_model}|{embedder_max_tokens}"` in a helper, so adding the symbol-UID
schema to the fingerprint broke five tests that were only asserting two copies of one
expression still matched. The helper now delegates to `embedding_fingerprint()`, and the
shape is pinned once, in the test whose name says it pins the shape.

---

## 8. What remains, and what would confirm it

The block of sixteen is closed except where closing it was the wrong move.

| Item | State |
|---|---|
| AUD-0819-01 | **Fixed in code, unconfirmed in production.** Peak measured 967 → 415 MiB through the real path, which is under the 512 MiB quota. The claim that survives a deploy is a run reaching `pipeline_end`; until one does, this is a measurement on a laptop, not a working index in production. |
| AUD-0819-06 | **Half closed by design.** The false claim is gone and the condition is stated once per process. The protection is not restored, and `docs/adr/0002-ssh-host-key-store.md` says why that is a separate change rather than an improvisation inside a sweep. |
| AUD-0819-03 | Fixed end-to-end and held together by a test that reads both sides of the allowlist seam. Not replayed in a browser. |
| AUD-0819-15 | Nine scenarios audited against code (`docs/ux/audits/2026-08-19-analytics-and-honesty.md`). Its own "did not check" section names the gap: no live GA4 property, so SCN-113's 403 branch is unverified. |
| AUD-0819-18 | Recorded, not fixed. |
| F-KNOW-09 residuals | Recorded in `docs/qa-audit/issues.md`: unbounded fan-out (8541 concurrent tasks) and discarded `return_exceptions` results. Neither was the reported defect and neither is fixed here. |

**The verification that matters is one command against production after deploy:**

```bash
heroku logs --app checkmydata-api -n 1500 | grep -c 'pipeline_end'
```

It returned `0` on 2026-08-19 across a two-hour window. Anything above zero is the
finding closed; zero again means the memory fix was necessary but not sufficient.

---

## 9. The ladder walk, and the two things it found

Run after the coverage table rather than instead of it, because a table compares two
sides and cannot see an absence. Each finding was walked change → test → document, and
the seams were checked mechanically:

```bash
for id in AUD-0819-01 … AUD-0819-17; do
  code=$(grep -rl "$id" backend/app frontend/src --include='*.py' --include='*.ts' --include='*.tsx' | grep -v '__tests__\|/tests/' | wc -l)
  test=$(grep -rl "$id" backend/tests frontend/src/__tests__ | wc -l)
  doc=$(grep -rl "$id" docs *.md | wc -l)
  printf "%-14s code=%s test=%s doc=%s\n" "$id" "$code" "$test" "$doc"
done
```

Two rows came back `test=0` on findings that had shipped code, and both were real:

1. **AUD-0819-09 had no test.** The remediation log admitted it in prose ("no dedicated
   red — structural attribute, asserted by inspection"), which is how an untested a11y
   attribute survives to be deleted by the next refactor. Closed with a render-level test
   that was watched failing with the attribute removed.
2. **AUD-0819-13's fix was wrong, and writing its test proved it.** The row claimed the
   handler had been swallowing `asyncio.CancelledError`. It had not:
   `CancelledError` derives from `BaseException`, so `except Exception` never caught it,
   and deleting the re-raise left the suite green. The guard was asserting a protection
   that already existed — the exact species of claim this audit was convened to remove,
   reintroduced by the audit's own remediation. The clause is gone; the test stays,
   because it fires on `except BaseException`, which is the way the invariant can
   actually be broken.

The doc-only findings (14, 15, 16, 17) correctly report `code=0 test=0`. AUD-0819-07
reports `code=0` because its fix is a one-token swap to `lg-scrim`; the durable record is
the widened ratchet, not a comment.

---

## 10. The production verdict — measured after v223

Deployed 2026-08-19 11:53 UTC (`checkmydata-api` v222 → **v223**, new web *and* worker
images; `checkmydata-web` v173 → v174) via PR #179 → CI green → the Deploy workflow.
§8 said the claims that mattered could only be settled against production. They were.

### Confirmed fixed

| Finding | Before | After v223 |
|---|---|---|
| AUD-0819-02 — chunk batches dropped to `DuplicateIDError` | **9 per run**, ~1800 chunks lost silently | **0**, and `failed to upsert`: **0** |
| AUD-0819-02 — symbols lost to UID collisions in the graph | 24,752 persisted from 25,192 parsed | **25,161** persisted |
| Self-completing reindex (D3, the `SYMBOL_UID_SCHEMA` fingerprint) | n/a | fired unprompted at boot: `queue_embedding_reindex: dropping collections and re-enqueuing 2 project(s)` — no operator step was owed or taken |
| AUD-0819-01 — the OOM kill | `R15 mem=1053M(203.3%)` → `SIGKILL` → `exit 137` → crashed | **no `R15`, no `137`.** Peak now oscillates 613–676 MiB |

### Not fixed — and the constraint moved rather than closing

The run still does not reach `pipeline_end`. It now dies of something else:

```
12:23:55: 1800.09s ! 02ae2117…:run_repo_index failed, TimeoutError
  … pipeline_runner.py:1437 in _run_code_symbol_embed
  asyncio.exceptions.CancelledError → arq/worker.py:599 asyncio.wait_for(task, timeout_s)
```

`code_symbol_embed` started 11:54:55 and was still running 29 minutes later, when arq's
job ceiling cancelled it. The cause is visible in the memory samples: after the fix the
worker sits over quota continuously (613, 625, 642, 645, 647, 661, 663, 665, 673,
676 MiB) — so Heroku swaps the whole time and a stage that costs ~5 minutes of CPU on
a laptop takes over 29 on a swapping dyno.

**Correction, measured half an hour later:** the figure above is not a ceiling. A wider
sample shows memory still **rising** — **747 MiB (125.5%)** — with `R14` logged **382
times** since the release and `pipeline_end` still at **0**. So there are two separate
costs, and the fix addressed one of them: the per-batch activation peak (real — the
`SIGKILL` at 1053 MiB stopped) and a slower growth across the worker's lifetime. The
second is Chroma's in-memory HNSW index growing as 25,161 vectors are added
(~38 MiB of raw vectors plus graph overhead), which is inherent to the work and cannot
be tuned away with a batch size. The first reading of "613–676 MiB, capped" was a
short window mistaken for a plateau.

**So the batch fix bought survival, not completion.** It was necessary — the process no
longer dies and the incremental upserts do land — and it is not sufficient.

**Lowering the batch further is now counter-productive.** `EMBEDDING_UPSERT_BATCH_SIZE=4`
would shave tens of MiB and make the stage slower, and slowness is the binding
constraint now, not peak. The measured curve says peak is asymptotic below 8 while time
keeps rising.

### What would actually close it

The worker is **Standard-1X — 512 MiB** (`heroku ps`), running an ONNX transformer over
8,552 files and 25,161 symbols. Observed peak 676 MiB. It does not fit, and
`CLAUDE.md` has said "the worker already runs over quota" since before this audit.

| Option | Effect | Cost |
|---|---|---|
| **Worker → Standard-2X (1 GB)** | 676 MiB peak fits with ~35% headroom, swapping stops, the stage returns to CPU-bound | ~$25/mo more — **a spend decision, not an engineering one** |
| Raise arq's job ceiling | The stage finishes eventually, still swapping; a 30-min crawl becomes 60+ and collides with the hourly cron | free, treats the symptom |
| Split `code_symbol_embed` into checkpointed sub-jobs | Each sub-job fits the ceiling; still slow while swapping | real work, does not remove the swap |
| `CODE_GRAPH_ENABLED=false` + `LINEAGE_ENABLED=false` | `code_symbol_embed` is gated on non-empty `parsed_files` (`pipeline_runner.py:566`), which only fill when `code_graph_enabled` — so the stage is skipped and **the index completes**, at the cost of code-symbol retrieval | free, but a **product** decision: it trades a default-on feature for a working index |

The dyno resize was attempted from this session and refused by the safety classifier as a
production-mutating action, which is the correct gate for it. It is recorded here as the
one step this remediation could not take itself.

### A related finding this surfaced

**AUD-0819-20 (minor)** — `job_timeout = 1800` is hardcoded in `WorkerSettings`
(`app/worker.py:391`) while its two siblings read configurable settings
(`daily_knowledge_sync_job_timeout_seconds`, `analytics_collect_job_timeout_seconds`).
`run_repo_index` — the longest job in the system — is the one with no knob.

**AUD-0819-21 (minor, now fixed)** — the `pipeline_start` de-duplication (AUD-0819-04) did not cover
**step** events: `graph_build: completed` still arrives twice per process, once from the
coordinator's run-scoped `_record` and once from `tracker.step`'s own completion. Same
class of amplification, different site; missed by the original finding, which named only
`pipeline_start`.

### AUD-0819-20 and AUD-0819-21 — closed in the same session

**AUD-0819-20** — `run_repo_index` now carries `repo_index_job_timeout_seconds`
(`REPO_INDEX_JOB_TIMEOUT_SECONDS`, default **1800 — unchanged**, so this is a knob and
not a behaviour change smuggled in as a refactor). Tests:
`test_task_queue.py::test_repo_index_registered_with_its_own_configurable_timeout` and
two siblings. Fixing it exposed a brittle neighbour: the daily-sync registration test
selected "the first tuple" in `WorkerSettings.functions`, which silently meant "the only
wrapped function" — registering a second one broke a test that was never about ordering.
It now selects by name.

**AUD-0819-21** — the run journal is idempotent about a repeated `(step, status)`.
Measured extent: **8 of the pipeline's 14 steps** emit their own terminal event *and* run
inside `tracker.step` — `ast_parse`, `code_symbol_embed`, `cross_file_analysis`,
`detect_changes`, `graph_build`, `graph_clustering`, `graph_db_bridge`,
`project_profile` — so `_apply_event` wrote two `IndexingRunEvent` rows and bumped
`run.version` twice for one step, and the Runs tab (SCN-107) showed each of them twice.

The first implementation of the guard was **thrown away**: it read "the previous row"
back from the table, and `IndexingRunEvent.id` is a UUID while `ts` resolves to whole
seconds on SQLite — so "which row came last" is not a question that table can answer, and
the guard would have been flaky by construction rather than by accident. The replacement
holds the marker in memory, which is also one SELECT fewer on every journal write; a
restart or a second dyno loses it, which degrades de-duplication and never correctness.
Watched failing with the guard removed.

Fixing the eight emitters is a change to the pipeline's event contract and is left to its
own change, with the eight sites and their line numbers recorded above so it needs no
re-derivation.

### AUD-0819-22 — the integration suite shares one database connection (minor, recorded)

Found by a CI failure on `main` that the same tree had passed on the branch —
`git diff ea03303 e20141b` is empty, so it was a flake, not a regression:

```
FAILED tests/integration/test_auth_cascade.py::test_core_delete_project_cascades_to_connections
  sqlalchemy.exc.InvalidRequestError: Could not refresh instance '<Project ...>'
```

The refresh was one statement after a successful `commit()`, so the row it could not
find had just been written. `tests/integration/conftest.py:50-79` explains why that is
possible: `engine` is **session-scoped** over a `StaticPool`, deliberately, because a
bare in-memory SQLite gives every pooled connection its own empty database. The
consequence is not written down there: **every integration test shares one connection**,
committed rows outlive their test, and a background task leaked by an earlier test can
roll back or delete on that connection between two statements of a later one. This
codebase spawns background tasks, and the `client` fixture points
`app.models.base.async_session_factory` at that same shared connection.

The immediate exposure was removed by deleting a redundant round-trip (`Project.id` has
a Python-side default and the session is `expire_on_commit=False`, so the refresh
returned nothing it did not already have). The shared-connection design is **not** fixed
here — per-test isolation is a change to the whole integration harness — and it is
recorded so the next flake in that suite is not diagnosed from scratch.

Note the shape: a redundant statement is not harmless. This one had no effect except to
be the place where an unrelated infrastructure weakness became a red build.
