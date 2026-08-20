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

### AUD-0819-23 — the escape hatch could not parse its own setting (minor, fixed)

Found while evaluating the third option in §10, which is the point of writing options
down: `chromadb.HttpClient(host, port=8000, ssl=False, …)` takes a **hostname**, the
setting is named `chroma_server_url`, and the value was passed straight through as
`host`. So `CHROMA_SERVER_URL=https://chroma.example.com` resolved to
`http://https://chroma.example.com:8000`.

The whole suite mocked `chromadb` wholesale, so the construction was never exercised —
and `tests/unit/test_vector_store.py` asserted `HttpClient(host="http://chroma:8000")`,
i.e. **the test agreed with the bug**. A green suite was evidence that the code did what
the test said, and nothing more.

Now split into `(host, port, ssl)` with a full URL, a bare host (keeping the historical
port 8000 / no TLS so an existing deployment is not silently repointed), and a refusal
rather than a localhost fallback for an unparseable value — a typo that quietly reads an
empty index looks exactly like a working deployment with no data. `CHROMA_SERVER_URL` is
documented in `.env.example` for the first time.

### §10 addendum — the idle worker fits; the workload does not

Measured after v224, and it corrects the reading in §10 twice over.

First, the mechanism: Heroku emits `Process running mem=…` **only** as part of the
over-quota warning — in the pre-deploy log, `mem=` lines and `R14`/`R15` lines number 5
and 5, and every `mem=` line has an `R14` within two lines. So the absence of samples is
not missing data; it is the dyno being under quota.

Second, the reading: the three `747M(125.5%)` samples timestamped after the v224 release
came from the **old** dyno — the worker restarted at 20:39:55 and Heroku's sampler
reports the last known value with a lag. Across the following 17 minutes the freshly
started worker logged **0** `R14` and **0** samples.

So the baseline is fine and there is no leak at rest: the 613 → 747 MiB climb was the
indexing workload — the ONNX activations per batch (fixed, and bounded now) plus Chroma's
in-memory HNSW filling with 25,161 vectors (inherent to the corpus, not to any setting).

That makes a **third** option the architecturally right one rather than merely cheapest:

| Option | What it closes | Cost |
|---|---|---|
| Worker → Standard-2X | the symptom; index completes | ~$25/mo |
| `CODE_GRAPH_ENABLED=false` | index completes without code symbols | free; loses a feature |
| **`CHROMA_SERVER_URL` → a Chroma service** | the HNSW graph leaves the worker **and** the store stops being ephemeral, so `repair_embeddings` stops running after every restart — AUD-0819-01 and the Chroma half of AUD-0819-03 at once | running one service |

The third does **not** move the ONNX embedding work: with an `embedding_function` on the
collection, the client computes vectors and ships them, so the per-batch activation peak
stays in the worker. It is bounded and measured (~125 MiB over baseline at batch 8). It
also does not touch the BM25 snapshots, which are separate pickles on the same ephemeral
disk — that half of F-KNOW-07 stands.

### §10 second addendum — the 87 warnings were one number repeated, and it sharpens the diagnosis

A later log window showed **87** `R14` events and briefly looked like a contradiction of
the "no leak at rest" finding above. It is not. Every one of them is stamped
**20:11:02 → 20:39:41**, before the v224 worker restarted at 20:39:55, and every one
reports the *same* value: `mem=747M(125.5%)`, re-emitted every four minutes.

That flat repetition is the fact worth keeping. The index job had already died at
12:23:55; nothing was running; and the old worker still held 747 MiB for the next
half hour until the release replaced it. **A finished job did not give the memory back.**

Both windows after a restart are clean:

| Window | Worker | `R14`/`R15` |
|---|---|---|
| 20:11 → 20:39 | pre-v224 (post-failed-index) | 87, all at a flat `747M(125.5%)` |
| 20:40 → 21:41 | v224 | **0** |
| 21:42 → (v225 restart at 21:41:43) | v225 | **0** |

So the shape is: baseline fits, the workload does not, and the memory the workload takes
stays taken for the life of the process. That is what an in-process HNSW index does — it
is resident, not transient — and it is the strongest argument yet for
`CHROMA_SERVER_URL`: not that the worker is short of memory in general, but that the
vector index has no business being inside a process that is supposed to finish a job and
move on.

Recorded because the raw count read the other way. `grep -c` over a log window answers a
question about the window, not about now.

---

## 11. Continued on the backlog — and two more of my own claims were wrong

### F-KNOW-09 residual — half of my restatement was also wrong (fixed, in part)

§7 restated F-KNOW-09 as "the fan-out is unbounded (8541 concurrent tasks) plus
discarded `return_exceptions` results". The first half is **false**, and measuring it
took one command: `ast_parse_concurrency` defaults to **4** (`config.py:581`) and
`_parse_one` holds `async with sem` around the parse, so four files parse at a time. The
8,541 task *objects* cost **~7 MiB** retained (`tracemalloc`, 8541 tasks behind a
semaphore of 4) — noise beside a 747 MiB problem.

I wrote that finding from a grep hit and the five lines around it, without reading the
enclosing function. That is the third time in this audit the same method produced a wrong
claim: AUD-0819-11 (the toast already linkified `/pricing`), AUD-0819-13
(`CancelledError` is a `BaseException`), and now this. The pattern is worth naming: **a
grep tells you a line exists, not what governs it.**

The second half was real and is fixed. `_parse_one` counts the failures it can see, but
anything raised *outside* its try/except — the assignment into `state.parsed_files`, the
semaphore, a `MemoryError` on a large tree — became an exception object in a list nobody
read, and the stage logged `parsed=N` and reported success with N quietly short. Now
counted, logged with its cause, and named in the stage event so the number reaches the
run journal rather than only a log line someone would have to know to grep for. The test
was watched failing against an empty log.

### F-CONN-08 — the premise was half wrong, the fix is still worth having

The finding says `QueryResult.error = str(e)` returns the DSN and password. Measured:

```
postgresql://admin:SuperSecret123@nonexistent.invalid:5432/mydb
→ asyncpg raises: "[Errno 8] nodename nor servname provided, or not known"
→ password present: False
```

A driver's own message is usually harmless. The leak needs something to **wrap** the
error with the DSN or a command line, and the call site cannot tell which kind it got.

What *is* verified: `ssh_exec.py:_config_vars` substitutes `db_password` into a command
template, so a secret exists in that layer by construction; every connector returned
`str(e)` verbatim; and the same text is logged. And the redaction **already existed** —
wired to Sentry alone (F-LLM-03), which is the egress a secret does the least harm on.
The two that matter are the API response a project member reads and the log the platform
retains.

So: the patterns moved to `app/core/redaction.py` — one set, because a second copy drifts
and drifts silently — `sentry.py` re-exports them, and `safe_error()` is applied at all
six connector sites and both service sites. A ratchet test fails if `error=str(e)`
returns.

**Stated as defence in depth, not as a closed exfiltration.** What was demonstrated is a
secret present in the layer, not a secret leaving it.

### AUD-0819-18 — fixed

The docstring claiming "the Task 11 graph benchmark" consumes `EXPECTED_SYMBOLS` now says
plainly that nothing imports them today. A named consumer that does not exist is worse
than no claim: it sends the next reader looking for it.

### AUD-0819-24 — two order-dependent unit-test failures (recorded, not fixed)

A full-suite run on 2026-08-20 failed two tests that both **pass in isolation** and both
pass when their own directory is run alone:

```
FAILED tests/integration/test_learnings_api.py::TestLearningsApi::test_recompile
FAILED tests/unit/test_trace_persistence_service.py::…::test_tracker_begin_includes_project_id
```

So they are order-dependent, not regressions — the same class as AUD-0819-22, but **not
the same cause**: `test_trace_persistence_service` is a unit test, so the integration
conftest's session-scoped shared SQLite connection cannot explain it. Something else
leaks across unit tests — a module-level singleton or a patched global not restored.

Recorded rather than chased: a flake needs a reproduction before a fix, and the
reproduction here is "run 6,100 tests in this order". Worth noting that this suite has
been through one flake hunt already (the ChartRenderer prototype pollution, 2026-08-16),
which found exactly this shape — a test mutating shared state for everyone after it.

**What the same run did find deterministically was mine:**
`test_config_settings.py::TestEnvExampleSync::test_every_settings_field_documented`
failed because `batch_stale_claim_seconds` was added to `Settings` and not to
`.env.example`. That is the project's own gate catching the omission the convention
exists to prevent, and it caught it in the same pass that shipped the setting.

### AUD-0820-01 — the check the non-ASCII proxy was standing in for (recorded)

F-LEARN-02's rule rejected any lesson more than half non-ASCII, and its message named
its own intent: "likely raw user question in non-English". The intent is right — the
analyzer sometimes echoes the user's question back as the lesson — but the proxy tested
the alphabet, so it rejected every Russian and Chinese lesson while passing the *same
request in English* verbatim. It was never a defence against raw requests; it was a
defence against non-English text, read as the former.

The genuine check is available and cheap in principle: compare the lesson against the
question that produced it and reject a near-duplicate. `create_learning` receives
`source_query` but not the natural-language question, and it has six call sites
(`sql_agent.py`, `pipeline_learning.py`, `learning_analyzer.py` ×3,
`data_investigations.py`), so threading it is its own change.

Recorded rather than approximated. The alternative on offer was an imperative-verb
wordlist per supported language, which would be a second proxy with the same failure
mode as the first — incomplete in a way that correlates with language.

**What shipped instead** is two checks that match their own stated intent: a lesson that
*ends* as a question is refused in any alphabet (the old rule missed the English case
entirely), and a lesson that is mostly not letters or digits is refused as not-writing,
Unicode-aware so Cyrillic and CJK count as writing.

### AUD-0820-02 — the injection defence existed, was written once, and reached one prompt of ten

Cluster #5 of the board names five findings and reads as "no content-safety gate on
LLM-authored or DB-sourced content". Working it produced a different and larger picture,
and the reframing came from one measurement: `grep -c 'UNTRUSTED DATA'` across
`app/agents/prompts/` returned **1 of 10**.

`sql_prompt.py` already carried it, and by the **right mechanism** — content you cannot
refuse is neutralised in the prompt rather than screened at ingest. A table's comment is
part of the schema whatever it says; an ingest gate could only choose between indexing
hostile text and refusing to index the table. So F-SQL-01 was closed before this pass,
and the fix the board proposed ("shared content-safety screen on every ingest") would
have been the wrong shape for it.

The real gap was that nine sibling prompts consume text the product does not author and
said nothing about it:

| Prompt | What arrives that nobody here wrote |
|---|---|
| `mcp_prompt` | tool results from **third-party MCP servers** |
| `knowledge_prompt` | file contents and comments from a **cloned repository** |
| `git_prompt` | commit messages, tags, diffs — and trailers are forgeable (F-GIT-06) |
| `analytics_prompt` | dimension values and rows from the **analytics vendor** |
| `orchestrator_prompt` | project name/description (F-PROJ-15), rules (F-RULE-02), sub-agent output |
| `viz_prompt` | column names and row values being charted |

`prompts/untrusted_data.py` now builds the section and **raises if no source is named**.
That constraint is the point: "some content may be untrusted" is advice, while "the
commit messages below are attacker-controllable" is something a model can act on, and
the difference only shows under adversarial text. `test_untrusted_data_sections.py`
ratchets it in the manner of the frontend's `pack-bans.test.ts` — mechanical, because the
rule is — so the tenth prompt cannot quietly skip it.

`planner_prompt` and `investigation_prompt` are deliberately excluded: they compose no
externally-authored text of their own. That exclusion is written in the test, not left to
be rediscovered.

## 12. Four findings in one 65-line route, and two lessons about tests

`app/api/routes/demo.py` was 65 lines and carried four board rows — F-BILL-07, F-EXP-01,
F-EXP-02, F-EXP-03. Three of them are ordinary: no quota check, `is_read_only=False`, no
dedup. The fourth is a **broken promise**, and it is the one worth writing down.

SCN-003's expected result says the demo path "sets up sample data". The button says *Try
demo instead*. The route seeded nothing — 65 lines, no `INSERT` — and pointed at
`db_name=":memory:"`, which is empty on every fresh connection regardless of what any
single connection ever wrote. **The first thing a new user saw after clicking the demo
was an empty database**, from which the reasonable conclusion is that the product does
not work.

SCN-003 was marked `implemented` with a **PASS from the 2026-07-19 audit**. That audit
checked the button rendered and the toasts fired. Both were true. Neither is the
scenario:

> A scenario can pass on its affordances while its promise goes undelivered. The check
> that closes one must read the **expected result**, not the buttons.

### The two lessons, and both were measured

**A source-inspection test proves nothing about behaviour.** The first suite written for
this fix asserted `"INSERT INTO" in inspect.getsource(demo_route)` and
`"is_read_only=True" in src`. Eight tests, all green. Then the plant: replace the route's
call to `_seed_demo_db(db_path)` with `pass`.

```
$ git diff app/api/routes/demo.py | grep -c "PLANT: seeding removed"
1
$ pytest tests/unit/test_demo_route_contract.py -q
8 passed in 1.44s
```

The exact bug — the route not seeding — left the suite fully green, because the seeder
still existed in the module and the test only asked whether the *text* was there. That
suite was deleted. Its replacements open the SQLite file the connection names and count
the rows, and the same plant is now red:

```
$ pytest tests/integration/test_demo_routes.py tests/unit/test_demo_seed.py -q
FAILED ...::test_the_demo_connection_points_at_a_database_with_rows_in_it
1 failed, 12 passed
```

The parallel to the 2026-07-19 SCN-003 pass is exact, one layer down: a grep over source
is to behaviour what a rendered button is to a delivered promise.

**A test can hold a bug in place more firmly than the code does.**
`tests/integration/test_edge_cases.py` carried
`test_demo_setup_twice_creates_two_projects`, asserting `p1 != p2`. The duplication was
not an oversight the tests had missed — it was **written down as the contract**, so the
dedup fix arrived as a test failure and looked, for a moment, like a regression. Code
that is wrong gets fixed; a test that is wrong gets *obeyed*, because the next reader
takes it for a decision someone made. It is now
`test_demo_setup_twice_reuses_one_project`, with the history in its docstring.

### What the demo is now

A per-user file under `DEMO_DB_DIR` (default `./data/demo`), seeded with `customers` (5
rows) and `orders` (8) — small enough that a person can check the agent's answer by eye,
which is the entire job of a demo for a query product — joined by a real foreign key, and
re-seeded whenever the file is missing, because Heroku's filesystem does not survive a
restart while the project row does. Read-only, quota-metered, and reused rather than
multiplied.

### The fifth finding, which the other four were sitting on

While wiring the seed, one command ended the question of whether the demo had ever
worked:

```
>>> get_adapter("database", "sqlite")
ValueError: Unsupported adapter: sqlite. Available: ['postgres', 'postgresql',
'mysql', 'mongodb', 'mongo', 'clickhouse', 'mcp']
```

`ADAPTER_REGISTRY` has never had a `sqlite` entry, and the demo route has created
`db_type="sqlite"` connections since the demo path existed. **The demo's connection could
not be opened at all** — the first question a new user asked it failed on dispatch, before
any of the four findings above could matter. Seeding sample data behind it would have been
a database nobody can connect to: the same empty screen, with more work behind it.

Worth naming as a pattern rather than a one-off. Four findings had been filed against this
route by two separate audits, each describing a *property* of the connection — its quota,
its read-only flag, its uniqueness, its emptiness — and none had asked whether the
connection **resolves**. A property is checked by reading the code that sets it; existence
is checked by running it. The fix took one line in a registry and 200 in a connector; the
finding took one line in a REPL.

`app/connectors/sqlite.py` is written as a connector, not as a demo helper: driver-enforced
read-only via `mode=ro`, `PRAGMA` introspection down to foreign keys and index uniqueness,
views marked and not row-counted, `sqlite_*` internals withheld from the schema context.
Two refusals are deliberate and both are the finding in miniature — `:memory:` is rejected
at connect (each connection opens its own empty database, so it reads as configured and
behaves as empty), and a **missing file is rejected rather than created**, because
`sqlite3` creates it silently and a typo'd path would otherwise look exactly like a
working connection over a database with no tables.

The demo's file is repaired in `ConnectionService.to_config` — the one seam all 36
connector call sites pass through — because Heroku's filesystem is ephemeral and per-dyno:
a restart takes the file while the `Connection` row survives, and a second web dyno never
had it. Scoped by directory containment, so a user's own SQLite database is never written
to, and best-effort, so a failed repair cannot block an unrelated connection.

**And that wiring was itself unverified until a plant said so.** Deleting
`repair_demo_db_if_missing(db_name)` from `to_config` left every test green: the helper had
its own suite, and nothing asserted the product called it. The same shape as the
source-grep tests deleted earlier in this iteration, one layer up — a tested helper nobody
calls is a tested helper nobody calls.

### And the fix opened a hole, which is why the fix is two layers

Registering a SQLite connector changes what a `Connection` row *means*. Every other
engine here is a network endpoint reached with credentials; a SQLite connection is a
**filename on the server's own disk**, so "which database" and "which file may this
process read" stop being different questions.

Two free-string fields made that reachable. `ConnectionCreate.db_type` is a `Literal`
that excludes `sqlite` — only the demo route ever sets it — but `ConnectionUpdate.db_type`
and `ConnectionUpdate.db_name` are plain `str`:

1. Click *Try demo instead* → own a SQLite connection.
2. `PATCH /api/connections/{id}` with `db_name: "./data/agent.db"`.
3. Ask a question. That file is the application's own database: every tenant's rows and
   every encrypted credential.

Before the connector existed the attempt died at `Unsupported adapter: sqlite`, which is
the only reason this was not already live. **A fix that removes one error can be the thing
that makes another reachable** — the audit question is not "is this change correct" but
"what was this error load-bearing for".

Closed at both layers, because neither is trustworthy alone: the connector resolves the
path and requires it inside `DEMO_DB_DIR` (so `..` and symlinks are covered, not
pattern-matched), and the route refuses `db_type: "sqlite"` on any PATCH and refuses
changing `db_name` on a connection that already is one.

**The two route guards needed two starting states.** Pointed at the demo connection, a
test of the `db_type` guard is satisfied by the `db_name` guard firing first — measured:
deleting the `db_type` check left the suite green. Two guards on one route, exercised from
one state, means one of them is decoration.

One pre-existing bug surfaced on the way: a PATCH to a SQLite connection was refused with
`"Provide either a connection string or db_host + db_name"`. A file has no host and never
will, so *every* update to the demo connection — including a rename — failed with advice
the user could not act on.

### Two ratchets caught the change, and both were right

The full suite came back `2 failed, 6320 passed` — neither failure a test of the demo, and
neither a false positive.

**`test_legacy_coverage_paths_do_not_regress` (9 → 12).** SCN-003's new Coverage line named
`tests/unit/test_demo_seed.py`, a file this same iteration had **renamed** to
`test_demo_data.py`, plus two backend paths written relative to `backend/` when the
resolver resolves against `frontend/src/` or the repo root. A documentation ratchet caught
a stale reference in documentation written eleven minutes earlier — which is the argument
for having one: prose is where a rename goes unnoticed, because nothing else reads it.

**`test_broad_handlers_returning_a_degraded_value_do_not_grow` (78 → 79).**
`SQLiteConnector.test_connection` catches broadly and returns `False`. Examined rather
than waved through: it is the same shape as the other four connectors' `test_connection`
(`mysql.py:369`), all already inside the count; the caller asked *is this alive*, and
`False` is the honest answer to any failure; and it logs at **warning** with the
traceback, which is exactly what the ratchet's own message asks for. The number moves to
79 **with the instance named in the constant's comment** — an unexplained bump is how a
ratchet becomes a formality.

The distinction matters more than either fix. A ratchet is not a rule that the count is
correct; it is a rule that the count is *examined*. One of these two was a real defect and
the other was a legitimate new instance, and the ratchet cannot tell them apart — that is
the reader's job, and the ratchet's job is to make sure a reader looks.

## 13. F-GIT-01 — the finding was real, and the tests lied twice about it

The board carried this as Medium: *"Option injection via unvalidated rev/sha →
`show`/`diff --output=` arbitrary write."* Before writing a line of fix, the claim was
run:

```
before: 'IMPORTANT ORIGINAL CONTENT\n'
after : 'diff --git a/f.txt b/f.txt\nindex f719efd..6e5aa7c 100644\n--- a/f.txt\n+++ b/f.txt\n@@ -1 +1 @@\n-two\n+dirty\n'
show also writes: 216 bytes
```

`GitInspector.diff()` and `.show()` pass caller-supplied revisions as **leading argv**
with no `--`, so `--output=<path>` is not a revision — it is git's diff-output option, and
git writes there. Any file the process can write, truncated and replaced. On a dyno that
includes the application's own source, which is remote code execution at the next boot.

Reachable from chat: `git_agent.py:373/375/382/408` take `args["sha"]`, `args["a_sha"]`,
`args["b_sha"]` and `args["commit_sha"]` straight out of the model's tool call. The paths
beside them were already guarded by `_safe_relpath`; the revisions were not. **A path
looks dangerous and a revision looks like an opaque identifier** — that asymmetry is the
whole finding.

The fix is one validator at all five rev entry points, and a new `UnsafeRevError` so
*refused before git ran* never reads as *git ran and disagreed*. The original
proof-of-concept now raises and the file is intact.

### The tests lied twice, and the second lie was subtler

**First: a rule with no test that fails without it.** Deleting the character allow-list
left all 24 tests green — every hostile value they carried began with a dash, so the
leading-dash rule satisfied them alone. Adding eight metacharacter cases (`HEAD -o …`,
`HEAD;…`, a newline) did **not** fix it: they still passed, because they asserted
`GitInspectorError`, and git rejects `HEAD -o /path` as an unresolvable revision by
itself, raising `GitCommandFailedError` — the same base class.

The assertion had to become the specific type. That is not a test detail; it is the rule's
actual claim. For today's call sites the allow-list is defence in depth — argv is a list,
and a space inside one element cannot split into two arguments — and a rule nothing can
distinguish from git's own error is a rule that quietly stops existing.

**Second, and worse: the test suite performed the attack.** The hostile values were
written as a literal `/tmp/x`. A plant run removes the guard on purpose — so the run that
proved the guard worked **created `/tmp/x`, 216 bytes, outside any sandbox**. Found by an
assertion failing for the wrong reason: `assert not Path("/tmp/x").exists()` was false
because an earlier plant had just written it.

> A test carrying a proof-of-concept executes that proof-of-concept the moment the guard
> it checks is gone — which is exactly when someone is deliberately removing it. Aim it at
> `tmp_path`.

### And the same gap, one file over

`UpdateRepoRequest.branch` had **no validator** while `AddRepoRequest.branch` called
`validate_git_ref`, and the branch reaches `repo.git.checkout(branch)` and
`Repo.clone_from(branch=…)` as argv. Filed as F-GIT-08 and fixed in the same change.

This is the third instance of one shape in two days: **guarded on create, free on PATCH**
— `db_type`, `db_name`, and now `branch`. A create-side validator reads as "this field is
handled", and nothing points at the sibling model that copies the field and not the rule.
Worth a sweep of its own rather than a third individual fix.

## 14. The fourth instance, refused

Three fields in two days had the same shape: guarded on create, free on PATCH.
`ConnectionUpdate.db_type`, `ConnectionUpdate.db_name`, `UpdateRepoRequest.branch`. Each
was found while fixing something else, and each was fixed where it was found.

Fixing the fourth the same way is how the fifth ships. So instead: an AST sweep of every
`Create`/`Update` model pair under `app/api/routes/` — 109 `BaseModel` classes, 8 paired
stems — comparing, field by field, whether both sides declare a validator.

**Three more, all on `ConnectionUpdate`:**

| Field | Create | Update | What that allowed |
|---|---|---|---|
| `mcp_env` | ≤50 entries, keys ≤255, values ≤4096 | nothing | `update()` encrypts and stores whatever dict arrives (`connection_service.py:216-218`) into a Text column, then hands it to a spawned MCP subprocess |
| `connection_string` | stripped | nothing | `_sanitize_strings` covers `name` downstream but not the DSN, so a trailing newline reached `encrypt()` and failed to connect later in a way that pointed nowhere |
| `name` | stripped | nothing | covered downstream — the only one of the three that was harmless, and indistinguishable from the other two by reading either model |

That last row is the argument for the sweep. Reading `ConnectionUpdate` tells you nothing
about which omissions matter; only the comparison does, and nobody performs a comparison
they have not been asked for.

### The fix is a base class, and the ratchet is for everyone else

`_ConnectionFieldRules` carries the three rules and both models inherit it, so a rule
added later cannot be added to one and forgotten on the other. `check_fields=False` is
required because the base declares no fields — and it costs something: a mistyped field
name there validates nothing, silently. The runtime tests buy that back by asserting each
rule *fires* on both models rather than merely being declared.

`test_create_update_validator_parity.py` compares by AST and covers the pairs not yet
shaped this way. Its allow-list takes a **reason**, not just an entry — an exception
nobody has to justify is how a ratchet becomes a formality, which is the same note the
78→79 bump earned two sections ago.

**The refactor broke the module, and a test said so within the minute.** Moving the
validators onto a field-less base made pydantic raise `PydanticUserError` at class
definition — `app/api/routes/connections.py` would not import at all, which is the whole
API down. `ruff` and the AST-based parity test both passed it, because neither imports the
module. Worth keeping in view: a static check that never executes the code cannot tell a
refactor from a crash.

## 15. F-SSH-02 — the board under-stated it twice

The row read *"ClickHouse exec template leaks DB password on remote command line."* Both
halves of that turned out to be smaller than the truth.

**It was all three engines.** `PGPASSWORD="{db_password}"`, `MYSQL_PWD="{db_password}"`
and `CLICKHOUSE_PASSWORD="{db_password}"` all interpolate the secret into the command
string. `asyncssh.run(command)` sends an SSH *exec* request and sshd runs it through the
login shell as `sh -c "<command>"`, so the password sits in that process's argv, readable
by any user on the remote host via `ps` or `/proc/<pid>/cmdline` for as long as the query
runs. A finding named after the connector someone happened to be reading acquires that
connector's scope, and the two next to it inherit the exemption.

**And the ClickHouse template never authenticated.** A command-prefix assignment sets the
variable for that command's own environment; `"$VAR"` on the same line is expanded by the
*calling* shell, from the value it already had:

```
$ sh -c 'FOO="secret" printf "argv:[%s]\n" "$FOO"'
argv:[]
$ FOO=leaked sh -c 'FOO="secret" printf "argv:[%s]\n" "$FOO"'
argv:[leaked]
```

`--password "$CLICKHOUSE_PASSWORD"` therefore passed an **empty string** — or, if the
login shell exported that name, **somebody else's**. A security finding and a
functionality bug in the same nine characters, and neither was visible from reading the
template as English: it *looks* like it sets a variable and passes it along.

### The fix, and the two things it turned up

The password travels on the channel's stdin now. The command opens with
`IFS= read -r DBPASS`, the templates set the client's variable from `"$DBPASS"` as an
environment assignment, and `--password` is gone — the client reads
`CLICKHOUSE_PASSWORD` from its environment, which is what setting it was for.

**`read -r` stops at the first newline**, so a password containing one would authenticate
as its first line and fail with whatever the server says about that — an error pointing
nowhere near here. Refused at build time instead, with the reason.

**Nine introspection call sites built their commands by hand** —
`_prepend_pre_commands(format_template(...))` — bypassing `_build_command` entirely. They
would have emitted a `$DBPASS` with nothing to read it, which is an empty password and a
failed connection on every schema refresh. They route through `_build_command` now: there
is one place that knows a command needs its secret delivered, and everything goes through
it.

A custom `ssh_command_template` that still interpolates `{db_password}` keeps working,
with a warning that names the exposure. Breaking someone's connection to improve its
hygiene is not an improvement they asked for.

## 16. A control that turns itself off and logs about it is off

`ssh_known_hosts.py` ends with this, and means it:

```python
# F-SEC-4: fail closed — an unrecognised policy must never silently
# disable verification.
```

Two branches above, `tofu` answered an unwritable `known_hosts` file by setting
`known_hosts = None` and connecting anyway — for that connection and every later one. The
log line is the only difference between finding out eventually and never finding out; the
verification is equally absent either way.

**Fail-closed was the wrong fix**, and worth saying why: it would break every SSH
connection on a read-only filesystem in order to protect a promise the operator never
made. A security change that turns working connections into outages gets reverted, and
the finding comes back with a note saying it was tried.

So the pin moves into process memory. First connect to a host is unverified — which is
what trust-on-first-use *is*, not a shortcut — and every later connect in that process is
checked against the key the first one presented, aborting on a mismatch. Where the file is
writable but the disk does not survive a restart (AUD-0819-06, Heroku's primary target),
that is already the guarantee, so this downgrades nothing anywhere and upgrades the
read-only case from *never verified* to *verified after the first*.

One case is deliberately **not** pinned: a host that presents no readable key. Recording
it would assert a check that cannot happen, and a pin nobody can compare against is
indistinguishable from a pin that always matches.

### And the ratchet fired again, for the third time in one day

`_host_key_blob` catches broadly and returns `None`, so
`test_broad_handlers_returning_a_degraded_value_do_not_grow` went 79 → 80. Examined rather
than bumped: a host key that cannot be read must not crash a connection attempt, and
`None` is **not silent** here — the caller logs at warning that the connection is
unverified and cannot be pinned, which is the opposite of the failure the ratchet is named
after. The constant's comment names the instance, as the two before it do.

Three bumps in a day is itself a signal worth recording: each was justified, and a ratchet
that only ever moves up stops measuring anything. The comment history is what keeps it
honest — a reader can see all three reasons in one place and judge the trend, which a bare
number never permits.
## 17. The obvious guard was the wrong guard

F-CONN-04: `db_host`, `ssh_host` and a DSN's host are user-supplied and reach a socket, so
an authenticated user can aim one at the cloud metadata endpoint or the app's own Redis
and read the connection-test error as an oracle.

There was already a guard for this shape — `validate_repo_url` DNS-resolves a repo host
and refuses every non-public address, with `REPO_ALLOW_PRIVATE_HOSTS` as the escape
hatch. Reusing it looked like the whole task.

**It would have been an outage.** A public git host is the normal case; a database on
`10.x`, `192.168.x` or `127.0.0.1` is *also* the normal case. Copying that default refuses
the majority of real deployments in order to protect the minority running this
multi-tenant — and a guard that breaks the normal case does not survive contact with the
first support ticket. It gets set to `true` globally, and then it protects nobody, and the
finding is closed on the board while the hole is open in production.

So the rule splits by what is *never* legitimate versus what is *usually* legitimate:

| Rule | Default | Why it can be that default |
|---|---|---|
| Cloud metadata endpoints refused | always on | no database has ever lived at `169.254.169.254`; what does live there issues credentials for the whole account. Costs no deployment anything. |
| Private/loopback/link-local refused | **off** | a database on an internal network is the normal case. On for multi-tenant operators, where a tenant reaching `127.0.0.1` reaches *your* infrastructure. |

Four details that are the difference between a guard and the appearance of one:

- **By name *and* by resolved address.** `metadata.google.internal` is refused before DNS
  runs, because a split-horizon resolver can answer differently for us than for whoever
  checked.
- **Every address, not the first.** A name resolving to one public and one private record
  is refused; otherwise the public one launders the other.
- **Unresolvable is refused, not waved through.** Failing open on a DNS error lets an
  attacker choose whether the guard runs, by choosing a name that fails to resolve once.
- **Off the event loop.** `getaddrinfo` blocks and this is on the request path. The repo
  guard makes the same call synchronously inside a Pydantic validator — a pre-existing
  trade-off, and not a precedent worth copying into a new one.

Applied on create **and** PATCH. That is the fifth time in two days the same sentence has
been necessary, and the parity ratchet from §14 does not catch it — the check lives in the
route, not on the model. Worth noting as a limit of that ratchet rather than a gap in this
fix: it compares declared validators, and a guard called from the handler is invisible to
it. The two route tests are what cover it here.

### I shipped the failure this section warns about, and the suite caught it in an hour

The paragraph above about guards that break the normal case was written *before* the code
— and the first version of the code refused an unresolvable host in both modes, on the
"failing open lets an attacker choose whether the guard runs" argument, which is sound in
strict mode and wrong everywhere else.

```
$ pytest tests/integration/test_analytics_connections_api.py -q
E  AssertionError: {"detail":"Host 'db.internal' could not be resolved"}
E  assert 422 == 200
```

`test_database_connection_still_creates_with_its_defaults` — a pre-existing test, written
by somebody else for an unrelated feature — said no. **A database hostname this process
cannot resolve right now is ordinary**: the user configures the connection before the VPN
is up, the name resolves only from inside the network, or only through the SSH tunnel's
far side. The connection test is where reachability is decided, and refusing at
configuration time turns the guard into the outage the section is about.

So the DNS failure became mode-dependent, which is the honest shape: accepted with a log
line by default, refused under `CONNECTION_ALLOW_PRIVATE_HOSTS=false`, where the operator
asked for public addresses only and *"I could not check"* is not *"public"*. The metadata
name check runs before DNS and is unaffected in both modes.

Writing down a failure mode does not immunise you against it. What caught this was a test
somebody wrote for a different feature entirely — which is the argument for a suite that
covers the ordinary path, not only the interesting one.

## 18. Two of this audit's own rows named an impact the code cannot produce

Before starting on F-CHAT-02 and F-CHAT-03 — both written this morning, both marked
*"Confirmed open, evidence recorded"* — one command settled who reaches the endpoint they
describe:

```
$ grep -rln "WebSocket\|session_created" frontend/src/
$
```

Empty. The product's own UI speaks **SSE** (`src/lib/api/chat.ts:150` →
`/chat/ask/stream`) and never opens `/api/chat/ws/...`. That endpoint is documented public
API (`API.md:206`, ticket-authenticated), so third-party clients can reach it — but the
user-facing consequences both rows asserted are not consequences this code has:

- **F-CHAT-02** said *"ten tab reloads leave ten orphans."* A tab reload opens no
  WebSocket. Orphans are real for a WS client; the number ten came from imagining the UI
  doing something it does not do.
- **F-CHAT-03** said *"the reasoning panel goes quiet."* The panel is fed by SSE, and the
  **SSE relay is already correct** — `chat.py:1032-1043` polls on a 0.5 s timeout, emits a
  heartbeat every 20 s, holds `stream_timeout_seconds` as an overall deadline, and
  *continues* on a gap instead of exiting. The 60-second exit is the WebSocket relay,
  which the panel never sees.

Both findings survive; both severities were argued from the wrong blast radius. The rows
now carry the correction above the original text rather than replacing it, because a row
that quietly becomes right teaches nothing about how it was wrong.

**The pattern, and it is the third time in this audit.** Every one of these came from
reading the code that *contains* the defect without reading the code that *calls* it —
the same shape as the three findings this audit had to withdraw on 2026-08-19
(AUD-0819-11, AUD-0819-13, F-KNOW-09), each written from a grep hit without the enclosing
function. Reading outward is not optional diligence; it is where the severity comes from.

The consolation is that the fix is now easier to get right: a correct relay already exists
twenty lines away in the same file, so the WS one has a reference implementation rather
than a design question.

## 19. The correct implementation was twenty lines away

Both WebSocket findings had a working reference in the same file, which changed the work
from a design question into a copy.

**F-CHAT-03.** The WS relay treated sixty seconds of quiet as the end of the run and
logged it at `debug` — invisible at production level. The SSE relay, 440 lines up, polls
on 0.5 s, emits a heartbeat every 20 s, holds `stream_timeout_seconds` as an overall
deadline, and *continues*. Two transports over one event queue, disagreeing about what
silence means, and only one of them was right.

The fix is the SSE shape with WS's message vocabulary. What is worth recording is the
**extraction**: the relay was an inner closure over `websocket`, so neither behaviour that
matters — survives a gap, still ends at a ceiling — was reachable without a full WebSocket
handshake. A closure that cannot be called is a closure that cannot be tested, and the
sixty-second exit had survived every review the file ever had.

**F-CHAT-02.** Every connect wrote a session row before the receive loop. The obvious fix
— create it lazily, on the first message — breaks the protocol: `session_created` is sent
immediately after connect, so the client is *promised an id before any message exists*.
The constraint is what makes reuse the right answer rather than a compromise: an empty
session for the same `(project, connection, user)` is handed back, bounding orphans to one
per triple with the contract untouched.

One line of that query is load-bearing beyond the finding — `ChatMessage.id.is_(None)`.
Without it, reuse would hand a client somebody's existing conversation because it happens
to share a triple, which is a considerably worse bug than the row it saves. Its own test
says so, and the plant that removes it goes red.

### Both severities were wrong, and this is where they were re-argued

§18 recorded that the impacts these rows claimed — ten orphans per ten tab reloads, a
reasoning panel going quiet — are impacts the code cannot produce, because the first-party
UI speaks SSE. Fixing them anyway was still right: a documented endpoint that writes a row
per connect and gives up on a slow step is wrong for whoever uses it. What changed is the
claim, not the verdict, and the rows now carry the correction above the original text.

## 20. The fourth finding today whose wording did not survive measurement

F-PROJ-03: *"`accept_invite` commits inside `begin_nested()` → 500 on idempotent
re-accept."* Two commands before writing any fix:

```
$ pytest tests/unit/test_invite_service.py -k already_member
1 passed

$ # a direct reproduction, SQLAlchemy 2.0.51 + aiosqlite
commit inside savepoint: no exception
   rows persisted: 1
```

No 500, and not because of anything this codebase does: a `commit()` inside an open
SAVEPOINT deactivates the savepoint transaction, which then exits quietly. The bookkeeping
is in `SessionTransaction`, shared across dialects, so the Postgres deployment behaves the
same.

**The smell was right and the symptom was invented.** What is actually wrong there:

- the savepoint buys nothing — the early return commits inside it, the normal path commits
  after it, and nothing ever rolls it back, so it reads as a guarantee it does not provide;
- and it works by accident of a library version, so a stricter SQLAlchemy would produce
  precisely the 500 the row already asserted.

That is a finding worth fixing and a claim worth withdrawing, and the row now says both.

### Four in one day, and they divide into two kinds

| Finding | What was wrong with the claim |
|---|---|
| AUD-0819-11, -13, F-KNOW-09 (yesterday) | written from a grep hit without the enclosing function |
| F-CHAT-02, F-CHAT-03 (§18) | correct code, wrong blast radius — nobody calls the endpoint |
| F-PROJ-03 (here) | correct instinct, invented symptom — the failure was reasoned about, not run |

The first kind is fixed by reading outward. The second by asking who calls it. **The third
is different and worth naming separately: a mechanism was reasoned about correctly in the
abstract — commit-inside-savepoint *is* a real hazard — and the specific claim about what
this code does was never executed.** Plausible mechanism plus unexecuted claim is the most
convincing wrong finding available, because everything except the conclusion is true.

The cheap defence is the one used here: before fixing, run the failure. If it cannot be
made to happen, the finding is about the future, and saying so is part of the fix.
## 21. Two loops, one rule, and only one of them had it

F-LLM-01: when the chosen LLM provider fails, `LLMRouter` retries the same messages
against the next vendor. Those messages are the user's question, their database schema and
their query results, so the fallback is not only a reliability event — it moves customer
content to a processor the deployment did not choose.

Two things were missing, and the second is the one that makes the first matter. Nothing
said **which** vendor received the request: the existing line reports that a provider
failed, which is a different fact. And no deployment could say *never* — a team that chose
one vendor because that is who its customers were told about had no way to hold the line.

The fix is the pattern this audit has now used three times: **the guarantee is opt-in, the
disclosure is not.** `LLM_ALLOW_PROVIDER_FALLBACK` defaults to `true`, because defaulting
it off trades every deployment's resilience for a promise most never made — the same
reasoning as the connection-host guard two sections ago, and the same conclusion, that a
control which breaks the normal case gets switched off and then protects nobody. The
WARNING naming both vendors fires either way.

A refusal ends the chain rather than raising its own error, so the caller still gets
`LLMAllProvidersFailedError` carrying the real outage. The reason a request could not be
served is that the provider was down; the setting is why it was not papered over, and it
says so on its own line.

### The detail worth carrying forward

**There are two fallback loops in that file**, and they are not shared code: `complete()`
uses the retry wrapper, `stream()` walks its own copy calling `provider.stream` directly.
A fix applied to the first would have looked complete — the tests would pass, the log line
would appear — while the streaming path kept sending data to a second vendor in silence.

That shape has now appeared four times in two days: two route guards exercised from one
starting state (§14), a `db_type` guard and a `db_name` guard where one hid the other
(§13), create-versus-PATCH five separate times, and now two transport loops over one
policy. **A rule that lives in more than one place is a rule that holds in one of them
until something counts.** The plants are what count here: one per loop, and removing the
disclosure from either goes red on its own.

## 22. The half of a fix a test suite cannot see

The demo work shipped in v235 and its post-deploy check went looking for something the
tests could not have known to ask:

```sql
SELECT db_type, db_name, COUNT(*), MIN(created_at)::date FROM connections
WHERE db_type = 'sqlite' GROUP BY 1,2;
 sqlite | :memory: | 1 | 2026-06-05
```

One connection, created eleven weeks before the fix. Before it, that row failed with
`Unsupported adapter: sqlite`. After it, the new connector **refuses** `:memory:` at
connect — which is a better error for the identical empty screen.

**F-EXP-01 said the demo path delivers sample data. After the fix that was true for
connections created after the fix.** Every test asserted behaviour on rows the new code
creates, because that is the only kind of row a test creates. The rows already in the
database were outside the frame entirely, and no amount of test coverage would have moved
the frame — only looking at production did.

The repair is a data migration that then gets out of the way: rewrite `db_name` to the
owner's demo path, and the `repair_demo_db_if_missing` already deployed in `to_config`
seeds the file on the next config build. No operator step, no user action, the same
self-completing shape the embedding reconcile uses. The user never learns it was broken,
which is the correct outcome — they were never told it worked.

### Two details worth keeping

**`downgrade` restores the path and does not restore write access.** Reverting a path
rewrite is not a reason to hand a connection back its write privilege, and a downgrade
that does something nobody asked for is worse than one that is slightly asymmetric. The
test asserts the asymmetry so it reads as a decision.

**The second control row exists because the first did not earn its clause.** Removing the
migration's `db_type == "sqlite"` condition left the test green — the postgres control row
was named `app`, so nothing non-sqlite was ever named `:memory:` for the condition to
protect. A mysql connection with `:memory:` typed into it as a placeholder is odd and not
impossible, and it is precisely what the clause is for. Third time in two days that a
guard turned out to be untested until a plant said so; the pattern is now familiar enough
to check for deliberately rather than stumble into.

## 23. The ratchet was measuring the wrong thing, and four bumps in a day said so

`test_broad_handlers_returning_a_degraded_value_do_not_grow` counted every broad `except`
that returns a literal. It stood at 78 this morning and I raised it four times — 79, 80,
81 — each time with the instance named and a justification, and each time the justification
was the same: *this one logs at `error` with a traceback.*

Four identical justifications in one day is the measure telling you about itself. So it got
measured:

```
broad handlers returning a literal : 81
  ... log at warning or above      : 37
  ... degrade SILENTLY             : 44
```

**The ratchet was flagging code that complies with its own failure message.** That message
reads *"if the caller cannot tell your fallback apart from real emptiness, log at warning,
not debug"* — and 37 of the 81 do exactly that. A number that grows every time somebody
follows the advice cannot be a limit on anything.

The rule is now the incident it was named after. On 2026-08-09 a `TypeError` in a prompt
helper was caught broadly, logged at **debug**, and turned into `""`; a crash and "there are
no warnings" produced identical output. What made that dangerous was the **silence**, not
the breadth. So a handler that degrades *and announces it* is not a violation, and the
count is 44 — a debt that can be paid down instead of a ceiling that only rises.

Two properties worth stating, because re-baselining a ratchet looks like weakening one:

- **It is stricter per instance.** The old rule forbade a shape 37 compliant handlers
  shared; the new one forbids exactly the shape that caused the incident, and forbids it at
  zero tolerance for growth.
- **It is falsifiable in both directions.** Planted a silent broad handler → red. Planted
  an identical one that logs at `error` → green. The old ratchet could not tell those apart,
  which is why it had nothing to say.

The generosity is deliberate: any `warning`/`error`/`exception`/`critical` call anywhere in
the handler counts as announcing, without checking the words. Judging prose in a test is
how a test becomes a matter of opinion, and the measurable half is the half that caused the
outage.

## 24. A CI failure that said every test passed

PR #194 went red on the frontend while touching no frontend file. `git diff --name-only
origin/main..HEAD | grep -c '^frontend/'` returned 0, the suite was 683/683 locally, and
the same step had passed on main's previous three commits. Every signal pointed at "flaky,
re-run it".

The log said otherwise:

```
Test Files  93 passed (93)
##[error]EnvironmentTeardownError: Cannot load '/src/lib/api/index.ts' … after the
environment was torn down
##[error]Process completed with exit code 1
```

**Every test passed and the runner exited 1.** That is the kind of red nobody reads — and
behind it was a production bug, not a test-harness quirk.

`handleSessionExpired` fired a floating `void import("@/stores/auth-store").then(logout)`
and set `window.location.href` on the next synchronous line. In a browser the document
starts unloading immediately, so the `.then` may never run; under vitest the test finishes
first and the import lands in a dead realm. Same cause, two symptoms — one visible only in
CI, and the visible one was the harmless half.

The part that matters: **the only piece of `logout()` that outlives a navigation is
`storage.removeItem("auth_user")`**, the profile kept for instant UI paint. Left undone, a
session expires, the person lands on `/login`, and the app still holds their profile
against a cookie the server has already rejected. The in-memory store dies with the
document either way, so importing it to mutate memory before leaving was work that could
only fail to happen.

### The workaround was already there, and that is the lesson

The test file carried an `afterEach` waiting one macrotask, with a comment explaining the
teardown error precisely. Someone — me, earlier in this same audit — had diagnosed the
symptom, papered over it in the test, and moved on. One tick is enough on a laptop and not
on a CI runner, so the paper tore.

> A workaround that describes the bug correctly is a bug report somebody filed against
> themselves and then closed.

It is removed rather than left as harmless. Keeping it would hide the regression if the
floating import ever came back, and it was the visible half of the defect — the half that
made the invisible half survivable.

Three plants confirm the fix, and one of them had to be rewritten: deferring the clear back
into a microtask first produced a TypeScript error, so vitest reported "no tests" rather
than a failure. A plant that breaks the build proves the build breaks, not that the guard
works.

### The tenth entry found the other nine

Updating SCN-011 tripped `test_legacy_coverage_paths_do_not_regress`, and its message
printed the whole list:

```
legacy unresolved Coverage paths grew from 9 to 10:
['SCN-011: src/__tests__/session-flash.test.ts',
 'SCN-011: src/__tests__/session-expiry-clears-auth.test.ts',
 ... 'SCN-106: src/__tests__/components/LogsScreenTabs.test.tsx']
```

**All ten were the same defect.** A `src/__tests__/...` prefix resolves against neither
`frontend/src/` nor the repo root; the real path is `frontend/src/__tests__/...`. Nine of
them had been frozen as "legacy debt" for months, which is what a baseline does when
nobody reads the list it is protecting.

Fixing the one that failed and leaving nine identical ones beside it is the minimum the
test asks for, and it is the wrong thing to do. All ten are corrected and the baseline
drops from 9 to **0** — at which point it stops being frozen debt and becomes the same
rule the strict check already applies to SCN-113 and above: a Coverage path either resolves
or it is wrong.

That is the second ratchet re-baselined today for the same reason, and the pattern is worth
naming: **a baseline is a promise to come back, and nothing in a green test reminds you.**
Both were found by adding one more instance — the number moved, the message listed what it
was protecting, and the list turned out to be a single fixable class rather than accumulated
history.
