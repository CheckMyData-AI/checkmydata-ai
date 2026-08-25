# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Fixed — the error catalog never heard about the failure it existed for (N3)

- `error_log` is the product's own record of what is going wrong — what `/api/logs`
  shows an operator. On 2026-08-23 it held **three rows**, newest 2026-08-17, while
  `indexing_runs` held **143** at `status='failed'`. The single most frequent production
  failure this system has was absent from the one place built to display it.
- The cause is structural, not an oversight. `RunCoordinator` catalogs failures in three
  places (`run_coordinator.py:317`, `:450`, `:485`) and every one sits on a *terminal
  event* path — `finish`, or a pipeline reporting its own end. The reaper does neither:
  it issues a bulk `UPDATE ... SET status='failed'` against rows whose process is gone,
  so no terminal event is emitted and **no writer is ever reached**.
- The reaper now reads the rows it is about to kill, then catalogs each one. The message
  carries the **step**: `stale run reaped` alone collapses every reaped run of a kind
  onto one line, and it was the step that made the cause findable — 64 of 70 failures
  were `graph_build` specifically. The product can now state that concentration itself
  instead of waiting for someone to run the SQL by hand.
- The run's own `error` column is left exactly `REAP_ERROR`. `run_coordinator.py:393`
  compares it verbatim to recognise a reaped run and reconcile it when the pipeline
  turns out to be alive; enriching that column instead of the catalog message would have
  broken reconciliation silently.
- Cataloguing is best-effort and cannot abort the sweep: a diagnostic that stops the
  recovery it describes would leave `running` rows unreaped and the UI spinning, which
  is the state the reaper exists to end.
- Six tests. Two are guards rather than features — the `error` column stays verbatim,
  and a **cancelled** run is not catalogued as an error, because `cancelling` →
  `cancelled` is somebody's decision.
### Fixed — a step longer than five minutes was killed for being slow (N1)

- `RunCoordinator.step` wrote `heartbeat_at` on entry and again on success, and nothing
  in between. `IndexingRun` is the row `StaleRunReaper` reaps, so **any single step
  running longer than the 300 s timeout was declared dead while it was still working**
  and flipped to `failed` with `error='stale run reaped'`.
- Production had been failing this way every day since 2026-08-07: **64 of 70**
  repo-index failures, all on `current_step='graph_build'` — the step that walks 25 421
  symbols. Runs made of many short steps completed fine at 417 s and 2 568 s, which is
  the signature of a per-*step* limit rather than a per-run one.
- **It hid for thirteen days because a heartbeat already existed, on the wrong row.**
  `_run_index_background` (`repos.py:556-563`) ticks `IndexingCheckpoint`; the checkpoint
  therefore stayed alive beside a run that was being reaped, so nothing about the failure
  looked like a missing heartbeat.
- The beat now wraps the step body. It lives in `step` rather than in any caller because
  all four entry points into a repo index — the ARQ task, the manual route, the retry
  route and the daily sync — reach the pipeline through this contextmanager; the fix
  first considered (wrapping `worker.py`'s `run_repo_index`) would have covered one of
  the four and added a second heartbeat beside the existing one.
- The writer opens **its own session**: the step's `db` driven from two tasks
  concurrently is a race, not a heartbeat. It issues a targeted `UPDATE` rather than
  loading the ORM object, so it cannot carry a stale `version` into a column the step
  boundaries bump deliberately, nor win on columns it does not own via a second identity
  map.
- Three tests, and the third is the point: the beat must **stop** when the step does, or
  a genuinely crashed run stays immortal — the failure the reaper exists to catch,
  reintroduced by its own fix.

### Fixed — a green gate that could not see a duplicate (N5)

- `docs/qa-audit/issues.md` carried **three unresolved git conflict markers** (lines 91,
  97, 100) and four copies of its tally paragraph, each claiming a different count:
  34/75, 37/72, 39/70, 35/74. The whole suite stayed green through it.
- The reason it stayed green is the interesting half. `test_the_tally_matches_the_rows_it_summarises`
  used `re.search`, which returns the **first** match and stops. The first copy happened
  to be the correct one, so the check passed and the three contradicting copies — and the
  raw markers beside them — were invisible to the only test that reads this file. A check
  that catches an absence but not a duplication is the case where a green gate is worse
  than no gate.
- The tally is now asserted to occur **exactly once** before its values are compared, and
  the pattern accepts both phrasings in circulation (`34 open rows` and ``34 open `F-` rows``)
  — a duplicate written in the other phrasing is precisely the one a narrow pattern lets
  through, and `main` carries such a pair today.
- New repository-wide ratchet: **no tracked file may contain a conflict marker.** It scans
  `git ls-files`, not `docs/` — the board is where it happened this time; the next one
  lands in a migration or a fixture, where the numbers look plausible and nobody re-reads
  them. Only `<<<<<<< ` and `>>>>>>> ` count as evidence: a bare `=======` is also a legal
  Markdown setext underline, and git never writes it without the other two, so excluding
  it costs no detection and removes the one possible false positive.
- The board's numbers are re-derived from the rows: **34 open `F-` rows, 75 struck, 3 open
  `CB-` rows**, matching the severity table's 37.

### Fixed — re-derivation weighed the same as a person's vote (F-LEARN-03)

- Two paths added exactly `+0.1` to a learning's confidence, carrying very different
  evidence. A **user upvote** is deduplicated per user by the `LearningVote` table — a
  second identical vote is a no-op — and vision §7 makes user feedback the highest
  authority there is. **Re-deriving the same lesson** was deduplicated *not at all*, so
  four `create_learning` calls in one agent run took 0.6 to 1.0, and the number then read
  as certainty earned from one lesson submitted four times.
- Re-derivation now has diminishing returns — the Nth adds `0.1/N` — and a ceiling of
  0.95. **Pumping is impossible by construction rather than by rule.** The first
  re-derivation still moves the number, because an independently re-derived lesson *is*
  evidence; forty of them cannot reach certainty.
- The vote path is deliberately untouched, and a test says so: dampening a person saying
  "this helped" would be the wrong lesson to take from this row. `times_confirmed` keeps
  counting honestly — only the weight changed.
- **Both mechanisms are load-bearing, and a plant proved it.** Raising the ceiling to 1.0
  passed a 40-iteration test, because the harmonic steps need roughly 55 repetitions to
  reach 1.0 unaided. The test now runs to 400 so the ceiling is what is actually left.
- **Two existing tests pinned the flat `+0.1`** and were re-pointed. They asserted the
  increment, which is the thing that made pumping possible — the same shape as the
  freshness test that pinned the word "pull".
### Added — leave a project; bounded member and invite lists (F-PROJ-12, F-PROJ-13)

- **F-PROJ-12** — `DELETE /api/invites/{project_id}/members/me` removes the caller's own
  membership. It is coherent only because F-PROJ-10 shipped first: an owner is **refused**,
  because walking out would leave the workspace with nobody able to manage it — the exact
  stranded state that row was raised about — so the refusal names the transfer route that
  unblocks it. Ownership is read from the member row *or* `Project.owner_id`, since
  checking one would let an owner whose row disagrees with the column slip out.
- The path is `/members/me` rather than `/members/{id}` deliberately: no request can even
  express "remove someone else", so there is no guard that could be forgotten.
- **F-PROJ-13** — both lists were bare `SELECT` by project, with `selectinload(user)` on
  top for members. Invites are the worse case: pending and expired rows are never pruned,
  so that list grows with time rather than with the team. Now bounded (default 500, hard
  maximum 1000).
- **The cap was the easy half.** A page shorter than the total is marked
  `X-Result-Capped: true` with the real number in `X-Total-Count`, and the service logs at
  warning when the cap bites. A capped page returned with no marker is a partial answer
  presented as a whole one. Headers rather than a wrapper object, because the response
  shape is what every existing client is generated against.
- `limit<=0` raises rather than meaning "unlimited" — that reading is how a cap becomes
  decorative — and an absurd limit is clamped, so a caller cannot lift the ceiling by
  asking for more.

### Fixed — a role is a value with a domain (F-PROJ-07, F-PROJ-08, F-PROJ-11)

- **F-PROJ-07 failed *open*, which the row does not say.**
  `ROLE_HIERARCHY.get(min_role, 0)` gave an unknown *required* role a rank of 0 — below
  every real role — so a typo in the required role did not deny access, it granted it to
  everyone including viewers. Measured before changing anything: **143 literal
  `require_role` call sites, all three literals valid** (`viewer` 76, `owner` 46,
  `editor` 21). Latent, and what made it latent was 143 bare strings happening to be
  right with nothing checking them.
- An unknown `min_role` now raises `UnknownRoleError`. The mirror case — a *stored* role
  outside the domain — still fails closed but no longer silently: a member locked out of
  everything by a corrupt row left no trace of why. `VALID_ROLES` and `ASSIGNABLE_ROLES`
  are declared once, and `add_member` checks its argument so the corrupt state cannot be
  created in the first place.
- **F-PROJ-08 — the schema promised a rejection.** The route already answered 400 for
  `owner`, so nothing was reachable; but the schema is what a client generates against.
  `AssignableRole` is declared once and shared with `RoleUpdate`, because ownership has
  one entrance — the transfer route that enforces the receiving owner's plan quota — and
  two schemas offering it independently is how that stops being true.
- **F-PROJ-11 — the losing writer surfaced a 500.** Read-then-insert against the
  `(project_id, user_id)` UNIQUE constraint now rolls back, re-reads, and applies the
  requested role to the winner's row. When the constraint fires and no row appears it
  re-raises: that is not the race, and without the re-raise the code reaches `None.role`
  and blames this function instead of the constraint that fired.
- Two plants were invisible until the tests asked a sharper question. Direct indexing
  into `ROLE_HIERARCHY` already raises `KeyError`, so the explicit check earns its place
  on the **message** — `KeyError: 'Owner'` is loud and useless — and the race branch
  decides **which** error surfaces rather than whether one does.

### Fixed — three DataGate checks that concluded from the wrong thing (F-DG-05, F-DG-06, F-DG-08)

- **F-DG-05 — the bounded-percent interval was tightened on one side only.** `200.0` no
  longer bounds a percentage at all: it is the *warn-only* magnitude threshold for
  **rate** columns, which legitimately exceed 100%. Bounded percents got their own
  hard-fail ceiling of `100.5` — a rounding tolerance — while the floor stayed at `-1.0`,
  so a `conversion_pct` of `-0.9` passed a check whose entire premise is that the column
  is a 0..100 share. A negative share is exactly as impossible as 150%. Now symmetric,
  and a test asserts the **defaults** stay symmetric, because the asymmetry was the
  defect.
- **F-DG-06 — the type-consistency check was wrong in both directions.** It counted
  distinct type *names* and warned above two: `{int, str}` is two and passed — precisely
  the pairing the module's own docstring blames for `"150"` bypassing every value-range
  hard check — while `{int, float, Decimal}` is three and warned, which is what any SQL
  numeric column looks like. A count cannot answer whether types are *related*, so the
  comparison is now by **family**, and a within-family mix is not a mix. `bool` is its own
  family despite being an `int` subclass: a column holding `True` and `3` is not
  consistent, and folding it into numeric is how that goes unnoticed.
- **F-DG-08 — the truncation half was already sound; the cross-stage half was not.**
  `_check_truncation` reads the authoritative `truncated` flag first and treats the
  common-LIMIT heuristic as a labelled fallback. The cartesian check divides one stage's
  `row_count` by its dependency's — and `row_count` is rows **returned**, with `truncated`
  the separate flag saying more existed. Two capped counts give a ratio near 1, so the
  check reported nothing wrong: **a reassuring verdict that was never earned.** It now
  says it could not judge, names which side was capped, and suggests what would make the
  check meaningful. A genuine blow-up on untruncated inputs is still reported.

### Changed — the release scan is proportional to the request (F-GIT-02, F-GIT-03, F-GIT-05)

- **F-GIT-05** was accurate and about *work*, not correctness. `list_releases` resolved
  `tag.commit` for every tag in the repository, built a dict per tag, sorted the lot and
  only then sliced to `max_count` — on a repository that tags each CI build, returning
  100 releases meant thousands of GitPython object resolutions and a full sort, on the
  answer path. Object resolution is the expensive part and is now proportional to the
  request: one `for-each-ref` yields name + date as text, the top `count` are chosen from
  that, and only those are resolved. Reading the ref list stays proportional to the
  repository, inherently — you cannot know which tags are newest without looking at all
  of them.
- Both date forms are asked for (`committerdate` and `*committerdate`) because one is
  always empty: a lightweight tag's ref points at the commit, an annotated tag's at a tag
  object, and a single sort key is undefined for half the tag kinds. **Ordering is
  unchanged** — a test proved the existing commit-date order correct *before* the change,
  which is why the sort key was left alone.
- That test surfaced something else worth keeping: twelve commits made within one second
  have no defined "newest", so the fixture now sets dates a minute apart. An ordering
  assertion over same-second tags tests the tie-break, not the sort.
- **F-GIT-02 does not reproduce.** The inherited risk is `repo_url` transport injection,
  and `RepoAnalyzer.clone_or_pull` validates the URL and branch and pins
  `GIT_ALLOW_PROTOCOL` **itself** — so `_maybe_auto_pull`, which passes both through
  unchecked, inherits the protection rather than having to remember it. That is the shape
  F-GIT-04 lacked, which is why that one was real and this is not. A test now asserts the
  validation lives *inside* the callee, so hoisting it to callers fails instead of
  silently unguarding this path.
- What is real about the flag, and now written where it is defined: it **moves the
  working tree mid-conversation**, so two answers in one session can come from different
  trees and a follow-up can contradict the answer it follows up on.
- **F-GIT-03 was already fixed** by AUD-0819-13, and the handler carries the reasoning:
  `except (TimeoutError, Exception)` read as a narrowing and was not one, since
  `TimeoutError` has been an `Exception` subclass since 3.11. The breadth is deliberate,
  and the pinned invariant is that widening to `BaseException` would start swallowing
  cancellation.

### Fixed — the freshness warnings named the wrong subject (F-GIT-04)

- **F-GIT-04 as written:** W5 built `classify_freshness` (exact AHEAD/BEHIND/DIVERGED
  with counts) and wired it into `KnowledgeFreshnessService`, leaving
  `GitAgent._freshness_warning` on `count_commits_ahead`. One signal, two producers, one
  fixed. The two invisible states matter most there because GitAgent answers from the
  **working tree**: BEHIND means blame and diffs come from a tree the index has already
  moved past; DIVERGED means the two sources can contradict outright. It said nothing.
- All four states now go through the same classifier. Only AHEAD keeps a threshold — a
  clone a commit or two ahead is the normal state of an active repository, and warning on
  it is the noise that trains people to ignore warnings. BEHIND and DIVERGED have none:
  losing history the index still describes is never benign.
- **The worse defect was in the producer W5 did fix.** `classify_freshness` defines
  `ahead` as commits on HEAD the index cannot reach, and `behind` as commits the index has
  that HEAD lacks. The warnings took the knowledge base as their subject without flipping
  the terms:
  - BEHIND read "Knowledge base is N commit(s) BEHIND current HEAD; **pull** before
    trusting answers about recent code." It is the *clone* that lost commits, and a pull
    cannot restore rewritten history.
  - AHEAD promised re-indexing would "capture removed code" when `ahead` means code
    *added*.
  - DIVERGED attributed both counts to the wrong side.
- **A warning that prescribes an action which cannot help is worse than silence** — it
  spends the reader's trust and their time, and the discrepancy is still there afterwards.
- It survived because a test pinned it: `test_behind_emits_pull_warning` asserted
  `"pull" in warning`. Asserting a word is not asserting a meaning. Renamed to
  `test_behind_names_the_clone_as_the_one_missing_commits` and re-pointed, along with two
  other W5 assertions.

### Fixed — a reconnect re-ran the command it had just lost (F-SSH-07)

- `_run_command` caught a lost SSH connection, reconnected, and re-sent the **same**
  command. `asyncssh.ConnectionLost` cannot say whether the command reached the server
  first, so an unconditional retry can apply an `UPDATE` twice — and this path serves
  note execution, batch `/execute` and the agent's `execute_query`, on connections that
  are not always read-only.
- The retry decision is not the connector's to guess. `idempotent` is now a keyword
  argument defaulting to **False**; a command nobody declared repeatable surfaces an
  honest "it may already have run on the server, it was NOT re-sent" instead of being
  applied again on a hunch.
- **The query path computes the answer rather than asserting it.** A read-only
  *connection* makes anything repeatable, because the DB session itself refuses writes;
  otherwise the statement must classify as read-only. That classification reuses
  `SafetyGuard` through a new `core/safety.is_read_only_statement` — comment stripping,
  the multi-statement refusal and the leading-keyword allow-list are already there, and a
  second definition of "read-only" is the kind that drifts from the first. So
  `/* SELECT */ DELETE FROM t` and `SELECT 1; DROP TABLE t` are both refused a retry.
- The other twelve call sites — introspection for all four engines, plus the connection
  and SSH probes — declare `idempotent=True` with a reason, and an AST test holds them
  to it.
- **My tests were wrong first**, and instructively: they counted `run` calls, but the
  reconnect path sends a liveness probe of its own, so the count answered a different
  question. They now record every send by text and assert the *original command* was not
  sent twice.

### Fixed — per-key lock lifecycle on the SSH seam (F-SSH-05, F-SSH-09)

- **F-SSH-09 was accurate.** `close_for_config`, `cleanup_idle` and `close_all` each
  popped `_tunnels` and `_refs` and none touched `_locks` — one `asyncio.Lock` per
  distinct cache key, forever. The key carries a credential discriminator, so rotating a
  password mints a new key and a new lock, and deleting a connection leaves its lock.
- **The obvious fix is a trap.** Popping a *held* lock is worse than the leak: the next
  caller builds a fresh one and two coroutines end up inside the critical section
  together. `_release_lock` checks `locked()` and pops in the same synchronous step —
  nothing interleaves on one event loop, and an `asyncio.Lock` queues waiters only while
  held, so `not locked()` means nobody is queued. A held lock is skipped and
  `cleanup_idle` sweeps what was skipped; best-effort without a later sweep would leave
  the leak in exactly the cases that cause it.
- `_MEMORY_PINS` is deliberately **not** treated as the same bug: a pin is meant to last
  the process lifetime, which is the point of a memory pin.
- **F-SSH-05 does not reproduce.** `_connect_with_memory_pin` runs read-key → compare →
  pin with zero `await`s, and `_host_key_blob` is a plain `def`, so two concurrent
  first-connects cannot both see "unpinned". The evidence is that both concurrency tests
  written to fail **passed against unmodified code**. A lock would be complexity for a
  race that cannot happen; an AST test now asserts no `await` appears between reading the
  pin and writing it. Planting `await asyncio.sleep(0)` there fails two tests — the guard
  and the race test — which shows the described mechanism is real and merely absent.

### Security — the SSH pre-command hatch was five switches in one (F-SSH-03, F-SSH-04)

- **F-SSH-03.** `SSH_PRE_COMMAND_ALLOWLIST_ENABLED=false` returned the input untouched,
  disabling five protections at once: the 20-command cap, the 512-character limit, the
  non-empty-string check, the shell-metacharacter screen and the command-shape allowlist.
  Only the last is allowlist *policy*. The flag is documented as an emergency hatch for
  an unusual bastion command — and an unusual *shape* is a different request from command
  substitution. The hatch now relaxes exactly one check; `;`, `|`, backticks, `$(`,
  newlines and both caps hold either way.
- Opening it logs **once per process**. On every call it would be the noise that teaches
  people to ignore warnings; never, and a disabled screen stays invisible for as long as
  the setting survives.
- Rating kept at Low deliberately: the flag defaults to `True` and nothing sets it, so
  this was a foot-gun rather than a live hole. But a hatch that silently opens the
  injection surface is one nobody can safely use, which made the documented escape route
  unusable in practice.
- **F-SSH-04** is accurate about the code and was **not exploitable**, and both halves
  are worth stating. `db_port` was the one placeholder excluded from `format_template`'s
  escape list, and it had no path in: the request schema bounds it to 1..65535, the column
  is `Integer`, and both `ConnectionConfig` construction sites build from the model.
  Fixed by escaping **every** value rather than adding one more name to the list — an
  allowlist of *which values are dangerous* goes stale the moment a template gains a
  placeholder, and `shlex.quote` of digits returns the digits.

### Security — the BM25 snapshot is no longer a pickle (F-KNOW-06)

- **The row named its own ordering — "swap to safe format *before* F-KNOW-07" — and I
  broke it.** F-KNOW-07 and F-KNOW-12 both shipped first, and F-KNOW-12 *widened* the
  exposure in between: the start-up reconcile it added reads a snapshot in both the web
  and the worker process, on every boot.
- `pickle.load` executes whatever its payload says. The stored form is now data, not
  opcodes: the **tokenized corpus** is persisted as gzip JSON (`{id}.json.gz`) and
  `BM25Okapi` is reconstructed on load, so nothing on disk is a class instance — and the
  file is inspectable with `zcat`.
- **`pickle` is not imported by the module at all**, asserted on the import graph.
  *Unused* is not *absent*: a module that still imports it invites the next person to
  reach for it, and a grep for the primitive keeps finding a hit.
- **A leftover `.pkl` is never read** — not once, not to migrate. Reading it "just for
  the upgrade" keeps the primitive alive for exactly the window that matters. It is
  deleted on build and on delete, and the F-KNOW-12 reconcile rebuilds the snapshot from
  Postgres for free — which is what makes the schema-version bump safe.
- **Cleaning up after the bump:** it also invalidates the per-connection *schema*
  snapshots, which the DB-index pipeline builds rather than the repo index. Leaving those
  to rot until someone re-indexes a database would be a gap this change introduced, so
  `bm25_local_reconcile` gained a schema pass under its own `schema_retrieval_enabled`
  flag.
- Twelve stale `.pkl` references in code comments, `CLAUDE.md` and `docs/ROLLOUT_M1_M6.md`
  corrected in the same change.

### Fixed — the BM25 snapshot was written on one dyno and read on another (F-KNOW-12)

- **The row I wrote said "dense-only after every restart". The measurement is sharper.**
  `Procfile` declares `web` and `worker` as separate Heroku process types, so they have
  separate ephemeral filesystems, and `bm25_data_dir` is a local path with no shared
  volume. The repo index **writes** the `.pkl` in the worker; every reader on the chat
  path runs in the web dyno. The file was written on one machine and read on another, so
  the BM25 leg had **no snapshot to read at all** — while `hybrid_retrieval_enabled` read
  as on the whole time.
- **Shared storage was the wrong fix.** The snapshot is derived data: it is built from
  `KnowledgeDoc` rows in Postgres, with no clone, no network and no LLM. Each process now
  rebuilds what it is about to read — `app/ops/bm25_local_reconcile.py`, wired into the
  web lifespan (off the boot path, so tokenizing does not delay accepting requests) and
  the ARQ worker's `on_startup`.
- **Deliberately not advisory-locked**, unlike the other two reconciles beside it. They
  coordinate a single shared outcome in the database; this produces a file on *each*
  process's own disk, so a lock would let one dyno satisfy the check while the other still
  reads nothing.
- **Only missing snapshots are rebuilt, never stale ones.** At boot there is no clone, so
  the true head SHA is unknowable; stamping the last *indexed* commit and presenting it as
  current is a claim this process cannot support. Staleness stays with
  `_repair_bm25_if_stale`, which has a clone.
- A project with no docs is skipped rather than given an empty snapshot — that would turn
  `no_snapshot` (a real gap, reported since F-KNOW-07) into a silent `no_match`. The guard
  is asserted where it lives, because the caller's own filter makes the branch unreachable
  and a plant removing it left every behavioural test green.
- Confirming measurement in production: `retrieval_degraded_total{leg="bm25",reason="no_snapshot"}`
  should fall to zero after a boot.

### Added — encryption key rotation (F-CONN-05)

- **There was one key and no way off it.** Swapping `MASTER_ENCRYPTION_KEY` made every
  stored credential permanently unreadable, so the only path was a hand-written
  re-encryption script — which meant the key was never rotated. `MASTER_ENCRYPTION_KEY`
  is now the only key that **writes**; `MASTER_ENCRYPTION_KEYS_OLD` is a comma-separated
  list of retired keys kept for **reading**. Rotation is two config values and a deploy,
  with nothing unreadable at any point.
- Two variables rather than one ordered list, on purpose: the primary is the one thing
  that must never be ambiguous, and a stray comma in a single list would silently change
  which key writes. **A malformed retired key raises at first use** — a silently-skipped
  entry is how a rotation appears to succeed while leaving rows nobody can read.
- **Retirement is made reachable, and countable.** `app.ops.encryption_reconcile` detects
  the primary key's fingerprint changing at boot and sweeps every stored secret onto it —
  advisory-locked, idempotent, never blocks boot, mirroring `embedding_reconcile`. The
  marker advances **only on a clean sweep**: a row readable by no configured key leaves
  the status `partial`, names the row, and tells the operator to keep the old key.
  `pending_rotation_count` is the retirement gate; zero is the green light.
- The deploy marker is a SHA-256 prefix of the key, never the key — it is written to the
  database and appears in logs.
- **The column set is derived, not remembered.** A test compares the sweep's map against
  every mapped column whose name ends in `_encrypted`, and it immediately found a seventh
  that an AST sweep over `encrypt(` calls could not see, because nothing writes it:
  `ProjectRepository.auth_token_encrypted` (now swept anyway, and tracked as F-REPO-04).
- Runbook: `SECURITY.md` → *Rotating the encryption key*, including the table of boot-log
  outcomes and the one irreversible mistake available (clearing the retired key on a
  `partial`).

### Added — transfer project ownership (F-PROJ-10)

- **The owner was permanent.** `update_member_role` refuses to touch an owner and the
  role route's schema accepts only `editor`/`viewer`, so no request could appoint a
  successor or resign — an owner leaving took the workspace with them and there was no
  in-product fix. New `POST /api/invites/{project_id}/transfer-ownership` and a "Make
  owner" row action visible only to the owner.
- **Both records move together.** Ownership is readable from `Project.owner_id` *and*
  from a member row, so changing one leaves two owners. The plant that moved only the
  column was invisible to every role assertion — `get_role` falls back to the column —
  and what actually breaks is the members list, which would print the project's owner as
  a viewer. That is the assertion the test now makes.
- **The receiving owner's plan quota is enforced**, before any write. Quotas count
  projects by `owner_id`, so a transfer that skips the check is a plan-limit bypass
  wearing a feature's name.
- **The target must already be a member** (transfer is not a covert access grant), and
  the old owner is **demoted to editor, not removed** — losing access is a different
  decision from losing ownership, and only the second was asked for.
- **The stranded case is what the finding is really about.** `owner_id` is
  `ondelete="SET NULL"`, so a deleted account leaves a project with no owner and no
  member who may appoint one. The route therefore does **not** gate on
  `require_role(..., "owner")`: that check would 403 everyone on exactly the project the
  feature exists to rescue. An admin can transfer it; a member claiming it for themselves
  gets 403, because self-appointment is the escalation that guard is for.
- The confirm names the demotion and that it cannot be undone by the actor. A confirm
  that omits the consequence asks someone to agree to something they were not told.

### Fixed — a run nobody could tell was stuck (F-SCHED-03)

- **The race the row named does not reproduce; the hole is its mirror image.**
  `_stale_run`'s NULL-heartbeat branch demands `started_at < cutoff`, and `heartbeat()`
  writes a beat before its first interval, so a just-started run is never reaped early —
  two tests written for this assertion were green against the unmodified code. What no
  branch matched was a `running` row with **neither** reference. `IndexingRun.started_at`
  is nullable, so such a row lived forever: the spinning-UI failure the reaper exists to
  end.
- "Age unknown" is now stale. Reaping is the safe direction, because `REAP_ERROR` lets
  `RunCoordinator` reconcile a run that turns out to still be alive — whereas nothing ever
  reconciles a row nobody can see is stuck. The state is unreachable through today's code
  (`run_coordinator.py:189` sets both columns), which is exactly why nothing else would
  ever report that it had stopped being unreachable.
- **Reaping it silently would swap one invisible state for another** — a run flipped to
  `failed` with no account of why. The count is taken before the update and logged at
  warning naming the invariant that broke, and deliberately **not** on an ordinary timeout
  reap, which keeps its own info line.
- `_stale` gets no equivalent branch on purpose: `updated_at` is NOT NULL on all three
  models it serves, so it would be defensive code no test could reach.
- Checked and **not** the defect: a long stage starving the heartbeat. `code_symbol_embed`
  runs 23+ minutes in production, but it goes through `asyncio.to_thread`, so the beacon
  task keeps getting scheduled.

### Fixed — one request, one wall clock (F-SQL-03)

- **Two of this finding's three multiplications were already closed; the third was
  invisible to both fixes.** `sql_agent_deadline_enabled` (2026-08-08) bounded the SQL
  tool loop and Path A threads the remaining wall clock down; ORCH-V02 bounded the
  per-stage × validation × data-gate retries inside `StageExecutor` and checks the
  deadline inside every retry loop. But `StageExecutor.execute` computed
  `deadline = monotonic() + budget` **on entry**, and `_run_pipeline_replans` re-enters it
  once per replan — so Path B's worst case was `(1 + max_pipeline_replans)` times the
  budget: **540 s against a documented 180 s limit**, plus a planner LLM call before each
  replan and the final synthesis, all outside any of it. ORCH-V02 had bounded the retries
  *inside* one plan and left the plan count multiplying that bound.
- `_new_pipeline_deadline()` establishes it once per request. It is passed to all three
  `executor.execute()` entries and into the replan loop, which refuses to start another
  plan once it is spent — the check sits **before** the replan, because a replan is an LLM
  call plus a whole fresh execution, the most expensive thing that loop can do.
  `execute()` still computes a budget when handed none, so the eval harness and
  standalone callers are unaffected.
- **Two of six plants walked past every behavioural test.** They enter at the replan loop,
  so dropping the deadline at the *initial* executor entry was invisible to all of them.
  Caught by AST tests that ask the wiring question directly: within one method, the initial
  `executor.execute` and the `_run_pipeline_replans` that follows must be handed the same
  deadline name, and no `executor.execute` may omit it.
- A test that **hung** under one plant was rewritten. Its stub never recorded a stage
  result, so whenever the deadline check did not fire the stage loop spun forever — and a
  test that hangs under a defect reports a CI timeout, which is indistinguishable from an
  infra flake. The stub now records a result the way the real collaborator does, so the
  same plant produces a clean assertion failure.

### Fixed — the degradation metric fired on the healthy path (F-KNOW-07)

- **`retrieval_degraded_total` existed since W0, and that was the problem.** `BM25Index.query`
  returned `[]` for five distinct causes and `_run_bm25` added two more; the caller labelled
  every one of them `reason="empty_result"`. One of those causes is healthy — a working index
  whose query had no lexical overlap — so the counter fired on the normal path and a non-zero
  value proved nothing in either direction. Nobody could tell from production whether the BM25
  snapshot had survived the last restart, which is the fact the row was raised about.
- `query_with_reason` / `load_with_reason` now carry the cause: `no_snapshot`, `corrupt`,
  `schema_mismatch`, `no_query_tokens`, `no_match`, `score_error`, plus `timeout` / `error` from
  the leg runner. **`no_match` and `no_query_tokens` are not counted at all** — the index worked.
  `query()` keeps its list-only contract, so no other caller changed.
- **The same class backs `schema_{connection_id}.pkl`**, and that miss was a `logger.debug` —
  invisible in production, while `schema_retrieval_enabled` still read as on. Now counted as
  `leg="schema"` and logged at info, with **no** reader-facing line: that path has a working
  relevance safety net, and a warning on every query after a restart is the noise that teaches
  people to ignore warnings.
- **The reader's sentence follows the cause.** "Returned nothing for this question", said of a
  missing index, sends someone to rewrite a question that was never the problem while half the
  search was never consulted. A missing/corrupt/stale index now reads "keyword search is
  unavailable for this project … re-indexing the repository restores it"; a timeout reads "did
  not respond in time".
- The dense leg has no cause channel — a missing collection and a genuine no-match both surface
  as `[]` — so its label is `empty_cause_unknown` rather than borrowing precision it does not
  have (tracked as F-KNOW-11).
- **Shared storage is not done and is not claimed.** BM25 snapshots still live on the dyno's
  ephemeral disk; hybrid retrieval really is dense-only after every restart until a reindex. This
  change makes that loss *measurable*, which was the row's own prescribed first step (F-KNOW-12).

### Fixed — dashboard card freshness (F-VIZ-01)

- **A dashboard card said how old its data was; it could not say whether that was a
  fault.** The finding read "no freshness signal", and a signal existed
  (`frontend/src/app/dashboard/[id]/page.tsx:320`). Four things it could not express are
  now expressed: the age is labelled ("Data from 3d ago" / "Never run") because the page
  header already prints "Updated …" about the dashboard itself; a card that declared a
  `refresh_interval` and exceeds twice it says the schedule is not being kept, while a
  card that declared none carries no marker (age alone cannot tell a stale number from a
  broken promise); past-due interval cards run once on open instead of waiting a full
  period, since `setInterval` fires first only after one and the load path merely read
  stored snapshots; and a failed refresh lands on the card rather than in
  `catch { /* */ }`. All three refresh paths — open, tick, Refresh All — share one
  function. Cards with no declared interval are still never executed by opening the page.
- **The board's own evidence checker truncated `.tsx` to `.ts`** — a lazy quantifier with
  `ts` ahead of `tsx` in the alternation. It surfaced as a missing file here; with a
  `page.ts` beside the `page.tsx` it would have passed while verifying the wrong file.
  Alternation is longest-first and followed by a `(?!\w)` guard, with a test on the
  extractor itself.

### Fixed — a failed email returned 200 and said nothing (2026-08-21)

F-PROJ-06 was recorded as *"commit-then-await-email → partial-success 500s"*. Measured, the
opposite happens. `EmailService._send` caught everything, called `logger.exception` and
returned `None`, so a failed send never reached the route: it answered **200 with an
invitation the recipient will never hear about**. Retrying then returned 409 *"Invite already
pending"*, which reads as *already done* and confirms the sender's wrong belief.

A 200 hiding a failure, not a 500 hiding a success — and `vision.md` §7 either way.

One mechanism, a decision per call site, because the consequences differ:

- `_send` and all six senders return `bool`. Still no raise: the row is already committed,
  and turning a notification failure into a 500 would say the whole operation failed.
- **Invite create and resend report `email_sent`.** Resending is what somebody does
  *because* they suspect the first never arrived, so `{"ok": True}` from a resend that did
  not send is the worse of the two lies.
- **Registration reports `verification_email_sent`.** Without that mail the account cannot
  verify and the user waits for a link that will never arrive.
- **The duplicate 409 now names the resend route** instead of reading as *done*.
- **`forgot_password` deliberately stays silent.** It answers a uniform `{"ok": True}` so the
  response cannot be used to probe which addresses exist, and a field that appears only when
  a reset was actually issued rebuilds that oracle. The reason is written at the call site so
  the next reader does not "fix" the silence.

`None` and `False` are kept distinct throughout: *not attempted on this response* is not the
same claim as *we tried and it did not go*.

Five planted defects, and **four walked past the first version of the tests** — asserting that
a response field *exists* says nothing about whether the route populates it. The replacements
drive the route with a real minimal `Request` (it carries `@limiter.limit`, and faking that
would mean patching machinery the test has no business touching) and check the registration
hand-off as a **call argument in the AST**, because a name appearing somewhere in a function
says nothing about where it goes.


### Security — a plan change through the Customer Portal did not change the plan (2026-08-21)

`_resolve_plan_id` read `metadata.plan_id` off the Stripe subscription and returned it
immediately, consulting the price only when metadata was absent.

Stripe's `metadata` is written once, when our Checkout session creates the subscription, and
**does not change when the price on that subscription changes**. So a customer moving plans
through the Customer Portal kept the plan they originally bought (F-BILL-01):

- **downgrade Team → Pro** — they pay Pro and keep Team's limits;
- **upgrade Pro → Team** — they pay Team and keep Pro's.

Both directions are wrong and both are money.

The price is what Stripe actually charges, so the price is now the authority. Metadata is
consulted for exactly one situation — the price is real and no catalog row matches it, which
means the catalog is behind Stripe. Falling back there beats returning `None`, because the
caller leaves `sub.plan_id` untouched on `None` and a paying customer would silently keep
whatever they had. That fallback logs at warning naming both the price and the metadata plan,
since a stale catalog otherwise surfaces only as somebody's wrong entitlement.


### Fixed — the result label said "Total rows" and the number was rows returned (2026-08-21)

`QueryResult.row_count` is set by every connector to `len(data)` **after** the row cap and
the byte cap. It means rows *returned*. The formatter the model reads said `Total rows: N`,
so a query matching fifty thousand rows against a thousand-row cap produced
`Total rows: 1000` (F-SQL-02).

Where truncation was detected, the banner above it already said "capped at 1000 rows (the
database has more)" — a prompt contradicting itself, with the mislabelled line reading like
the fact. **The two consumers already disagreed**, and that is what located it:
`answer_validator.py` wrote "rows returned" while the formatter wrote "Total rows".

An agent told it has the total states a total, and the user cannot see that it counted a
page. `vision.md` §7, not wording.

The line now reads `Rows returned: N`, with a partial marker when the result was truncated,
so the count and the banner agree.

**Three producers wrote that claim, not one.** An AST sweep ran before the finding was
closed — because fixing the site you found and asserting completeness is a mistake this
audit had already made twice — and turned up `viz_agent._summarize_results`, which is what
the chart layer reasons over, and `tool_dispatcher`'s enrichment summary, where a model may
compute a share from the number. A caption carrying a total it does not have is a wrong
number in a picture, and nobody re-checks a picture. Also closed: F-KNOW-08's board
row, which had stayed open for two iterations after the clone cleanup shipped in #194.

### Added — the board's own citations have to resolve (2026-08-21)

`docs/qa-audit/issues.md` records what was found and what was done, and nothing checked that
its evidence existed. Two kinds of drift, both real:

- **F-KNOW-08 was left open after the work shipped**, noticed by accident while reading the
  list for something else.
- **F-EXP-01 cited `tests/unit/test_demo_seed.py`** — a file renamed in the same iteration
  that wrote the citation. The row read as verified and pointed at nothing.

`test_board_evidence_resolves.py` asserts every cited path exists, that the stated tally
equals the rows it summarises, and that there are closed rows to check at all — a regex
matching nothing passes everything downstream by vacuity and looks green doing it.


### Fixed — the rules budget existed at two call sites of five, and CLAUDE.md said otherwise (2026-08-21)

Rule text goes straight into an LLM prompt, and nothing in the code bounds its size: files
an operator drops in `rules/` plus rows a user adds through `manage_custom_rules`.
CLAUDE.md described this as injected "with budget-aware truncation". Measured, that held at
two of five callers:

| site | cap |
|---|---|
| `orchestrator.py:605` | 2000 chars |
| `sql_agent.py:1991` | 3000 chars |
| `sql_agent.py:710` — the `get_custom_rules` tool | none |
| `sql_agent.py:1974` — repair | none |
| `code_db_sync_pipeline.py:509` | none |

Both existing caps sliced the joined string, cutting the last rule mid-sentence and
reporting `"... (truncated)"` — which tells the model something was removed and not what,
so it cannot tell the user its answer may ignore rules they wrote (`vision.md` §7).

The budget now lives in `rules_to_context` (`RULES_CONTEXT_MAX_CHARS`, default 3000):

- **Whole rules are dropped, never half of one.** A truncated instruction is one the model
  may still follow.
- **The notice carries a count** — "N of M rules omitted" — so the degradation is
  reportable rather than merely present.
- **A single rule larger than the whole budget is cut and named**, pointing at the setting
  to raise. Of the three bad options for that case — keep it whole and blow the prompt,
  drop it silently and lose the user's business logic, or cut it — only the third can be
  reported. It was found by a pre-existing test, not by the new ones.

CLAUDE.md's sentence is corrected in place rather than quietly brought into line, because
the way it was wrong is the useful part.


### Security — two concurrent creates both passed the same quota check (2026-08-21)

`enforce_connection_quota` ran `SELECT COUNT(…)`, compared, and returned; the insert
happened afterwards in the route. Two concurrent requests both counted `N-1`, both passed,
and both inserted — a plan allowing one connection ended up with two (F-BILL-02). Creation
is rate-limited to 10/minute, which bounds how far it goes and does not stop it.

A row lock on the owner (`SELECT … FOR UPDATE` on `users`), taken **before** the count,
serialises quota decisions for that user and leaves different users uncontended. No counter
is introduced that could drift out of step with the rows it counts.

**Honest about scope.** `FOR UPDATE` is a Postgres guarantee; SQLite's driver accepts the
clause and ignores it. Production is Postgres, and SQLite dev is a single-writer database
where the interleaving this race needs cannot happen — so the guard is real where the race
is real and inert where it cannot occur. The tests assert the lock is *requested*, because
asserting that it *serialises* is something SQLite cannot be made to demonstrate.

- A lock failure logs at warning and lets the check proceed. Refusing the write would trade
  a rare over-count for a hard outage.
- An unlimited plan returns before the lock: serialising a decision already made is
  contention bought for nothing.
- `_db_returning` in the billing tests keyed on call order and broke the moment a query was
  added ahead of the count, failing with `StopAsyncIteration` — which says nothing about
  quotas. It now answers the lock and leaves the ordered sequence for the lookups that
  genuinely rely on it.


### Fixed — a done-callback is not a lifetime, and my own previous fix missed half its sites (2026-08-21)

**F-PROJ-05.** The named route already used `spawn_tracked`, so the *silent* half was
closed before the row was read. The retention half was open in three places the row does
not mention — `batch.py`, `data_investigations.py`, `chat_feedback.py` — each assigning a
task to a local, attaching a done-callback and returning. asyncio keeps only a **weak**
reference, so the handler returning is what makes the task collectable mid-flight; `chat.py`
documents the same hazard in its own words. All three use `spawn_tracked` now.

**F-SCHED-04, again.** That fix declared `allow_in_process=False` at three heavy `enqueue`
sites and its test asserted exactly those three by name. An AST sweep found three more:
manual sync-now, a repo-index retry, and the daily-sync cron loop — which runs **inside the
web dyno**, so a broken Redis put the entire daily sync in the process serving requests.

> A test written from the list of things you changed cannot tell you what you missed.

Both checks are now sweeps derived from the code rather than enumerations:

- Every `enqueue` of a heavy task must pass the guard — plus an assertion that the sweep
  finds call sites at all, because a sweep matching nothing passes everything downstream by
  vacuity and looks green doing it.
- No route may assign a task, attach a callback and return. Asked as an AST question —
  *is the name used for anything besides `add_done_callback` inside its function?* — after a
  25-line text window produced two false positives on tasks that are awaited and cancelled
  further down.

`main.py`'s `coro_factory` still runs where no Redis exists; the guard only applies when
Redis is configured and the enqueue throws, and the comment says so at the call site.


### Fixed — a malformed `cards_json` rendered a shared dashboard as empty (2026-08-21)

F-VIZ-02 was filed as a stored-XSS vector and correctly downgraded — React escapes its
children, so nothing executes. The residual was quieter than "unvalidated storage" sounds.

`parseCards` is `try { JSON.parse(json) } catch { return [] }`, so a malformed string — or
valid JSON of the wrong shape — renders as an **empty dashboard**. Dashboards are shared by
default, so one bad write shows everyone else a page with nothing on it and no sign that
anything is wrong.

`cards_json` is now validated at the write boundary against the contract the consumer
declares (`frontend/src/lib/api/types.ts:502`): a JSON array of objects, `note_id` a
non-empty string, `viz_config` an optional object, `refresh_interval` an optional number,
and at most 200 cards.

- **The card cap bounds work, not bytes.** The viewer issues one note fetch per card, and
  the existing 500 KB payload cap allows roughly thirty thousand `{"note_id":"x"}` entries.
- **`viz_config`'s interior is deliberately not inspected.** The viewer treats it as opaque
  and hands it to the chart layer; validating it here would invent a contract nobody wrote.
- **Create and PATCH share one `_DashboardCardRules` base**, so the rule cannot be added to
  one and forgotten on the other.
- **Writes only.** A row stored before this change reads exactly as it did: making a legacy
  row fail to *load* would turn a cosmetic problem into an outage.


### Fixed — a session could expire and leave the app holding the profile (2026-08-21)

`handleSessionExpired` fired `void import("@/stores/auth-store").then(({ useAuthStore }) =>
useAuthStore.getState().logout())` and set `window.location.href = "/login"` on the **next
synchronous line**. The browser begins unloading the document immediately, so the `.then`
may never run — and the only part of `logout()` that outlives a navigation is
`storage.removeItem("auth_user")`, the profile kept for instant UI paint.

So a session expires, the user lands on `/login`, and the app still holds their profile
against a cookie the server has already rejected. Whether they see it depended on a race
nobody chose (F-AUTH-16).

The teardown is synchronous now and the dynamic import is gone. The in-memory store dies
with the document either way, so importing it to mutate memory before leaving was work that
could only fail to happen; what has to happen before the redirect is clearing the persisted
copy. Each `removeItem` is individually guarded, because Safari private browsing can throw
on storage access and a session that cannot be cleared must still redirect rather than trap
somebody on a page that no longer works.

**Found through a CI failure that reported every test passing.** The floating import landed
after vitest tore the environment down:
`EnvironmentTeardownError: Cannot load '/src/lib/api/index.ts' … after the environment was
torn down` — 683 tests green, runner exiting 1. The test file had already grown an
`afterEach` waiting one macrotask to paper over it, which is enough on a laptop and not on
a CI runner. That workaround is removed rather than left in place: it was the visible half
of a real bug, and keeping it would hide the regression if the floating import came back.
Frontend suite is 688 passed, exit 0.


### Changed — the silent-degradation ratchet now measures silence, not breadth (2026-08-20)

`test_broad_handlers_returning_a_degraded_value_do_not_grow` counted every broad `except`
returning a literal. It was raised four times in one day, and every justification was the
same: *this one logs at `error` with a traceback*. Measured at the fourth: of 81 such
handlers, **37 log at warning or above and 44 do not**.

The ratchet was flagging code that complies with its own failure message. It now counts
only handlers that degrade **without** announcing it — baseline 44, and lower is better.

That is stricter per instance, not looser: the old rule forbade a shape 37 compliant
handlers shared, and the new one forbids exactly the shape behind the 2026-08-09 incident,
where a `TypeError` became `""` under a `debug` log. Planting a silent handler goes red;
planting the same handler with an `error` line stays green — the old version could not tell
those apart, which is why it had stopped measuring anything.

### Fixed — an ARQ enqueue failure ran the repo index inside the web dyno (2026-08-20)

`enqueue()` had two situations and one warning for both. With no `REDIS_URL`, the
in-process `asyncio.create_task` path **is** the intended mode — that is how dev runs.
With Redis configured, an `enqueue_job` that throws means something is wrong with Redis,
and the code logged a warning and ran the job here anyway (F-SCHED-04).

For `run_repo_index` that is the pipeline measured at ~1 GB peak, executing inside the
dyno that serves user requests. It either OOMs the API or badly degrades latency, and the
only trace is one line at a level nothing alerts on.

- **No Redis** → in-process, `INFO`, unchanged.
- **Redis configured and failing** → `ERROR`, naming the task, because a warning is where
  a broken Redis goes to die.
- **`allow_in_process=False`** lets a call site say that running here is not a substitute.
  It returns `None`, so the caller surfaces a retryable failure instead of a gigabyte
  quietly relocating into the web process. Declared at `run_repo_index`, `run_db_index`
  and `run_code_db_sync` — all three already gate on `is_arq_active()`, so they reach the
  fallback only on this exact fault.

The fallback itself is kept. For light work a Redis blip should not lose the job, and
removing it would trade a rare incident for a common one.

### Fixed — demo connections created before the fix pointed at `:memory:` (2026-08-20)

Found by the post-deploy check for the demo work, not by a test. Production held one
connection with `db_type='sqlite'` and `db_name=':memory:'`, created 2026-06-05:

```
 db_type | db_name  | n |   first    |    last
---------+----------+---+------------+------------
 sqlite  | :memory: | 1 | 2026-06-05 | 2026-06-05
```

Before the demo work it failed with `Unsupported adapter: sqlite`; after it, the new
connector **refuses** `:memory:` at connect — a better error for the same empty screen. So
F-EXP-01's promise held for connections created after the fix and not for the ones created
before it, which is the half of a fix a test suite cannot see (F-EXP-06).

Migration `d3e4f5a6b7c8` rewrites `db_name` to `./data/demo/demo_<owner>.db` and flips
`is_read_only`. Nothing else is needed: once the path is inside `DEMO_DB_DIR`, the
already-shipped `repair_demo_db_if_missing` in `ConnectionService.to_config` seeds the file
on the next config build — self-completing, no operator step and no user action, the same
shape as the embedding reconcile.

`downgrade` restores the path and deliberately does **not** hand back write access:
reverting a path rewrite is not a reason to change a privilege, and the asymmetry is the
safe direction. Verified up and down on a fresh database with two control rows — a
postgres connection and a mysql one named `:memory:`, the second because the first did not
earn the migration's `db_type == "sqlite"` clause.


### Security — a failed provider silently sent the request to a different vendor (2026-08-20)

`LLMRouter` walks a fallback chain, and the messages it retries with are the user's
question, their database schema and their query results. When the chosen provider failed,
that content went to the next vendor with nothing saying where — the existing log line
reports that a provider *failed*, not where the request was sent next — and no deployment
could make its choice binding (F-LLM-01).

That is a data-processing question, not only a reliability one: a deployment that chose
one vendor because that is who its customers were told about had no mechanism to hold the
line and no record afterwards that it was crossed.

- **Crossing a provider boundary now logs at WARNING**, naming the vendor that failed, the
  vendor that received the request, and what was in it. On **both** fallback loops — the
  streaming path walks its own copy and would otherwise have kept the old behaviour, which
  is how one of two loops keeps an old rule.
- **`LLM_ALLOW_PROVIDER_FALLBACK=false` makes the choice binding.** A refusal ends the
  chain, so the caller still raises `LLMAllProvidersFailedError` carrying the real outage —
  the reason the request could not be served is the provider being down, not the setting,
  and the setting's own line sits beside it in the log.
- **The default stays on.** Turning fallback off for everyone would trade every
  deployment's resilience for a guarantee most never asked for — the same argument as the
  connection-host guard, and the same conclusion: a control that breaks the normal case
  gets switched off, and then it protects nobody. The disclosure is not opt-in.
### Fixed — `accept_invite` runs in one transaction, and the finding it closes was wrong (2026-08-20)

F-PROJ-03 read *"commits inside `begin_nested()` → 500 on idempotent re-accept."* Measured
on SQLAlchemy 2.0.51 before anything was changed: **it does not 500.**
`test_does_not_duplicate_if_already_member` has always passed, and a direct reproduction
raised nothing and persisted the row — a `commit()` inside an open SAVEPOINT deactivates
the savepoint transaction, which then exits quietly. That bookkeeping lives in
`SessionTransaction`, shared across dialects, so Postgres does not differ.

The smell was real even though the symptom was not:

- **The savepoint bought nothing.** The early return committed inside it and the normal
  path committed after it, so no rollback path existed for it to provide. A savepoint that
  never rolls back reads as a guarantee and is decoration.
- **It worked by accident of the library version.** A SQLAlchemy that tightens
  commit-inside-savepoint would have produced exactly the 500 the board already believed
  in.

Now one transaction, committed once, with the `IntegrityError` retry that was always the
real concurrency guard. Four tests pin the behaviour the block is meant to have — accepting
twice settles the same way, an existing member is not silently upgraded, an expired invite
leaves no membership and stays `pending` — because removing a transaction boundary is the
kind of change whose damage shows up somewhere else.

### Fixed — the WebSocket relay stopped giving up on quiet, and stopped a session per connect (2026-08-20)

Both on `/api/chat/ws/{project}/{connection}`, documented public API (`API.md:206`) that
the product's own UI does not use — it speaks SSE. Both were filed with a user-facing
impact this code cannot produce (a tab reload opens no WebSocket; the reasoning panel is
fed by SSE); the findings survive for third-party clients with the severity re-argued.

**F-CHAT-03.** The relay was `asyncio.wait_for(queue.get(), timeout=60)` with
`except TimeoutError: logger.debug(...)`, so sixty seconds of quiet ended the event stream
while the run continued — the client got nothing more and no reason, and the line saying
so was at debug, invisible at production level. An unnamed number, five times tighter than
the `ws_idle_timeout_seconds` beside it.

A gap in events is not the end of a run, and the SSE relay in the same file has always
known that. The WS relay now has its shape: poll on `ws_event_relay_poll_seconds` (0.5),
continue on a gap, and stop at `ws_event_relay_timeout_seconds` (900) if a run never
reaches `pipeline_end`. Extracted to `relay_workflow_events` so both halves — *survives a
quiet period* and *still ends at the deadline* — are testable without a WebSocket
handshake; neither was reachable through the endpoint in a unit test.

**F-CHAT-02.** Every connect wrote a session row, before the receive loop and
unconditionally, so a client that connects and sends nothing leaves one behind — and they
reach the session list a user reads, not only the table. Lazy creation is ruled out by the
protocol: `session_created` is sent immediately after the connect, so the client is
promised an id before any message exists.

`ChatService.get_or_create_empty_session` reuses this `(project, connection, user)`'s
**empty** session instead, bounding the orphans to one per triple with the contract
unchanged. A session someone has spoken in is never handed back — resuming a stranger's
conversation because it shares a triple would be far worse than the row it saves.


### Security — where a connection is allowed to point, and why the obvious guard was wrong (2026-08-20)

`db_host`, `ssh_host` and a DSN's host are user-supplied and reach a socket, so an
authenticated user could aim one at the cloud metadata endpoint or at the app's own Redis
and read the connection-test error as an oracle for what answered (F-CONN-04).

**The existing SSRF guard's default could not be copied.** `validate_repo_url` refuses
every non-public address, which is right for a git remote — a public git host is the
normal case. A database is the opposite: most deployments reach theirs at `10.x`,
`192.168.x` or `127.0.0.1`. The same default would break the product for the majority in
order to protect the minority running it multi-tenant, and a guard that breaks the normal
case gets turned off, after which it protects nobody.

So the default is narrow and absolute, and the broad rule is opt-in:

- **Always refused: cloud metadata endpoints** — `169.254.169.254`, `169.254.170.2`,
  `fd00:ec2::254`, and the names that resolve to them, checked **by name and by resolved
  address** so a split-horizon resolver cannot answer differently for us than for whoever
  checked. No database has ever lived there, and what does hands out credentials for the
  whole cloud account, so refusing it costs no deployment anything.
- **Optionally refused: every private/loopback/link-local address** —
  `CONNECTION_ALLOW_PRIVATE_HOSTS`, default `true`. Set it `false` when running
  multi-tenant, where a tenant reaching `127.0.0.1` reaches *your* infrastructure.

Every address a name resolves to is checked, so one public record cannot launder the
private one beside it; a host that cannot be resolved is **accepted with a log line by
default and refused only in the strict mode** — a database name that does not resolve from
the API process is ordinary (VPN not up, internal-only DNS, resolvable only through the
tunnel), while an operator who asked for public hosts only is entitled to have
"unverifiable" count as "no"; a literal address costs no DNS lookup; and the whole check runs off the event loop, unlike the repo guard's synchronous
call inside a Pydantic validator. Applied on **create and PATCH** — the
guarded-on-create/free-on-PATCH shape has surfaced four times in two days.

DSN host extraction is deliberately best-effort: the common
`scheme://user:pass@host:port/db` shape is parsed, anything else is left to the driver.
The guard's job is to remove the easy path, not to claim a completeness it does not have.
### Security — `tofu` turned itself off when it could not write, and logged about it (2026-08-20)

`connect_with_policy` answered an unwritable `known_hosts` file by setting
`known_hosts=None` and connecting anyway — for that connection and every one after it. A
warning went to the log and the connection proceeded unverified, indefinitely. The
module's own closing branch reads *"an unrecognised policy must never silently disable
verification"*; two branches above it, that is exactly what happened.

Fail-closed is not the fix either: it would break every SSH connection on a read-only
filesystem to protect a promise the operator never made. The pin moves into process
memory instead.

- **First connect to a host is unverified** — which is what trust-on-first-use *is* —
  and its key is remembered.
- **Every later connect is checked against it.** A mismatch aborts the connection and
  raises `HostKeyChangedError` naming the host, where before it was accepted without
  comment.
- **A host presenting no readable key is not recorded**: remembering it would assert a
  check that cannot happen. The connection is logged as unverified and unpinnable.
- Where the file is writable but the disk does not survive a restart
  (AUD-0819-06 — Heroku), that was already the guarantee, so nothing is downgraded. The
  warning now says the pin is process-local and points at `SSH_KNOWN_HOSTS_PATH`.
- The writable path, `strict`, and the explicit `disabled` opt-out are unchanged.


### Security — the database password rode in the remote command line, on all three engines (2026-08-20)

`asyncssh.run(command)` sends an SSH *exec* request and sshd runs it through the login
shell as `sh -c "<command>"`, so everything in that string sits in a process's argv —
readable by **any** user on the remote host through `ps` or `/proc/<pid>/cmdline` for as
long as the query takes. Every exec template interpolated the password there:
`PGPASSWORD="…"`, `MYSQL_PWD="…"`, `CLICKHOUSE_PASSWORD="…"`. The finding recorded this
as a ClickHouse problem; it was all three.

**And the ClickHouse template never authenticated.** A command-prefix assignment sets the
variable for that command's environment only, so `"$VAR"` on the same line is expanded by
the *calling* shell from whatever value it already had — measured:

```
$ sh -c 'FOO="secret" printf "argv:[%s]\n" "$FOO"'
argv:[]
$ FOO=leaked sh -c 'FOO="secret" printf "argv:[%s]\n" "$FOO"'
argv:[leaked]
```

So `--password "$CLICKHOUSE_PASSWORD"` passed an empty string — or, if the login shell
exported that name, somebody else's value.

- The password now travels on the channel's **stdin**. The command opens with
  `IFS= read -r DBPASS` and the templates set the client's variable from `"$DBPASS"` as
  an environment assignment, so it is neither in the command string nor in the client's
  arguments.
- `--password` is gone from the ClickHouse templates; the client reads
  `CLICKHOUSE_PASSWORD` from its environment, which is what setting it was for.
- **A password containing a newline is refused** rather than silently truncated: `read -r`
  stops at the first one, and half a password authenticates as a server-side error that
  points nowhere near here.
- The **nine introspection call sites** that built commands by hand — template plus
  pre-commands, bypassing `_build_command` — now route through it. They would otherwise
  have emitted a `$DBPASS` with nothing to read it.
- A custom `ssh_command_template` that still interpolates `{db_password}` keeps working,
  with a warning naming the exposure. Breaking someone's connection to improve its
  hygiene is not an improvement they asked for.


### Fixed — a field guarded on create and free on PATCH, as a class rather than a fourth instance (2026-08-20)

Three of these landed in two days, each found while fixing something else:
`ConnectionUpdate.db_type` and `.db_name` (a demo connection repointed at the
application's own database), and `UpdateRepoRequest.branch` (F-GIT-08 — `validate_git_ref`
on create, nothing on PATCH, and the branch reaches `repo.git.checkout()` as argv). An
AST sweep of every `Create`/`Update` model pair under `app/api/routes/` found three more,
all on `ConnectionUpdate`:

- **`mcp_env` was unbounded on PATCH.** Create caps it at 50 entries with 255-char keys
  and 4096-char values; `ConnectionService.update` encrypts and stores whatever dict
  arrives, into a Text column, and hands it to a spawned MCP subprocess.
- **`connection_string` was not stripped on PATCH.** `_sanitize_strings` covers `name`
  downstream but not the DSN, so a trailing newline survived into `encrypt()` and failed
  to connect later in a way that pointed nowhere.
- `name` was covered downstream, and is now covered in both places for the same reason
  the other two are.

The fix is structural, not another copy: `_ConnectionFieldRules` is a base both models
inherit, so a rule added to it cannot be added to one and forgotten on the other.
`tests/unit/test_create_update_validator_parity.py` is the ratchet for every pair not yet
shaped that way — it compares by AST, and an accepted asymmetry needs a written reason
rather than an entry.


### Security — a git revision starting with a dash is an option, and git obeyed it (2026-08-20)

`GitInspector.diff()` and `.show()` passed caller-supplied revisions as **leading argv**
to the git binary with no validation and no `--`, so `--output=<path>` was never a
revision: it is git's diff-output option. Measured against a scratch repository, not
inferred:

```
before: 'IMPORTANT ORIGINAL CONTENT\n'
after : 'diff --git a/f.txt b/f.txt\nindex f719efd..6e5aa7c 100644\n…'
show also writes: 216 bytes
```

Any file the process can write, truncated and replaced — on a dyno that includes the
application's own source, which makes it remote code execution at the next boot. It was
reachable from chat: `git_agent.py:373/375/382/408` take `args["sha"]`, `args["a_sha"]`,
`args["b_sha"]` and `args["commit_sha"]` straight out of the model's tool call, and the
model is driven by a user's message and by repository content.

- `GitInspector._safe_rev` — no leading dash (the vector), plus a character allow-list
  covering git's real revision syntax (`HEAD~1`, `HEAD^`, `feat/some-thing`, `v1.0.0`,
  `a..b`, `@{upstream}`, a hex sha). Not a hex-sha regex: a guard that refuses the refs
  people use gets removed, and then neither rule is left.
- Applied at **all five** rev entry points — `show`, both revisions of `diff`, `blame`,
  `log(rev=…)`, `review_signals` — because a guard on the two the proof-of-concept
  happened to use would move the hole rather than close it.
- New `UnsafeRevError`, distinct from `InvalidRefError`: *refused before git ran* and
  *git ran and disagreed* deserve different answers, and only the first is worth
  refusing outright.
- **`UpdateRepoRequest.branch` had no validator** while `AddRepoRequest.branch` called
  `validate_git_ref`, and the branch reaches `repo.git.checkout()` and
  `Repo.clone_from(branch=…)` as argv. Same class, same create-guarded/PATCH-free shape
  as the connection routes. Both models validate now.

The original proof-of-concept now raises and the file is intact.


### Fixed — the demo path delivers the sample data it promised (2026-08-20)

`POST /api/demo/setup` was 65 lines carrying four board findings, and the largest was a
promise. SCN-003's expected result says the demo path "sets up sample data" and the
button offers to load it; the route seeded nothing and pointed at `:memory:`, which is
empty on every fresh connection regardless. **A first-run user clicking "Try demo
instead" saw an empty database.**

- **It seeds now.** A per-user SQLite file under `DEMO_DB_DIR` (new setting, default
  `./data/demo`) with `customers` (5 rows) and `orders` (8), joined by a real foreign
  key — small enough to check the agent's answer by eye, which is what a demo of a query
  product is for. Re-seeded whenever the file is missing: the dyno filesystem does not
  survive a restart and the project row does, so "seeded once" would have meant an empty
  database on the second visit.
- **Read-only** (`is_read_only=True`), like every other connection by default —
  `vision.md` §7 #1. The demo is the last place to make an exception to the product's own
  invariant.
- **Quota-metered.** `enforce_project_quota` and `enforce_connection_quota` run before
  either row exists, and a breach answers 402 with the same payload every other route
  sends. Rate-limited to 3/minute with no gate, the route minted three projects and three
  connections a minute against a plan the user was never charged for.
- **Reused, not multiplied.** A second call returns the first demo project and
  connection.
- SCN-003 was `implemented` with a PASS from the 2026-07-19 audit, which verified the
  button and the toasts. A scenario can pass on its affordances while its promise goes
  undelivered; the scenario now states the row counts, the read-only flag and the reuse,
  so the next audit has an expected result it can measure.
- The success toast is "Demo project ready" rather than "created" — "created" stopped
  being true on the second click.

### Added — a SQLite connector, because the demo's connection could never be opened (2026-08-20)

Found while fixing the demo, and larger than the four findings that led there:

```
>>> get_adapter("database", "sqlite")
ValueError: Unsupported adapter: sqlite. Available: ['postgres', 'postgresql',
'mysql', 'mongodb', 'mongo', 'clickhouse', 'mcp']
```

The demo route has created `db_type="sqlite"` connections since the demo path existed and
`ADAPTER_REGISTRY` never had an entry for it, so the first question a new user asked the
demo failed on dispatch. Seeding sample data behind that connection closes nothing on its
own — a database nobody can connect to is the same empty screen with more work behind it.

- `app/connectors/sqlite.py`: file-backed, no pool (SQLite has no server to pool against
  and a long-lived handle in an async web process is a lock waiting to happen).
- **Read-only enforced by the driver**, not by a regex: `mode=ro` in the URI makes SQLite
  itself refuse writes, matching how the other four connectors push the guarantee into
  the engine (`vision.md` §7 #1). `SafetyGuard`'s allow-list still runs above it.
- Introspection via `PRAGMA` — columns with types, nullability and primary keys, foreign
  keys, indexes with uniqueness, views marked as views and not row-counted, and SQLite's
  internal `sqlite_*` tables kept out of the LLM's schema context.
- **`:memory:` is refused at connect**, with the reason: each connection opens its own
  empty database, so it reads as configured and behaves as empty. That was the demo's
  configured target. A **missing file is refused rather than created** — `sqlite3` creates
  it silently, so a typo'd path would otherwise look exactly like a working connection
  over a database with no tables.
- `app/services/demo_data.py` owns the sample data, and
  `ConnectionService.to_config` repairs a demo file that has gone missing. Heroku's
  filesystem is ephemeral and per-dyno: a restart takes the file while the `Connection`
  row survives. Scoped by directory containment — a user's own SQLite database is never
  written to — and best-effort, so a failed repair never blocks an unrelated connection.

### Security — a SQLite connection is a filename, so it is confined to the demo directory (2026-08-20)

Registering the connector above turns "which database" into "which file may this process
read", and two free-string fields made that reachable: `ConnectionUpdate.db_type` and
`ConnectionUpdate.db_name` are plain `str` while `ConnectionCreate.db_type` is a `Literal`
that excludes `sqlite`. A user who clicked the demo could therefore `PATCH` their own
connection to `./data/agent.db` — the application's own database, holding every tenant's
rows and encrypted credentials — and ask a question about it. Closed in the same change,
at both layers:

- **The connector** resolves the path and requires it inside `DEMO_DB_DIR`, so `..` and
  symlinks are covered rather than pattern-matched.
- **The route** refuses `db_type: "sqlite"` on any PATCH, and refuses changing `db_name`
  on a connection that already is one.
- Fixed alongside: a PATCH to a SQLite connection was answered
  `"Provide either a connection string or db_host + db_name"` — a file has no host and
  never will, so that refused even a rename with advice the user could not act on.


### Fixed — Query timeouts stop being treated as broken SQL (2026-08-08)

Found by reading production trace `2026-08-06 11:39:24` (84 spans, `status=failed`).
Every `execute_query` timed out at exactly 30 000 ms while `explain_check` completed in
72–466 ms — the database planned instantly and executed never — and the system spent
**120 280 ms across ten `query_repair` calls** rewriting a query that was never wrong,
277 831 ms inside the SQL tool, until the route's 360 s ceiling killed the request.

- **A timeout now reaches the classifier as a type, not as prose.** `asyncio.wait_for`
  raises a builtin `TimeoutError` carrying *no message*, so each connector hand-wrote
  `"Query timed out after Ns"`; `ErrorClassifier`'s TIMEOUT patterns only ever matched
  vendor wording, so that self-written sentence fell through to `UNKNOWN`/retryable.
  `QueryErrorType` moved to the leaf module `app/core/error_types.py` (importable by
  both layers without a cycle), `QueryResult` gained `error_type`, and all four
  connectors set it. **No regex was added for the app's own string** — the point is to
  stop reading it.
- **One narrowing repair, then transient.** `_MAX_TIMEOUT_REPAIRS = 1`, counted from the
  attempt log so post-validation, EXPLAIN and execution share one allowance. The repair
  hint spends it on volume, not logic. `TIMEOUT` stays out of `_TRANSIENT_RETRY_ERRORS`:
  re-running the same query after a sub-second backoff cannot beat a 30 s timeout.
- **The SQL tool loop can stop.** Consecutive-timeout breaker
  (`SQL_TIMEOUT_BREAKER_THRESHOLD`, default 2, reset by any successful query) and a
  wall-clock deadline (`SQL_AGENT_DEADLINE_ENABLED`). Both are call-frame locals: one
  `SQLAgent` serves every request in the process, so instance state would leak across
  tenants. Non-positive threshold raises at boot.
- **Fixed an existing cross-request leak** uncovered by that constraint:
  `SQLAgent._wall_clock_remaining` was written by `run()` and read back off `self`, so
  concurrent requests overwrote each other's query timeout. It is now a parameter.
- **`finalize_trace` stopped erasing what the run measured.** Its UPDATE listed every
  column unconditionally, so its own parameter defaults clobbered the buffer flush's
  real values — `total_duration_ms` to NULL, steps to 0/0, route/complexity to
  `"unknown"`. The UPDATE is now additive, and it finally accepts `failure_kind`, which
  it had no parameter for at all.

`docs/ux/scenarios.md` gains **SCN-120**. Suite: 6043 passed / 5 skipped / 1 xfailed,
coverage **79%** (gate 72%). Deployed as Heroku release **v202** from commit `278b043`.
Behaviour in production is **not** yet observed — see the run's carry-over ledger, K14.


### Fixed — Audit remediation (2026-07-24)

Remediation of the 2026-07-24 full repository audit (`docs/qa-audit/full-audit-2026-07-24/` — 144 findings; per-finding status and commit mapping in `11-findings-registry.md`). Branch `fix/audit-remediation-2026-07-24`, 8 commits. Post-remediation run: backend 5580 passed / 5 skipped / 1 xfailed / 0 failed, coverage **78.03%** (gate 72%); frontend 546 passed (79 files); ruff check/format + mypy clean.

**Security**

- **FA-004 — git-SSRF guard** — `validate_repo_url` DNS-resolves the repo host and rejects loopback/private/link-local/reserved targets (incl. cloud metadata `169.254.169.254`) on both add-repo and `check-access`; opt-out `REPO_ALLOW_PRIVATE_HOSTS` for trusted internal git servers (commit `97616b7`).
- **FA-033 — fail-closed `ENVIRONMENT`** — now defaults to `production`, so unset/empty/unknown values keep the strict secret guards (non-default `JWT_SECRET` ≥32 chars, `DEBUG=false`, no CORS `*`) instead of silently passing as development (commit `97616b7`).
- **Missing rate limits (FA-017/054/055/056)** — `/api/billing/checkout` + `/api/billing/portal` (10/min), `/api/chat/ws-ticket` (30/min), `confirm-fix` and `PATCH /api/schedules/{id}` (10/min) (commit `97616b7`).
- **Dependency CVEs (FA-034/FA-005)** — `gitpython>=3.1.51`, `mcp==1.28.1`, `pyasn1>=0.6.4` (commits `97616b7`, `fee7b49`); `next` 15.5.12→15.5.21 closes the request-smuggling GHSA-ggv3-7p47-pfv8 (commit `f3aff7d`). Residual (deferred): `chromadb` and `ecdsa` have no upstream fix (ecdsa not exploitable under the HS256 whitelist); `postcss`/`sharp` remain transitive inside next 15.x — clearing them needs a next major.

**Fixed**

- **FA-001 (Critical) — MongoDB connector** — `if not self._db` → `is None` ×5: motor forbids truthiness, so every operation against a real MongoDB raised `NotImplementedError` (commit `0567e21`).
- **Connector correctness** — ClickHouse client recovery after a client-side timeout (session-lock wedge, FA-011); CH `EXPLAIN indexes = 1` ends false "full MergeTree scan" warnings (FA-026); SafetyGuard `validate_mongo` parity with the connector guard — `$out`/`$merge`/server-side JS blocked (FA-081); note-decay `func.greatest` now works on SQLite (FA-025) (commit `0567e21`).
- **Learnings & feedback** — idempotent downvote (AQ-1/FA-002, closes F-LEARN-08); per-user vote dedup via a new `LearningVote` table + migration `f8a9b0c1d2e3` (AQ-7/FA-031, closes F-LEARN-03); prompt-injection guards — untrusted framing on tool results + validation on `record_learning` (AQ-2/FA-003); DataGate `datetime` and string-number coercion for hard checks (AQ-4/5, FA-028/029); AnswerValidator verdict parsing (AQ-9/FA-084); reconcile float tolerance (AQ-10/FA-085 — un-xfails DATA-15) (commit `2c1a835`).
- **Resilience** — reaped runs reconcile on a late `pipeline_end` instead of staying phantom-`failed` (FA-007); intra-step heartbeats on long pipeline stages (FA-008); post-index heartbeat closes the duplicate-dispatch window (FA-009/RES-3); `update_connection` business validation 422→400 (FA-061) (commit `453df6f`).
- **Frontend** — session-expired flash survives the `/login` redirect (FA-010); one-shot 401 guard re-arms on re-authentication (FA-020); single shared session-expired message (FA-021); inline list errors + Retry for connections/schedules/learnings and all LogsScreen tabs (FA-024, FA-069); SCN-041 auto-growing textarea, SCN-054 per-step elapsed, SCN-077 Cancel in the create-rule modal (FA-064/065/066); lazy `remark-gfm` import (FA-042); dead `msw` devDependency removed (FA-103) (commit `f3aff7d`).
- **Daily knowledge sync on ARQ** — `task_queue.enqueue` no longer forwards `_job_timeout` to `arq.enqueue_job` (unknown kwargs reach the coroutine → every ARQ-dispatched daily sync crashed with `TypeError: ... unexpected keyword argument '_job_timeout'`; found in production worker logs post-deploy). The 2 h timeout now lives on the `arq.worker.func(timeout=...)` registration in `WorkerSettings` (hotfix, post-remediation).

**Performance**

- **Hot-path indexes** — migration `eff7aad70326`: `chat_messages(session_id, created_at)`, `agent_learnings(connection_id, is_active, confidence)`, `notifications(user_id, is_read, created_at)`, `request_traces(session_id)` and `(message_id)` (FA-046/047/048/107/109, commit `3db2c72`).
- **Pagination bounds + logs 404** — `limit`/`offset` caps on notes, dashboards, data-graph metrics/relationships, and repo docs (FA-062, partial); `logs.py update_error` returns 404 for unknown error ids and 400 for invalid status (FA-060) (commit `3db2c72`).

Deferred per the registry (marked «deferred» in `11-findings-registry.md`): the AQ-3/AQ-6/AQ-8 DataGate enforcement cluster (→ R12), gsap+lenis→motion consolidation (FA-012), API.md regeneration (FA-014–016), multi-dyno/Redis rate-limit parity (FA-036), and the remaining UX Low items.

### Added — UX audit remediation (2026-07-19)

Remediation of the findings from the UX scenario audit (`docs/ux/`, super-ux scenario base installed in `5011885`). Closes the last open High finding (F-PROJ-01) outside the R3 release. Verified by the 2026-07-24 full audit: 112/112 UX scenarios verified against code (109 PASS / 3 PARTIAL — SCN-041, SCN-054, SCN-077).

- **Email verification (F-PROJ-01)** — registration now issues a verification email; unverified accounts can no longer be auto-accepted into projects via email-based invite matching, closing the invite/access-harvesting vector. Backend token flow (single-use, SHA-256 hash at rest) + verification UI; the login `next` param is honored post-verify (commit `1701b46`). Covered by `backend/tests/integration/test_auth_email_verification.py`.
- **Forgot / reset password (SCN-012/013, F-AUTH-13)** — full self-service password-reset flow: `POST /api/auth/forgot-password` + `POST /api/auth/reset-password` (single-use token, 1 h expiry, `token_version` bump revokes all sessions) plus the frontend reset pages (commit `5ead515`). Forgotten password is no longer a permanent lockout.
- **Decline invite (SCN-015)** — invitees can decline a pending invite (`POST /api/invites/decline/{id}`) instead of only ignoring it (commit `b100e44`).
- **Dashboard delete + batch results view** — dashboards can be deleted from the UI, and batch executions got a proper results view instead of a dead end (commit `27104ef`).
- **Honesty sweep** — silent failures and dishonest success states surfaced across the app (empty states, error toasts, partial-result caveats) per the UX-audit honesty findings (commit `68f47e4`).
- **Logout confirmation toast (SCN-008)** — logout now confirms with a toast, closing out the UX audit (commit `e695caa`).

### Security — R3 cross-tenant isolation & IDOR (2026-06-25, commit `fbf8112`)

Release R3 of the QA/security audit roadmap (`docs/qa-audit/issues.md`). All "resource loaded/mutated by bare id (or shared cache key) without tenant scoping" findings closed in one ownership-scoping sweep. **0 open High findings remain.**

- **F-SSH-08** — SSH tunnel cache key now includes a credential discriminator (key fingerprint hash); cross-tenant tunnel sharing is no longer possible.
- **F-SSH-06** — `SshKeyService` no longer treats `user_id IS NULL` keys as shared across tenants.
- **F-RULE-01** — global (`project_id=null`) rule creation requires admin; non-admin rules are gated by project membership. Cross-tenant prompt injection via global rules closed.
- **F-RULE-05** — agent `manage_rules` update/delete scopes the rule lookup by project; IDOR on arbitrary `rule_id` closed.
- **F-DG-07 / F-DG-09** — `/investigate` validates that the referenced chat message, connection, and session belong to the URL project before reading/executing; cross-tenant leak + exec closed.
- **F-GRAPH-01** — `DELETE /api/data-graph/{project_id}/metrics/{metric_id}` scopes the metric load to the project; cross-tenant destructive IDOR closed.
- **F-LEARN-07** — global-pattern learnings are tenant-isolated (fail closed); `cross_connection_learnings_enabled` can no longer leak patterns across tenants.

## [1.16.0] - 2026-08-02 - Analytics sources (m0): Google Analytics 4 as a first-class source

**Release summary.** Adds a second, non-SQL ingestion path: external analytics report APIs become first-class connections, collected on a schedule into typed fact tables behind an import journal, and answered in chat by a dedicated sub-agent with the honesty gates wired explicitly. Module m0 of three (spine + GA4); App Store Connect (m1) and Google Play (m2) follow. Branch `feat/analytics-m0-ga4`; single new migration `a7b8c9d0e1f2` (head `eff7aad70326` → `a7b8c9d0e1f2`). Collection ships **off** (`ANALYTICS_COLLECT_ENABLED=false`), so a project that does not add a GA4 connection sees no behavioural change. Operator runbook: [`docs/ANALYTICS_SOURCES.md`](docs/ANALYTICS_SOURCES.md). Spec: `docs/superpowers/specs/2026-08-01-m0-ga4-spine-design.md`.

### Added

- **GA4 as a first-class data source.** `Connection.source_type` accepts `ga4` (plus `appstore` / `googleplay`, reserved — see *Changed*). `GA4Adapter` (`backend/app/analytics/ga4/`) speaks the Data API v1beta through an injectable client, so no test touches the network. It pages on `offset` — a single un-paginated `runReport` silently truncates at 10 000 rows — and when a cap is still hit after paging the report is marked `truncated`, so a lower bound never reads as a total. `keep_empty_rows` is requested on every report, so a day with no traffic arrives as a **zero, not a gap** a chart would interpolate over. `PropertyQuota` is read from every response and a spent bucket raises a typed `QuotaExhaustedError` rather than being inferred from a 429 alone. Five reports land in five natural-keyed fact tables — `ga4_overview_daily`, `ga4_geo_daily`, `ga4_platform_daily`, `ga4_trend_daily`, `ga4_event_daily` — with `ON CONFLICT DO UPDATE`, counts as `BigInteger` and revenue as `Numeric(18,4)`. `db_type` / `db_port` / `db_name` become nullable (batch-mode migration, so the dev SQLite path works): a GA4 connection has no engine, and persisting `127.0.0.1:5432` would make every downstream "is this a database?" guard answer yes.
- **Vendor-credential store** (`vendor_credentials`; `GET`/`POST /api/vendor-credentials`, `DELETE /api/vendor-credentials/{id}`). Owner-scoped and reusable across connections, deliberately shaped like `ssh_key_service`: Fernet-encrypted at rest, owner-strict lookups that **never** union NULL-owner rows (F-SSH-06 verbatim), and **no response ever contains the secret** or its ciphertext — a `fingerprint` (sha256 prefix) answers "is this the same key?" instead. A malformed GA4 service-account paste is refused with a 422 naming the missing field, before anything is persisted. `connections.vendor_credential_id` is `ON DELETE RESTRICT`, so deleting an in-use credential fails loudly with **409** rather than orphaning a connection; the refusal comes from the database, not a pre-check a concurrent create could slip past.
- **Scheduled collection with an import journal.** `run_analytics_collect` (ARQ, per-function timeout `analytics_collect_job_timeout_seconds`) plus `_analytics_collect_cron_loop` in `app/main.py` — an hourly wall-clock wave mirroring the daily-knowledge-sync loop, with an hour-scoped Redis lock so exactly one dyno dispatches and a day-scoped `task_id` so a connection cannot be collected twice in one day. The in-process `coro_factory` fallback keeps the no-Redis path working. The journal (`analytics_imports`, UNIQUE `(connection_id, report, period)`) computes pending as **`expected − done`**, never `max(period)`: a day that failed *below* the high-water mark refills instead of being skipped forever, an `empty` period counts as complete rather than being retried, and the most recent 2 periods are always refetched because vendors revise. The exit contract is three-valued and never collapses: errors with rows written is `partial`, errors with none is `failed`, and no errors with zero rows is `ok` (nothing was due). `POST /api/connections/{id}/collect` (202) and `GET /api/connections/{id}/collection-status` expose it; `collect` ignores `collection_enabled` on purpose, since that flag pauses only the *schedule* and pulling on demand is how a credential fix gets verified.
- **`AnalyticsAgent` with the honesty gates wired** (`backend/app/agents/analytics_agent.py`; orchestrator tool `query_analytics_source`, gated by `ContextLoader.has_analytics_sources`). It reads the **local fact tables**, never the vendor, through three parameterised tools (`list_reports`, `query_report`, `coverage`) — **no free-form SQL, and no user string reaches a query**: the group-by name is resolved against a fixed column set, and a comma-separated list is refused as exactly the shape an injection attempt takes. Gates run in spec order: DataGate hard checks (impossible values withhold the rows and discard the model's prose rather than caveating it) → truncation/partial caveat → freshness → `AnswerQualityGate`. Because answers are composed from local rows, *"we have no data for July"* and *"July collected as zero"* are different sentences, and `coverage()` exists so the agent can tell them apart. Budget exhaustion returns `no_result` rather than presenting half a gather as a conclusion, and an answer produced without a single tool call behind it is re-prompted once and then **refused outright**.
- **Analytics results chart like any other answer.** Tabular sub-agent results route through the existing `VizAgent` path. An empty result produces **no** chart (an empty chart reads as "the answer is zero"), and a result carrying pending periods is flagged partial so the chart inherits the same caveat as the text.
- **`vision.md` §8 carve-out + [`docs/adr/0001-external-report-cache.md`](docs/adr/0001-external-report-cache.md).** The "not a data warehouse or ETL pipeline" bullet is **amended, not quietly reinterpreted**: external report APIs are quota-limited, lag by days, and expose no query language, so their reports are cached per connection with provenance and a TTL. The production-database rule is unchanged and absolute — the carve-out applies only to vendor-credentialed report APIs, never to data in a user's own database. ADR-0001 records the context, the retention rules, and the two rejected alternatives (live proxy, MCP-only).
- **UI** — a `Vendor Credentials` panel under sidebar *Setup*; a GA4 branch in the connection form (credential picker with an inline "new credential" affordance, property id, backfill days, collection hour, auto-collect toggle); and a collection row on analytics connections showing the outcome badge, last run, next scheduled hour, per-report coverage, pending periods and **Collect now**. The row keeps the caveat/error split visible: a caveat is amber and prefixed, an error is red with `role="alert"`, never swapped.
- **Config** — six settings, all validated at boot so a misconfiguration fails loudly instead of silently idling the collector: `analytics_collect_enabled` (**false**), `analytics_backfill_days` (30), `analytics_refetch_tail_periods` (2), `analytics_collect_job_timeout_seconds` (1800), `analytics_http_attempts` (3), `analytics_journal_retention_days` (400). Per connection: `collection_enabled` (**true**) and `collection_hour` (3, local to `daily_knowledge_sync_timezone`). New dependency: `google-analytics-data`.

### Security

Four fixes found by review on this branch. The last two matter beyond analytics — one predates it entirely.

- **Cross-tenant vendor-credential attach (blocker).** A two-step `PATCH` let any tenant attach and then use another tenant's vendor credential. The ownership check was nested inside the analytics branch **and** keyed on `vendor_credential_id` being present in that payload, so two requests walked straight past it: attach the victim's credential while the row is still a database (non-analytics branch — no check at all), then flip `source_type` to `ga4` without naming the credential (analytics branch, key absent, check skipped). `POST /collect` then returned 202, and the collect path — which resolves the secret with `user_id=None`, trusting exactly the ownership this route was supposed to have settled — decrypted the victim's service-account key and collected their GA4 property into the attacker's project. The check is now a **single assertion on the merged row**: after any PATCH, if the connection carries a `vendor_credential_id`, that credential belongs to the requester. Keying on the merged id also refuses vendor key material on a database connection (provider mismatch → 422). Both `require_role` guards on `/collect` and `/collection-status` are now pinned by tests — deleting them previously left 29 analytics tests green.
- **Account-deletion deadlock.** `DELETE /api/auth/account` returned 500 for any user holding a GA4 connection in a co-owned project: `vendor_credentials.user_id` is FK CASCADE while `connections.vendor_credential_id` is FK RESTRICT, and `delete_account` only deletes projects the user *owns* — so an invite-granted co-owner could leave behind a connection still referencing the departing user's credential. The user CASCADE then fired into the RESTRICT and the entire delete aborted: a data-subject deletion request that hard-failed, forever. Deletion now detaches every connection referencing the user's credentials **and sets `collection_enabled = False`** (an analytics source whose credential was just destroyed would otherwise be dispatched nightly to journal an auth failure) before destroying the credentials and the user. The detaching UPDATE is keyed on a subquery rather than a previously-read id list, so a connection created between the two statements is still detached.
- **Secrets reaching Sentry through frame locals** (pre-existing exposure, wider than analytics). `sentry_sdk.init` left `include_local_variables` at its default `True`, which attaches `repr()`-ed frame locals under `exception.values[].stacktrace.frames[].vars` — the one payload the `before_send` scrubber never walks. `ConnectionConfig` was a plain dataclass, so **any** exception raised in a frame holding one (a connector's `connect`, `to_config`, the analytics collect loop) shipped `db_password`, `ssh_key_content` and — on the analytics path — the plaintext service-account JSON in `extra` to a third party. Both halves are fixed: `include_local_variables=False`, plus a hand-written `ConnectionConfig.__repr__` (and `__str__`) that renders every secret as a presence marker and `extra` as redacted keys, while keeping host/port/database/user/mode/connection-id readable for debugging. The repr is the transport-independent half — it also covers log lines and error messages. `GA4Credentials` redacts for the same reason.
- **Reserved source types were creatable.** `appstore` / `googleplay` connections could be created and scheduled but have no fact tables, so the cron would have journalled a failure for them every day until m1/m2 land. Creation and PATCH now refuse them with a **422** derived from the registered fact-table map, so the gate lifts itself when those modules ship rather than needing a second hand-maintained list.

### Changed

- **`is_queryable_database()` is now the predicate for "is there a database to query".** An analytics connection carries the vendor id where a database carries its engine, so the old `connection_config is not None` test advertised `query_database` for a GA4 source and `get_connector("ga4")` raised mid-chat. Schedules, batch execution and the schema/code routes (`index-db`, `refresh-schema`, `sync`) now refuse an analytics connection with the same honest message instead of crashing — the scheduler loop records the run `failed` with that reason rather than dying on "Unsupported adapter".
- **`QUERY_MCP_SOURCE_TOOL` no longer claims Google Analytics.** Its description used GA as its example; it now points at `query_analytics_source` for the three vendors with first-class connectors, and keeps MCP for sources with no native support.
- **Journal pruning joins the 24 h maintenance cron**, alongside learning/insight decay. Best-effort: failing to prune never fails the maintenance pass, because the journal is what distinguishes "collected as zero" from "never collected".

### Retention

Fact rows are **kept** for the life of the connection — expiring them would silently turn answered history into "not collected". Raw vendor payloads are **never** written to disk or to a blob column: `fetch()` returns parsed rows and the response body goes out of scope. The journal is pruned at 400 days. `analytics_imports` and all five `ga4_*` tables cascade on `connections.id`, so deleting a connection removes every cached row for it, and deleting a project cascades through its connections.

### Deploy notes

- **No operator action required for existing installs.** The migration only adds tables/columns and drops three `NOT NULL` constraints; existing rows are untouched. Collection stays dormant until `ANALYTICS_COLLECT_ENABLED=true`.
- **To enable collection:** set `ANALYTICS_COLLECT_ENABLED=true` and **restart the API process**. The hourly wave lives in the web process (`app/main.py` lifespan) and reads the flag once at start-up, so a config change without a restart leaves the loop dormant. The worker does not gate on the flag — it only executes the jobs the wave (or a manual "Collect now") enqueues. The wave dispatches each connection at its own `collection_hour`, in `DAILY_KNOWLEDGE_SYNC_TIMEZONE`.
- **GA4 access is a human step.** A service account, the Google Analytics Data API enabled in the same GCP project, a JSON key, and — the step most often missed — **Viewer on each GA4 property** in Admin → Property Access Management. The Property ID is the number in Admin → Property details, **not** the `G-XXXXXXX` Measurement ID. Full walkthrough in [`docs/ANALYTICS_SOURCES.md`](docs/ANALYTICS_SOURCES.md).
- **App Store Connect and Google Play are not usable yet** — their credentials can be stored, but connection creation returns 422 until m1/m2 register their fact tables.

### Verification

Backend suite collects **6,028** tests; frontend Vitest **606 passed across 86 files**. Backend combined-coverage gate unchanged at 72%. UX scenarios **SCN-113…116** added to `docs/ux/scenarios.md` (add a GA4 connection · add/delete a vendor credential · collection status incl. partial and pending periods · credential delete blocked while in use), enforced by `backend/tests/unit/docs/test_ux_scenarios.py`.

## [1.15.1] - 2026-07-09 - Embedding-loader log hygiene + infra guidance

Post-release hardening from a production log review of the 1.15.0 deploy (v194).

### Fixed

- **Embedding-loader startup noise (observability).** When the configured `chroma_embedding_model` (default `BAAI/bge-base-en-v1.5`) cannot be loaded because the optional `sentence-transformers` package is absent, `app/knowledge/vector_store._get_embedding_function` now logs a **single concise WARNING** and degrades to ChromaDB's built-in default ONNX model (`all-MiniLM-L6-v2`, 384-dim). Previously this known, handled condition dumped a full exception **traceback twice at every boot**, which read like a crash in the logs. A new `_sentence_transformers_available()` helper (cheap `importlib.util.find_spec`, never raises) pre-empts the failing instantiation; genuine unexpected load failures still retain their diagnostic traceback. No behavioural change to retrieval — index and query both use the same effective model, so dense retrieval stays self-consistent.

### Deploy notes

- **bge embeddings + reranker require ≥1GB-RAM dynos (infra decision).** Production currently runs on Heroku **Standard-1X** (512 MB) web+worker dynos. `BAAI/bge-base-en-v1.5` (768-dim) and the cross-encoder reranker both need `sentence-transformers` + `torch`, which will not fit in 512 MB (OOM at model load). Until the dynos are upgraded to ≥1 GB (Standard-2X / Performance-M) **and** `sentence-transformers` is added to `Dockerfile.backend` / `Dockerfile.worker`, the system runs on the ONNX `all-MiniLM-L6-v2` default (fully functional, lower retrieval ceiling) and the reranker is a no-op. **To enable bge + reranker:** (1) scale web+worker to ≥1 GB, (2) add `sentence-transformers` to the images, (3) run a full reindex (`queue_embedding_reindex`) so the 768-dim vectors replace the 384-dim ones — the embedding fingerprint marker must then be advanced (or the reconcile re-run) so index and query dimensions match.

## [1.15.0] - 2026-07-09 - Intelligence remediation (W0–W6), self-completing embedding reconcile, sync & orchestrator hardening

**Release summary.** This release cuts the full intelligence-remediation program (Waves 0–6) plus the June sync/orchestrator audit remediation and the self-completing embedding reconcile. All code was merged and auto-deployed to production incrementally between 2026-06-25 and 2026-07-06; this entry formalises the version boundary (1.14.0 → 1.15.0). Highlights: data-quality honesty (truncation/partial-data caveats, DataGate on both paths), hybrid retrieval + ContextPack with provenance and reranking, orchestrator live step-budget termination + single-loop/pipeline path unification, DB schema-capture depth across all four connectors, code↔DB trust signals with exact git-freshness states, code-graph correctness, and a zero-touch embedding reindex on deploy. Default-on flag flips (benchmark-gated): `code_graph_enabled`, `lineage_enabled`, `reranker_enabled`, `context_planner_enabled`. See the per-wave sections below and the **Deploy notes** block for operator prerequisites.

### Fixed — W5 intelligence-remediation: code↔DB trust signals (2026-07-06, branch `worktree-intelligence-remediation`)

Wave 5 wave-closer (T11). All 10 prior W5 tasks committed; ruff/mypy clean; unit+integration suite green at 78% coverage (≥72% gate); retrieval-eval gate green (18/18); single alembic head `c9b8a7f6e5d4`.

- **SYNC-L3 (git freshness states AHEAD/BEHIND/DIVERGED)** — `classify_freshness()` in `git_tracker.py` uses `iter_commits` to compute exact ahead/behind counts and returns `GitFreshness(FRESH|AHEAD|BEHIND|DIVERGED)`. `KnowledgeFreshnessService.evaluate()` maps each state to a distinct warning with the commit count; DIVERGED is severity `critical`. `git_freshness_fetch_origin` flag (default `false`) gates a remote fetch for cross-machine accuracy. Env key: `GIT_FRESHNESS_FETCH_ORIGIN`.
- **SYNC-L2 (table-ref attribution)** — `EntityExtractor` tracks which SQL statement each column reference appears in; phantom cross-table attributions eliminated. Noise-only SQL tokens (literals, parameters, operators) are stripped before attribution. Confidence on attributed refs defaults to L2 rather than the weaker L1.
- **SYNC-L5 (deterministic drift set-diff)** — `CodeDbSyncPipeline._compute_column_drift()` produces a stable sorted `{code_only, db_only, matched}` diff (case-normalised). When both sides are non-empty and drift exists, `sync_status` is set to `"mismatch"` deterministically, overriding any LLM opinion. Diff persisted to `CodeDbSync.column_mismatch_json` (migration `c9b8a7f6e5d4`).
- **SYNC-L6 (schema-qualified ORM matching)** — sync loaders and `get_table_sync` now match on `(schema, table)` pair when the ORM model carries a qualified table name (e.g. `public.orders`); unqualified model names still work against the default schema.
- **SYNC-L7 (bare-suffix keying)** — all sync loaders and `get_table_sync` normalise keys to bare table name (no schema prefix) before cache lookup; eliminates duplicate and missed cache hits when some code paths pass qualified names.
- **SYNC-L8 (code-graph warning gate)** — the "code graph is empty" freshness warning is gated on `lineage_enabled OR clustering_enabled` (the actual graph consumers) rather than `code_graph_enabled` (the indexing flag); operators who index the graph but don't enable lineage/clustering no longer receive spurious empty-graph warnings.
- **SYNC-L9 (op-kind word-boundary)** — HTTP operation-kind extraction in `graph_db_bridge.py` uses word-boundary regex (`\bget\b`, `\bpost\b`, etc.) to prevent false matches (e.g. `forget` → `get`). Low-confidence name-inference now emits a debug log rather than a noisy warning.
- **Low-batch L11–L14** — `_coerce_confidence` rounds float strings before clamping (`"4.5"→4`, `"4.7"→5`) instead of silently defaulting to 3; `CallerRef.depth_estimated=True` sentinel replaces fabricated depth integers; enum-table link matching uses token word-boundary (not raw substring) so `reorder_reason` no longer spuriously links to table `order`; DB-index TTL is read from `settings.db_index_ttl_hours` (default 24, env key `DB_INDEX_TTL_HOURS`).

**Note:** SYNC-L1 was delivered in W1; SYNC-L4 (table-name inflector) was delivered in W6; the W5 set covers L2/L3/L5/L6/L7/L8/L9 + low-batch L11–L14.

### Fixed — W3 intelligence-remediation: orchestrator termination + path unification (2026-07-06, branch `worktree-intelligence-remediation`)

Wave 3 wave-closer (T14). All 13 prior W3 tasks committed; ruff/mypy clean; unit+integration suite green at 78% coverage (≥72% gate); retrieval-eval gate green (18/18).

- **ORCH-T01 (live step budget)** — `max_orchestrator_iterations` is now a live termination signal: the wrap-up phase is entered as soon as the counter is reached, not only after a post-loop check; no extra LLM call is wasted on an already-budget-exceeded loop body.
- **ORCH-T02 (wrap-up gate)** — the synthesis/wrap-up phase is only entered when at least one data retrieval has been attempted; static-prompt-only turns no longer trigger a premature "composing answer" emission.
- **ORCH-T03 (no-tool re-prompt)** — on a data route, if the model emits a planning/thinking turn with no tool calls and no data yet, the orchestrator re-prompts once to keep the loop alive; bounded to one shot (`reprompted_no_data` flag) — no infinite loop.
- **ORCH-A03 (routing metrics)** — `route`, `complexity`, and `estimated_queries` from the unified router are now recorded into `MetricsCollector` on every turn; `complexity` is no longer `"unknown"` in metrics/Prometheus.
- **ORCH-PR01 (prompt de-dup)** — duplicate reconciliation guidance removed from the orchestrator system prompt; stale self-description updated; net ~200-token reduction per request.
- **ORCH-CP01 (cue precision)** — `ContextPlanner` cue matching upgraded to word-boundary regex; over-broad single-letter cues removed; false-positive cue matches on unrelated words eliminated.
- **ORCH-P01 (validation scope)** — `StageValidator` now scopes data-quality criteria to data stages only; text/knowledge stages require a non-empty summary instead; prevents false failures on non-SQL stages.
- **ORCH-P02/P03 (planner/replan fixes)** — trivial single-step plans are bounced back for replanning; `degraded` flag is propagated across replan so downstream stages know quality was compromised; the failed tool name is stored in learnings for root-cause analysis.
- **ORCH-RP01/RP02 (cohort_window params)** — `cohort_window` params are unified across the planner and executor; both use the same type/default; no more implicit coercion mismatch.
- **ORCH-R01 / ORCH-P04 (non-DB pipeline)** — complex non-DB questions (knowledge, git, MCP) are now routed through the full multi-stage pipeline when complexity warrants it (`use_complex_pipeline`), not silently dropped to the single-loop path. Source-aware quick-plan fallback avoids a DB-specific stage appearing in a knowledge-only plan.
- **ORCH-A01 (path unification — ResultValidation on both paths)** — `ResultValidation` (DataGate + result gate + reconcile) is now wired into the pipeline SQL stage as well as the single-query path; impossible values are caught on both code paths.
- **ORCH-A02 (path unification — AnswerQualityGate on pipeline)** — `AnswerQualityGate.evaluate` is now called on the pipeline final answer, matching the single-loop path; answer quality is enforced regardless of which execution path produced the result. Pipeline answers may now surface `response_type: "step_limit_reached"` when the pipeline exhausts its budget (see API.md).
- **ORCH-P04 / pipeline reconciliation** — SQL reconciliation note injected into pipeline synthesis prompt so the LLM is aware of all prior SQL results when composing the final pipeline answer (parity with the single-loop path).
- **Low-batch fixes (A05/V02/PR03/R03/R04)** — orchestrator low-batch edge cases resolved: empty-result SQL no longer silently swallows the answer; viz-stage failure degrades gracefully; prompt refs cleaned up; router/replan boundary conditions tightened.

### Changed — W6 intelligence-remediation: code-graph correctness + flag flips (2026-07-06, branch `worktree-intelligence-remediation`)

Wave 6 wave-closer (T11). All code-graph correctness fixes (T1–T10) landed; graph-quality benchmark PASS; `code_graph_enabled` and `lineage_enabled` flipped to default-on.

- **CODEIDX-C4 (cross-file CALLS re-resolve)** — incremental re-index correctly re-resolves cross-file CALLS edges after any file in the reverse-dependency set changes; callers are no longer orphaned after incremental updates.
- **CODEIDX-C7 (UID line-drop)** — symbol UIDs use `{lang}:{file}:{kind}:{name}` format (no trailing line number); UIDs are stable across reformats and incremental rebuilds.
- **CODEIDX-C6 (EXTENDS heritage)** — multi-base Python EXTENDS edges are emitted for all explicit base classes; `Worker(Base)` produces a `Worker → Base` edge even when Base is defined in another file.
- **CODEIDX-C5 (JS/TS symbols)** — TypeScript/JavaScript arrow-function components are extracted as `kind=function`; module-level `const` exports are extracted as `kind=variable`; both produce stable UIDs.
- **CODEIDX-C8 (ORM Mapped)** — SQLAlchemy `Mapped[T]` and `mapped_column` annotations are treated as typed columns rather than class-body CALLS; no phantom call edges from ORM model definitions.
- **CODEIDX-C17 (checkpoint gate)** — pipeline stage `graph_build` is skipped (checkpoint-resume) when the graph has already been written to DB; avoids redundant CPU-heavy re-parse on resume.
- **CODEIDX-C9 (shared ignore + prune-by-degree)** — `shared_ignore.py` provides a single `is_ignored_path()` function consumed by both the pipeline and the benchmark; zero-degree symbols (no edges, private-prefixed) are pruned to reduce graph noise.
- **CODEIDX-C15 (enum-via-annotation)** — Python `StrEnum`/`IntEnum` subclass bodies are extracted as `kind=enum`; members are not emitted as spurious `variable` symbols.
- **CODEIDX-C16 (table-name inflector / SYNC-L4)** — ORM `__tablename__` or `declared_attr` is resolved first; falls back to the pluralized snake-case class name only when absent; lineage `code→DB` mapping is no longer wrong for non-default table names.
- **Graph-quality benchmark** — `app/eval/graph_benchmark.py` (`run_graph_benchmark() → GraphBenchmarkResult`) runs the fixture repo through the full AST→graph pipeline and asserts ≥7 symbols, ≥1 CALLS, ≥1 EXTENDS, ≥1 IMPORTS. Gate command: `python -m app.eval.graph_benchmark` (exit 0 = PASS). Benchmark PASS result: `symbols=7 CALLS=2 EXTENDS=1 IMPORTS=1`.
- **Flag flips (benchmark-gated)** — `code_graph_enabled` and `lineage_enabled` flipped to `True` (default-on) after the benchmark passed (spec §9, F-ARCH-6). **Deploy note:** `code_graph_enabled=true` enables CPU-heavy tree-sitter AST parsing during repo indexing; allocate ≥2 CPU cores and expect indexing time to increase on large repos (≥50k LOC).

### Added — Self-completing embedding reconcile (2026-07-06, branch `feat/embedding-self-reconcile`)

- **Automatic post-deploy reindex.** On startup, `app/ops/embedding_reconcile.reconcile_embeddings` (wired into the FastAPI `lifespan`) compares the current embedding fingerprint (`chroma_embedding_model` + `embedder_max_tokens`) against a new single-row `deploy_state` marker table and enqueues a one-shot full reindex of all projects when it changed. Idempotent (marker advanced only after a successful enqueue), multi-dyno-safe (Postgres `pg_try_advisory_xact_lock`), and graceful (never raises, never blocks boot; SQLite dev skips the lock). Migration `d5e6f7a8b9c0` seeds the OLD fingerprint on databases that already have projects so the feature's own deploy closes the existing stale-embedding backlog. **Removes the previous manual post-deploy reindex step.**

### Added — W2 intelligence-remediation: retrieval + ContextPack wave-closer flag flips (2026-07-06, branch `worktree-intelligence-remediation`)

Wave 2 wave-closer (T15). All retrieval + ContextPack fixes (T1–T14) landed; eval gate green; flags flipped to default-on.

- **C1/C2 (tokenizer/chunk-window)** — knowledge indexer tokenizer aligned to the actual embedding model; chunk window sized correctly so oversized chunks no longer exceed the model's context window silently.
- **C3 (raw-code embedding)** — raw source code is embedded with a dedicated code-embedding path rather than being passed through the prose tokenizer; code retrieval quality improved.
- **R1/R2/R3/R8 (ContextPack hybrid+budget+provenance)** — `ContextPack` assembles a single traceable knowledge context with hybrid retrieval (BM25 + dense RRF), a token-budget cap, and per-chunk provenance metadata surfaced to the orchestrator.
- **R4 (retrieval_degraded signal)** — a `retrieval_degraded` flag is set on `ContextPack` when any retrieval stage falls back; the orchestrator prompt carries the caveat so the LLM knows context may be incomplete.
- **R5 (relevance floor)** — results above `rag_relevance_threshold` (distance > 0.45) are filtered out before entering the ContextPack; tail-noise chunks no longer dilute context.
- **R9/D7 (FK-aware schema retrieval)** — `SchemaRetriever` expands FK neighbours up to one hop so tables joined by a foreign key are co-retrieved even when only one side matches the query.
- **R10 (safety-net floor)** — `sql_agent_safety_net_min_relevance` (default 3) filters low-signal safety-net tables so retrieved + FK-expanded entries are not crowded out.
- **R14 (reranker `.rank`)** — `CrossEncoderReranker` calls `.rank()` when available (sentence-transformers ≥ 3.x) and falls back to `.predict()` for older model versions; both paths produce a sorted `List[Candidate]`.
- **Low batch** — BM25 retrieval batch size tuned to avoid memory spikes on large corpora.
- **Flag flips (gated)** — `reranker_enabled` and `context_planner_enabled` flipped to `True` (default-on) after the retrieval-eval + reranker gate passed (18/18 tests, including `test_harness_oracle_passes_thresholds` at `hit_at_k==1.0` and `test_cross_encoder_uses_rank_when_available`). Wave-gate assertion test `test_w2_flag_flips.py` added.

> ⚠️ **Deploy notes (intelligence remediation — all three apply to this release)**
>
> **1. ChromaDB reindex — now AUTOMATIC (self-completing deploy)**
> The default embedding model changed from `all-MiniLM-L6-v2` (384-dim) to `BAAI/bge-base-en-v1.5` (768-dim, 512-token window) and code chunks now use a dedicated `sym:` prefix path. This reindex is now handled automatically at startup by `app/ops/embedding_reconcile` (see the **Added** entry below) — **no operator action required.** Migration `d5e6f7a8b9c0` seeds the OLD fingerprint on databases that already have projects, so the first deploy carrying this feature reindexes the existing backlog once. Until the enqueued reindex completes, hybrid retrieval falls back to BM25-only (functional, lower quality). Manual override remains: `from app.services.embedding_reindex import queue_embedding_reindex`, or "Re-index repository" per project in the UI.
>
> **2. `code_graph_enabled` + `lineage_enabled` now default-on (CPU-heavy)**
> Both flags flip to `True` in this release (W6). Code-graph indexing is CPU-intensive; recommend ≥2 cores on the worker dyno. Operators who want to defer the CPU cost can set `CODE_GRAPH_ENABLED=false` and `LINEAGE_ENABLED=false` in env until ready.
>
> **3. `reranker_enabled` now default-on — requires image update**
> `reranker_enabled=true` requires `sentence-transformers` + a cross-encoder model (e.g. `cross-encoder/ms-marco-MiniLM-L-6-v2`) in the production image. The flag degrades gracefully to a no-op when the library or model is absent — retrieval still works, just without reranking.

### Fixed — W1 intelligence-remediation: data-quality hardening (2026-07-05, branch `worktree-intelligence-remediation`)

Wave 1 of the intelligence-remediation audit. All 15 tasks committed; ruff/mypy clean; unit+integration suite green at ≥72% coverage.

- **DATA-01 (truncation propagation)** — `DataProcessor` additive aggregations (sum/count/count_distinct) over a row-capped input are flagged as `PARTIAL DATA`; the summary and the agent-facing output both carry the caveat; never silently presented as a complete total.
- **DATA-02/04 (dispatcher/synthesis/pipeline truncation honesty)** — `ToolDispatcher._full_data_hint` now distinguishes truncated from complete datasets; the synthesis path and pipeline result builder propagate the same caveat; LLMs downstream cannot conflate a capped sample with the whole.
- **DATA-03 (SQL-correctness prompt)** — `SQLAgent` system prompt updated with explicit instructions on GROUP BY completeness, COUNT(*) vs COUNT(DISTINCT), and NULL-handling to reduce silent miscounts at the generation step.
- **DATA-05 (phone E.164)** — `PhoneCountryService` now requires E.164 format (`+<country_code><number>`); non-E.164 inputs degrade gracefully with a warning rather than producing a silent wrong-country mapping. User-facing: phone→country enrichment now needs E.164-formatted numbers.
- **DATA-06 (DataGate on single-query path)** — `DataGate.check_query_result()` public method added; wired into `ResultValidation` so impossible values (150% conversion, negative counts) are caught on the direct single-query path, not only inside multi-stage pipelines.
- **DATA-09 (chart nulls)** — Chart-building path guards against null/missing values in series data; nulls are rendered as gaps rather than plotted as zero, preventing silent chart distortion.
- **DATA-16/17 (validator/investigation honesty)** — `AnswerValidator` and `InvestigationAgent` prompts updated: both must declare uncertainty when data is partial, and must not assert completeness when the result set is capped or the investigation is inconclusive.
- **SYNC-L1 (satisfiable required-filter guard)** — `RequiredFilterGuard` degrades gracefully when a required filter is satisfiable but cannot be applied (emits a warning + increments `filter_guard_degrade_total`) instead of blocking the query entirely.
- **DATA-14 (range-scan late rows)** — Regression test confirms `_check_value_ranges` scans the full in-memory result when `data_gate_value_range_sample=0` (default); impossible value in the last row of a 501-row result is caught. Positive-cap behaviour documented as intentional speed/correctness trade-off.
- **DATA-15 (reconciliation rounding tolerance)** — Deferred: fix belongs to `insight_memory.py` (W3-owned file). `xfail` test documents the gap.
- **DATA-18 (duplicate/null-rate false signals)** — `_check_duplicates` minimum sample raised from 3 → 10 rows to avoid false positives on legitimately-sparse tables. Null-rate warnings labelled "advisory, based on sample only" per DATA-22.
- **DATA-19 (COUNT semantics doc)** — `_compute_agg` docstring updated with explicit NULL-handling notes: `count` uses SQL COUNT(*) semantics (includes NULLs); `count_distinct` uses SQL COUNT(DISTINCT col) semantics (excludes NULLs).
- **DATA-20 (unformatted numbers)** — `ToolDispatcher._fmt_cell` static helper added; aggregation output loop now calls it instead of `str(v)`; large integers and Decimal values render with thousands separators (e.g. `1,234,567`).
- **DATA-21 (small-fan-out cartesian)** — `xfail` test documents that `_check_cross_stage_consistency` only warns above `cartesian_multiplier` (default 100×); a 2× fan-out passes silently. Known limitation, no over-engineering.
- **DATA-22 (sampled signals unmarked)** — Null-rate and duplicate-rate warnings now include "sampled" / "advisory, based on sample only" labels so the LLM knows the signal is partial.

### Added — W4 intelligence-remediation: schema-capture depth (2026-07-06, branch `worktree-intelligence-remediation`)

Wave 4 of the intelligence-remediation audit. All 18 tasks committed; ruff/mypy clean; unit+integration suite green at 77% coverage (≥72% gate).

- **DBIDX-D1/D2/D3 (MongoDB native introspection)** — `MongoDBConnector` overrides `distinct_values` and `approx_stats` using native aggregation pipelines (`$group`/`$sortByCount`/`$sample`). Field types are inferred by union-sampling nested documents; `$type` operator maps BSON types to SQL equivalents. `ProbeService` routes `distinct_count` and `sample` through connector methods so Mongo never receives a raw SQL fallback.
- **DBIDX-D4 (ClickHouse sort key)** — `ClickHouseConnector.introspect_schema` reads `system.columns.is_in_sorting_key` and sets `ColumnInfo.is_sort_key`; schema-context renderer surfaces it as `[sort-key]`.
- **DBIDX-D5 (PostgreSQL enum + CHECK constraints)** — `PostgresConnector.introspect_schema` queries `pg_type`/`pg_enum` for enum labels and `information_schema.check_constraints` for per-column CHECK expressions; both land in `ColumnInfo.enum_labels` and `ColumnInfo.check_constraints`.
- **DBIDX-D6 (views + `object_kind`)** — all four connectors (PG, MySQL, ClickHouse, MongoDB) index VIEWs and MATERIALIZED VIEWs alongside base tables; `TableInfo.object_kind` is set to `"table"`, `"view"`, or `"materialized_view"` so query generation knows not to DML a view.
- **DBIDX-D8 (comments + indexes render)** — `_format_table_context` in `DbIndexService` (the default multi-table schema context path) now renders column comments, table/column-level indexes, enum labels, and ClickHouse sort-key markers in the schema block handed to the LLM.
- **DBIDX-D9 (approx_stats persistence)** — `DbIndexService` persists `ColumnInfo.distinct_count`, `null_pct`, `numeric_format`, and `enum_labels` into `DbIndex.column_stats_json` and `DbIndex.column_distinct_values_json` (JSON columns added in W0); gated by `db_index_stats_enabled` (default on). These fields are now available to the schema-context renderer and downstream consumers (R9/D7 handoff).
- **DBIDX-D10 (completeness gate)** — `DbIndexService` emits a deterministic completeness score (0–1) per index run; runs below the threshold are logged as warnings rather than silently accepted; prevents regressions from partial connector failures.
- **DBIDX-D11 (MongoDB field inference)** — MongoDB schema inference samples `mongo_schema_sample_size` (default 100) documents per collection, unions field paths across the sample, and derives `ColumnInfo` entries for nested sub-document paths; wider schemas with optional fields get better coverage.
- **DBIDX-D12 (schema-cache bust)** — `SchemaCacheRegistry` invalidates the 300-second TTL schema cache on explicit re-index or schema-change event so a re-index is immediately visible to the next query agent turn.
- **DBIDX-D14 (reltuples < 0 fix)** — `PostgresConnector` treats `pg_class.reltuples < 0` (un-analyzed tables in PG 13+) as `None` (unknown) rather than surfacing a negative row count that confuses LLM table selection.
- **DBIDX-D15 (LLM cap)** — DB-indexing LLM analysis is capped at `db_index_max_tables_analyzed` (default 500) tables per run; tables beyond the cap receive a deterministic fallback analysis to prevent runaway cost on very wide schemas.
- **DBIDX-D16 (column prompt cap)** — the LLM analysis prompt is capped at `db_index_max_prompt_columns` (default 100) columns per table; excess columns are replaced with a `"(… N more columns)"` note.
- **DBIDX-D17 (ClickHouse freshness)** — ClickHouse connector surfaces table `last_modified` from `system.tables.metadata_modification_time` so `KnowledgeFreshnessService` can detect stale schema without a full re-index.
- **DBIDX-D18 (MongoDB freshness)** — MongoDB connector surfaces collection `last_modified` approximated from `collStats.lastModified` (if present) or `$natural` order sampling so freshness checks work on document stores.
- **Pipeline routed via connector methods** — `ProbeService` dialect-aware dispatch means `sample(n)`, `distinct_count(col)`, and `approx_stats(col)` calls go through each connector's native implementation (T6/T7); no raw SQL fallbacks for MongoDB.

**W4 handoff note (R9/D7):** `ColumnInfo.distinct_values`, `distinct_count`, `numeric_format`, and `enum_labels` are now populated by all connectors and persisted to `DbIndex.column_stats_json` / `column_distinct_values_json`; downstream waves can read these from the index without re-querying the DB.

### Removed — W4 intelligence-remediation: dead-code pruning (2026-07-06, branch `worktree-intelligence-remediation`)

- **DBIDX-D13 (dead `SchemaIndexer`)** — removed `app/knowledge/schema_indexer.py` and its unit test; schema rendering is unified in `DbIndexService` + `_format_table_context` (T13); no runtime path lost coverage.

### Added — W0 intelligence-remediation foundations (2026-07-03, branch `worktree-intelligence-remediation`)

Wave 0 of the intelligence-remediation audit (spec `docs/superpowers/specs/2026-07-03-intelligence-remediation-design.md`).
All 18 tasks committed; ruff/mypy clean; unit+integration suite green at ≥72% coverage.

- **`derive_result` helper** — pure function extracted from `SQLAgent._handle_execute_query`; converts raw connector rows + column list into a `QueryResult`; locks the data-shaping contract for downstream waves.
- **`ResultValidation` façade + `AnswerQualityGate`** — `ResultValidation(data_gate, result_gate, *, reconcile)` composes the three post-query quality checks into one callable; `AnswerQualityGate.evaluate` (async) wraps `AnswerValidator`; both wired into the agent paths.
- **DataGate Decimal/truncation fixes** — `Decimal` values are now `float()`-converted before comparison (was silently skipped → bogus pass); row-level loop `break` replaced with early `continue` so all rows are checked, not just the first suspicious one.
- **C-D schema-capture surface** — `ColumnInfo` gains `object_kind`, `sample_values`, `distinct_count`, `null_pct`; `TableInfo` gains `object_kind`; `SchemaInfo` gains `object_kind`; `DbIndex` model gains `sample_values_json`, `stats_json` columns (Alembic migration `add_dbindex_capture_columns`).
- **`RequestTrace` routing columns + migration** — `approach`, `complexity`, `route_ms` columns added to `RequestTrace` (Alembic migration `add_request_trace_routing_columns`); both migrations chain to a single Alembic head.
- **Chunk metadata + `retrieval_degraded` scaffold** — `ChunkMetadata` dataclass with `source_path`, `heading_path`, `token_count`, `embedding_model`; `retrieval_degraded` flag on `KnowledgeResult`; `KnowledgeFreshnessService` emits `retrieval_degraded_total` counter when flagged.
- **Prometheus counters** — `retrieval_degraded_total`, `datagate_block_total`, `filter_guard_degrade_total` registered in `MetricsCollector`; incremented at the gate call sites.
- **Config defaults hardened** — `max_orchestrator_iterations` default lowered 100→20; `chroma_embedding_model` defaults to `BAAI/bge-base-en-v1.5` (512-token context model); `embedder_max_tokens` default 512.
- **Hotspot decomposition** — `format_query_results`, `format_schema_overview`, `format_table_detail` extracted from `SQLAgent` → `app/agents/result_handler.py`; `_record_request_metrics` extracted from `OrchestratorAgent._run_tool_loop` (partial ORCH-A04; larger decomposition deferred to W3).
- **5 validation-lock tests** — regression tests in `tests/unit/test_validation_locks_w0.py` assert current (known-buggy) behavior for findings RET-R3, SQL-S4, ORCH-A01, VAL-V3, DATA-D2; owning waves must flip assertions when fixing.

### Added — Diagnostics capture (2026-06-30, branch `feat/diagnostics-capture-2026-06-30`)

Make failed queries fully diagnosable after the fact (motivated by the cohort/GROUP BY
incident where the failing SQL, raw DB error and repair-attempt history evaporated). Spec
`docs/superpowers/specs/2026-06-30-diagnostics-capture-design.md`, plan
`docs/superpowers/plans/2026-06-30-diagnostics-capture.md`.

- **`query_failures` table + capture** — every failed/recovered query execution persists its
  full failing SQL, full raw DB error (capped), classified `error_type`, and the complete
  repair-attempt history (`QueryFailure` model + `QueryFailureService`; captured in
  `SQLAgent._handle_execute_query` after the validation loop). Best-effort, off the request
  path, gated by `diagnostics_capture_enabled`. Composes with the GROUP BY classifier:
  `error_type` reads `group_by_violation` and `final_status` shows `recovered` vs `failed`.
- **Sync/background-job flag provenance** — `IndexingRun.meta_json["flags"]` snapshots the
  feature-flag state (git webhook/poll, auto-sync, freshness reconciler, schema-change alerts,
  incremental index) at creation, so "which flag produced this failed run?" is answerable.
- **Self-observability** — the diagnostics layer can no longer fail silently: persistence
  failures increment `diagnostics_persist_failures`, surfaced at `/api/metrics` under
  `diagnostics`.
- **Read API** — owner-gated `GET /api/logs/{project_id}/query-failures` (list + filters) and
  `/query-failures/{id}` (detail with attempts), project-scoped + tenant-isolated; frontend
  analytics client methods added.

Audit note: the existing trace stack (RequestTrace/TraceSpan/ErrorLog/IndexingRun + owner/admin
read APIs + LogsScreen) is mature; verified that SSE backpressure does NOT starve trace
persistence (persistence hooks fire for every event) — no fix needed there.

### Fixed — Orchestrator audit remediation (2026-06-27, branch `fix/orchestrator-audit-remediation-2026-06`)

Remediation of the multi-specialist orchestrator audit (intake → routing → planning →
execution → data acquisition → validation → bad-data/replan loops). TDD throughout
(failing test first); backend suite 4635 passing at 75.39% coverage; ruff/mypy clean;
new `make smoke` startup self-check (6 deterministic tests on the revenue/cohort scenario).

- **CRITICAL — DataGate semantic gate revived.** The advertised LLM-semantic column
  classifier was dead in prod and the keyword heuristic only covered percent/date, so
  impossible values in differently-named columns (e.g. `conversion` 150%) and negative
  counts reached the user. Now token-based classification (snake/camelCase aware, no
  substring false positives like `account`→count / `electric`→ctr), strict bounded-percent
  vs loose signed rates (NRR>100%, deltas, declines allowed), hard-fail on negative counts,
  and the `data_gate_llm_semantics` flag is observable when wired without a classifier.
- **Security — cross-tenant SSE/WS leak closed.** `/ask/stream` and the WS endpoint now
  subscribe to the process-global workflow tracker scoped by `user_id`+project, so a stream
  can no longer relay/latch another user's in-flight workflow events.
- **Correctness/robustness:** budget hard-stop now emits a proper terminal `pipeline_end`;
  the tool loop no longer KeyErrors (and discards the turn) on a duplicate tool-call id;
  history trimming is tool-pair-aware (no orphaned `tool_call`/`tool` → no provider 400);
  the generic error handler returns a typed code instead of raw `str(exc)` (no DSN/host
  leak); `process_data` honors its declared `depends_on` (no scavenging an unrelated
  dataset); deterministic exceptions are no longer retried as transient; replans with
  dangling deps are rejected before wasting the budget; `query_database` truncation is
  surfaced so the LLM doesn't aggregate over a silently-capped set; `row_count` semantics
  are uniform across all four connectors (returned-count + `truncated`).
- **Resource/abuse:** `POST /api/chat/ask` now acquires the `agent_limiter` slot (+timeout),
  closing the only chat entry point that bypassed concurrency/hourly caps; external MCP
  tool calls have a wall-clock timeout; auto-investigation is budget-gated + limiter-bound
  and its verdict is surfaced to the user via a Notification instead of dead-ending.
- **Validation honesty:** AnswerValidator parse failures now respect `answer_validator_fail_closed`
  (were fail-open); planner rejects stages missing `stage_id`/`description` (was an uncaught
  `KeyError` mid-planning) and reports duplicate stage ids clearly.

Remaining lower-severity findings are tracked in `docs/ORCHESTRATOR_AUDIT_2026-06.md`.

### Fixed — Orchestrator audit follow-ups (2026-06-29, branch `fix/orchestrator-audit-followups-2026-06`)

All 21 deferred follow-ups from the orchestrator audit remediated, TDD throughout (one
commit per finding); full unit suite green, ruff/mypy clean. Register:
`docs/ORCHESTRATOR_AUDIT_2026-06.md` (§ Follow-up remediation).

- **Pipeline robustness:** per-pipeline wall-clock budget (`pipeline_max_wall_seconds`) caps
  the compounded retry surface; the unified-loop wall budget is now respected by every
  expensive sub-agent (not just SQL); a `process_data` call batched with a fresh
  `query_database` is deferred so it can't transform the previous turn's stale result; a
  replan that repeats a prior plan (by semantic fingerprint) is rejected instead of burning
  the budget; resume has an in-process duplicate-run guard and sample-only restores are
  flagged `truncated` so a sample is never treated as the full dataset.
- **Query/validation:** transient DB connection errors retry (same query + backoff) rather
  than fail immediately; a clean empty result is returned as success (not a failure) and the
  repairer won't re-run an equivalent query; the dynamic per-query timeout reaches every
  connector's `execute_query` (Mongo gains one); DataGate's value-range hard check scans the
  full in-memory result by default.
- **Routing/recovery:** a question mis-routed `direct` can escape to the tool loop via a
  model-emitted sentinel (router prompt hardened); the router honors a configured
  `router_model` and `estimated_queries` now influences pipeline selection.
- **MCP:** `call_tool` returns a structured `MCPToolCallResult` so a tool-level `isError` is
  surfaced to the LLM instead of read as data.
- **Context/observability:** a hard per-result ceiling caps a fresh tool result at insertion;
  `_workflow_owners` is FIFO-bounded and `_stream_tokens` event count is capped; robust router
  JSON extraction (nested/trailing-safe) with a larger token cap.
- **Quality/correctness:** entity-info lookups are attributed as sources; auto-investigation
  gains `auto_investigate_budget_enforcement_enabled`; reconciliation rejects non-finite
  numbers; `process_data` defaults `min_rows=0`; dependency serialization into prompts is
  field-capped; cross-stage/business-rule checks documented as intentionally advisory.
- **WebSocket:** idle timeout (`ws_idle_timeout_seconds`) closes abandoned sockets; pipeline
  Continue/Modify/Retry actions are now plumbed over the WS transport.

### Fixed — R5: code↔DB sync reliability & correctness (2026-06-25 sync audit)

Closes all 22 findings of the five-specialist code↔DB synchronization audit (9 High, 9 Medium,
4 Low). Branch `fix/sync-remediation-2026-06-25`; 18 TDD tasks; combined suite 4560 passing, 75%
coverage; ruff/mypy clean. Spec `docs/superpowers/specs/2026-06-25-sync-remediation-design.md`,
plan `docs/superpowers/plans/2026-06-25-sync-remediation.md`.

- **Reliability (High):** the daily-sync parent `IndexingRun` now emits a continuous heartbeat
  (targeted `UPDATE`, no `version` lost-update) so the stale-run reaper no longer kills a healthy
  multi-minute sync (**H1**); the daily cron sub-steps **adopt-or-skip** instead of launching an
  untracked concurrent pipeline on an active-run conflict (**H9**); `RunCoordinator.start` translates
  the single-active `IntegrityError` into a clean `RunAlreadyActiveError`/409 with session rollback,
  and the partial-unique active index is mirrored onto the model for `create_all` test parity (**H8**);
  `is_indexed` now only counts `completed`/`completed_partial` (a failed-only index is no longer
  reported as indexed) (**H7**).
- **Data correctness (High):** batch table analyses are reconciled by the LLM-echoed `table_name`
  instead of tool-call position, ending silent cross-table misattribution (**H2**); a malformed
  `confidence_score` degrades only its own table instead of aborting the batch (**H3**); a degraded
  LLM run (mostly fallback) no longer overwrites previously-good sync rows, and low-confidence rows
  no longer enforce/surface required-filter guidance (**H4**).
- **Cost & privacy (High):** sync LLM calls are now metered + budget-gated against the project
  owner (manual triggers 429 on exhaustion; cron degrades gracefully; ownerless projects run
  unenforced) (**H5**); DB sample data + distinct values are scrubbed (column denylist + value
  redaction) before egress to the LLM at both the sync and db-index analyzers, with a per-connection
  `send_sample_data_to_llm` opt-out (default on) (**H6**).
- **Medium:** freshness reconciler now covers all connections, not just the first (**M1**);
  schema-qualified table identity prevents same-named cross-schema tables from collapsing (**M2**);
  the daily-sync parent run advances through manifest steps instead of 0%→100% (**M3**); the cron
  wave honors the per-project schedule hour (**M4**); daily sync regenerates the project overview
  and the worker logs the correct matched count (**M5**); investigation enrichment is routed to a
  non-enforced field and `required_filters` payloads are validated + value mappings deep-merged
  (**M6**); graph-derived `op_kind` heuristics are labelled non-authoritative (over-broad write verbs
  reclassified) (**M7**); freshness `warnings` uses a proper default + a `sync_failed` flag (**M8**);
  `get_index_age` guards a NULL `indexed_at` (**M9**).
- **Low:** the reaper logs a sweep even when the driver returns an unknown rowcount (**L1**); the
  prompt header no longer fabricates an "analyzed" date for a never-completed sync (**L2**); daily
  child-run orphaning is covered by H1+H9 (**L3**); context truncation is marked and relevance
  matching tightened (**L4**).

### Added

- **MCP protocol-polish (F5/F6/F9).** Shipped in three batched releases on top
  of the remote mount. **F6 — error contract:** actionable tool/resource failures
  now raise `ToolError` so MCP clients receive a proper `isError=true` result
  (access denied, not-found, budget-exhausted, safety block, rate-limit, internal
  error) instead of a normal result whose body is an `{"error": …}` string.
  **F5 — structured output:** `checkmydata_ping`, `checkmydata_query_database`,
  `checkmydata_search_codebase`, and `checkmydata_execute_raw_query` return typed
  Pydantic models, emitting `structuredContent` + an auto-generated `outputSchema`
  for machine-parseable results; the three `response_format` list tools stay text
  (a single schema can't cover the json+markdown switch — intentional). **F9 —
  cleanups:** `query_database` prefers an `is_active` connection when defaulting;
  the `project_schema` resource caps aggregation at 500 tables with
  `total_tables`/`truncated`; `sse` is marked deprecated in the CLI help (still
  accepted); the principal is a typed `Principal` `TypedDict`; and the benign
  userless-sync `TracePersistence` "skipping initial persist" log dropped from
  WARNING to DEBUG to quiet prod logs. Plan:
  `docs/superpowers/plans/2026-06-23-mcp-protocol-polish.md`.

- **MCP server: remote multi-tenant HTTP mount.** The MCP server can now be
  mounted into the FastAPI app as an ASGI sub-app at `/mcp` (streamable-HTTP,
  stateless), gated behind **both** `MCP_ENABLED` and the new
  `MCP_MOUNT_ENABLED` (default off — enabling the stdio surface no longer
  exposes the network endpoint). On the mounted transport, every request is
  authenticated **per request**: a pure-ASGI `McpAuthMiddleware` resolves the
  `Authorization: Bearer` token (`cmd_mcp_…` or JWT; `X-API-Key` fallback) to a
  principal carried in a `ContextVar`, so two clients with two tokens resolve to
  two different users — closing the prior gap where the network transport bound
  every caller to one env-configured user. Fails closed (`401` +
  `WWW-Authenticate: Bearer`) on missing/invalid/errored auth. New config:
  `MCP_MOUNT_ENABLED`, `MCP_MOUNT_PATH` (default `/mcp`), `MCP_ALLOWED_HOSTS`
  (opt-in DNS-rebinding Host validation; empty = permissive). Transport runs
  `stateless_http=True, json_response=True` for horizontal scaling. The stdio
  entry point (`python -m app.mcp_server`) is unchanged. New tests prove
  per-request isolation under both sequential and concurrent (`asyncio.gather`)
  load. Design/plan: `docs/superpowers/specs/2026-06-22-mcp-server-hardening-design.md`,
  `docs/superpowers/plans/2026-06-22-mcp-remote-hardening.md`.

### Changed

- **MCP agent tools enforce token budgets + concurrency.**
  `checkmydata_query_database` and `checkmydata_search_codebase` now run the
  shared token-budget gate before invoking the orchestrator (returning an
  upgrade hint when a plan's budget is exhausted), and all three agent-invoking
  tools acquire a per-user slot from the existing `agent_limiter` (concurrency +
  hourly cap, shared with chat). The budget gate logic was extracted from the
  chat route into `UsageService.check_token_budget` so both surfaces share one
  implementation (chat behaviour unchanged). MCP request traces now persist
  under the mount via a runtime trace-service holder, replacing the
  `app.main` reach-through that never resolved in the standalone process.

### Fixed

- **Pipeline checkpoint "Continue / Modify / Retry" buttons were dead.** When a
  multi-stage pipeline paused at a checkpoint (`stage_checkpoint` / `stage_failed`),
  the agent's `viz_config` — which carries `pipeline_run_id` (+ `stage_id`) — was
  built by the backend but **never serialized** into any client-facing response
  (REST `/api/chat/ask`, SSE `/api/chat/ask/stream` `result` event, or the
  WebSocket `response` payload all dropped it). The checkpoint card still rendered
  (its visibility is driven by the separate streaming `checkpoint` event), so the
  buttons appeared, but the frontend never learned `pipeline_run_id`; its resume
  handler (`sendPipelineAction`) guards `if (!pipelineRunId) return`, so every
  click silently no-op'd and the pipeline could not be resumed. Added the
  `viz_config` field to `ChatResponse` and to all three response paths (and the
  matching frontend `ChatResponse` type). New regression tests cover both the
  REST and SSE checkpoint paths.

- Pinned `mcp` to exactly `==1.27.2` (was `>=1.2.0`) for CI reproducibility,
  matching the ruff/mypy pinning convention.

## [1.14.0] - 2026-06-21 - Audit remediation, MCP tokens & sync-workflow reliability

### Added

- **MCP observability + drop-in agent skill.** Every MCP auth attempt, tool
  start/ok/crash, and key-CRUD event now emits a structured log line
  (`MCP auth: …`, `MCP tool <name> starting (user=…)`, `MCP key issued`,
  etc.) — see `docs/MCP_SERVER.md#logging--debugging` for the grep cheatsheet.
  Plaintext tokens are redacted to their 12-char display prefix in every
  log; tests pin that the secret cannot leak. New documentation:
  `docs/MCP_SERVER.md` (full integration guide), `API.md` (token CRUD
  endpoints + rate limits), `backend/.env.example` (per-user vs operator
  modes), `CLAUDE.md` (architecture note). Portable agent skill at
  `.claude/skills/checkmydata-mcp/` with `SKILL.md`,
  `references/client-configs.md` (Claude Desktop, Cursor, OpenAI Agents
  SDK), `references/tools.md` (tool schema reference), and
  `references/troubleshooting.md` (common error → root-cause table) — any
  MCP-aware agent can ingest this folder and learn the full integration
  flow.

- **Per-user MCP API tokens.** Each user can mint their own `cmd_mcp_…`
  tokens (`POST /api/auth/mcp-tokens`) and point Claude Desktop / Cursor /
  any MCP client at them via `CHECKMYDATA_API_KEY`. The MCP `authenticate()`
  flow now resolves a per-user token to the issuing user, so tool calls and
  resources are scoped to that user's project membership — no shared
  service-account binding required. Storage: new `mcp_api_keys` table
  (sha256 hash + display prefix, optional expiry, revocation, last-used
  touch). Routes (JWT/session-authenticated): list/create/revoke; plaintext
  is returned exactly once at creation. Legacy server-level
  `CHECKMYDATA_API_KEY` + `MCP_API_KEY_USER_ID` operator binding remains
  for single-tenant self-hosted setups. Frontend: `McpTokenManager` in the
  Settings panel with create/list/revoke + one-time plaintext reveal and a
  Claude Desktop config snippet. New backend tests cover issuance,
  hashed-lookup, revocation, expiry, the per-user auth path, and the route
  contract (no plaintext leak on list).

- **MCP server best-practices alignment.** All MCP tools now use the
  `checkmydata_*` service prefix to avoid collisions with other MCP servers a
  client may load in parallel. Every tool carries explicit `ToolAnnotations`
  (`readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`) so
  clients can render appropriate confirmation prompts. List tools
  (`list_projects`, `list_connections`, `get_schema`) gained pagination
  (`offset`/`limit` with `has_more`/`next_offset`) and a `response_format`
  switch between `"json"` (default) and `"markdown"`. New `checkmydata_ping`
  tool returns the resolved principal for client smoke-testing. The package
  now re-exports `create_mcp_server`. Tool/resource descriptions, titles, and
  MIME types are filled in for richer client UI. Tests cover annotations,
  pagination, markdown output, and the package export. Server name updated
  from `CheckMyData.ai` to `checkmydata-mcp` per the MCP naming convention.

- **Knowledge pipeline visibility.** New `GET /api/projects/{id}/pipeline-status`
  aggregates repo index, DB index, and code-DB sync state for all project
  members. ARQ worker workflow events are bridged to API SSE via Redis pub/sub
  (`cmd:workflow_events`). Frontend polls pipeline status and seeds
  `ActiveTasksWidget`, Sidebar, ConnectionSelector, and Knowledge Health panel.

- **Heroku worker + Redis TLS.** Production Docker image installs the `[redis]`
  extra (ARQ task queue). `heroku.yml` and CI deploy release both `web` and
  `worker` dynos. Heroku `rediss://` URLs use `ssl_cert_reqs=none` via
  `app/core/redis_tls.py` (redis-py 5.x compatibility).

- **Daily knowledge sync cron.** Opt-in nightly job (`DAILY_KNOWLEDGE_SYNC_ENABLED`)
  at 00:00 Europe/Berlin runs incremental repo index → DB index → code↔DB sync
  for every eligible project (repo + active connections). Results are persisted
  in `knowledge_sync_runs` and logged with the `Cron: daily knowledge sync`
  prefix for monitoring.

- **Sync-workflow reliability (heartbeat + reaper, durable audit, single-flight cron).**
  A set of interlocking features that make background indexing and sync jobs
  crash-proof and observable:

  - *Heartbeat + StaleRunReaper crash recovery:* every DB-index, code↔DB sync,
    and repo-index run now ticks a `heartbeat_at` timestamp on its status row
    every `HEARTBEAT_INTERVAL_SECONDS` (default 30 s). `StaleRunReaper` runs
    in both the web and worker processes every `REAPER_INTERVAL_SECONDS`
    (default 60 s); any `running` row whose heartbeat is older than
    `STALE_RUNNING_HEARTBEAT_TIMEOUT_SECONDS` (default 300 s) is reset to
    `failed`, so a hard worker crash no longer leaves the UI spinning forever.
    Controlled by `REAPER_ENABLED` (default `True`).

  - *Durable daily-sync audit + history endpoint:* the daily knowledge sync now
    records a `knowledge_sync_runs` row with full outcome (per-project status,
    counts, errors) in a crash-safe way — the audit row is written even if the
    job process dies mid-run. New `GET /api/projects/{id}/sync-history` returns
    the last N runs with per-project breakdown (see `API.md`). Frontend: a
    **Sync History** panel in Project Overview shows run timeline, duration, and
    errors.

  - *Single-flight cron via Redis advisory lock:* the daily_sync ARQ cron
    acquires a Redis `SET NX EX` lock before scheduling work so only one
    scheduler instance can trigger a given sync window, eliminating duplicate
    runs on multi-dyno deployments.

  - *Parent `daily_sync` workflow:* a durable ARQ parent task orchestrates each
    project's sync steps (repo → DB → code↔DB) as child tasks, emitting
    per-project progress SSE events and writing the audit row with final status.

  - *Stale-marking gate:* DB-index and sync stale-marking is gated on real
    status changes — a row already at `failed`/`idle` is not touched again,
    preventing spurious `updated_at` bumps and false SSE events.

  - *Unified background-tasks store:* replaced the frontend `task-store` with a
    unified `useBackgroundTasks` Zustand store that reconciles ARQ/SSE events
    and poller results using SSE-provenance precedence — a running SSE event
    cannot be overwritten by a stale poll response.

  API, agent/orchestrator, MCP, connectors/SSH, and billing:
  - *MCP resources auth (P0):* `project://{id}/schema|rules|knowledge` resources
    now resolve a principal and enforce project membership via
    `_require_project_access` — same fail-closed ownership model as MCP tools.
  - *SSH hardening (P0):* default host-key policy is now `tofu` (unknown policy
    values fail closed to `strict`); SSH pre-commands are validated against a
    strict allowlist (`app/connectors/ssh_pre_commands.py`) with metacharacter
    rejection, count/length limits, and validation at both the API layer and
    `ssh_exec`.
  - *Billing end-to-end (P0):* new `plans`/`subscriptions`/`stripe_events`
    tables (+ seeded Free/Pro/Team plans), Stripe Checkout/Customer Portal/
    webhook routes under `/api/billing/*`, `EntitlementService` (plan-derived
    token limits, connection/project quotas with HTTP 402), `BillingService`
    with idempotent webhook event handling, `/pricing` marketing page,
    `PricingTable` + `BillingPanel` UI, and 402-aware frontend API client.
    Token budget gate (`check_budget`) is now wired into all chat entry points
    (HTTP/SSE/WS) with plan-based limits.
  - *Redis-backed limits (P1):* central `app/core/redis_client.py`; slowapi
    rate limiting, `AgentLimiter` (Lua-scripted concurrency slots), and
    `WsTicketStore` (SET EX / GETDEL) all use Redis when configured, with
    in-memory fallbacks for dev.
  - *Sentry (P1):* backend `sentry-sdk[fastapi]` and frontend `@sentry/nextjs`
    initialization with shared PII/secret scrubbing (`app/core/sentry.py`,
    `frontend/src/lib/sentry-scrub.ts`) covering Bearer tokens, API keys,
    cookies, DSNs, and emails.
  - *ClickHouse streaming + health loop (P1):* `ClickHouseConnector` now streams
    row blocks and stops at the row cap instead of materializing full results;
    the background health loop iterates all registered connector pools via the
    new `app/core/connector_pools.py` registry.
  - *Orchestrator tails (P1):* stuck pipelines emit a `stage_failed` tracker
    event; `WorkflowTracker.end` reports the true terminal status;
    `AnswerValidator` fails closed on LLM errors (configurable via
    `answer_validator_fail_closed`).

### Changed

- **Frontend auth is cookie-only:** removed the legacy `localStorage`
  `auth_token` fallback from `_client.ts` / `sse.ts`; all requests rely on
  httpOnly session cookies + CSRF.
- **Next.js security headers:** `next.config.ts` now emits CSP, HSTS,
  `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`, and
  `Permissions-Policy` for the Next shell.
- **Feature flags default-on:** `orchestrator_auto_investigate_enabled`,
  `hybrid_retrieval_enabled`, and `schema_retrieval_enabled` now default to
  `True`; `code_graph_enabled` and `lineage_enabled` remain opt-in.
- **`chat.py` decomposed** (2 855 → ~1 700 lines): session CRUD moved to
  `chat_sessions.py`, feedback/learning-credit endpoints to `chat_feedback.py`,
  and estimate/search/suggestions/explain-sql/summarize to `chat_utility.py`.
  Route URLs are unchanged.

### Removed

- Deprecated legacy modules `app/core/orchestrator.py` and
  `app/core/tool_executor.py` (superseded by `app/agents/*`).

- **Knowledge Architecture roadmap — Phase 0 & Phase 1.** Foundation work toward
  a unified Knowledge Fabric (see `docs/KNOWLEDGE_CATALOG.md`).
  - *Phase 0 (Stabilize & Unify):* the plan-summary routing label now mirrors the
    actual router decision (`RouteResult.use_complex_pipeline` from planner
    signals) instead of the cosmetic table-count heuristic (BACKLOG 10.1); DB
    indexing is dispatched through a single `_dispatch_db_index` helper that uses
    `task_queue.enqueue` (ARQ) when Redis is configured and falls back to
    in-process `asyncio` otherwise, with an ARQ-aware status endpoint that no
    longer false-resets worker-managed runs to `failed`; new `task_queue.is_arq_active()`
    helper; new `docs/KNOWLEDGE_CATALOG.md` artifact-schema & `ContextPack` contract.
  - *Phase 1 (Knowledge Catalog):* new `KnowledgeCatalogService` read-facade and
    `Artifact`/`ContextPack` DTOs (`backend/app/knowledge/context_pack.py`) that
    assemble a structured, traceable bundle (tables+sync notes, lineage,
    learnings, insights, rules, RAG chunks, freshness) from the existing stores
    with per-section graceful degradation. `KnowledgeFreshnessService` now emits
    structured `FreshnessWarningDetail`s carrying a machine-readable
    `recommended_action` (reindex_db / reindex_repo / resync). New
    `GET /api/projects/{id}/knowledge-health` endpoint and a **Knowledge Health**
    UI panel in Project Overview showing artifact counts and one-click
    re-index/re-sync buttons wired to the consolidated execution path.
  - *Phase 2 (Event-Driven Smart Ingestion):* knowledge now refreshes itself
    after a `git push` without user action. All triggers ship OFF by default
    (opt-in flags). New `POST /api/repos/{id}/webhook` endpoint verifies
    GitHub-style `X-Hub-Signature-256` HMAC (and GitLab `X-Gitlab-Token`),
    debounces push bursts (`WEBHOOK_DEBOUNCE_SECONDS`), and enqueues a re-index
    via the consolidated `_spawn_repo_index` dispatcher. A new ARQ task
    `run_repo_index` runs out-of-process when Redis is configured (mirrors the
    in-process path: checkpoint/resume, docs/BM25, overview, auto-sync). A cron
    poll loop (`GIT_POLL_ENABLED` / `GIT_POLL_INTERVAL_MINUTES`) covers repos
    without webhooks by `git fetch` + HEAD comparison. The repo index→sync chain
    is automatic (`AUTO_SYNC_AFTER_INDEX`) via `maybe_autostart_sync`, closing
    the lineage-lag gap. A `FreshnessReconciler` (`FRESHNESS_RECONCILER_ENABLED`)
    in the maintenance loop evaluates `KnowledgeFreshness` per connection and
    auto-dispatches DB re-index / resync / repo re-index when stale. RAG chunks
    now carry temporal metadata (`commit_sha`, `indexed_at`, `source_path`),
    closing the retrieval temporal gap. New `_dispatch_code_db_sync` /
    `maybe_autostart_db_index` consolidate the sync/index dispatch paths.
  - *Phase 3 (Retrieval Stack):* optional cross-encoder reranker
    (`backend/app/knowledge/reranker.py`) as a second stage over fused
    hybrid/schema candidates — lazy model load, graceful no-op when
    `sentence-transformers` is absent (`RERANKER_ENABLED`, `RERANKER_MODEL`,
    `RERANKER_CANDIDATES`). Wired into `HybridRetriever`, `KnowledgeAgent`,
    `ContextLoader`, and a new async `SchemaRetriever.aquery` used by
    `SQLAgent`. New deterministic, LLM-free retrieval-eval harness
    (`backend/app/eval/`: golden set, `hit@k`/`MRR`/context precision·recall/
    `nDCG@k`, threshold gate) with a golden dataset and a CI gate
    (`.github/workflows/ci.yml`).
  - *Phase 4 (Context Planner):* `ContextPlanner`
    (`backend/app/agents/context_planner.py`) turns eager context loading into
    query-aware lazy loading — a `ContextPlan` (needs + per-category limits)
    derived from the question and router signals (`CONTEXT_PLANNER_ENABLED`,
    `CONTEXT_PLANNER_MODE` heuristic|llm, `CONTEXT_PLANNER_BUDGET_TOKENS`).
    `KnowledgeCatalogService.get_context_pack` honours the plan and enriches
    each `Artifact` with a `trust` block (confidence + freshness) via the trust
    layer; `ContextPack` gains `plan`, `all_artifacts()`, and a
    `provenance_summary()` for per-block reasoning transparency.
    `ContextLoader.build_context_pack` is the orchestrator's single entry point.
  - *Phase 5 (Proactive & Cross-Source Intelligence):* proactive
    `schema_change` insights — a DB re-index that detects added/removed/changed
    tables vs the last persisted fingerprint stores an actionable insight
    (`SchemaChangeDetector`, `SchemaChangeAlertsEnabled`), wired into
    `DbIndexPipeline` and surfaced through the existing freshness/insight loops.
    New cross-source foundations (`backend/app/knowledge/cross_source.py`):
    `CrossSourceJoinPlanner` proposes explainable join keys across *different*
    connections (multi-DB JOIN), and `CrossSourceCausalGraph` unions intra-DB
    FK edges with code↔DB lineage into one directed graph answering
    "what feeds / consumes X?" across the code/DB boundary.

- **Pipeline + Admin UX upgrade (Phases 0–4).** Redesigned live pipeline progress
  (`StageProgress`) with `ProgressBar`, icon-based `StatusBadge`, progressive
  disclosure, and `CheckpointCard` data preview. Wired `ToolCallIndicator` during
  active stages; `data_gate` is a first-class SSE event (backend frozenset +
  frontend handler with validating sub-state). Mobile reasoning opens in a bottom
  sheet. Shared UI primitives (`Button`, `Input`, `Card`, `Badge`, `ProgressBar`).
  App shell IA: Setup / Workspace / Operations sidebar groups, deep-linkable
  `?panel=` routes, Project Overview default panel, consolidated Settings, Live
  Activity vs Request History naming, Knowledge hub for Insights/Metrics.
  Custom motion easing tokens in `globals.css` (see DESIGN_SYSTEM §3.2).

Fixes a batch of correctness and lifecycle issues found in a full
business-logic audit of the orchestrator, data integration/storage, and the
self-learning/memory system.

### Fixed

- **Usage Summary "Failed to fetch" on Heroku.** slowapi rate limiting uses Redis
  when `REDIS_URL` is set; Heroku `rediss://` requires `ssl_cert_reqs="none"`
  (same as ARQ/worker). Without it, every rate-limited route (including
  `GET /api/usage/stats`) crashed with SSL verify errors → HTTP 500. Fixed by
  passing `redis_connect_kwargs()` into slowapi `storage_options`.

- **Google sign-in missing on production login page.** Frontend CSP added in
  `next.config.ts` (security headers rollout) blocked Google Identity Services
  (`accounts.google.com` / `apis.google.com` script, connect, and iframe). The
  client ID was baked into the bundle but GIS never loaded, so the login form
  showed email/password only. CSP now mirrors the backend Google OAuth
  allowlist (`script-src`, `connect-src`, `frame-src`, `img-src` for profile
  avatars).

- **Multi-stage chat crash: `WorkflowTracker.emit() got multiple values for
  argument 'status'`.** Every orchestrated request that produced a multi-stage
  execution plan failed with `An unexpected error occurred`. `StageExecutor.
  _emit_stage_result` built an `extra` dict containing a `"status"` key and ALSO
  passed `result.status` positionally to `emit(workflow_id, step, status, ...,
  **extra)`, so `**extra` collided with the positional `status` parameter
  (Python raises a `TypeError` at argument binding). Fixed by dropping the
  redundant `"status"` key from `extra` (the value is already conveyed as the
  positional `status` -> top-level `WorkflowEvent.status` and the SSE payload),
  and updating the frontend `stage_result`/`stage_complete` handler to read the
  top-level `event.status` instead of `extra.status` (value-identical). Closed
  the test gap that let it ship: the `StageExecutor` test tracker now uses
  `create_autospec(WorkflowTracker)` so the real `emit` call signature is
  enforced (plain `AsyncMock(spec=...)` does not), plus a regression test for
  `_emit_stage_result` (success + error). No backend consumer relied on
  `extra.status` (trace persistence uses the top-level `evt.status`).
- **LLM agent outage: Anthropic mid-conversation `system` 400.** Every
  multi-turn chat (and any session with an auto-welcome message) failed with
  `LLMAllProvidersFailedError` -> `400 Bad Request` from OpenRouter for
  `anthropic/*` models. The orchestrator inserted an `--- END OF CONVERSATION
  HISTORY ---` marker as a `Message(role="system", ...)` after the chat history;
  Anthropic (and Bedrock via OpenRouter) reject a `system` role that does not
  immediately follow a user message. Fixed by folding the history-framing
  guidance and the continuation summary into the final user turn instead of
  emitting mid-conversation `system` messages. Added a defensive normalizer in
  the OpenRouter adapter (`_merge_nonleading_system`) that merges any non-leading
  `system` message into the adjacent user turn, making the whole class of bug
  unreachable from any future caller.
- **Planner dict-tool `AttributeError` log spam.** `AdaptivePlanner` passed
  `_CREATE_PLAN_TOOL` (a raw OpenAI function-schema `dict`) where a `Tool`
  dataclass was expected, raising `'dict' object has no attribute 'parameters'`
  on every plan attempt (silenced by a fallback but noisy in logs). Hardened
  `_tools_to_schema`/`_tools_to_anthropic` to accept dict tool specs
  (pass-through / mapped to Anthropic shape) via a new `ToolSpec` type, emit a
  valid `items` clause for `array` parameters (and `properties` for `object`),
  added an optional `ToolParameter.items` field, set explicit array `items` on
  the `git_tools` path params, and dropped the `# type: ignore[list-item]` hacks
  in the planner.
- **Split-domain cookie auth outage (post T-SEC-3).** Browser login broke in
  production because the SPA (`checkmydata.ai`) and API (`api.checkmydata.ai`)
  run on different subdomains while `AUTH_COOKIE_DOMAIN` was empty (host-only).
  The non-httpOnly CSRF cookie set by the API was unreadable by the SPA, so the
  double-submit header was never sent and every cookie-authenticated mutation
  (notably `POST /auth/refresh` during session restore) returned 403, bouncing
  users back to `/login` after a successful Google/email login. Fixed by scoping
  the session + CSRF cookies to the shared parent domain
  (`AUTH_COOKIE_DOMAIN=.checkmydata.ai`). Added a startup guardrail that warns
  when `AUTH_COOKIE_DOMAIN` is empty while serving cross-origin HTTPS SPA
  origins, hardened `clear_session_cookies` to also expire legacy host-only
  cookies, and documented the parent-domain requirement.

### P0 security & reliability (S1/S2 launch-blockers)

Implements the first remediation sprint from the production audit
(`docs/production-plan/00-AUDIT-FINDINGS.md`): the pure-code security and
reliability fixes that unblock any public/paid launch.

- **Query result bounding / MySQL OOM fix (T-ARCH-5).** `MySQLConnector.execute_query`
  now streams via a server-side cursor (`aiomysql.SSDictCursor` + `fetchmany`)
  instead of materializing the full result with `fetchall()`. A shared byte guard
  (`cap_rows_by_bytes`, `MAX_RESULT_BYTES=50MB` in `connectors/base.py`) backstops
  the row cap for wide rows/BLOBs and is applied consistently across the MySQL,
  Postgres, and ClickHouse connectors. `truncated` is reported accurately.
- **CSP + HSTS headers (T-SEC-6).** `SecurityHeadersMiddleware` now emits a
  configurable `Content-Security-Policy` (report-only capable) and
  `Strict-Transport-Security` (HSTS, applied only over HTTPS, proxy-aware via
  `X-Forwarded-Proto`). New `SECURITY_CSP_*` / `SECURITY_HSTS_*` settings.
- **MCP authentication & tenancy (T-SEC-1).** Every MCP tool now requires an
  authenticated principal (no more `mcp-user`/`mcp-anonymous`); project/connection
  ownership is enforced via `MembershipService.can_access` / `list_accessible`,
  `list_projects` is scoped to the caller, the API key is bound to a real platform
  user (`MCP_API_KEY_USER_ID`, compared with `hmac.compare_digest`), and the server
  is off by default (`MCP_ENABLED`), refusing to start unconfigured.
- **WebSocket ticket auth (T-SEC-2).** The chat WS no longer accepts a JWT in the
  URL query string. Clients call an authenticated `POST /api/chat/ws-ticket` to
  mint a short-lived, single-use ticket (`app/core/ws_tickets.py`) and pass it via
  `Sec-WebSocket-Protocol` — credentials never appear in a URL/log.
- **httpOnly cookie session + CSRF (T-SEC-3).** Login/register/Google/refresh now
  set the JWT as an `httpOnly`/`Secure`/`SameSite` cookie plus a readable CSRF
  cookie (`app/core/auth_cookies.py`); `get_current_user` accepts the cookie and
  enforces a double-submit CSRF check on cookie-authenticated mutations. Added
  `POST /api/auth/logout`. `Authorization: Bearer` still works for API clients.
  Frontend stops persisting the token in `localStorage`, sends cookies
  (`credentials: "include"`) + the `X-CSRF-Token` header, and restores sessions
  via refresh.
- **Coverage gate aligned with reality (T-QA-1).** The CI/`pyproject` coverage
  floor is raised from `--fail-under=40` to `72` to match the documented value in
  `README.md`/`CONTRIBUTING.md` (actual combined coverage ~73%); `docs/DEPLOYMENT.md`
  updated to match. New tests cover all of the above (connector bounding + byte
  guard, security headers, MCP auth/tenancy, WS tickets, cookie/CSRF).

### Live Git access + release cohort analysis

Gives the orchestrator live, read-only access to the project's local Git clone
(commit history, diffs, blame, releases, authorship, churn, and commit-trailer
review signals) and a release→cohort bridge so it can correlate releases with
post-release retention/revenue.

- **`GitInspector` service** (`backend/app/knowledge/git_inspector.py`) — async,
  read-only GitPython wrapper: `log`, `show`, `diff`, `blame`, `list_releases`,
  `authors_stats`, `file_churn`, `commits_touching`, `review_signals`. Security
  hardened: explicit arg lists (never `shell`), path-traversal guard
  (`is_relative_to`), output/count limits, no hook execution, binary/non-UTF-8
  safe, and a typed error taxonomy (`RepoNotClonedError`, `InvalidRefError`,
  `PathOutsideRepoError`, `GitCommandFailedError`). Empty/unborn-HEAD repos and
  bad refs are handled explicitly.
- **`GitAgent` sub-agent** (`backend/app/agents/git_agent.py` + `prompts/git_prompt.py`
  + `tools/git_tools.py`) — mirrors `KnowledgeAgent`'s bounded tool-calling loop,
  with a clone-freshness warning (commits ahead of the last indexed SHA), an
  opt-in auto clone-or-pull (`git_agent_auto_pull`), a deterministic
  `get_release_timeline`, and `write_code_note`.
- **Single-loop wiring.** New orchestrator meta-tools `analyze_git`,
  `get_release_timeline`, and `write_code_note` (gated by a `has_repo` capability
  flag threaded through the router, context loader, tool definitions, and
  prompts, exactly like `has_kb`); dispatched to the `GitAgent` via
  `ToolDispatcher`. The router gains a `git` route that downgrades to `explore`
  when no clone is present.
- **Full pipeline wiring.** `analyze_git` is now a first-class planner stage tool
  (`query_planner` validation + `stage_executor._run_git_stage`), enabling the
  release→cohort recipe: `analyze_git` → `query_database` → `process_data`
  (cohort_window) → `synthesize`.
- **`cohort_window` data operation** (`backend/app/services/data_processor.py`) —
  buckets rows into each release's `[release, release+window]` and computes summed
  revenue or distinct-id retention at 7/14-day (configurable) windows. Robust
  date parsing (unparseable rows skipped and counted), empty-window safe, column
  validation. Structured params reach the single-loop `process_data` tool via a
  new `params_json` blob.
- **Code findings persisted to Insight Memory.** Added the `code_finding` insight
  type; `write_code_note` stores durable findings that the context loader already
  auto-injects into future prompts.
- **Bug fix:** `ContextLoader.has_repo` referenced `Path` without importing it,
  so the capability probe always returned `False` (caught by the new unit test).
- **Tests.** New `test_git_inspector.py` (temp-repo + edge cases),
  `test_git_agent.py`, `test_tool_dispatcher_git.py`, plus git-route/plan/stage/
  cohort_window/has_repo cases added to the router, planner, stage-executor,
  data-processor, tools, and context-loader suites.

### Marketing site — narrative, conversion & SEO refine

Repositions the landing and marketing pages around the product's real moat —
correct answers grounded in your schema *and* codebase, self-healing queries,
and institutional memory — and replaces unverifiable social proof with honest,
verifiable trust signals. The cinematic 2.5D system is unchanged; this is a
copy/structure/SEO refine.

- **Hero repositioned to correctness.** H1 now leads with "Correct answers from
  your database — on the first try"; the "Like ChatGPT, but for your database"
  hook is demoted to a small secondary line, and the subhead explains *why* the
  answers are correct (schema + codebase context).
  (`frontend/src/app/(marketing)/page.tsx`)
- **Honest trust signals.** The social-proof bar's unverifiable claims and the
  "Most loved feature" badge are replaced with true signals (MIT open source,
  read-only by default, credentials encrypted at rest, self-host or hosted,
  transparent SQL) plus an optional live GitHub star count that renders only
  when it truly resolves (server-fetched, 1h revalidate, hidden on failure/zero).
- **Moat-first features.** Codebase-aware context is promoted to first; new
  Self-healing queries and Institutional memory cards surface vision-level
  differentiators; all descriptions tightened to benefit-first.
- **New "why the answers are correct" section** (context engine: schema + code +
  rules + memory → validated, dialect-aware SQL) with an honest comparison vs. a
  plain SQL editor and vs. a generic chatbot.
- **Landing FAQ** with objection handling (safety/read-only, vs. ChatGPT, no SQL
  required, what codebase indexing sends, self-host vs. hosted), reusing the
  support accordion pattern.
- **SEO schema & metadata.** Landing JSON-LD now emits `Organization`,
  `SoftwareApplication`, and `FAQPage`; support adds `FAQPage` + `BreadcrumbList`;
  about/contact add `BreadcrumbList`. Meta/OG/Twitter descriptions across the
  landing, about, and root layout are unified around the correctness narrative
  while keeping text-to-SQL / natural-language keywords.
- **Cross-page consistency.** About hero/mission and the footer tagline are
  re-threaded around context/correctness/memory; subtle `cmd-reveal` cohesion
  added to about/support headers (each mounts `CinematicEngine` so reveals
  resolve, with the existing reduced-motion + `<noscript>` failsafes intact).

### Conversational turn isolation & response language

Makes the orchestrator behave like a normal chat partner: it acts only on the
latest user message instead of re-running tasks from earlier turns, and it
replies in the user's language.

- **History is read-only, never re-executed.** The unified tool loop now keeps
  full conversation history for reference but hard-isolates it: a strengthened
  boundary system message states that prior turns are already answered and must
  never be re-run, and a new `CURRENT TURN FOCUS` block in the orchestrator
  prompt reinforces that only the latest message is the task.
  (`backend/app/agents/orchestrator.py`,
  `backend/app/agents/prompts/orchestrator_prompt.py`)
- **Raw SQL stripped from history.** `ChatService.get_history_as_messages` no
  longer echoes the executed `query: SELECT ...` text into assistant history —
  the strongest cue for the model to re-run earlier queries. Result-shape
  metadata (viz, row count, columns, insight/follow-up counts) is preserved.
  (`backend/app/services/chat_service.py`)
- **Per-turn dedup safety net.** New `ToolDispatcher.filter_already_executed`
  skips a data-retrieval call whose question semantically matches one that
  already *succeeded* earlier in the same turn. Gate-flagged and failed calls
  are intentionally not recorded, so corrective re-queries are never blocked.
  (`backend/app/agents/tool_dispatcher.py`, `backend/app/agents/orchestrator.py`)
- **Think in English, answer in the user's language.** A language rule is
  injected at every user-facing synthesis point — orchestrator `PRINCIPLES`,
  direct-response prompt, step-limit synthesis (`build_synthesis_messages`),
  emergency synthesis, and the complex-pipeline `_synthesize` — instructing the
  model to reason internally in English but write the final answer in the same
  language as the user's most recent message. Internal/intermediate prompts
  (planner, router, SQL agent, analysis stage) stay English.

### Google sign-in button disappearing on the login/register page

- **Fixed an init race that hid the Google button.** The Google Identity
  Services init effect on `/login` ran while the page was still in its
  `restoring` state — during which the page renders only a spinner, so the
  button container (`googleBtnRef`) is not mounted. The effect would call
  `renderButton()` against a `null` ref and bail, and (since its deps did not
  include `restoring`) never retry once restore finished. With the GIS script
  already cached — e.g. landing → login warm navigation — the button silently
  vanished. The effect now waits for `!restoring` and re-runs when restore
  completes, so the button reliably renders. The build-time
  `NEXT_PUBLIC_GOOGLE_CLIENT_ID` and CSP were verified correct and were not the
  cause. (`frontend/src/app/login/page.tsx`)
- **Regression tests** cover the warm-navigation race (GIS preloaded + deferred
  restore → button renders after restore) and the no-client-id case.
  (`frontend/src/__tests__/components/LoginPage.test.tsx`)

### Marketing landing — cinematic 2.5D redesign

- **Cinematic landing motion layer (`epic-design`).** The marketing landing now
  has a dark, depth-layered "intelligence" treatment: a drifting technical
  grid, parallax glow blobs, scroll-reveal entrances with stagger, word-lighting
  shimmer on accent headings, and a rising showcase. All built from existing
  semantic design tokens — no color reskin, no image assets, no GSAP.
- **Animated "intelligence core" hero visual.** New `SchemaGraph` (pure SVG +
  CSS) shows database/codebase sources streaming data into a pulsing core that
  emits a verified, charted answer. (`components/marketing/SchemaGraph.tsx`)
- **`CinematicEngine`** client component drives reveals (IntersectionObserver)
  and depth parallax (rAF). Honors `prefers-reduced-motion` (snaps to final
  state, no listeners) and disables parallax on touch (`pointer: coarse`).
  A `<noscript>` failsafe keeps all content visible when JS is off.
- **Design system:** new `cmd-*` cinematic animation catalog documented in
  `DESIGN_SYSTEM.md` §3.2; GPU-safe properties only, all motion neutralized
  under reduced-motion. Scoped to the landing — not for app UI.

### Re-audit remediation

A meta-audit of the audit-remediation changeset surfaced a functional
regression and several correctness gaps that silently negated their own
fixes. These are now fixed, each with a regression test.

- **SSE session lock no longer leaks on normal completion.** The `/ask/stream`
  handler acquired `session_processing_lock(session_id)` but only released it
  on the client-disconnect path; a normally-completing stream left the lock
  held in its 1h-TTL cache, so the session returned `409 Busy` for up to an
  hour. The lock is now released on the normal-completion branch with a
  `finalized` guard so the disconnect and normal paths can't both
  release/persist. (`app/api/routes/chat.py`)
- **Compile-lock eviction race closed.** `_get_compile_lock` could hand out a
  lock and then have it evicted by a concurrent caller (the cap evicted
  *unheld-looking* entries), letting two `_compile_prompt_locked` run for one
  connection. Eviction now tracks an in-flight refcount and never evicts a
  recently-handed-out lock; the bounded cap is preserved.
  (`app/services/agent_learning_service.py`)
- **Binary-skip re-queue is no longer dropped (R3-7).** `state.failed_doc_paths`
  was reassigned (not unioned) late in the run, dropping the binary-skipped
  paths appended earlier; they are now unioned, and binary skips are no longer
  marked processed. (`app/knowledge/pipeline_runner.py`)
- **Stale "suspicious" workflow flag cleared (R5-3).** The result gate set
  `_wf_suspicious[wf_id]` on an over-budget result but never cleared it on a
  later good result, so a subsequent valid query stayed flagged. The flag is
  now popped when the current result is acceptable. (`app/agents/orchestrator.py`)
- **Validation learning credit is idempotent.** A successful answer credited
  exposed learnings, and a following thumbs-up credited them again
  (`apply_learning` is not idempotent), double-bumping `times_applied`; credit
  is now keyed per `message_id` and skipped for results flagged
  `suspicious_result`. (`app/api/routes/chat.py`)
- **Shared SSH tunnels are ref-counted.** Tearing down a tunnel keyed by
  transport identity closed a tunnel still in use by a sibling connection, and
  `delete()` never evicted the connector pool. Tunnels are now ref-counted
  (only torn down at zero refs, unless forced), `delete()` reuses
  `_evict_runtime_caches`, and a metadata-only update with unchanged transport
  identity preserves the tunnel. (`app/connectors/ssh_tunnel.py`,
  `app/services/connection_service.py`)
- **Postgres query timeout no longer poisons the pool.** `asyncio.wait_for`
  cancels mid-cursor; the connection could return to the asyncpg pool in an
  aborted state. On timeout/cancel the connection is now `terminate()`d so the
  pool discards it. (`app/connectors/postgres.py`)
- **Recent-learnings ranking fixed.** `context_loader` fetched the top 15 by
  confidence and *then* sorted by `priority_score`, so high-priority rows past
  the first 15 never surfaced. It now fetches an uncapped pool, sorts by
  `priority_score`, then slices the display count. (`app/agents/context_loader.py`)
- **`process_data` passthrough on the unified path (R5-8).** `_handle_process_data`
  defaulted a missing operation to `""` (→ `ValueError`) while the stage
  executor defaulted to `passthrough`; it now defaults to `passthrough` and
  the tool enum lists it. (`app/agents/tool_dispatcher.py`,
  `app/agents/tools/orchestrator_tools.py`)
- **`completed_partial` indexing is surfaced.** `db_index_service.get_status()`
  now returns `is_partial`, and the connection UI shows an `IDX*` badge plus a
  warning toast so a partial index isn't mistaken for a complete one.
  (`app/services/db_index_service.py`, `frontend/.../ConnectionSelector.tsx`)
- **Reused tables recompute `is_active` from fresh samples.** Incremental reuse
  cloned a possibly-stale `is_active`; it is now recomputed from the fresh
  sample / row count (preserving the prior value only when sampling failed),
  while the LLM analysis is preserved. (`app/knowledge/db_index_pipeline.py`)
- **Code-index incremental correctness (R3-3 / R3-4).** A partial AST parse
  failure no longer purges the failed file's existing graph symbols
  (per-file parse outcome is tracked; failed files are excluded from the merge
  purge set), and a transient-diff fallback to a full re-list now recovers
  deletions by diffing known doc paths against the current tree instead of
  silently leaving `deleted=[]`. `get_head_sha()` in the staleness check also
  runs via `to_thread` instead of blocking the loop.
  (`app/knowledge/pipeline_runner.py`, `app/core/orchestrator.py`)
- **Config hardening.** `SSH_HOST_KEY_POLICY` rejects unknown values
  (`disabled | tofu | strict`), `ORCHESTRATOR_MAX_RESULT_CORRECTIONS` must be
  `>= 0`, and `.env.example` documents the correct SSH policy values. Note:
  `QUERY_EMPTY_RESULT_RETRY` now defaults to `True` (an empty result is treated
  as suspicious and retried once within the correction budget). (`app/config.py`,
  `backend/.env.example`)
- **`cleanup_idle()` is called once.** The shared tunnel manager's idle sweep
  ran once per connector module aliasing it; `main.py` now invokes it a single
  time. (`app/main.py`)
- **Session-note conflict rules aligned with learnings (R4-5).** Note
  reconciliation now uses the strict `>` tie rule and same-polarity conflict
  detection used by learnings, so a verified incumbent can't leave a new
  contradicting note active.

### Indexing integrity

- **Incremental code-graph runs no longer wipe the graph.**
  `CodeGraphService.save()` does a full project-wide delete+reinsert; on an
  incremental run only changed files are parsed, so the graph collapsed to
  that subset and corrupted M5 lineage / M6 clustering for unchanged files.
  Added `save_incremental()` / `_merge_graphs()` that preserve unchanged
  files, replace changed ones, and drop deleted ones; the pipeline runner
  calls it on incremental runs and rehydrates the merged graph for M5/M6.
- **Partial doc-generation failures no longer leave permanent KB holes.**
  Failed paths are persisted (`project_cache.failed_doc_paths_json`, migration
  `68aa15e554e2`) and re-queued into `changed_files` on the next index run,
  then cleared once they succeed.
- **Binary-skipped docs are retried instead of silently lost (R3-7).** A doc
  the `_is_binary_content` heuristic flags is now appended to
  `failed_doc_paths` (and a failure to persist that queue logs at `warning`,
  not `debug`), so a false-positive gets one more attempt on the next run
  instead of being dropped until a forced full re-index.
- **Schema-qualified BM25 doc IDs (R2-6).** The schema-retriever keyed BM25
  docs by the bare lowercased table name, so two same-named tables in
  different schemas (`public.users` / `analytics.users`) collided and one
  became unsearchable. IDs are now `{schema}.{table}`; `metadata["table_name"]`
  stays the bare name for downstream consumers.
- **Worker DB-index path parity (R2-6).** The ARQ `run_db_index` route now
  regenerates the project overview, runs data probes, and surfaces the
  `PARTIAL` evidence status — previously only the in-process fallback did, so
  Redis-backed deployments silently diverged. Index-completion logging also
  reads the returned `tables` key (the old `tables_indexed` never existed and
  always logged `None`).

### Learning / memory lifecycle

- **Compiled-prompt cache invalidation on dedup paths.** Confidence/confirm
  bumps on the exact-hash and fuzzy-dedup paths now invalidate the
  `AgentLearningSummary` cache (previously only new inserts did), so prompt
  ranking no longer served stale order.
- **`times_applied` is live again.** A thumbs-up now credits the learnings
  exposed for that answer as applied (symmetric with the V4 thumbs-down
  contradiction), restoring the ranking and slower-decay signals that had
  degraded to confidence-only because `apply_learning` had no caller.
- **Polarity-aware conflict resolution.** `lessons_contradict()` (negation
  parity + substantive content overlap) runs *before* the fuzzy merge so
  opposite-polarity lessons aren't merged; ties deactivate the older lesson
  and an outranked new lesson is stored inactive so two contradictory lessons
  never both feed prompts.
- **Decay/TTL run on an independent schedule.** A dedicated
  `_maintenance_loop` (`MAINTENANCE_INTERVAL_HOURS`, default 24) runs learning
  + session-note decay and insight TTL/decay regardless of whether backups are
  enabled; session-note decay also runs at startup now.
- **Session-note contradiction reconciliation (R4-6).** `create_note()` now
  runs `_reconcile_contradictions`, reusing the learning-side
  `lessons_contradict` heuristic to penalize (or retire, when the new note is
  verified/stronger) an existing active note that contradicts a new one for
  the same subject+category, so the agent prompt can't carry both sides.
- **Tighter table-scoped note filtering (R4-6).** `get_notes_for_context`
  matches table names on word boundaries (`\btable\b`) instead of a naive
  substring search, so "users" no longer pulls in notes about "power_users".
- **Bounded compile-lock map (R4-6).** The per-connection `_COMPILE_LOCKS`
  dict was unbounded and leaked one `asyncio.Lock` per connection touched over
  a process's lifetime. It's now an `OrderedDict` capped at 512 that evicts the
  oldest *unheld* lock (a held lock is never evicted, so in-flight critical
  sections are safe).

### Retrieval

- **Unified hybrid retrieval.** The orchestrator's pre-loaded knowledge now
  uses the shared BM25⊕Chroma+RRF path (bounded by the previously-dead
  `HYBRID_K`) instead of a Chroma-only lookup. Low-relevance dense hits are
  filtered by `RAG_RELEVANCE_THRESHOLD` before fusion.

### Orchestrator / pipeline

- **Raised the "20" caps.** `MAX_ORCHESTRATOR_ITERATIONS` corrected from 20 to
  the documented 100 (the wall-clock timeout already bounds requests); the
  LLM result preview is no longer hardcoded to 20 rows and reads
  `LLM_RESULT_PREVIEW_ROWS` (default raised 20 → 50).
- **Case-insensitive expected-column validation** removes spurious "missing
  column" stage failures from quoted/lowercased identifiers.
- **Router multi-source signal is acted on.** `needs_multiple_data_sources`
  now also routes to the multi-stage pipeline.
- **Partial data surfaced on `stage_failed`.** The last successful stage's
  query/results are attached and the number of completed stages is noted,
  instead of discarding all progress.
- **`process_data` defaults to `passthrough` (R5-8).** When no operation is
  given the stage executor no longer silently coerces to `filter_data` (which
  could drop rows against intent); it passes data through unchanged. The
  orchestrator's `LLMError` retry check also reads the correct `is_retryable`
  attribute (was the non-existent `retryable`, so retryable LLM errors were
  never retried).
- **`connection_string` + `ssh_host` footgun documented (R1-7).** Supplying a
  raw `connection_string` bypasses SSH tunneling; the combination now warns so
  operators don't assume a tunnel is in effect.

### Knowledge freshness

- `get_head_sha()` no longer blocks the event loop (run via `to_thread`), and
  `count_commits_ahead()`'s `-1` error sentinel no longer surfaces as
  "-1 commit(s) behind".

## [1.13.1] - 2026-06-01

### CI/Deploy Restoration & Toolchain Pinning

Restores a green CI pipeline (and therefore the gated Heroku deploy, which
only runs on `workflow_run` success). CI had been red since early May: the
unpinned dev tooling (`ruff>=0.8.0`, `mypy>=1.13.0`) silently drifted to
newer releases that reformat code and add stricter type rules, so the
`Format check` step failed on commits that never touched the affected files,
and the downstream `Type check`/tests never even ran (fail-fast). Because
`deploy.yml` is triggered by CI success, every Heroku release was skipped.

- **Pinned linters/type-checkers to exact versions** (`ruff==0.15.15`,
  `mypy==2.1.0`) so formatter output and type rules can no longer drift
  between unrelated commits. Bumps are now deliberate.
  (`backend/pyproject.toml`)
- **Reformatted 16 drifted files** with the pinned `ruff` so
  `ruff format --check` passes. Purely cosmetic (line collapsing within the
  100-char limit). (`app/agents/{orchestrator,sql_agent,knowledge_agent}.py`,
  `app/knowledge/{bm25_index,code_db_sync_pipeline,code_graph,graph_db_bridge,hybrid_retriever}.py`,
  `app/models/code_graph.py`, `app/services/code_graph_service.py`, and tests)
- **Resolved 24 `mypy` errors** surfaced by the newer type checker:
  - Fixed a **real runtime bug**: `GET /investigate/{id}` referenced
    `DataInvestigation.current_step`, a column that does not exist, which
    would raise `AttributeError` on every call. The response now mirrors the
    backing `phase` field. (`app/api/routes/data_investigations.py`)
  - Supplied the missing value type-arg on `TTLCache[...]` annotations
    (`app/core/cache.py`, `app/agents/{sql_agent,knowledge_agent}.py`).
  - Switched `Model.__table__.update()` to the typed `update(Model)`
    construct (`app/services/code_graph_service.py`).
  - Added the established `# type: ignore[attr-defined]` for SQLAlchemy
    `Result.rowcount` in the two services that lacked it; disambiguated
    reused loop variables; narrowed dynamic tree-sitter node/grammar types;
    removed three now-unused `# type: ignore` comments.
- **Made the `pg_dump` backup test hermetic.** `test_pg_dump_failure`
  patched `subprocess.run`, but the code pipes `pg_dump` into `gzip` via
  `subprocess.Popen`, so the patch was a no-op and the test only passed when
  a `pg_dump` binary happened to be installed (it errored otherwise). It now
  patches `subprocess.Popen` and is deterministic.
  (`backend/tests/unit/test_backup_manager_extended.py`)
- **Bumped GitHub Actions to their Node 24-native majors**
  (`checkout@v5`, `setup-python@v6`, `setup-node@v6`, `cache@v5`,
  `upload-artifact@v7`) ahead of the June 2 2026 Node 20 deprecation.
  (`.github/workflows/ci.yml`, `.github/workflows/deploy.yml`)
- **Stabilized flaky `RulesManager` frontend tests.** The `Save` button is
  rendered inside a `FormModal` gated on `editingId`; under CI load the
  default real-timer `userEvent` typing interleaved with the modal's focus
  effects and intermittently closed the editor mid-test. Switched the
  interactive tests to the recommended `userEvent.setup({ delay: null })`
  pattern so interactions flush synchronously inside `act()`.
  (`frontend/src/__tests__/components/RulesManager.test.tsx`)

Full suite remains green (3,178 backend unit + 470 backend integration +
400 frontend); combined backend coverage 73%.

## [1.13.0] - 2026-05-19

### Vision Invariants & Correctness Restoration

This release closes four vision invariant violations and six critical
correctness bugs identified during the post-1.12.x cross-subsystem audit.
Every change is paired with focused unit tests; full suite remains green
(3,648 backend / 400 frontend, up from 3,599 / 400 baseline). The release
is single-feature in spirit: it makes the system actually behave the way
vision.md, SYSTEM_ARCHITECTURE.md, and the README have been claiming it
behaves.

### Vision invariants restored

- **V1 — Per-connection learning isolation by default.** A lesson learned
  on connection A is no longer silently injected into prompts for
  connection B. `AgentLearningService.compile_prompt()` now gates
  `_get_cross_connection_learnings()` and `promote_global_patterns()`
  behind the new `CROSS_CONNECTION_LEARNINGS_ENABLED` flag (default
  `False`). The old behavior, where two unrelated databases in the same
  project could poison each other's learnings, is now opt-in for
  homogeneous-schema customers. (`backend/app/services/agent_learning_service.py`,
  `backend/app/config.py`, `backend/.env.example`,
  `backend/tests/unit/test_agent_learning_service.py::TestCompilePromptCrossConnection`)
- **V2 — Continuous learning on every outcome, not just every retry.** The
  `len(attempts) < 2` gate that suppressed learning extraction on
  first-shot successes and first-shot failures is removed from both
  `SQLAgent._extract_learnings` and `ToolExecutor._extract_learnings`. The
  `LearningAnalyzer` cooldown is reduced from 1 h to 5 min, a lightweight
  heuristic `_extract_first_shot_success_signal` captures
  "what worked the first time" patterns (e.g., soft-delete filters, key
  joins), and lesson persistence is unified through `_persist_lessons`.
  The system now learns from every attempt, not only from messy ones.
  (`backend/app/agents/sql_agent.py`, `backend/app/core/tool_executor.py`,
  `backend/app/knowledge/learning_analyzer.py`,
  `backend/tests/unit/test_learning_analyzer_extended.py`,
  `backend/tests/unit/test_sql_agent.py`)
- **V3 — Staleness warning threaded through the complex pipeline.** The
  freshness banner used to die at the orchestrator boundary: planner LLM
  calls and stage-executor sub-agents never saw it. Both
  `AdaptivePlanner._llm_plan` / `replan` and `StageExecutor.execute` now
  accept a `staleness_warning` argument and prepend it to their own
  system / stage prompts, so every LLM call in the complex pipeline —
  initial plan, re-plan, every stage, final synthesis — sees the
  freshness block, not just `_run_tool_loop`. (`backend/app/agents/orchestrator.py`,
  `backend/app/agents/adaptive_planner.py`,
  `backend/app/agents/stage_executor.py`,
  `backend/tests/unit/test_adaptive_planner_staleness.py`,
  `backend/tests/unit/test_stage_executor.py::TestStalenessInjection`)
- **V4 — Negative feedback overrides prior learnings.** Assistant
  responses now record which learnings were exposed in their system
  prompt via `AgentResponse.exposed_learning_ids`, the chat route writes
  the list into message metadata on both the synchronous and SSE paths,
  and the `/feedback` endpoint reads it back. On a thumbs-down, the new
  helper `contradict_exposed_learnings_on_negative_feedback` calls
  `contradict_learning(...)` on each ID (capped to avoid cascades), so
  the very next turn no longer trusts the lessons that produced the bad
  answer. (`backend/app/agents/orchestrator.py`,
  `backend/app/core/agent.py`, `backend/app/api/routes/chat.py`,
  `backend/tests/unit/test_negative_feedback_contradiction.py`)

### Critical correctness fixes

- **C1 — Git rename handling.** `GitTracker.get_changed_files` switched
  from `R=True` to `M=True` on `repo.commit(...).diff()` so renames are
  detected with the correct `--find-renames` semantics; old paths are
  classified as `deleted` and new paths as `changed`, fixing a class of
  silent drift between the indexed graph and the working tree.
  (`backend/app/knowledge/git_tracker.py`,
  `backend/tests/unit/test_git_tracker.py`)
- **C2 — `generate_docs` resilience.** Per-doc LLM failures used to
  abort the indexing pipeline. `pipeline_runner.generate_docs` now uses
  `asyncio.gather(..., return_exceptions=True)` with per-doc retry, and
  only fails the whole step when the failure ratio exceeds the new
  `GENERATE_DOCS_MAX_FAILURE_RATIO` setting (default `0.3`). One bad
  file no longer takes the whole index down. (`backend/app/knowledge/pipeline_runner.py`,
  `backend/app/config.py`, `backend/.env.example`,
  `backend/tests/unit/test_generate_docs_resilience.py`)
- **C3 — Chroma failure policy.** The vector-store health check used to
  treat "Chroma collection is empty" and "Chroma is unreachable"
  identically, causing partial re-indexes on transient network blips.
  The check now distinguishes the two: an empty-but-reachable collection
  forces a full re-index, while an unreachable Chroma warns and
  preserves the previous `last_sha` so the next pipeline run resumes
  cleanly when the service comes back. (`backend/app/knowledge/pipeline_runner.py`,
  `backend/tests/unit/test_pipeline_chroma_failure_policy.py`)
- **C4 — `DataGate.fail()` path.** Out-of-range percentages and dates
  were classified as warnings, so plainly impossible numbers reached the
  final synthesis. `_check_value_ranges` now calls `outcome.fail()` on
  hard violations when `DATA_GATE_HARD_CHECKS_ENABLED` (default `True`)
  is on, blocking obviously wrong results before they're rendered.
  (`backend/app/agents/data_gate.py`, `backend/app/config.py`,
  `backend/.env.example`, `backend/tests/unit/test_data_gate.py`)
- **C5 — Read-only `get_agent_learnings`.** Loading learnings for a
  prompt used to mutate `times_applied`, conflating "the LLM saw it"
  with "the LLM used it." A new `times_exposed` column (Alembic
  migration `f0a1b2c3d4e5_add_times_exposed_to_agent_learning`) tracks
  exposure separately, `SQLAgent._track_exposed_learnings` calls the new
  `expose_learning` service method, and the exposed IDs are stashed into
  `ctx.extra["exposed_learning_ids"]` for V4 to pick up. `times_applied`
  is now reserved for confirmed application by the learning analyzer.
  (`backend/app/models/agent_learning.py`,
  `backend/app/services/agent_learning_service.py`,
  `backend/app/agents/sql_agent.py`,
  `backend/app/alembic/versions/f0a1b2c3d4e5_add_times_exposed_to_agent_learning.py`)
- **C6 — Insight expiry + decay actually run.** `InsightRecord.expires_at`
  and the `decay_stale_insights` job existed but nothing called them.
  The new `_periodic_insight_maintenance` task runs on every backup-cron
  tick (~24 h) and once on startup, calling `expire_old_insights` and
  `decay_stale_insights`. Insight TTL+confirmation semantics now
  actually happen. (`backend/app/main.py`,
  `backend/tests/unit/test_periodic_insight_maintenance.py`)

### Config additions

| Setting | Default | Purpose |
|---|---|---|
| `CROSS_CONNECTION_LEARNINGS_ENABLED` | `False` | Opt-in for cross-connection learning transfer + global pattern promotion (V1). |
| `GENERATE_DOCS_MAX_FAILURE_RATIO` | `0.3` | Per-doc LLM failure ratio at which `generate_docs` aborts (C2). |
| `DATA_GATE_HARD_CHECKS_ENABLED` | `True` | When true, out-of-range percent/date checks call `outcome.fail()` instead of `warn()` (C4). |

### Schema

- `agent_learnings.times_exposed INTEGER NOT NULL DEFAULT 0` — added via
  Alembic revision `f0a1b2c3d4e5`.

### Tests

- **Backend**: 3,648 passing (up from 3,599 baseline). 49 new tests added
  across `test_adaptive_planner_staleness.py`,
  `test_stage_executor.py::TestStalenessInjection`,
  `test_negative_feedback_contradiction.py`,
  `test_generate_docs_resilience.py`,
  `test_pipeline_chroma_failure_policy.py`, `test_data_gate.py`,
  `test_periodic_insight_maintenance.py`, plus updates to
  `test_agent_learning_service.py`, `test_sql_agent.py`,
  `test_learning_analyzer_extended.py`, `test_git_tracker.py`,
  `test_orchestrator.py`.
- **Frontend**: 400 passing (unchanged — release is backend-only).

## [1.12.3] - 2026-05-18

### Changed — Documentation actualization (no code, no schema, no flag flips)

A docs-only pass that closes every doc-vs-code gap surfaced during the
post-1.12.2 Heroku audit, plus consolidates the M1-M6 follow-ups into the
strategic backlog so they stop living only inside the rollout playbook.

**Doc-vs-code accuracy fixes**

- **`docs/SYSTEM_ARCHITECTURE.md` §2.4** rewritten — the old narrative
  pointed at `app/agents/intent_classifier.py::classify_intent()` and
  `prompts/orchestrator_prompt.py::build_classification_prompt()`, none of
  which exist. Routing now goes through the unified LLM router in
  `backend/app/agents/router.py` (`_build_router_prompt()`,
  `route_request()`, `RouteResult` dataclass with `route` + `complexity`
  in a single call). Section reflects the actual route list (`direct` /
  `query` / `knowledge` / `mcp` / `explore`) and complexity tag.
- **`ARCHITECTURE.md` Knowledge Indexing Flow** reordered to match
  `pipeline_runner.py`: `ast_parse` and `graph_build` (M1+M2) now precede
  `analyze_files` / EntityExtractor instead of being listed after. Added
  `record_index` final step, the `CodeGraphService.load_graph()`
  rehydration path that fires on M5/M6 resume, and the
  `services/indexing_artifacts.py` cleanup contract on project/connection
  delete.
- **`ARCHITECTURE.md` module table** — extended the `knowledge/` and
  `services/` rows with the modules that shipped during M1-M6
  (`pipeline_runner.py`, `db_index_pipeline.py`, `ast_parser.py`,
  `code_graph.py`, `bm25_index.py`, `hybrid_retriever.py`,
  `schema_retriever.py`, `code_db_sync_analyzer.py`,
  `code_graph_service.py`, `knowledge_freshness_service.py`,
  `indexing_artifacts.py`).
- **`docs/ROLLOUT_M1_M6.md` §2.1** — replaced an invalid + unsafe SQL
  smoke command (`xargs -I{} psql {} -c "… COUNT(*) FROM a, COUNT(*) FROM
  b …"`, which both leaked `DATABASE_URL` into `ps` and was malformed
  SQL) with `heroku pg:psql -a checkmydata-api -c "SELECT (SELECT
  COUNT(*) FROM …) …"` using subqueries.
- **`docs/ROLLOUT_M1_M6.md` §2.5** — renamed prose `has_clusters` →
  `has_code_clusters` to match the actual identifier in
  `sql_agent.py` / `sql_prompt.py` / `sql_tools.py`.
- **`docs/ROLLOUT_M1_M6.md` §4.2** — converted the brittle line-anchored
  cleanup-PR table (`pipeline_runner.py:406`, `sql_agent.py:1887`, …) to
  stable `grep -n "<predicate>"` markers so the inventory survives normal
  line drift.
- **`docs/MASTER_TEST_PLAN.md`** — fixed `POST /api/chat/stream` →
  `POST /api/chat/ask/stream` (the actual route in
  `backend/app/api/routes/chat.py`).
- **`README.md`** — `LEARNING_ANALYZER_MODE` default `hybrid` →
  `llm_first` (matches `backend/app/config.py:225`); test count `3,309
  total` → `3,999 total (3,129 backend unit + 470 backend integration +
  400 frontend)` (verified via `pytest --collect-only`); added the
  `make rollout-check` row to the Development Commands table; added a
  paragraph each on `indexing_artifacts.py`, the `staleness_warning`
  injection, and the `graph_callers` lineage rendering in the M1-M6
  summary section.
- **`CHANGELOG.md` 1.x historical entry** — corrected
  `learning_analyzer_mode` default note from `"hybrid"` to `"llm_first"`
  for consistency with code.

**New documentation (shipped behavior that previously had no docs)**

- **`docs/SYSTEM_ARCHITECTURE.md` §2.6.1 — Knowledge Freshness Warning
  Injection** — describes how `KnowledgeFreshnessService.check_staleness()`
  feeds a `KNOWLEDGE FRESHNESS WARNINGS` block into both the simple
  tool-calling loop and the multi-stage pipeline orchestrator messages,
  with the code-graph-conditional behavior gated by
  `settings.code_graph_enabled`.

**Backlog consolidation (BACKLOG.md, ROADMAP.md)**

- **`BACKLOG.md` Sprint 8 — M1-M6 rollout completion** (P0, blocked by
  2-week per-flag soak): seven tasks covering the five default flips and
  the post-soak cleanup PR (flag-gate removal + prompt-builder kwarg
  removal), with an explicit non-removal list (preserve
  `_dense_only_search`, ABC stubs, per-request flag overrides).
- **`BACKLOG.md` Sprint 9 — Test coverage gaps** (P2): eight tasks
  covering the full-pipeline E2E with a real fixture repo, incremental
  indexing, binary-file filtering, hybrid-retrieval relevance smoke,
  `KnowledgeDocs` / `WorkflowProgress` component tests, a11y matrix
  execution + fixes, and the 72% → 80% coverage threshold flip.
- **`BACKLOG.md` Sprint 10 — Documented "for now" debts** (P2/P3): seven
  tasks covering the planner-LLM table-routing replacement, optional
  Chroma extension for `SchemaRetriever`, incremental per-file
  code-graph updates, multi-language receiver-type resolution,
  multi-repo cross-repo code graph, and the
  `query_empty_result_retry` / `data_gate_llm_semantics` opt-in flags.
- **`ROADMAP.md`** — new "Architectural Debt & Rollout-Gated Cleanups"
  subsection pointing at the rollout playbook and Sprints 8/9/10 so a
  casual roadmap reader finds the M1-M6 story.

**Heroku audit snapshot (informational, no action)**

- Release **v129** (`b13f530`), web dyno up 10h+, `/api/health` = 200.
- 38h of production logs (1500 lines): **0** app-level WARNING / ERROR /
  CRITICAL / exception lines from `app[web.1]`.
- Router warnings limited to expected SSE client disconnects (`H27`) on
  `/api/workflows/events`; 1 × `H18` over 38h (single 1133s SSE backend
  interruption — not a defect).
- No production fix needed; documentation was the only out-of-sync piece.

### Notes

- **No** source edits under `backend/app/**` or `frontend/src/**`.
- **No** Alembic migrations, **no** schema changes.
- **No** `heroku config:set`, **no** flag flips, **no** dyno restart.
- The M1-M6 feature flags still default to `False` per [docs/ROLLOUT_M1_M6.md](docs/ROLLOUT_M1_M6.md); the operator drives the rollout (see Sprint 8).

## [1.12.2] - 2026-05-17

### Added — M1-M6 rollout playbook

Closes the final M1-M6 plan item (`rollout`). Every milestone has shipped
to production (v129, commit `b13f530`); all five feature flags still
default to `False`. This release ships the operator-facing artifacts to
safely flip them.

- **`docs/ROLLOUT_M1_M6.md`** — per-flag canary criteria, smoke tests,
  daily soak metrics with healthy/alarm bands, rollback commands, and a
  precise file:line inventory of the legacy branches the post-soak
  cleanup PR will delete (plus an explicit "do not delete" list for the
  load-bearing fallbacks like `_dense_only_search` and the
  `relevance_score` safety net).
- **`make rollout-check`** — one-command production health snapshot
  (flag state, dyno state, `/api/health`, and `code_graph_*` counters
  via JSON `/api/metrics`). Accepts `ADMIN_TOKEN` and `HEROKU_APP`
  overrides for staging.
- **README** — links to the playbook from the M1-M6 feature section.

The rollout itself (`code_graph_enabled` → `hybrid_retrieval_enabled` →
`schema_retrieval_enabled` → `lineage_enabled` → `clustering_enabled`,
each with a 2-week soak) is the operator's job from here. The status
table at the bottom of `ROLLOUT_M1_M6.md` is the canonical record.

## [1.12.1] - 2026-05-15

### Fixed — M1–M6 integration audit

Concrete bugs + wiring gaps surfaced by an end-to-end audit of the
M1–M6 code-intelligence pipeline against the consumer-facing surfaces
(orchestrator, SQL agent, knowledge agent, CodeDbSyncAnalyzer). Each
flag now flips cleanly to `True` without leaking artifacts or silently
serving stale data.

- **Broken `get_settings` import** in `db_index_pipeline.py` schema-embed
  step would have silently aborted M4 the moment `schema_retrieval_enabled`
  flipped to `True`. Replaced with the canonical `settings` singleton.
- **Orphan artifact lifecycle**: `ProjectService.delete`,
  `ConnectionService.delete`, and `DbIndexService.delete_all` now invoke a
  new `app/services/indexing_artifacts.py` helper to wipe the BM25 `.pkl`
  snapshots (code corpus + schema) and the ChromaDB collection that used to
  outlive their parent Postgres rows.
- **Checkpoint integrity**: `bm25_build` and `graph_clustering` now only
  call `complete_step` on actual success. A failed step no longer fools a
  later resume into thinking the artifact is fresh.
- **Code graph rehydration on resume**: when `ast_parse` collects no files
  (incremental run) or `graph_build` raises, `state.code_graph` was `None`
  and M5/M6 silently skipped. `CodeGraphService.load_graph` now reconstructs
  the in-memory `CodeGraph` from persisted rows so lineage + clustering can
  still run from existing data.
- **Staleness warning now reaches the LLM**: the orchestrator's unified
  tool loop appends a `KNOWLEDGE FRESHNESS WARNINGS` section to the system
  prompt, and the complex pipeline path now computes the same signal
  instead of passing `None`.
- **`graph_callers` rendered in `KnowledgeAgent`**: `_format_entity_detail`
  surfaces the M5 lineage block (caller name / file / endpoint kind / op
  kind / confidence) when `lineage_enabled=True`.
- **Prompts taught the new capabilities** so the model actually uses them:
  - `sql_prompt.py` documents question-aware ranking (M4), the
    `Lineage (top callers)` block (M5), and the `get_tables_in_cluster`
    tool (M6).
  - `knowledge_prompt.py` explains hybrid retrieval (BM25 ⊕ vectors fused
    via RRF) and the entity lineage section.
  - `code_db_sync_analyzer.py` system prompt instructs the LLM to derive
    `required_filters` / `column_value_mappings` from the new "Code
    callers" section.
  - `get_query_context` tool description now describes question-aware
    table ranking and the inline lineage block.
- **`MetricsCollector.snapshot_counters(prefix=...)`** + JSON `/api/metrics`
  now exposes `code_graph_*` counters without scraping Prometheus.
- **Tests**: 6 new integration assertions in `test_indexing_e2e.py` cover
  prompt rendering, entity-detail lineage, code-graph rehydrate, cleanup
  idempotency, and metrics prefix filtering. Suite total: 3,309.

## [1.12.0] - 2026-05-11

### Added — In-house code intelligence pipeline (M1–M6)

A GitNexus-inspired layer that augments (does not replace) our existing 5-pass
ORM/SQL pipeline. All milestones ship behind feature flags and degrade
gracefully to legacy behavior when disabled.

- **M1 — AST parser**: `app/knowledge/ast_parser.py` wraps `tree-sitter` +
  `tree-sitter-language-pack` to extract `Symbol` / `ImportRef` / `CallSite` /
  `ParsedFile` records for Python, JS/TS, Go, Java, Ruby, PHP, C#. File-size
  guard, binary/minified detection, parse-error ratio threshold, async
  semaphore in the pipeline. Flag: `code_graph_enabled`.
- **M2 — Code knowledge graph**: `app/knowledge/code_graph.py` two-pass
  builder produces a NetworkX `CodeGraph` (CALLS/IMPORTS/EXTENDS edges with
  confidence scores). Persisted via `app/services/code_graph_service.py` to
  new `code_graph_symbols` + `code_graph_edges` tables (Alembic
  `d8e9f0a1b2c3`).
- **M3 — Hybrid retrieval**: `app/knowledge/bm25_index.py` (rank_bm25 with
  code-aware tokenizer + atomic snapshots on disk) and
  `app/knowledge/hybrid_retriever.py` (BM25 ⊕ Chroma fused with Reciprocal
  Rank Fusion, soft timeouts, graceful single-leg degradation).
  `KnowledgeAgent._handle_search_knowledge` now uses the hybrid path when
  `hybrid_retrieval_enabled=true`. Flag: `hybrid_retrieval_enabled`.
- **M4 — Question-aware table resolution**:
  `app/knowledge/schema_retriever.py` builds a per-connection BM25 snapshot of
  LLM-enriched schema docs. `SQLAgent._build_query_context` unions retrieved
  tables with the legacy `relevance_score >= 2` safety net, bounded by
  `sql_agent_max_context_tables`. Flag: `schema_retrieval_enabled`.
- **M5 — Code→DB lineage**: `app/knowledge/graph_db_bridge.py` walks the code
  graph outward from each entity, classifies callers as
  `http`/`cli`/`migration`/`service` and ops as `read`/`write`, decays
  confidence with depth, and writes the top-N refs onto
  `EntityInfo.graph_callers`. Consumed by `CodeDbSyncAnalyzer` and rendered
  by `SQLAgent._format_table_context`. Flag: `lineage_enabled`.
- **M6 — Functional clustering**: `app/knowledge/code_clustering.py` runs
  Louvain community detection on the weighted CALLS+IMPORTS graph,
  optionally LLM-labels clusters in batches of 10, and persists to a new
  `code_clusters` table (Alembic `e9f0a1b2c3d4`). SQL agent exposes a new
  `get_tables_in_cluster` tool. Flags: `clustering_enabled`,
  `cluster_llm_label_enabled`.
- **Observability**: `KnowledgeFreshnessService` now surfaces a
  `code_graph_symbol_count` signal (warns when the graph is empty).
  `MetricsCollector` grew a generic `inc()` / `add()` API; new counters:
  `code_graph_symbols_total`, `code_graph_edges_total`,
  `code_graph_lineage_refs_total`, `code_graph_clusters_total`,
  `code_graph_builds_total`. Visible via `/api/metrics` and
  `/api/metrics/prometheus`.

### Added (files)
- `backend/app/knowledge/ast_parser.py`, `code_graph.py`, `bm25_index.py`,
  `hybrid_retriever.py`, `schema_retriever.py`, `graph_db_bridge.py`,
  `code_clustering.py`.
- `backend/app/models/code_graph.py` (extended with `CodeCluster`).
- `backend/app/services/code_graph_service.py` (extended with cluster ops).
- Alembic migrations `d8e9f0a1b2c3_add_code_graph_tables.py`,
  `e9f0a1b2c3d4_add_code_clusters_table.py`.
- Tests: `tests/unit/test_ast_parser.py`, `test_code_graph.py`,
  `test_bm25_index.py`, `test_hybrid_retriever.py`, `test_schema_retriever.py`,
  `test_graph_db_bridge.py`, `test_code_clustering.py`,
  `test_entity_info_graph_callers.py`; integration:
  `tests/integration/test_code_graph_service.py`,
  `test_schema_retriever_integration.py`,
  `test_graph_db_bridge_integration.py`, **`test_indexing_e2e.py`** (full
  M1→M6 chain).

### Changed
- `backend/pyproject.toml`: pinned `tree-sitter>=0.23.0,<0.24` +
  `tree-sitter-language-pack>=0.7.3,<1.0`, added `networkx`, `rank-bm25`.
- `backend/app/agents/knowledge_agent.py`: hybrid retrieval branch
  preserving the legacy "no relevant" / "no sufficiently relevant" message
  distinction.
- `backend/app/agents/sql_agent.py`: schema-retriever union, lineage
  formatting, cluster lookup tool wiring.
- `backend/app/agents/tools/sql_tools.py`: new
  `GET_TABLES_IN_CLUSTER_TOOL` (gated by `has_code_clusters`).
- `backend/app/knowledge/entity_extractor.py`: `EntityInfo.graph_callers`.
- `backend/app/knowledge/code_db_sync_pipeline.py`: caller groups in the
  code-context prompt.
- `backend/app/services/knowledge_freshness_service.py`: empty-graph signal.
- `backend/app/core/metrics.py`: generic `inc`/`add` API.
- `backend/.env.example` & `app/config.py`: new flags
  `code_graph_enabled`, `ast_parse_concurrency`, `ast_max_file_bytes`,
  `ast_parse_error_ratio`, `code_graph_max_symbols`,
  `code_graph_call_confidence_threshold`, `hybrid_retrieval_enabled`,
  `bm25_data_dir`, `hybrid_rrf_k`, `hybrid_min_score`, `hybrid_k`,
  `schema_retrieval_enabled`, `sql_agent_max_context_tables`,
  `lineage_enabled`, `lineage_max_depth`, `clustering_enabled`,
  `cluster_llm_label_enabled`.

### Notes
- All flags default `false` for a 2-week soak. Per-feature rollout planned;
  legacy paths will be deleted in a separate cleanup PR once the new
  pipeline holds in production.

## [1.11.0] - 2026-05-05

### Changed — AI-First Refactor: Infra & Deploy (T33–T40)
- **Multi-stage backend image (T33)**: `Dockerfile.backend` now builds deps in an isolated builder stage and ships them through a venv into a minimal runtime; added `HEALTHCHECK` against `/api/health`. `.do/app.yaml` aligned with DigitalOcean's `$PORT` convention (`http_port: 8080`) and the platform health-check schedule.
- **DB indexes (T34)**: Alembic `c7d8e9f0a1b2` adds `ix_connections_project_id` and `ix_projects_owner_id` to back the `list_by_project` / `get_accessible_projects` hot paths. SQLAlchemy models declare `index=True` for parity.
- **Config drift guard (T35)**: rewrote `backend/.env.example` to mirror every `Settings` field (commented when optional); added `TestEnvExampleSync` to fail CI if a new setting forgets a doc entry. `Settings._validate_production_secrets` now also rejects short JWTs (<32 chars), `DEBUG=true`, and `*` in `CORS_ORIGINS`. New `_validate_numeric_ranges` validator fences invalid percentages, learning-analyzer mode, and default LLM provider.
- **CI hardening (T36)**: `ci.yml` now caches HuggingFace / sentence-transformer downloads + pytest cache + Next.js build cache, runs unit and integration tests under a single `coverage append` flow, enforces a combined coverage gate (`--fail-under=40`), uploads the combined `coverage-combined.xml` as an artifact, and uses concurrency cancellation per ref.
- **Test gap closure (T37)**: added `frontend/src/__tests__/usePolling.test.tsx` (6 cases: interval, leading, disabled, max-duration cap, unmount cleanup, error swallowing) and `frontend/src/__tests__/pipeline-event-handlers.test.ts` (11 cases covering every SSE event type → state transition).
- **Regression sweep (T38)**: full backend (`3007 unit + 453 integration`) and frontend (`400 vitest`) suites green. Updated `test_edge_cases.py` and `test_routes_coverage.py` to grant admin via `monkeypatch.setattr(settings, "admin_emails", …)` for routes hardened in T01/T03.
- **Deploy (T39–T40)**: green release pushed to Heroku; production rollout guarded by combined CI coverage gate + container HEALTHCHECK.

### Added
- `backend/alembic/versions/c7d8e9f0a1b2_add_tenancy_hot_path_indexes.py`.
- `frontend/src/__tests__/usePolling.test.tsx`, `frontend/src/__tests__/pipeline-event-handlers.test.ts`.

## [1.10.0] - 2026-05-01

### Changed — AI-First Refactor (T01–T32)
- **Security & tenancy (P0)**: backup router admin/owner enforcement with 403 tests, project-scoped usage stats, SSE/workflow tenancy hardening, `project_service.update` mass-assignment whitelist, fixed `insight_feed` sample-size bug and `models` route OpenRouter fallback.
- **AI-first reasoning (P1)**: replaced heuristics with LLM-driven flows in `learning_analyzer`, `data_gate`, `stage_validator`, `suggestion_engine`, `default_rule_template`, `feedback_pipeline`, `orchestrator`, `tool_dispatcher`, `viz_agent`. Added structured `span_type` to all trace producers and consolidated chart rules into `app/viz/chart_rules.py`.
- **Performance (P2)**: parallelized sequential LLM/IO via `asyncio.gather`, eliminated N+1s (delete_stale_tables, list_projects roles, ClickHouse introspect), batched GeoIP/phone lookups, shared connector-per-batch in `batch_service`. Added `TTLCache` for `SESSION_LOCKS`, health state, SSH tunnels, and workflows. Replaced `SequenceMatcher` with embedding-based similarity (`text_similarity.semantic_similarity`/`semantic_best_match`). Moved bcrypt to `asyncio.to_thread`. Migrated `IndexingCheckpoint` from JSON-rewrite to append-only `indexing_checkpoint_step` / `indexing_checkpoint_doc` tables (Alembic `b6c7d8e9f0a1`).
- **Architecture (P3)**: split `chat.py` into `cost_estimation_service` + `chat_response_builder`, split `connections.py` into `connection_learnings`, split `data_validation.py` into `data_investigations`. Centralized magic numbers in `app/config.py`. Standardized Pydantic `response_model` (`OkResponse`, `OkWithIdResponse`, `AckWithCountResponse`). LLM adapters now classify errors via structured codes/types instead of substring matching.
- **Frontend (P4)**: split `lib/api.ts` (1794 lines) into `lib/api/{_client,types,auth,projects,connections,chat,workspace,analytics,index}.ts` while preserving the `@/lib/api` import surface. Extracted helpers from `ChatPanel` (`pipeline-event-handlers.ts`) and `ConnectionSelector` (`connection-form-helpers.ts`). Added unified `usePolling` hook with visibility-aware backoff and tightened `useGlobalEvents` reconnect lifecycle. Introduced zod (`lib/schemas/workflow-event.ts`) for runtime DTO validation. Design system pass: replaced raw palette classes with semantic tokens, added `--color-error-hover` and `--color-accent-strong`.

### Added
- `app/services/text_similarity.py` — embedding-first similarity helpers with `difflib` fallback.
- `app/services/cost_estimation_service.py`, `app/services/chat_response_builder.py` — extracted chat helpers.
- `app/api/schemas/common.py` — shared Pydantic response models.
- `app/api/routes/connection_learnings.py`, `app/api/routes/data_investigations.py` — split routers.
- `app/viz/chart_rules.py` — consolidated chart-validation rules.
- Backend Alembic `b6c7d8e9f0a1_add_append_only_checkpoint_tables`.
- Frontend `hooks/usePolling.ts`, `lib/schemas/workflow-event.ts`, `components/chat/pipeline-event-handlers.ts`, `components/connections/connection-form-helpers.ts`.

## [1.9.0] - 2026-04-13

### Changed
- **Orchestrator audit & improvement plan implementation** — completed the full multi-phase improvement program covering conversation handling, error handling, SQL planning, data/knowledge layer, observability, and long-term refactors.

#### Phase 3 — Error handling parity
- Centralized LLM retry/back-off via shared `llm_call_with_retry` helper.
- Stage-error normalization (`_stage_error_message`, `_classify_stage_error`); `StageResult` now carries `error_category` (`transient | configuration | data_missing | fatal`) and a `retryable` property.
- Pipeline `AgentResponse` now correctly populates `error` and supports a `degraded` synthesis status with `degraded_reason`.
- `LLMAllProvidersFailedError.is_retryable = False` (no infinite provider thrash).
- Parallel tool-call errors are typed (`tool_call:error` events with structured `error_type`).

#### Phase 4 — Planner/executor improvements
- Removed the legacy `QueryPlanner` class (`AdaptivePlanner` is now the sole planner).
- `_MAX_REPLANS` moved to `settings.max_pipeline_replans`.
- Replan history is threaded into `build_replan_prompt` so the LLM avoids repeating failed approaches.
- Repair context (`ContextEnricher.build_repair_context`) now includes attempt error type and longer query/error excerpts.
- Stage executor implements topological scheduling with `pipeline_max_parallel_stages` for safe parallel stage execution.

#### Phase 5 — Data/knowledge layer
- **Insight expiry & dedup (D1, D2):** `InsightRecord.expires_at` is now set per severity; `_find_duplicate` uses title+description+type+severity; `expire_old_insights` reaper added.
- **Unified learning API (D12):** `AgentLearningService.get_learnings(...)` consolidates the previous getters with category/table/confidence/limit filters.
- **Unified freshness (D6):** new `KnowledgeFreshnessService` combines DB-index age, code↔DB sync status, and Git HEAD into a single `staleness_warning`.
- **Note deactivation (D5):** `SessionNote.deactivated_at` column + `decay_stale_notes` now deactivates notes whose confidence drops below `deactivate_below`. Alembic migration `a5b6c7d8e9f0_add_deactivated_at_to_session_notes` ships the column.
- **Structured tool responses (D14):** `_handle_record_learning` and `_handle_write_note` return JSON (`{"status": "ok"|"rejected", ...}`) so the LLM can parse outcomes and retry.
- **RAG pre-query (D13):** `ContextLoader.load_relevant_knowledge` injects the top-K relevant KB chunks into the orchestrator context for every question.
- **Insight reconciliation (D15):** `InsightMemoryService.reconcile_with_query_results` auto-confirms reproduced anomalies and dismisses stale ones.
- **Insight injection (D11):** `ContextLoader.load_relevant_insights` surfaces the top active insights for the orchestrator prompt.

#### Phase 6 — Quality and observability
- **Answer validator (S11):** new `AnswerValidator` LLM-based quality gate replaces the `len > 80` heuristic when step / wall-clock limits are hit. Toggle via `answer_validator_enabled`.
- **Metrics (X2):** new `MetricsCollector` records per-request route / complexity / response_type / replans / retries / SQL calls / wall clock. Exposed at `/metrics` (recent rows) and `/metrics/prometheus` (text exposition format).
- **Settings group (X1):** new `AgentSettingsView` dataclass (accessible via `settings.agent`) groups all agent-related thresholds into a single typed view.
- **End-to-end tests (X5):** added integration coverage for the question → router → complex pipeline → stage failure → replan → success path.

#### Phase 7 — Long-term
- **LLM-first learning analyzer (D10):** new `learning_analyzer_mode` setting (`heuristic | hybrid | llm_first`); the analyzer now falls back to (or leads with) the LLM extractor while keeping the legacy `_detect_*` rules as a fast pre-filter.
- **ClickHouse EXPLAIN warnings (S5):** `ExplainValidator` now parses ClickHouse plan text and warns on full MergeTree scans without `PREWHERE`/`WHERE` and on unbounded result sets.
- **Token-aware synthesis budget (S8):** `ResponseBuilder.build_synthesis_messages` now budgets data inclusion by real token estimates (`LLMRouter.estimate_tokens`) instead of a `chars / 4` heuristic.

### Added
- `pipeline_max_parallel_stages` config (default `3`).
- `answer_validator_enabled` config (default `True`).
- `learning_analyzer_mode` config (default `"llm_first"`).
- `KnowledgeFreshnessService`, `AnswerValidator`, `MetricsCollector`, `AgentSettingsView` modules.
- `/metrics/prometheus` endpoint.
- Alembic migration `a5b6c7d8e9f0_add_deactivated_at_to_session_notes`.
- New unit tests: `test_answer_validator.py`, `test_metrics_collector.py`, `test_knowledge_freshness_service.py`.

### Removed
- `QueryPlanner` class (legacy plan-decomposition path).
- Hardcoded `_MAX_REPLANS` constant in `orchestrator.py`.

## [1.8.0] - 2026-04-14

### Changed
- **LLM-driven agent architecture refactor** — eliminated hardcoded heuristics, keyword matching, and rigid decision logic across the entire agent system, empowering the LLM to make all routing, complexity, tool selection, and budget decisions based on context
- **Unified LLM router** (`router.py`) — replaces `intent_classifier.py` and `AdaptivePlanner._is_complex()` with a single LLM call that determines route, complexity, approach, estimated queries, and multi-source needs
- **Unified tool loop** — merged `_run_data_query`, `_run_knowledge_query`, `_run_mcp_query` into a single `_run_unified_agent` that provides all available tools to the LLM without intent-gated tool surface restrictions
- **Dynamic budget management** — replaced rigid synthesis deadlines (`orchestrator_synthesis_reserve_steps`, `orchestrator_synthesis_time_ratio`, `orchestrator_max_query_db_calls`) with per-iteration budget injection; the LLM self-regulates based on step/time percentages with emergency synthesis at 90% threshold
- **LLM-driven visualization** — `VizAgent` now delegates all chart type selection to the LLM, replacing `_rule_based_pick()` with a minimal `_edge_case_fallback` for degenerate cases only
- **LLM-driven SQL table/rule handling** — removed `_auto_detect_tables`, `_filter_rules`, `_extract_warning_tag` from `sql_agent.py`; the LLM receives the full table map and all custom rules directly
- **LLM-driven query repair** — `retry_strategy.py` now passes raw error details and schema context to the repair LLM instead of pre-generated hint templates per error type
- **Semantic tool deduplication** — `tool_dispatcher.py` uses word-overlap similarity (Jaccard, threshold 0.8) instead of exact string matching
- **Simplified prompts** — `orchestrator_prompt.py` and `sql_prompt.py` replaced rigid behavioral rules (TOOL CALL ECONOMY, SINGLE-QUESTION RULE, STEP BUDGET, ERROR RECOVERY, QUERY PLANNING, SELF-IMPROVEMENT PROTOCOL) with concise PRINCIPLES sections, letting the LLM decide approach
- **Removed `_parse_process_data_params` heuristics** — `stage_executor.py` no longer infers operations from description keywords; operation must be explicit in `input_context`

### Removed
- `table_resolver.py` — LLM + table map handles resolution
- `_COMPLEXITY_KEYWORDS`, `_TEMPORAL_PATTERN`, `_DIMENSION_KEYWORDS`, `_CONJUNCTION_WORDS` from `adaptive_planner.py`
- `detect_complexity`, `detect_complexity_adaptive` from `query_planner.py`
- `build_classification_prompt` from `orchestrator_prompt.py`
- `max_simple_query_steps`, `orchestrator_synthesis_reserve_steps`, `orchestrator_synthesis_time_ratio`, `orchestrator_max_query_db_calls` config settings

### Added
- `agent_emergency_synthesis_pct` config setting (default: 0.90) — budget threshold for emergency synthesis
- `router_model` config setting — optional model override for the routing LLM call

## [1.7.0] - 2026-04-14

### Changed
- **Always-deliver orchestrator (two-phase loop)** — the orchestrator tool-calling loop now operates in two phases: Phase 1 (data gathering) runs tool calls normally, and Phase 2 (mandatory synthesis) strips all tools from the LLM call, guaranteeing a text response. The system automatically enters Phase 2 when step budget (`orchestrator_synthesis_reserve_steps`, default 2) or time budget (`orchestrator_synthesis_time_ratio`, default 65%) is mostly consumed. This eliminates the "Analysis reached step limit" dead-end: even when resources are exhausted, the system always produces a complete, professional answer from whatever data was gathered
- **Time-budget propagation to sub-agents** — the orchestrator now threads `remaining_wall_seconds` through `ToolDispatcher` to the SQL agent. The SQL agent caps its per-query timeout at `min(query_timeout_seconds, remaining_wall * 0.5)` (floor: 5s), preventing a single slow query from consuming the entire time budget
- **Smarter synthesis prompt** — `ResponseBuilder.build_synthesis_messages` now includes ALL SQL query results (not just the last one), with query explanations and insights. The prompt instructs the LLM to produce a complete, professional analysis without mentioning step limits or partial results
- **Graceful response_type on budget exhaustion** — when synthesis produces a valid answer and at least one SQL result has data, the `response_type` is set to `sql_result` instead of `step_limit_reached`, giving users a normal-looking answer rather than a warning banner
- **Expanded complexity detection** — `AdaptivePlanner._is_complex` now recognizes temporal ranges ("last N months"), comparison keywords ("which performed better", "vs"), and multi-dimensional analysis patterns ("by payment method", "by region"). Revenue analysis queries that previously ran through the flat tool loop now get the more robust multi-stage pipeline
- **Continuation budget boost** — `continue_analysis` runs receive 50% more steps and wall-clock budget, reducing the chance of hitting limits again during continuation
- **Lighter repair queries on timeout** — when a SQL query times out and enters the repair loop, the repair hints now explicitly instruct the LLM to produce a lighter query (add LIMIT, remove unnecessary JOINs, narrow date ranges, use approximate aggregations)
- **Two-phase step budget prompt** — the orchestrator system prompt STEP BUDGET section updated to describe the two-phase model, instructing the LLM to maintain a running analysis so it can synthesize from partial data at any point
- **`query_database` cap raised to 3** — new `orchestrator_max_query_db_calls` setting (default 3, up from hard-coded 2) allows richer multi-query analyses

### Added
- `orchestrator_synthesis_reserve_steps` config setting (default: 2) — steps reserved for the synthesis phase
- `orchestrator_synthesis_time_ratio` config setting (default: 0.65) — fraction of wall-clock time after which synthesis begins
- `orchestrator_max_query_db_calls` config setting (default: 3) — configurable cap on `query_database` calls per request
- `wall_clock_remaining` parameter on `SQLAgent.run()` for time-aware query timeout capping

## [1.6.1] - 2026-04-08

### Fixed
- **Rule schema validation now functional** — `validate_rules_against_schema` no longer requires a `previous_tables` diff (which was never supplied). Instead it scans rule content for underscore-delimited identifiers not present in `known_tables`, detecting stale table references without needing a before/after comparison
- **Table resolution for complex queries** — `_run_data_query` now computes `table_hints` before the complexity check, so complex queries also benefit from programmatic table resolution instead of silently skipping it
- **`build_resolution_hints` logic** — fuzzy NOTEs are no longer suppressed when some tables matched exactly; unresolved-term WARNINGs are now always emitted regardless of whether other terms were resolved
- **Reasoning state cleanup on stream errors** — `handleSend` error handler, `handleStop`, and session-switch `useEffect` now finalize reasoning traces and clear `streamingMsgIdRef`, preventing orphaned traces and memory leaks
- **Reasoning store memory bounds** — traces are capped at 20 (evicting oldest on overflow), steps per trace capped at 200, and `clearAllTraces` action added for session resets. `closePanel` now also clears `activeMessageId`
- **ReasoningButton always visible** — moved out of the metadata-metrics conditional block so it appears for all assistant messages that have a reasoning trace, not only those with row_count/execution_time/token_usage
- **ReasoningButton render efficiency** — store selector narrowed from `s.traces` (entire object) to `!!s.traces[messageId]` (boolean), eliminating unnecessary re-renders when other traces update
- **`handleSend` useCallback deps** — added `reasoningInitTrace`, `reasoningFinalize`, `reasoningAddStep` to the dependency array

## [1.6.0] - 2026-04-08

### Added
- **Programmatic table resolution** — new `table_resolver.py` with `resolve_tables()` heuristic that matches user question terms against known tables via exact, plural/singular, substring, and keyword-to-description matching. Generates prompt-injectable warnings for unresolved terms. Wired into `_run_data_query` and `_run_full_pipeline` as a soft-nudge before the tool-calling loop
- **QUERY PLANNING rule 5** — orchestrator prompt now mandates `ask_user` when TABLE RESOLUTION WARNINGS are present, preventing the LLM from guessing at unknown tables
- **RULE FRESHNESS CHECK** — new prompt section (only when custom rules are loaded) instructs the orchestrator to compare query results against loaded rules and propose updates via `manage_rules` when discrepancies are detected
- **Schema-aware rule validation** — `RuleService.validate_rules_against_schema()` detects rules referencing tables that were dropped during schema refresh; wired into `POST /connections/{id}/refresh-schema` alongside existing learning validation
- **Execution plan visibility** — `plan_summary` event emitted from orchestrator (tables, strategy, rules_applied, learnings_applied, has_warnings); forwarded via SSE; rendered as a collapsible `PlanSummaryCard` in the chat thinking area
- **Agent Reasoning Panel** — new slide-out right-side panel (`ReasoningPanel.tsx`) showing full orchestrator internals: plan summary, thinking log, step-by-step timeline with icons and durations, rules and learnings applied. Brain icon on each assistant message toggles the panel
- **Reasoning store** — new `reasoning-store.ts` (Zustand) collecting per-message reasoning traces from SSE events during streaming, with trace finalization and temp-to-real message ID mapping
- **ToolCallIndicator wired into ChatPanel** — previously unused component now renders active tool calls as badges below the thinking area
- **`agent_start`/`agent_end` SSE events forwarded** — enriched with `extra` metadata and consumed by the frontend SSE parser as step events for the reasoning panel

### Changed
- Orchestrator prompt `build_orchestrator_system_prompt` now accepts optional `table_hints` parameter
- `_run_tool_loop` accepts optional `table_hints` parameter and emits `plan_summary` before the loop starts
- SSE pipeline events set extended with `plan_summary` in both backend (`chat.py`) and frontend (`api.ts`)
- `app/app/page.tsx` layout includes `ReasoningPanel` alongside `NotesPanel` in the right-side slot

## [1.5.4] - 2026-04-03

### Fixed
- **Custom rules ignored by orchestrator and SQL agent** — custom rules were never proactively injected into system prompts; they relied entirely on the LLM choosing to call optional tools (`get_custom_rules`, `get_query_context`), which was frequently skipped. Now rules are loaded via `CustomRulesEngine` and injected directly into both `build_orchestrator_system_prompt` and `build_sql_system_prompt` with budget-aware truncation (2000 chars for orchestrator, 3000 chars for SQL agent). The `ContextBudgetManager` `rules_text` slot (10% of budget) is now wired into the orchestrator's `_run_tool_loop`. An efficiency hint in the SQL prompt tells the LLM not to re-fetch rules via the tool when they're already in the prompt

## [1.5.3] - 2026-04-03

### Fixed
- **Intent classifier parse error resilience** — `_parse_classification_response` now uses a three-tier extraction strategy: (1) direct `json.loads`, (2) regex-based `{...}` extraction for JSON with trailing text, (3) plain-text intent name recovery. Previously, LLM responses with trailing text or without JSON structure caused `parse_error` fallback to `MIXED` intent, leading to unnecessary full-context loading and slower responses
- **Pipeline continuation crash protection** — `json.loads` calls on `stage_results_json` / `user_feedback_json` in `orchestrator.py` now wrapped in try/except, returning a user-friendly error instead of crashing when pipeline state is corrupted
- **Complexity classifier logging** — `query_planner.py` now logs at WARNING level when the LLM returns non-JSON for complexity classification, making parse failures visible in production logs

### Changed
- **Intent classifier logging promoted** — parse_error and invalid_intent logs elevated from DEBUG to WARNING level for production visibility on Heroku

## [1.5.2] - 2026-04-03

### Added
- **Hard step limits by query type** — simple data queries capped at 4 steps (`max_simple_query_steps`), global max reduced from 100 to 12 (`max_orchestrator_iterations`). Wrap-up injection fires 1 step before limit
- **`query_database` call cap** — after 2 `query_database` calls in a single request, a hard system message is injected and the tool is stripped from the tool list, forcing the LLM to compose a final answer
- **Multilingual complexity keywords** — `_COMPLEXITY_KEYWORDS` extended with Russian, Spanish, German, and Portuguese equivalents; conjunction words in `_is_complex` heuristic now include multilingual variants
- **Per-viz timeout** — each `viz.run()` call wrapped with `asyncio.wait_for(timeout=viz_timeout_seconds)` (default 15s); catches `TimeoutError` and `CancelledError` with graceful fallback to table visualization
- **Empty-answer guard** — all `_run_tool_loop` exit paths now check for empty `final_text`; when the LLM returns empty content but SQL results exist, `build_partial_text` is used as a fallback to guarantee a visible response
- **Viz deduplication** — `viable_sql` is deduplicated by query text before the viz loop; duplicate queries keep only the result with more rows, preventing redundant viz calls
- **`_stream_tokens` on all exit paths** — step-limit and synthesis-failure branches now always stream final text to the client, fixing silent empty responses

### Changed
- **Orchestrator prompt strengthened** — TOOL CALL ECONOMY, SINGLE-QUESTION RULE, and STEP BUDGET sections now explicitly instruct the LLM to combine sub-queries into one comprehensive SQL call; hard limit of 2 `query_database` calls stated in prompt
- **`orchestrator_wrap_up_steps` default** changed from 2 to 1 for earlier wrap-up injection
- **Config** — new settings: `max_simple_query_steps` (4), `viz_timeout_seconds` (15); `max_orchestrator_iterations` reduced from 100 to 12

## [1.5.1] - 2026-04-02

### Added
- **Agent Learning quality gates** — blocklist for SQL keywords/metadata subjects (`columns`, `tables`, `information_schema`, `pg_catalog`, etc.), minimum lesson length (15 chars), non-ASCII ratio rejection (>50%), and normalization (whitespace cleanup, capitalization, max 500 chars). Write-time validation via `validate_learning_quality()` and read-time filtering via `skip_blocklisted` flag
- **Schema cross-validation** — `validate_learnings_against_schema()` deactivates learnings whose subject no longer exists in the DB schema. Runs automatically on schema refresh and available as manual `POST /connections/{id}/learnings/validate-schema` endpoint
- **Learning confirm/contradict API** — `POST /connections/{id}/learnings/{lid}/confirm` (upvote) and `POST /connections/{id}/learnings/{lid}/contradict` (downvote) endpoints with RBAC (editor+). Votes immediately invalidate the compiled prompt cache
- **Audit script** (`scripts/audit_learnings.py`) — production database learning audit tool with dry-run and apply modes; diagnoses blocklisted subjects, short lessons, and high non-ASCII content
- **Orchestrator request summary logging** — each request now logs `request_summary` with step count, wall clock time, SQL call count, response type, and error types
- **RulesManager view mode** — viewers can now click rules to read them in a read-only modal; editors get dirty-state tracking with disabled Save button when unchanged

### Changed
- **Accelerated confidence decay** — never-applied learnings (times_applied=0) lose 0.05 per 30-day cycle vs 0.02 for applied ones, enabling faster cleanup of unproven learnings
- **Orchestrator hardened wrap-up** — time limit and step limit messages use stronger "CRITICAL" directive; hard wall-clock cutoff tightened from 1.5x to 1.2x to prevent excessive overruns
- **Table map propagation** — orchestrator now sets `context.table_map` from the loaded table map when not already set, fixing downstream stages receiving empty table maps

### Fixed
- **Vote cache invalidation** — `confirm_learning()` and `contradict_learning()` now call `_invalidate_summary()` to clear the compiled prompt cache immediately after voting
- **Blocklist filtering on read** — `get_learnings()` and `get_learnings_for_table()` now skip blocklisted subjects by default, catching legacy bad data that was stored before write-time validation

## [1.5.0] - 2026-04-01

### Added
- **AdaptivePlanner** — replaces heuristic + LLM complexity detection with a unified planner that generates quick (deterministic) plans for simple queries and LLM-driven plans for complex ones. Supports `recent_learnings` injection
- **DataGate** — intermediate data-quality validator between pipeline stages. Checks null rates, type consistency, duplicate rows, value ranges, truncation, and cross-stage consistency
- **Replan loop** — when a pipeline stage fails after retries, the orchestrator asks the `AdaptivePlanner` to generate a new plan (up to 2 replans) that avoids the failed approach and reuses completed results
- **PipelineLearningExtractor** — extracts lessons from pipeline events (replans, DataGate failures, validation failures) and stores them via `AgentLearningService` for future planning
- **ToolDispatcher** — extracted from `OrchestratorAgent`; centralizes all meta-tool dispatch logic
- **ResponseBuilder** — extracted from `OrchestratorAgent`; centralizes response assembly and synthesis
- **ContextLoader** — extracted from `OrchestratorAgent`; lazy-loads table maps, KB, learnings, staleness
- **Per-stage `max_retries`** — each `PlanStage` can define its own retry budget; `StageExecutor` respects it over the global setting
- **`replan_on_failure` flag** — per-stage control over whether a failed stage triggers replanning
- **Replan prompt** — `build_replan_prompt` in `planner_prompt.py` provides context about completed stages and the failure to guide replanning
- **Pipeline learning categories** — `pipeline_pattern`, `data_quality_hint`, `replan_recovery` added to `AgentLearningService`

### Changed
- **Orchestrator slimmed** — `orchestrator.py` reduced from 2728 to ~1760 lines by extracting `ToolDispatcher`, `ResponseBuilder`, and `ContextLoader`
- **`StageExecutor` unified validation loop** — now runs `StageValidator` then `DataGate` after each stage, with retry and replan signals
- **Complexity detection** — replaced dual `detect_complexity` + `detect_complexity_adaptive` with `AdaptivePlanner._is_complex` (single deterministic check, no extra LLM call)
- **Pipeline planning** — `_run_complex_pipeline` now uses `AdaptivePlanner._llm_plan` instead of `QueryPlanner.plan`, with learnings injected into the prompt

## [1.4.0] - 2026-04-01

### Added
- **Compound SQL responses** — when a user asks multiple questions in one message, each SQL result now gets its own chart, "View SQL Query" section, and insights card. Previously only the last SQL result was shown
- **`SQLResultBlock` dataclass** — new structured type for individual SQL results with their own viz_type, viz_config, and insights
- **`SQLResultSection` React component** — extracted reusable component for rendering per-query SQL viewer, chart toggle, visualization, data table, and insight cards
- **`sql_results` field** on `AgentResponse`, `ChatResponse`, SSE event, and `ChatMessage` — carries the array of compound results end-to-end from orchestrator to frontend
- **VizAgent runs per-result** — each SQL result in a compound response gets its own visualization recommendation instead of only the last one

## [1.3.2] - 2026-04-01

### Changed
- **Agent step limits raised** — `max_orchestrator_iterations` 25 → 100, `max_sql_iterations` 3 → 15, `agent_wall_clock_timeout_seconds` 90 → 300. Prevents premature termination on complex queries or slow LLM responses
- **Wall-clock timeout now uses distinct message** — hard timeout fallback produces "I reached the processing time limit" instead of the misleading "maximum number of analysis steps" message (via new `_build_timeout_text` method)
- **Timeout sets `response_type` correctly** — `wall_clock_timeout_hit` flag ensures `response_type = "step_limit_reached"` when the wall-clock cutoff fires (previously fell through as `"sql_result"`)

### Fixed
- **SSE stream closing before agent finishes** — `stream_timeout_seconds` 120 → 360, `stream_safety_margin_seconds` 90 → 120 (total 480s). The old SSE deadline of 210s was shorter than the new 300s agent timeout, causing premature "Request timed out" errors and agent task cancellation

## [1.3.1] - 2026-03-31

### Fixed
- **CI lint fixes** — resolve 24 ruff errors: `IntentType` migrated from `(str, Enum)` to `StrEnum` (UP042), unused `ClassifiedIntent` imports removed (F401), import blocks sorted (I001), line-length violations fixed (E501), local variable naming corrected (N806), format inconsistencies resolved

## [1.3.0] - 2026-03-31

### Fixed
- **8 bugs**: Clarification requests no longer swallowed in parallel tool execution; double `tracker.end()` eliminated from complex pipeline fallback, pipeline resume, and `_run_data_query`/`_run_full_pipeline` paths; intent classifier no longer crashes on JSON array responses; `KnowledgeAgent._collected_sources` moved from instance state to per-run local to prevent concurrency corruption; `MCPSourceAgent` adapter now restored after each `run()` call; `loop_budget` aligned with `max_context_tokens` cap (was using raw model window); `StageContext.from_persistence` now warns when resumed data is truncated

### Changed
- **Dedup extended to all data tools** — `_dedup_tool_calls` now deduplicates `search_codebase` and `query_mcp_source` in addition to `query_database`. Removed error-prone history-based substring dedup (prompt-level guidance is more reliable)
- **Viz fallback uses structured data** — `ValidationOutcome.fallback_viz_type` replaces fragile string-matching on warning text; viz type set in `validation.py` consolidated (viz_agent imports from validator)
- **Context immutability** — all intent-path methods now use `replace(context, ...)` instead of mutating `context.chat_history` in-place
- **Symmetric tool scoping** — `_run_data_query` no longer exposes MCP tools (matching `_run_mcp_query` which doesn't expose DB tools); mixed intent still exposes all
- **MCP plan validation** — `query_mcp_source` added as valid data-retrieval tool in `_validate_plan_structure`, enabling MCP-only complex plans
- **Pipeline responses include metadata** — `_build_pipeline_response` now populates `token_usage`, `tool_call_log`, `steps_used`, `steps_total`
- **MCP connection hoisted out of retry loop** — `_handle_query_mcp_source` lookups DB once, then retries only the LLM/tool calls
- **MCP source check cached** — `_has_mcp_sources` now caches results per project for 60s
- **Config defaults tuned** — `max_context_tokens` raised from 16K to 32K; `rag_relevance_threshold` lowered from 1.3 to 0.8; `"then"` keyword tightened to `" then "` to reduce false-positive complexity detection

### Added
- **`list_rules` tool** — LLM can now list existing project rules to discover IDs before update/delete (resolves `manage_rules` update/delete being unusable)
- **Intent classification tracker event** — orchestrator now emits the classified intent and reason to the workflow tracker
- **MCP result thinking event** — `_emit_tool_result_thinking` now called for MCP source results (parity with SQL and Knowledge)
- **`manage_rules` output_preview** — step data now includes output_preview for observability

### Removed
- Dead error types `AgentTimeoutError` and `AgentValidationError` (never raised/caught)
- Dead config settings `daily_token_limit`, `monthly_token_limit`, `query_cache_persist_dir`
- Aspirational prompt text: "Data Verification Protocol" tracking, "session note" references, "sanity checker" mention, "COMPLEX MULTI-STEP QUERIES" section (moved to code-level handling)
- `numeric_range` question type from `ask_user` (never implemented)

## [1.2.0] - 2026-03-31

### Added
- **Orchestrator intent classification** — The orchestrator now runs a lightweight LLM-based intent classification step (~500 tokens, ~0.5s) before loading any heavy context. User messages are classified into `direct_response`, `data_query`, `knowledge_query`, `mcp_query`, or `mixed`, and only the relevant context and tools are loaded for each intent type. A simple greeting like "What can you do?" now completes in ~1-2s with 2 LLM calls and 0 DB queries, down from ~15s / 34 spans / 174K tokens. New module: `backend/app/agents/intent_classifier.py`. New prompt builders: `build_classification_prompt()`, `build_direct_response_prompt()` in `orchestrator_prompt.py`. The orchestrator `run()` method now routes to `_run_direct_response`, `_run_data_query`, `_run_knowledge_query`, `_run_mcp_query`, or `_run_full_pipeline` based on the classified intent. Falls back to `mixed` (full pipeline) on any classification error

## [1.1.1] - 2026-03-31

### Fixed
- **402 Payment Required misclassified as retryable error** — HTTP 402 from OpenRouter (insufficient credits) was falling through to `LLMServerError` (retryable), causing 12+ seconds of futile retries before surfacing the error. Added `LLMBillingError` to the error hierarchy (non-retryable, allows fallback to other providers). Fixed the same gap in all three adapters (OpenRouter, OpenAI, Anthropic). The router now skips per-provider retries for billing errors but still tries the next configured provider in the fallback chain

## [1.1.0] - 2026-03-31

### Added
- **Welcome chat for new users** — When a user enters a project with no existing chats, a default "Welcome" session is automatically created with an agent greeting that explains capabilities (database queries, codebase analysis, visualizations, learning, data validation) and invites the user to communicate in any language. Backend endpoint `POST /chat/sessions/ensure-welcome` is idempotent. Frontend triggers it on project restore and project switch

### Improved
- **Orchestrator history-awareness refactoring** — Fixed the orchestrator re-executing SQL queries from prior conversation turns. Six changes: (1) Explicit turn separator injected between chat history and the current user message so the LLM sees history as completed, not actionable; (2) New prompt directives (CURRENT TURN FOCUS, TOOL CALL ECONOMY, SINGLE-QUESTION RULE) prevent the LLM from decomposing history+current into multiple tasks; (3) Chat history enrichment simplified — removed raw SQL text and sample data from assistant context, keeping only row count, column names, and viz type to reduce token usage and avoid "looks like active tool output" confusion; (4) Tool-call deduplication guard removes duplicate `query_database` calls in the same batch and skips calls whose questions already appear in history; (5) SQL sub-agent now receives only the last 4 history messages instead of the full conversation, reducing noise in the validation/repair loop; (6) Reduced `max_history_tokens` from 4000 to 2500
- **Orchestrator gaps audit follow-up** — Extended history scoping to the complex pipeline path and all sub-agent call sites: (1) StageExecutor now scopes chat_history to last 4 messages for both SQL and Knowledge stages; (2) `_run_complex_pipeline` and `_resume_pipeline` pass scoped context to the executor; (3) SINGLE-QUESTION RULE amended to exclude `process_data` chaining from the tool-call cap; (4) Legacy `QueryBuilder.build_query` now injects a history boundary and scopes to last 4 messages; (5) Removed dead `chat_history` parameter from `detect_complexity` and `detect_complexity_adaptive`; (6) `_handle_search_codebase` and `_handle_query_mcp_source` defensively scope context; (7) SQL agent system prompt now includes a CURRENT QUESTION FOCUS directive; (8) Cost estimate formula aligned with runtime — `max_history_tokens` is now a separate budget from static context
- **Orchestrator full flow audit** — Seven fixes from end-to-end audit: (1) CRITICAL: initialized `iteration = 0` before the main loop to prevent `UnboundLocalError` when `max_iter == 0`; (2) CRITICAL: VizAgent now receives scoped context (last 4 history messages) instead of the full unscoped context, matching all other sub-agents; (3) MCP tool `query_mcp_source` is now described in the orchestrator system prompt (capabilities + guidelines) via new `has_mcp_sources` parameter, giving the LLM proper routing guidance; (4) Parallel-tools guideline amended to explicitly exclude `process_data` from parallel recommendations ("chain sequentially"); (5) Knowledge validation failure in `_handle_search_codebase` now retries (matching `_handle_query_database` pattern) instead of returning immediately; (6) `steps_used` formula simplified to always use `iteration + 1` (1-based) regardless of how the loop ended; (7) Integration test added verifying `_run_complex_pipeline` passes scoped context to `StageExecutor`

- **Orchestrator audit round 3** — Comprehensive 32-finding audit with fixes across the entire orchestrator system: (1) HIGH: Fixed `exclude_empty="false"` truthy string bug in process_data — the string `"false"` was treated as truthy, now only `"true"/"1"/"yes"` activate; (2) HIGH: `_handle_process_data` no longer mutates shared `SQLAgentResult` in-place — uses `dataclasses.replace()` to preserve original query results for chain operations; (3) HIGH: `_run_complex_pipeline` and `_resume_pipeline` wrapped in try/except with pipeline-specific logging and tracker.end on failure; (4) HIGH: `query_mcp_source` added to planner `_VALID_TOOLS`, planner prompt, and stage executor with new `_run_mcp_stage` method — MCP data sources can now participate in multi-stage pipelines; (5) MEDIUM: `_apply_continuation_context` uses `replace()` instead of in-place mutation; (6) MEDIUM: `_create_pipeline_run` and `_persist_stage_results` wrapped in try/except; (7) MEDIUM: `RETRYABLE_LLM_ERRORS` added to SQL handler's except chain; MCP handler now validates results via `validate_mcp_result()`; (8) MEDIUM: VizAgent and MCPSourceAgent LLM calls wrapped with local try/except and graceful fallbacks; (9) MEDIUM: `_handle_ask_user` return type corrected to `NoReturn`; (10) MEDIUM: Fixed `ctx.session_id` to `ctx.extra.get("session_id")` in sql_agent.py; (11) MEDIUM: Planner now receives `project_overview` and `current_datetime`; (12) MEDIUM: `process_data` returns enriched sub-result for all operations (not just aggregate); (13) MEDIUM: `QueryRepairer` imports `EXECUTE_QUERY_TOOL` from `sql_tools` instead of deprecated `query_builder`; (14) MEDIUM: `_determine_response_type` returns `"mcp_source"` when only MCP results exist; (15) LOW: Dead constants `KNOWLEDGE_SYSTEM_PROMPT`/`VIZ_SYSTEM_PROMPT` removed; double synthesis skipped when last stage is `synthesize`; `_emit_tool_result_thinking` now logs exceptions; `AgentResponse` type annotations parameterized; history enrichment includes query, insights, followups; empty pipeline answer guarded; (16) 30 new tests covering process_data handler, wall-clock timeout, trim_loop_messages, should_wrap_up, MCP validation, and response type determination

### Fixed
- **Agent timeout hang (330s)** — Complex queries could hang for 330 seconds before timing out due to no wall-clock budget on the orchestrator loop and a double SSE timeout cascade (210s event loop + 120s wait loop). Fixed with three changes: (1) Added `AGENT_WALL_CLOCK_TIMEOUT_SECONDS` (default 90s) that forces the orchestrator to wrap up when elapsed time exceeds the limit, with a hard cutoff at 1.5x; (2) Reduced the SSE post-event grace period from `stream_timeout_seconds` (120s) to 20s, bringing worst-case total from 330s to ~230s; (3) Added `MAX_PARALLEL_TOOL_CALLS` (default 2) semaphore to cap concurrent tool executions, preventing resource exhaustion from unbounded parallel `query_database` calls
- **Trace persistence FK violation** — `_persist_workflow` was inserting into `request_traces` with empty `project_id` which violated the foreign key constraint. Now skips the initial persist when `project_id` or `user_id` is empty; `finalize_trace()` creates the trace row with correct IDs via its else branch

### Fixed
- **Favicon looked squished in browser tabs** — Regenerated `favicon.ico` as multi-size ICO (16x16, 32x32, 48x48) instead of single 32x32. Added `favicon.svg` for modern browsers. Removed unused `favicon-32.png`
- **OG image dimensions mismatch and size** — Resized `og-image.png` from 1376x768 to standard 1200x630 and compressed from 985KB to 74KB. Optimized all icons from SVG source (icon-512.png 247KB → 20KB, icon-192.png 31KB → 6KB)
- **Duplicate `<head>` tags in HTML output** — Removed manual `<link>` and `<meta>` tags from root layout `<head>` that duplicated what the Next.js `metadata` export already generates
- **Sub-page titles bypassed template** — Changed all marketing sub-pages from hardcoded `"Title | CheckMyData.ai"` to just `"Title"` so the root `template: "%s | CheckMyData.ai"` applies consistently
- **Missing Twitter cards on sub-pages** — Added `twitter` metadata to About, Contact, Support, Privacy, and Terms pages
- **`/login` in sitemap** — Removed auth page from sitemap and added `robots: { index: false }` via a login layout
- **`#main-content` skip link target missing** — Added `id="main-content"` to `<main>` in the marketing layout so the skip-to-content link actually works for keyboard users
- **`text-tertiary` failed WCAG AA** — Lightened token from `#71717a` (4.12:1) to `#84848e` (5.37:1 on surface-0, 4.79:1 on surface-1). Fixed `text-muted` usage on meaningful content (copyright, CTA notes) by switching to `text-tertiary`
- **No mobile navigation on marketing pages** — Added hamburger menu component (`MobileMenu`) with animated dropdown for About, Support, GitHub, and Log in links
- **PWA manifest missing icon purpose** — Added `"purpose": "any maskable"` to manifest.json icon entries for Android adaptive icon support

### Fixed
- **Orchestrator `steps_used` always same** — Fixed dead ternary `iteration + 1 if step_limit_hit else iteration + 1` (both branches identical); now correctly reports `iteration` when the agent finished before the step limit
- **SPAN_TYPE_MAP stale tool names** — Updated trace span classification keys to match actual knowledge agent tools (`search_knowledge` instead of `search_codebase`, `get_entity_info` instead of `get_entity_details`) and SQL agent tool (`get_sync_context` instead of `get_sync_status`); removed non-existent `list_entities` entry
- **Tautological test assertion** — Fixed `assert ... or True` in `test_persists_when_project_id_empty` that always passed regardless of actual condition
- **ARCHITECTURE.md wrong API paths** — Corrected traced request paths (`/ask` → `/api/chat/ask`, `/ws/chat` → `/api/chat/ws/{project}/{connection}`) and health endpoint path (`/health` → `/api/health`)
- **CHANGELOG duplicate entries** — Removed 5 duplicate fix entries (useRestoreState race, ProjectSelector race, Health endpoint, Graceful shutdown, seedActiveTasks race)
- **deploy.yml checkout ref** — Added `ref: ${{ github.event.workflow_run.head_sha }}` to ensure CI-validated commit is deployed, not whatever is on the default branch at deploy time
- **deploy-heroku.sh exit code** — Unknown CLI options now exit 1 instead of falling through to `usage()` which exits 0
- **`.env.example` wrong default** — Fixed `STREAM_SAFETY_MARGIN_SECONDS` comment from 30 to 90 to match actual `config.py` default
- **Clarification flow broken end-to-end** — The `ask_user` tool's structured data (question type, options, context) was lost in transit from orchestrator to frontend because `clarification_data` was stored in `viz_config` but never mapped to the API response. Added a dedicated `clarification_data` field to `AgentResponse`, `ChatResponse`, and all three response paths (REST, SSE, WebSocket). The `ClarificationCard` UI (yes/no, multiple choice, free text, numeric range) now renders correctly with structured data
- **`ask_user` unavailable without DB connection** — The `ask_user` tool was gated behind `has_connection=True` in `get_orchestrator_tools()`, preventing clarification questions for knowledge-only projects. Moved `ask_user` to be always available regardless of connected capabilities

### Improved
- **Proactive request analysis** — Added "REQUEST ANALYSIS PROTOCOL" to the orchestrator system prompt instructing the LLM to assess request ambiguity, check schema/knowledge coverage, and use `ask_user` proactively before executing tools. Previously the prompt only encouraged post-query verification

### Fixed
- **CI backend build failure** — `pyproject.toml` referenced `../README.md` which broke `pip install -e .` in CI because setuptools prohibits reading files outside the package root. Replaced with inline description text
- **29 backend lint errors** — Fixed variable naming conventions (`N806`), line-too-long violations (`E501`) in welcome message and email HTML templates, CamelCase-as-acronym import (`N817`), module-level imports not at top of file (`E402`), duplicate test method name (`F811`), and unused local variable (`F841`)
- **24 backend mypy errors** — Fixed type mismatches across 5 files: `ssh_tunnel.py` dict.pop default arg type; `email_service.py` resend `SendParams`/`Tag` type conflicts (5 call sites); `trace_persistence_service.py` missing `rowcount` attribute on `Result`; `sql_agent.py` handler dict value type inference (10 entries); `orchestrator.py` `result` variable shadowed by two incompatible types in `_resume_pipeline`
- **Frontend logs components not tracked in git** — `.gitignore` pattern `logs/` was matching `frontend/src/components/logs/` recursively; changed to `/logs/` to only ignore the root-level logs directory
- **Lost error traces** — Failed requests that crashed before `pipeline_end` was emitted now always appear in the Logs screen with full step breakdown and error details. Six root causes fixed: (1) `ConversationalAgent.run()` now wraps the orchestrator call in `try/except/finally` with a safety-net `pipeline_end` emission via `WorkflowTracker.has_ended()`; (2) Orchestrator `_resume_pipeline` early return ("pipeline not found") now calls `tracker.end()`; (3) Non-streaming `POST /ask` wraps `_agent.run()` in `try/except` to call `finalize_trace()` on crash; (4) `_persist_workflow` no longer silently drops traces with empty `project_id`/`user_id` — they are persisted with empty IDs and `finalize_trace()` updates later; (5) `_cleanup_stale_buffers` persists stale buffers as failed traces (synthetic `pipeline_end`) instead of discarding them; (6) Streaming `_finalize_on_error` uses a fallback workflow ID when the original is `None`, and the "no result" branch now surfaces the actual task exception
- **Trace persistence FK violation** — `_persist_workflow` now persists traces even when `project_id` or `user_id` are missing from the workflow context, using empty strings as placeholders. `finalize_trace()` later updates these rows with correct IDs. This replaces the earlier approach of skipping persistence entirely, which caused error traces to be lost
- **SSE stream cut off on complex queries** — Increased `stream_safety_margin_seconds` from 30 to 90 (total deadline 210s) to accommodate multi-step agent workflows that exceed 150s, preventing premature "SSE event loop exceeded safety timeout" breaks

### Improved
- **Enriched trace spans** — Trace spans in the Request Logs screen now include full step-by-step data: LLM prompt/response previews with token counts and model info, SQL query text and result summaries, RAG search inputs/outputs, sub-agent delegation details, and validation step data. Noise events (`token`, `thinking`, `orchestrator:warning`, `orchestrator:llm_retry`) are filtered out. Duplicate `execute_query` spans removed. `WorkflowTracker.step()` now accepts a `step_data` dict for capturing enrichment data inside context managers. `SPAN_TYPE_MAP` expanded with all agent step names for accurate classification. Fallback `_build_spans_from_tool_log` now handles both `args`/`result` and `arguments`/`result_preview` key formats. Initial trace creation now includes `project_id` and `user_id` from `begin()` context
- **Complete trace capture** — Fixed multiple gaps where requests bypassed trace persistence: WebSocket chat now calls `finalize_trace()` after each message; SSE streaming error/timeout/cancel paths now finalize traces with `status=failed`; MCP tools (`query_database`, `search_codebase`) switched from isolated `WorkflowTracker()` instances to the singleton tracker so events reach `TracePersistenceService`; data validation investigation agent switched to singleton tracker with `project_id` context; batch execute now includes `project_id` and `user_id` in `tracker.begin()` context; standalone LLM endpoints (`generate-title`, `explain-sql`, `summarize`) now create lightweight traces with proper pipeline names. Request list in Logs screen now shows user display names when viewing all users, and date range filter is passed to the request list API call for consistency with summary/user sidebar time windows

### Fixed
- **Markdown table rendering in chat** — Added `remark-gfm` plugin to `react-markdown` so GFM pipe tables (`| col | col |`) generated by the LLM are rendered as proper HTML tables instead of raw text. Affects `ChatMessage.tsx`, `ChatPanel.tsx` (streaming), and `SQLExplainer.tsx`
- **Streaming text markdown** — Streaming (in-progress) assistant messages now render through `ReactMarkdown` with GFM support instead of plain `<p>` tag, so tables/bold/lists display correctly while generating
- **Backend tool result formatting** — `_format_query_results` in `sql_agent.py` and `tool_executor.py` now produces proper GFM markdown tables (with header + separator rows) instead of bare pipe-separated lines, improving LLM output quality
- **Table CSS layout** — Removed `display: block` from `.chat-markdown table` in `globals.css` which broke native table column alignment; overflow scrolling is now handled by the wrapper `<div>` in `mdComponents`

### Added
- **Request Logs screen (owner-only)** — New full-panel logs screen accessible from the sidebar that shows every chat request as a structured trace. Features: KPI summary cards (total requests, success rate, failed count, LLM calls, DB queries, avg latency, cost), user filter panel, paginated request list with status/type badges, and expandable trace detail view showing the full orchestrator route with individual spans (LLM calls, DB queries, sub-agent steps, validation, RAG). Each span displays type icon, duration, token count, and error details. New `request_traces` and `trace_spans` DB tables persist orchestrator workflow events via `TracePersistenceService`. New `/api/logs/` endpoints with owner-only access control. Date range filter (7d/14d/30d/90d) and status filter (All/Completed/Failed)
- **Usage API server-side authorization** — `/api/usage/stats` now enforces owner-level access when `project_id` query param is provided (previously only frontend-gated)
- **Project creation eligibility gate** — New `can_create_projects` flag on users table (default `false`). Only eligible users can create projects on the hosted version; others see a "Request Access" modal with email/description/message form that sends a request to `contact@checkmydata.ai`. Backend enforces with 403 on `POST /api/projects`. New `POST /api/projects/access-requests` endpoint. Admin emails (configured via `ADMIN_EMAILS` env var) are seeded with `can_create_projects=true` via Alembic migration. Non-eligible users can still join projects via invite or use the self-hosted version
- **Analytics & Usage RBAC** — Analytics (`GET /chat/analytics/feedback/{pid}`, `GET /data-validation/analytics/{pid}`, `GET /data-validation/summary/{pid}`) and Usage sidebar panels are now restricted to project **owners** only. Non-owners no longer see these sections in the sidebar
- **Dashboard RBAC** — Dashboard create/edit/delete operations now require at least **editor** role. Viewers can list and view shared dashboards but cannot modify them. The "New dashboard" sidebar action and Edit button on dashboard pages are hidden for viewers. Any editor/owner can edit or delete any dashboard in their project (not just the creator)
- **`FormModal` component** (`frontend/src/components/ui/FormModal.tsx`) — Reusable modal shell with title bar, close (X) button, Escape key, backdrop click dismiss, focus trap, and scroll support
- **KnowledgeResult.sources populated** — RAG search results now correctly wire `RAGSource` objects into `KnowledgeResult.sources`, enabling citation display in chat
- **Global learning patterns** — `AgentLearningService` now identifies learnings that appear across 2+ connections and promotes them into every connection's prompt as universal patterns
- **Pre-call token estimation** — `LLMRouter.estimate_tokens()` uses tiktoken (OpenAI-accurate) with char-based fallback for pre-call context budgeting
- **Knowledge quality scoring** — `RAGFeedbackService` now computes per-source quality scores combining success rate and average retrieval distance, and identifies low-quality sources for re-indexing
- **Persistent query cache** — `QueryCache` supports optional file-based persistence via `query_cache_persist_dir` config, surviving process restarts
- **Incremental schema diff** — `SchemaInfo.fingerprint()` and `SchemaInfo.diff()` enable comparing schemas to detect only changed tables, avoiding full re-introspection
- **Token budget caps** — `UsageService.check_budget()` enforces configurable daily/monthly token limits per user with `BudgetExceededError` and remaining-budget reporting
- **Landing page and full branding** — New public landing page at `/` with hero section, feature grid (6 cards), how-it-works flow, open-source CTA, and supported databases banner. Dark theme using existing design system tokens with JSON-LD structured data for SEO
- **Marketing layout** — Shared `(marketing)` route group layout with sticky blurred header (logo, nav, Login, Get Started CTA) and 4-column footer (Product, Legal, Community links)
- **Dedicated login page** (`/login`) — Standalone authentication page with CheckMyData.ai branding replacing the inline AuthGate form. Supports email/password and Google OAuth
- **About page** (`/about`) — Product mission, technology stack overview, and open-source philosophy
- **Contact page** (`/contact`) — Email channels (contact@checkmydata.ai, support@checkmydata.ai) and GitHub community links
- **Support page** (`/support`) — FAQ with expandable details, documentation links, and support channels
- **Branding assets** — Generated favicon.ico, icon-192.png, icon-512.png, apple-touch-icon.png, og-image.png (1200x630), and reusable `Logo.tsx` SVG component (`LogoMark` + `LogoFull` variants)
- **SEO infrastructure** — robots.txt (disallows /app and /dashboard), dynamic sitemap.xml via Next.js `sitemap.ts`, `metadataBase` on root layout, canonical URLs and OG/Twitter Card metadata on all pages

### Fixed
- **Authenticated user landing redirect** — Added `AuthRedirect` client component to the landing page so authenticated users visiting `/` are automatically redirected to `/app` instead of seeing the marketing page

### Changed
- **Custom Rules editor enlarged** — Rule edit/create modal widened from `max-w-lg` (512px) to `max-w-3xl` (768px) with a taller monospaced textarea (rows=12, min-h-200px) for comfortable markdown editing
- **Agent Learnings popup** — LearningsPanel converted from an inline accordion inside the sidebar to a centered `FormModal` popup (`max-w-3xl`) with 60vh scroll area, larger text, and roomier edit textareas
- **Sidebar forms → centered modals** — All 6 sidebar create/edit forms (Project, Connection, SSH key, Rule, Schedule, Dashboard) now open as centered pop-up modals instead of rendering inline in the sidebar
- **StageValidator configurable strictness** — Min/max row count checks can now fail (not just warn) via `strict_row_bounds` flag
- **SSH tunnel idle cleanup** — `SSHTunnelManager` now tracks last-used time per tunnel and closes idle tunnels (default 30min TTL)
- **Parallel batch queries** — `BatchService.execute_batch()` now runs queries concurrently (up to 4 parallel, configurable)
- **Expanded rule-based viz** — `VizAgent` now handles more cases without LLM calls: auto-detects pie/bar/line charts for common data shapes
- **Deprecated orchestrator decoupled** — `core/orchestrator.py` is no longer imported by any production code
- **Route restructure** — Main application moved from `/` to `/app`. Unauthenticated users see the landing page at `/` instead of a login form
- **AuthGate simplified** — Reduced from 293-line login form to a 42-line redirect guard that sends unauthenticated users to `/login`
- **Legal pages moved** — `/terms` and `/privacy` migrated from `(legal)` to `(marketing)` route group to share the common header/footer
- **401 redirect** — Session-expired handler in `api.ts` now redirects to `/login` instead of `/`
- **manifest.json** — Updated `start_url` to `/app`, added enhanced description

### Added
- **Adaptive step budget system** — Replaced the hard 10-iteration orchestrator ceiling with an adaptive step budget (default 25). The LLM is now informed when it's running low on steps via a step-budget-aware wrap-up prompt (`orchestrator_wrap_up_steps`). When exhausted, a final LLM synthesis call (`orchestrator_final_synthesis`) produces a coherent summary instead of a static "maximum steps reached" message.
- **Continuation protocol** — When the step limit is reached, the response includes `response_type: "step_limit_reached"` with `steps_used`, `steps_total`, and `continuation_context`. The frontend renders a "Continue analysis" button that lets users resume the analysis from where it left off.
- **Per-project and per-request step overrides** — Added `max_orchestrator_steps` column to the `Project` model and `max_steps` field to the chat request body. Resolution order: request `max_steps` > project `max_orchestrator_steps` > global `max_orchestrator_iterations`.
- **Consistent sub-agent iteration limits** — `KnowledgeAgent` and `InvestigationAgent` now use `settings.max_knowledge_iterations` and `settings.max_investigation_iterations` instead of hardcoded class constants. `MAX_SUB_AGENT_RETRIES` in the orchestrator uses `settings.max_sub_agent_retries`.
- **Orchestrator prompt efficiency guideline** — Added a tool-usage efficiency guideline to the orchestrator system prompt encouraging the LLM to combine related questions and parallelize independent tool calls.

### Fixed
- **Email service security and reliability hardening** (`backend/app/services/email_service.py`) — Fixed HTML injection vulnerability: all user-provided values (`display_name`, `project_name`, `inviter_name`, etc.) are now HTML-escaped via `html.escape()` before interpolation into email templates. Added retry with exponential backoff (1s, 2s, 4s) for transient Resend errors (429 rate-limit, 500 server error), max 3 retries. Moved `resend.api_key` assignment from every `_send()` call to `__init__()`. Email send results now log the Resend email ID for traceability. Added category tags (`welcome`, `invite`, `invite-accepted`) for Resend dashboard analytics.
- **ARQ worker crash** — `run_db_index` and `run_code_db_sync` worker tasks referenced non-existent service methods (`set_indexing_status_standalone`, `index_connection`, `run_sync_standalone`). Rewrote both to use `DbIndexPipeline` and `CodeDbSyncPipeline` with proper session management. Fixes #128
- **ReadinessBanner stale state** — Banner showing "index outdated" from a previous project was never cleared on project switch. Now resets `staleInfo` to null when the new project is not stale. Fixes #129
- **WrongDataModal empty connection_id** — Investigation form sent `connection_id: ""` when no DB connection was selected, causing 422 errors. Now validates connection and shows user-friendly toast. Fixes #130
- **useGlobalEvents null workflow_id crash** — `toLogEntry` called `.slice()` on potentially null `workflow_id`, crashing SSE event processing. Added null-safe fallback. Fixes #131
- **Traceback logging in task callbacks** — 5 files passed exception instances to `exc_info=` in asyncio task done callbacks where `sys.exc_info()` is empty. Changed to explicit `(type, value, traceback)` tuples for reliable stack traces. Fixes #132
- **chat.py missing ConnectionConfig import** — Added `TYPE_CHECKING` import for `ConnectionConfig`, resolving ruff F821 and mypy name-defined errors. Fixes #133
- **Ruff lint violations** — Resolved all E501 (line too long) and I001 (import sorting) across `chat.py`, `task_queue.py`, `main.py`, `email_service.py`. `ruff check app/` now passes clean. Fixes #134
- **Logout state leak** — Sign-out now resets all Zustand stores (app, notes, log, task) preventing previous user's chat messages and project data from persisting in memory. Fixes #135
- **Knowledge agent raw tool fallback** — When max iterations exhausted, fallback now uses the last assistant message instead of raw tool output. Fixes #136
- **task_queue.py mypy regression** — Fixed `exc_info` tuple type by adding explicit None guard on `t.exception()`. Fixes #137
- **SSE premature connected flag** — Removed eager `setConnected(true)` after subscription setup; connected state now only set on first received event. Fixes #138
- **Orchestrator shared SQL state** — Per-request SQL results (`_last_sql_result`) scoped per `workflow_id` to prevent data leakage between concurrent requests. Fixes #139

### Added
- **Design system documentation** (`DESIGN_SYSTEM.md`) — Comprehensive visual guide covering semantic color tokens, typography scale, spacing, border-radius, shadows, icons, button variants, form inputs, cards, modals, tooltips, toasts, status indicators, animations, responsive rules, and accessibility guidelines
- **Frontend design system skill** (`.cursor/skills/frontend-design-system/SKILL.md`) — Cursor agent skill that enforces design system compliance on all future frontend work
- **Celery worker infrastructure** (`backend/app/worker.py`, `backend/app/core/task_queue.py`, `backend/app/core/cache.py`) — Redis-backed task queue with shared cache layer for background job processing

### Changed
- **Full design system migration** (68 frontend files) — Migrated all raw Tailwind palette classes (`zinc-*`, `blue-*`, `red-*`, `emerald-*`, `amber-*`, `purple-*`, etc.) to semantic design tokens (`surface-*`, `text-*`, `border-*`, `accent`, `success`, `error`, `warning`, `info`). Zero raw palette classes remain in component files
- **Typography scale enforcement** — Eliminated all off-scale font sizes: `text-[8px]`/`text-[9px]` → `text-[10px]`, `text-[11.5px]` → `text-[11px]`, `text-[12px]`/`text-[13px]` → `text-sm`, legal page h1 `text-3xl` → `text-2xl`
- **Card/panel border-radius standardization** — All card and panel containers now use `rounded-xl`; form inputs use `rounded-lg`; modals use `rounded-lg`
- **Modal accessibility** — OnboardingWizard now has `role="dialog"`, `aria-modal="true"`, `aria-labelledby`, focus trap, and Escape-to-close. WrongDataModal updated with `aria-labelledby` and correct shadow level
- **Toast styling** — Success/error/info toast variants now use semantic tokens instead of raw palette colors
- **Button focus rings** — ConfirmModal Cancel/Confirm buttons now have `focus-visible:ring` styles
- **Shadow standardization** — Eliminated `shadow-2xl` (modals → `shadow-xl`), `shadow-md` (LogPanel toggle → `shadow-lg`)
- **Batch service refactored** for Celery task queue support with improved error handling

### Fixed
- **Missing ARIA labels** — Added `aria-label` to icon-only buttons in InviteManager, LearningsPanel, ScheduleManager, NoteCard, DashboardBuilder, AccountMenu, LlmModelSelector, and OnboardingWizard
- **Missing `transition-colors`** — Added smooth color transitions to interactive elements in StageProgress, Sidebar, NotificationBell
- **ActionCard `aria-expanded`** — Expand/collapse button now correctly announces its state to screen readers
- **ConfirmModal typing input** — Added `aria-label` for the confirmation phrase input
- **SessionContinuationBanner invalid tokens** — Fixed references to non-existent tokens (`text-text-2`, `bg-border`) → valid semantic tokens
- **Test assertions updated** — VerificationBadge and ConfirmModal tests updated to match semantic token class names

### Added
- **Transactional emails via Resend** (`backend/app/services/email_service.py`) — Three email types: welcome email on registration, invite notification when a project owner invites a collaborator, and acceptance confirmation when an invite is accepted. Uses the Resend Python SDK with `asyncio.to_thread()` for async compatibility. Idempotency keys prevent duplicate sends. Gracefully no-ops when `RESEND_API_KEY` is not configured. New env vars: `RESEND_API_KEY`, `RESEND_FROM_EMAIL`, `APP_URL`
- **Session rotation** (`backend/app/services/session_summarizer.py`) — Automatic context-aware session rotation when chat history approaches the context window limit. Summarizes the old session via LLM, creates a new session with a continuation banner linking back to the original. Frontend `SessionContinuationBanner` component shows the transition. Cost estimate endpoint now includes `rotation_imminent` flag. Configurable via `SESSION_ROTATION_ENABLED`, `SESSION_ROTATION_THRESHOLD_PCT`, `SESSION_ROTATION_SUMMARY_MAX_TOKENS`
- **Context usage tracking in AgentResponse** — `context_usage_pct` field added to `AgentResponse` so the frontend can display how much of the context window has been consumed
- **Connection health auto-refresh** — `ConnectionHealth` component now auto-refreshes status periodically and shows more detailed health info
- **ChatMessage copy-all button** — New button on chat messages to copy the entire message content
- **GeoIP two-tier cache** (`backend/app/services/geoip_cache.py`) — In-memory LRU (100k entries, ~20MB) + SQLite persistent storage (`data/geoip_cache.db`, WAL mode, `WITHOUT ROWID`) for IP geolocation results. Eliminates redundant lookups across requests and survives process restarts. Handles millions of unique IPs. Batch operations deduplicate IPs and use batch SQL reads/writes. Configurable via `GEOIP_CACHE_ENABLED`, `GEOIP_CACHE_DIR`, `GEOIP_MEMORY_CACHE_SIZE` env vars
- **Data Processing meta-tool (`process_data`)** — Orchestrator tool that enriches query results with derived data between query steps. Enables multi-step analysis workflows (e.g., query DB for IPs, convert to countries, filter, aggregate). Supports chaining multiple operations sequentially
- **IP-to-country enrichment (`ip_to_country`)** — Offline GeoIP resolution using `geoip2fast` (MaxMind GeoLite2 database). Converts IP address columns to ISO country codes and country names with no external API calls
- **Phone-to-country enrichment (`phone_to_country`)** — Offline E.164 dialing code prefix resolution (~250 countries/territories) with Canadian area code disambiguation for US/CA differentiation within NANP +1 zone
- **In-memory aggregation (`aggregate_data`)** — Groups enriched data by one or more columns and computes `count`, `count_distinct`, `sum`, `avg`, `min`, `max`, `median`. **Multiple functions per column supported** (e.g., `amount:sum,amount:avg,*:count`). Optional `sort_by` / `order` params for controlling result ordering
- **Row filtering (`filter_data`)** — Post-enrichment row filtering by column value. Supports operators: `eq`, `neq`, `contains`, `not_contains`, `gt`, `gte`, `lt`, `lte`, `in`. Can exclude empty/null values with `exclude_empty`
- **`count_distinct` aggregation** — Counts unique non-null values in a column within each group (e.g., unique users per country)
- **`median` aggregation** — Computes median value for numeric columns within each group
- **GeoIPService** (`backend/app/services/geoip_service.py`) — Singleton service for offline IP geolocation lookups with graceful fallback when the library is unavailable
- **PhoneCountryService** (`backend/app/services/phone_country_service.py`) — Singleton service for offline phone number to country resolution via E.164 dialing codes, including Canadian area code disambiguation
- **DataProcessor** (`backend/app/services/data_processor.py`) — Pluggable data transformation engine that operates on `QueryResult` objects with four operations: `ip_to_country`, `phone_to_country`, `aggregate_data`, `filter_data`
- **Complex pipeline support** — `process_data` registered as a valid stage tool in `QueryPlanner` and `StageExecutor` for multi-stage queries (up to 10 stages). Stage executor parses structured JSON from `input_context` with fallback heuristics and emits fine-grained progress events
- **Sequential guard for `process_data`** — When `process_data` appears among parallel tool calls, the orchestrator forces sequential execution to prevent race conditions on shared `_last_sql_result` state
- **Aggregation visualization** — VizAgent is automatically triggered after `aggregate_data` to produce charts/tables for aggregated results
- **Cross-message enriched data persistence** — Enriched `QueryResult` survives across conversation turns for 5 minutes, enabling follow-up questions without re-running the full enrichment pipeline
- **Orchestrator iteration limit raised to 10** — Supports complex multi-enrichment workflows (e.g., dual-query call+SMS analysis with ip_to_country + phone_to_country + aggregate_data for each)

### Fixed
- **Google OAuth 403 on cross-origin** — CSRF double-submit cookie check in `/api/auth/google` now skips verification when the cookie is absent (cross-origin setup where frontend and API are on different domains). The nonce parameter already provides replay protection for the programmatic GIS callback flow
- **Heroku backup skip** — `BackupManager` now detects Heroku (`DYNO` env var) and skips `pg_dump` for managed Postgres, recommending `heroku pg:backups` instead
- **Noisy orchestrator context messages** — Replaced verbose SSE "thinking" events for context usage with quieter log-level messages to reduce UI clutter
- **LLM error formatting** — Improved error message formatting in LLM error classes
- **Registration race condition** — Concurrent duplicate email registrations now caught by DB `IntegrityError` and returned as 409 instead of 500
- **Invite accept commit on early return** — `accept_invite` now commits invite status change when user is already a project member, preventing the update from being silently rolled back
- **PATCH project response missing user_role** — `update_project` now returns a full `ProjectResponse` with `user_role` instead of the raw ORM object
- **Chat feedback learning trigger** — Negative feedback learning now triggers based on the clamped rating value instead of the raw request value, ensuring ratings like -2 or -5 still fire the learning pipeline
- **Reconnect handler connection leak** — `reconnect_connection` now always calls `connector.disconnect()` in a `finally` block, preventing connection/tunnel leaks on successful health checks
- **MCP connector TypeError on health check** — Reconnect and test-connection endpoints now gracefully handle MCP connections that don't support the `DatabaseAdapter` interface
- **Session rename title validation** — `SessionUpdate.title` now enforces `min_length=1` and `max_length=255` to prevent empty or oversized session titles
- **useRestoreState access detection** — `isAccessError` now detects permission errors by matching actual API error messages instead of just HTTP status code strings
- **Missing model imports** — Added 5 missing models (`BatchQuery`, `DataBenchmark`, `Dashboard`, `DataValidationFeedback`/`DataInvestigation`, `SessionNote`) to `models/__init__.py` for consistent mapper registration
- **Integration test auth for /health/modules** — Tests for the authenticated `GET /api/health/modules` endpoint now use `auth_client` instead of unauthenticated `client`
- **Performance smoke test limit for external API** — `test_models_list_latency` now uses a 2-second limit appropriate for the external OpenRouter API call instead of the 300ms internal-only limit
- **Mobile sidebar missing Dashboards** — Added Dashboards section to mobile sidebar drawer, matching desktop feature parity
- **DashboardBuilder JSON.parse crash** — Wrapped `visualization_json` parse in try/catch to prevent builder crash on malformed data
- **Investigation IDOR** — `get_investigation` and `confirm-fix` endpoints now verify the investigation's connection belongs to the requested project, preventing cross-project data access
- **SQL safety guard bypass** — UPDATE pattern now matches qualified table names (`schema.table`, `"schema"."table"`) and added MERGE/UPSERT DML patterns to read-only guard
- **Backend container runs as root** — Dockerfile.backend now creates a non-root `appuser` and runs the application with reduced privileges
- **Auth store localStorage consistency** — `storeAuth` now uses the safe-storage module matching the rest of the auth store, preventing partial state on Safari private mode
- **Pipeline end event not emitted** — Complex query and pipeline resume paths now emit `pipeline_end` event, preventing SSE streams from hanging indefinitely
- **SQL agent connector leak** — Connector cache now capped at 32 entries with LRU eviction and stale connector detection, preventing unbounded connection growth
- **Session title generation MissingGreenlet** — `generate_session_title` now uses explicit async query instead of triggering lazy-loaded relationship
- **Chat search LIKE injection** — Search term `%`, `_`, `\` characters now escaped before building LIKE pattern
- **WebSocket error information leak** — Error handler now sends generic message instead of raw exception string
- **SSE event regex mismatch** — Frontend SSE parser now matches hyphenated event names (e.g., `pipeline-end`)
- **ChatInput max length mismatch** — Frontend char limit raised from 4000 to 20000 to match backend
- **ChatMessage note state not reactive** — Note saved indicator now uses reactive Zustand subscription
- **Learning IDOR** — `update_learning` now verifies ownership before mutating, preventing cross-connection learning edits
- **MongoDB URI credential encoding** — Username and password now URL-encoded with `quote_plus` to handle special characters
- **SSH tunnel race condition** — Per-key asyncio locks prevent concurrent tunnel creation for the same config
- **ClickHouse password in process list** — Exec templates now pass password via environment variable instead of CLI argument
- **SSH key delete without user_id** — `delete()` now called with `user_id` for ownership verification consistency
- **Schedule pagination** — `list_schedules` and `get_history` endpoints now accept `skip`/`limit` query params
- **Alert conditions validation** — `alert_conditions` JSON validated as array with max_length; `notification_channels` capped
- **Result summary size cap** — Schedule run results truncated to 50 rows if JSON exceeds 1MB
- **Benchmark query unbounded** — `get_all_for_connection` now limited to 500 results
- **OpenRouter model fetch contention** — Double-check locking pattern reduces lock contention during cache misses
- **Connection service default limit** — `list_by_project` default reduced from 2000 to 200
- **Test connection error sanitization** — Error messages truncated to 500 chars to prevent internal detail leaks
- **Input validation hardening** — Added `max_length` to `LearningUpdate.lesson`, `SshKeyCreate.passphrase`, `mcp_env` size limits
- **Orchestrator fire-and-forget warning** — `ensure_future` callback now retrieves exceptions to suppress "Task exception was never retrieved" warnings
- **Default rules protection** — Default rules (system-generated) now return 403 on update/delete attempts, preventing accidental corruption
- **Shared notes access broken** — `get_note` and `execute_note` now use `_require_note_access` which allows project members to access shared notes (previously always returned 403)
- **NoteCard comment editing for non-owners** — Comment section now read-only for non-owners, preventing guaranteed 403 failures
- **Viz endpoint DoS** — `RenderRequest` rows capped at 10K, `ExportRequest` at 50K, columns at 500 to prevent server OOM
- **Dashboard update/delete membership check** — Both endpoints now verify project membership before checking creator ownership
- **Session notes unbounded queries** — `_find_similar` capped at 100 candidates, `get_notes_for_context` capped at 200 with 50-note default return
- **Rules rate limiting** — Added rate limits to `list_rules` (60/min) and `update_rule` (20/min)
- **Dashboard refresh parallelized** — `handleRefreshAll` now uses `Promise.allSettled` instead of sequential awaits
- **DashboardBuilder noteMap memoization** — `noteMap` wrapped in `useMemo` to prevent needless re-renders
- **Frontend input maxLength** — Added maxLength to RulesManager name/content, DashboardBuilder title inputs
- **ChartRenderer unknown type fallback** — Shows descriptive message instead of blank rectangle for unsupported chart types

### Security
- **Auth register error sanitization** — Register endpoint no longer exposes internal ValueError messages; returns static "already exists" message while logging details server-side
- **Rate limits on write endpoints** — Added rate limits to 7 previously unprotected mutation endpoints (PATCH projects, PATCH/DELETE sessions, generate-title, feedback, mark notification read, delete SSH key)
- **Probe service SQL injection hardening** — Tightened `_VALID_TABLE_RE` regex to reject quote characters; added `_quote_identifier()` with proper double-quote escaping per SQL standard
- **WebSocket input validation** — Chat WebSocket handler now validates incoming JSON with `WsChatMessage` Pydantic model (enforces message length, provider/model max_length)
- **Credentials cleanup** — Deleted local `notes.md` containing plaintext DB password and SSH private key (never committed to git history)

### Fixed
- **LLM health checks activated** — `start_health_checks()` now called on app startup; failed providers auto-marked unhealthy and skipped in fallback chain until recovered
- **Connector query result row cap** — All 4 DB connectors now cap results at 10,000 rows with `truncated` flag, preventing OOM on large result sets
- **useRestoreState race condition** — Sequence counter prevents stale restore data from overwriting user's active project selection during rapid switching
- **Misleading reconnect banner** — ChatPanel connection-down banner now says "Click Retry to reconnect" instead of the inaccurate "Attempting reconnect..."
- **Form input length limits** — Added maxLength to all text inputs in OnboardingWizard and ConnectionSelector (hosts, ports, credentials, URLs, commands)
- **Connector query timeout** — All connectors now use `settings.query_timeout_seconds` (default 30s) instead of hardcoded 120s
- **Workflow tracker synchronization** — `subscribe()` and `unsubscribe()` now async and acquire `_lock`, matching `_broadcast`'s locking discipline
- **Error boundary logging** — Both ErrorBoundary and SectionErrorBoundary now log caught errors with component stack via `componentDidCatch`
- **WebSocket token usage tracking** — WebSocket chat path now records LLM token usage via UsageService, matching HTTP `/ask` and `/ask/stream` endpoints (costs were previously untracked for WS users)
- **Toast notification cap** — Toasts limited to 5 max; oldest evicted when exceeded (prevents screen flooding during network failures)
- **Unbounded message loading** — `ChatService.get_session()` no longer eagerly loads all messages via `selectinload`; messages now fetched with DB-level LIMIT/OFFSET
- **SSH tunnel cleanup on connection delete** — `ConnectionService.delete()` now closes associated SSH tunnels across all connector types, preventing tunnel accumulation
- **localStorage Safari compatibility** — All localStorage access across 9 files wrapped in try/catch to prevent crashes in Safari private browsing mode
- **JWT expiry zombie state** — `scheduleRefresh` now triggers immediate logout with toast when token is already expired, instead of silently returning
- **WrongDataModal focus trap** — Tab key now cycles within the modal when open, preventing keyboard users from tabbing into background content
- **SSE stream deduplication** — `ConnectionHealth` components now use a shared event bus instead of each opening its own SSE stream to `/workflows/events`
- **Connector pool leak** — All 4 DB connectors (Postgres, MySQL, MongoDB, ClickHouse) now close existing pool/client in `connect()` before creating new ones, preventing connection leaks on repeated connect calls
- **Silent exceptions in sql_agent.py** — Added `logger.debug(exc_info=True)` to 13 previously silent `except` blocks in context-loading helpers, making failures diagnosable from logs
- **ConnectionHealth loading state** — Component now shows pulsing indicator during initial health check instead of immediately displaying "unknown" status
- **Accessibility** — Added `aria-label` attributes to 3 inputs in `ClarificationCard` and `MetricCatalogPanel` that only had placeholder text

### Added
- **Frontend API retry** — GET/HEAD requests automatically retry up to 2 times on network errors and 502/503/504 with exponential backoff; mutation methods (POST/PATCH/DELETE) never retry
- **TTLCache utility** — Generic TTL + LRU cache class (`app/core/ttl_cache.py`) with bounded size and time-based expiry
- **Safe storage utility** — `safe-storage.ts` module with try/catch-wrapped localStorage helpers
- **SSE event bus** — Local pub/sub (`broadcastEvent`/`onEvent`) in `sse.ts` for sharing SSE events without duplicate streams
- **Custom 404 page** — Branded `not-found.tsx` with dark theme styling and link back to home
- **Focus refresh** — `useRefreshOnFocus` hook re-fetches projects, connections, and sessions when browser tab regains focus (throttled to once per 30 seconds)

### Performance
- **Agent cache LRU eviction** — `sql_agent` and `knowledge_agent` caches now use TTLCache with max_size=128, preventing unbounded memory growth over long runtimes
- **Lazy-loaded react-markdown** — `ChatMessage.tsx` and `SQLExplainer.tsx` now use `next/dynamic` to load `react-markdown` on demand as a separate chunk

### Changed
- CI coverage threshold raised from 69% to 72%
- **Chat feedback redesign** — Removed quick-action chips, FollowupChips, DataValidationCard, and WrongDataModal from chat messages. Thumbs up/down now record data validation and thumbs down auto-triggers agent investigation in chat
- **Sidebar "+New" redesign** — Moved all "+New" buttons from section content into section header "+" icons that appear only when expanded. Applies to Projects, Connections, Chat History, Rules, Schedules, and Dashboards

### Security
- **KnowledgeAgent cache isolation** — Fixed critical cross-project data leakage where cached knowledge could bleed between projects (single-slot cache → dict keyed by project_id)
- **MCP connection IDOR** — Added project ownership check before using MCP connections in orchestrator
- **SafetyGuard on diagnostic queries** — Investigation agent `run_diagnostic_query` now validates SQL through SafetyGuard before execution
- **SafetyGuard on schedule run-now** — Manual schedule execution now applies the same safety checks as the cron scheduler
- **Rate limiting** — Added rate limits to `/visualizations/render`, `/exploration`, `/semantic-layer`, `/reconciliation`, `/temporal` endpoints

### Fixed
- **Build type error** — Fixed TypeScript build failure in ChatSessionList.tsx: added proper type assertions for metadata fields after Record<string, unknown> migration
- **Health modules auth** — /api/health/modules now requires authentication, preventing unauthenticated infrastructure reconnaissance
- **Session messages pagination** — GET /sessions/{id}/messages now supports limit/offset (default 500, max 2000) to prevent unbounded responses
- **Knowledge cache TTL** — KnowledgeAgent and SQLAgent now expire cached project knowledge after 5 minutes, preventing stale data after DB/schema updates
- **Query timeouts** — MySQL and ClickHouse connectors now enforce 120s query timeout via asyncio.wait_for, preventing pool exhaustion from long-running queries
- **Connector disconnect safety** — All 6 connectors (postgres, mysql, mongodb, clickhouse, mcp, ssh_exec) now use try/finally in disconnect() to always clear handles even when teardown throws
- **Keyboard shortcut conflict** — Removed duplicate Cmd/Ctrl+K handler from ChatInput; ChatSearch now exclusively owns the shortcut
- **Double-submit guards** — ConnectionSelector handleUpdate/handleIndexDb/handleSync and ScheduleManager toggle now prevent duplicate API calls on rapid clicks
- **useRestoreState race** — Added cancellation flag to prevent stale async restore results from overwriting store after unmount or auth change
- **ProjectSelector race** — Added sequence counter to discard out-of-order API responses when rapidly switching projects
- **Health endpoint** — /api/health now verifies DB connectivity (SELECT 1), returns 503 when database is unreachable
- **Graceful shutdown** — Indexing and sync background tasks are now cancelled during app shutdown
- **seedActiveTasks race** — useGlobalEvents checks active flag before writing to store, preventing stale seed after disconnect
- **Markdown image blocking** — ChatMessage and SQLExplainer now block markdown img tags to prevent arbitrary external image requests
- **Suggestion stale closure** — ChatPanel suggestion reset now depends on activeProject?.id, ensuring suggestions reload on project switch
- **ConnectionHealth feedback** — Reconnect failure now shows error toast instead of silently swallowing errors
- **Silent exceptions** — Added debug logging to remaining silent except blocks (WebSocket send, OpenRouter error body, tunnel introspection)
- **Input validation** — Added max_length constraints to ConnectionCreate (10+ fields) and ProjectUpdate (10 fields)
- **localStorage quota safety** — Wrapped localStorage.setItem calls in auth-store and app-store with try/catch to handle QuotaExceededError gracefully
- Recreated backend venv to fix stale shebangs from old project path
- **InsightFeedPanel** now shows "Couldn't load insights" with Retry when API fails (previously showed misleading empty state)
- **DashboardList** now shows "Couldn't load dashboards" with Retry when API fails (previously showed misleading empty state)
- **ConnectionSelector** now shows "No connections yet" empty state when no connections exist
- **VizRenderer** now shows "Visualization data unavailable" instead of rendering nothing when payload is missing
- **SSE stream completion guard** — Chat stream now fires `onError` if server ends without result/error event, preventing stuck loading state
- **DataValidationCard** — Removed premature optimistic `setVerdict` before API confirmation; UI only updates on success
- **AccountMenu** — Added Escape key handler for keyboard dismissal
- **RetryStrategy** — Fixed empty repair hints when COLUMN_NOT_FOUND has no suggested columns
- **Sidebar callbacks** — Replaced 11 inline lambdas with stable useCallback refs to prevent unnecessary child effect re-runs
- **Notes store** — `loadNotes` failure now shows toast error instead of silent empty state
- **Silent exceptions** — Added debug logging to 10+ previously silent `except: pass` blocks across chat, connectors, and agent modules
- **Accessibility** — Added dialog semantics to BatchRunner, aria-labels to icon-only buttons and form inputs across 6 components
- **Performance** — Narrowed Zustand selectors in 17+ components to prevent full-store re-renders
- **test_alembic.py** — use `sys.executable -m alembic` instead of bare `alembic` CLI to avoid picking up system Python outside venv

### Tests
- batch_service.py: 46% -> 100% coverage (9 new tests for execute_batch)
- code_db_sync_service.py: 55% -> 93% coverage (39 new tests — CRUD, status helpers, runtime enrichment, formatting)
- connection_service.py: 69% -> 99% coverage (20 new tests — test_ssh full flow, to_config error paths, update extended fields, pagination)
- project_overview_service.py: 67% -> 93% coverage (24 new tests — save_overview, _split_overview_sections, _hash_section, notes section, edge cases)
- viz/export.py: 68% -> 100% (xlsx export test), viz/utils.py: 83% -> 100% (serialize_value edge cases)
- agent_learning_service.py: 66% -> 87% (53 new tests — CRUD, fuzzy dedup, decay, compile_prompt, priority score)
- benchmark_service.py: 66% -> 100% (24 new tests — find/create/confirm/flag_stale, normalize, edge cases)
- db_index_service.py: 69% -> 100% (48 new tests — upsert, delete, index_age, is_stale, indexing_status, detail edge cases)
- Overall backend coverage: 68.78% -> 72.63%

### Added
- Open-source repository documentation (CONTRIBUTING, ARCHITECTURE, API, etc.)
- GitHub issue templates and PR template
- MIT License
- **Foundation Layer: Data Graph** — unified metrics registry with auto-discovery from DB index, relationship mapping, and graph queries (`/api/data-graph/`)
- **Foundation Layer: Insight Memory** — persistent store for discovered findings with lifecycle management (active → confirmed/dismissed/resolved), deduplication, and confidence decay (`/api/insights/`)
- **Foundation Layer: Trust Layer** — confidence scoring, provenance tracking, and freshness labels for every insight (`TrustService`, `TrustedInsight`)
- New models: `MetricDefinition`, `MetricRelationship`, `InsightRecord`, `TrustScore`
- Frontend `InsightFeedPanel` component with severity filtering, confidence badges, and insight lifecycle actions (confirm/dismiss/resolve/investigate)
- **Autonomous Insight Feed Agent** — proactive data source scanning, auto-discovers trends/outliers/patterns from DB index, LLM-powered deep analysis, stores findings in Memory Layer (`InsightFeedAgent`, `/api/feed/`)
- **Anomaly Intelligence Engine** — upgrades `DataSanityChecker` with root cause analysis, business impact scoring, severity classification, recommended actions, and confidence. Replaces basic warning text with rich `AnomalyReport` objects (`AnomalyIntelligenceEngine`, `AnomalyReportCard`)
- New API endpoints: `POST /api/data-validation/anomaly-analysis` (ad-hoc analysis), `POST /api/data-validation/anomaly-scan/{connection_id}` (table-level scan)
- SQL Agent now automatically stores critical/warning anomalies as insight records in Memory Layer
- Probe Service enriched with anomaly intelligence reports per table
- Frontend `AnomalyReportCard` component with expandable root cause, impact, and action details
- **Opportunity Detector** — finds high-performing segments, conversion gaps, undermonetized users, and growth-potential channels with impact estimates (`OpportunityDetector`, `OpportunityCard`)
- New API endpoint: `POST /api/feed/{project_id}/opportunities/{connection_id}` (opportunity scan with auto-store to insights)
- **Loss Detector** — finds revenue leaks, funnel drop-offs, spend inefficiency, declining trends, and high-churn segments with monetary quantification (`LossDetector`, `LossReportCard`)
- New API endpoint: `POST /api/feed/{project_id}/losses/{connection_id}` (loss scan with auto-store to insights)
- **Insight → Action Engine** — transforms every insight (anomaly, opportunity, loss) into a concrete recommended action with expected impact %, priority, effort, prerequisites, and risks (`ActionEngine`, `ActionRecommendation`, `ActionCard`)
- **Cross-Source Reconciliation Engine** — compares data between two connections: row counts, aggregate values, schemas, and key overlap. Detects missing records, value mismatches, schema divergence. Stores critical discrepancies as insights. (`ReconciliationEngine`, `ReconciliationCard`, `/api/reconciliation/`)
- **Semantic Layer Auto-Build** — auto-discovers metrics from DB index entries, infers aggregation (SUM/COUNT/AVG), units, and categories, normalizes across connections via canonical name mapping (70+ business metric aliases), and links equivalent metrics in the Data Graph. Browsable metric catalog with search and category filters. (`SemanticLayerService`, `MetricCatalogPanel`, `/api/semantic-layer/`)
- **Query-less Exploration** — autonomous investigation engine: user says "What's wrong?" and the system scans insights, anomalies, opportunities, losses, reconciliation discrepancies, and data health to compile a prioritized investigation report with findings sorted by severity. (`ExplorationEngine`, `ExplorationReport`, `POST /api/explore/`)
- **Temporal Intelligence Engine** — pure-Python time series analysis: linear trend detection with R² fit quality, seasonality detection via autocorrelation on detrended data (weekly/monthly/quarterly/yearly), temporal anomaly detection adjusted for trend, and cross-series lag/lead detection via cross-correlation. (`TemporalIntelligenceService`, `TemporalReport`, `/api/temporal/`)
- New API endpoint: `GET /api/insights/{project_id}/actions` (generate prioritized action recommendations from active insights)
- BACKLOG.md for iterative development tracking

### Fixed
- **Sidebar popup overflow** — NotificationBell dropdown, AccountMenu, and Tooltip now render via React portals (`PopoverPortal`) to escape sidebar `overflow-hidden`, preventing clipping on desktop collapsed/expanded states
- **Charts missing in Saved Queries** — NoteCard now renders `VizRenderer` (bar/line/pie/scatter charts) from `visualization_json` in a collapsible "Chart" section
- **Refresh-to-chat** — Clicking "Refresh" on a saved query now posts the refreshed result as a message in the currently active chat session (with `[Refreshed]` prefix)
- **Critical: Router prefix duplication** — Sprint 1 routes (reconciliation, semantic-layer, explore, temporal) had double-prefixed paths (e.g. `/api/reconciliation/reconciliation/...`) causing 404s from frontend. Removed redundant router-level prefix.
- **Security: Cross-project insight access** — confirm/dismiss/resolve insight endpoints now verify the insight belongs to the target project before mutation, preventing cross-project data manipulation.
- **Feed API empty responses** — `scan_opportunities` and `scan_losses` now return `insights_stored: 0` when no DB entries exist, matching frontend DTO expectations.
- **Next.js viewport metadata deprecation** — moved `themeColor` and `viewport` from `metadata` export to proper `viewport` export per Next.js 15 API, eliminating build warnings.
- **Float conversion safety** — added `_safe_float` utility in action_engine and exploration_engine to handle `None`, non-numeric, and string confidence values without crashing.
- **Reconciliation schema handling** — `reconcile_schemas` now handles `None` column lists gracefully with `set(schema.get(table) or [])`.
- **Feed HTTPException consistency** — replaced inline `from fastapi import HTTPException` with top-level import and keyword args for consistency.

### Changed
- Test coverage increased from 68.90% to 71.03%
- Added integration tests for Sprint 1 route path reachability (reconciliation, semantic-layer, explore, temporal)
- Added integration test for cross-project insight access prevention
- Added unit tests for `_safe_float` edge cases and `None`/non-numeric confidence handling

## [0.10.0] - 2026-03-22

### Security
- Path traversal protection via `validate_safe_id` on filesystem-facing params
- Project creation uniqueness check (owner_id + name) returns 409 on duplicates
- Audit logging on auth routes, repo mutations, and data validation
- SQL identifier quoting in probe_service to prevent injection
- Rate limiting on all mutating endpoints
- Security headers middleware (X-Content-Type-Options, X-Frame-Options, etc.)
- Command injection fix in subprocess calls
- Input validation with Pydantic Literal types across all routes

### Fixed
- VectorStore shutdown cleanup (close ChromaDB client)
- Stale git lock file cleanup on app shutdown
- Silent exception handling replaced with proper logging across 15+ locations
- Race condition in VectorStore collection access (threading.Lock)
- Invite acceptance atomicity with begin_nested transaction
- MongoDB connection timeout configuration
- N+1 queries in project_overview_service and batch_service
- Frontend unmounted setState guards on 18+ components
- Silent .catch blocks replaced with toast notifications

### Added
- Configurable timeouts: model_cache_ttl, health_degraded_latency, ssh_connect/command
- Database pool_timeout configuration
- Pagination on list_repositories endpoint
- aria-live regions for streaming chat and batch progress
- Cmd/Ctrl+K keyboard shortcut to focus chat input
- React.memo + useCallback optimization on ChatSessionList
- DataTable row cap (500) with "show all" toggle
- LearningsPanel item cap (200)
- DataValidationCard maxLength + aria-label on inputs
- Accessibility: skip-to-content, focus traps, keyboard navigation

### Changed
- Background task error logging via add_done_callback
- Moved hardcoded timeouts to centralized config

## [0.1.0] - 2026-03-15

### Added
- Initial release
- Multi-agent chat system (Orchestrator, SQL, Knowledge, Viz agents)
- Database connectors (PostgreSQL, MySQL, ClickHouse, MongoDB)
- SSH tunnel support
- Git repository indexing with ChromaDB RAG
- Natural language to SQL translation
- Automatic visualization (tables, charts)
- Batch query execution
- Dashboard creation
- Custom validation rules
- Team collaboration with invitations
- Google OAuth integration
- Onboarding wizard
- Demo project setup
