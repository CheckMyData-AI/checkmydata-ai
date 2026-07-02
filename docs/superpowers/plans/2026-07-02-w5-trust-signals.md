# Plan — W5: Code↔DB sync & freshness trust signals (TDD + subagent-driven)

Spec: `docs/superpowers/specs/2026-07-02-intelligence-remediation-design.md` (§1 GitPython facts;
§2 contract **C-F**; §3 W5 scope). Audit: `docs/INTELLIGENCE_AUDIT_2026-07.md` §7 (`SYNC-L*`).
Branch: `feat/w5-trust-signals-2026-07-02`. Group **G3** (parallel with W3, after W0). Every task:
failing test → confirm fail → minimal impl → confirm pass → conventional commit. Status protocol:
DONE / DONE_WITH_CONCERNS / NEEDS_CONTEXT / BLOCKED. Two-stage review per task (spec compliance,
then code quality).

**NOTE — scope boundary:** `SYNC-L1` (required-filter guard, `core/required_filter_guard.py`)
lives in **W1**, NOT here. Do not touch `required_filter_guard.py` in this wave. `SYNC-L10` (enable
lineage by default) is a W6 flag-flip decision — out of scope. This wave owns only the files in the
spec §3 W5 line: `code_db_sync_pipeline.py`, `code_db_sync_analyzer.py`, `graph_db_bridge.py`,
`git_tracker.py`, `knowledge_freshness_service.py`, `entity_extractor.py` (sync-relevant regions
only), plus `code_db_sync_service.py` and the sync-keying region of `sql_agent.py`.

## Conventions (apply to every task)

- Tests live under `backend/tests/unit/`. `asyncio_mode = "auto"` is global — no
  `@pytest.mark.asyncio`, just `async def test_...`.
- Run a single test: `cd backend && PYTHONPATH=. .venv/bin/pytest tests/unit/<file>::<test> -v`.
- Confirm-fail step is mandatory (systematic-debugging Phase 4): run the new test BEFORE impl and
  paste the failing assertion/ImportError into the commit body or task status.
- Line length 100; `ruff` 0.15.15 pinned. After each task:
  `cd backend && .venv/bin/ruff format app/ tests/ && .venv/bin/ruff check app/ tests/`.
- Structured logging only; never log secrets or full sample rows. Degrade honestly (return a
  neutral/`unknown` value or a warning), never silently swallow a real signal.

## Dependency graph / groups

```
G0 (sequential, contracts-first — MUST land before any parallel W5 task):
  T1  git_tracker.classify_freshness + GitFreshness (C-F)      [git_tracker.py]
G1 (parallel after G0, non-overlapping files):
  T2  knowledge_freshness_service distinguishes states (L3)    [knowledge_freshness_service.py]
  T3  entity_extractor table-ref + read/write attribution (L2) [entity_extractor.py — _scan_table_usage + regex region]
  T4  code_db_sync_pipeline deterministic drift set-diff (L5)  [code_db_sync_pipeline.py]
  T6  code_db_sync_pipeline schema-qualified matching (L6)     [code_db_sync_pipeline.py]  ← same file as T4 → SEQUENCE after T4
  T7  sql_agent bare-suffix keying alias (L7)                  [sql_agent.py + code_db_sync_service.py]
  T8  knowledge_freshness_service code-graph gate (L8)         [knowledge_freshness_service.py] ← same file as T2 → SEQUENCE after T2
  T9  graph_db_bridge op-kind word-boundary (L9)               [graph_db_bridge.py]
  T5  entity_extractor _model_name_to_table inflection (L4)    [entity_extractor.py — _model_name_to_table] ← same file as T3, different function → SEQUENCE after T3
G2 (sequential glue):
  T10 Low batch L11/L12/L13/L14                                [code_db_sync_service.py, graph_db_bridge.py, knowledge_freshness_service.py]
G3 (integration):
  T11 full suite + ruff + mypy + docs (CLAUDE.md, CHANGELOG)
```

**File-ownership resolution.** Two waves and two tasks contend for shared files; resolve by
sequencing, never concurrent writes on the same file:
- `code_db_sync_pipeline.py`: **T4 then T6** (sequential; T6 depends on T4 landed).
- `knowledge_freshness_service.py`: **T2 then T8** (sequential; T8 depends on T2 landed).
- `entity_extractor.py`: **T3 (`_scan_table_usage` + regex region) then T5 (`_model_name_to_table`)**
  — different functions, but same file, so sequence T5 after T3. This file is **also** owned by W6
  (symbol/enum extraction regions); W5 touches ONLY `_scan_table_usage`, `TABLE_REF_SQL`/`WRITE_SQL`/
  `READ_SQL` regex, and `_model_name_to_table`/`_model_to_table`. Do not edit `_extract_columns`,
  `_extract_enums`, or symbol extraction — those are W6.
- `code_db_sync_service.py`: T7 (add helper) and T10 (L11 coercion) — sequence T10 after T7.

Truly parallel after G0: {T2, T3, T4, T7, T9}. Then {T6 after T4}, {T8 after T2}, {T5 after T3}.

---

### T1 — `git_tracker.classify_freshness` + `GitFreshness` (C-F, SYNC-L3)  [G0, sequential, first]

**Files:**
- `backend/app/knowledge/git_tracker.py` (add enum + function; keep `count_commits_ahead` for
  back-compat — T2 stops calling it but other callers may exist).
- `backend/app/config.py` (add one flag).
- `backend/.env.example` (document the flag).
- `backend/tests/unit/test_git_tracker_freshness.py` (NEW — do not edit the existing
  `test_git_tracker.py`).

**Interfaces (Consumes C-F VERBATIM — this task IMPLEMENTS the frozen signature; do not rename):**
```python
from enum import Enum

class GitFreshness(Enum):
    FRESH = "fresh"
    AHEAD = "ahead"
    BEHIND = "behind"
    DIVERGED = "diverged"

def classify_freshness(repo, indexed_sha: str, branch: str) -> tuple[GitFreshness, int, int]:
    """Return (state, ahead, behind).

    ahead  = commits on the working ref (HEAD) not reachable from indexed_sha.
    behind = commits reachable from indexed_sha (or origin/<branch>) not on HEAD.
    Uses repo.is_ancestor + repo.merge_base + repo.iter_commits count.
    """
```
Semantics (§1 verified GitPython facts):
- Resolve the working ref commit `head = repo.commit(branch)` if `branch` resolves, else
  `repo.head.commit`. Resolve `indexed = repo.commit(indexed_sha)`.
- `ahead = len(list(repo.iter_commits(f"{indexed.hexsha}..{head.hexsha}")))`.
- `behind = len(list(repo.iter_commits(f"{head.hexsha}..{indexed.hexsha}")))`.
- Classify from counts: `(0,0)→FRESH`, `(>0,0)→AHEAD`, `(0,>0)→BEHIND`, `(>0,>0)→DIVERGED`.
- `is_ancestor(indexed, head)` is the fast FRESH/AHEAD short-circuit; `merge_base` is used to prove
  DIVERGED (base ≠ either tip) — but the count-based rule above already yields the same partition,
  so compute counts and derive `merge_base` only for logging. Optional `origin/<branch>` compare
  (below) is the only place fetch matters.
- Bad SHA / unresolved branch → `(GitFreshness.FRESH, 0, 0)` is WRONG (would report false-fresh);
  instead raise nothing but return a sentinel the caller treats as "unknown": return
  `(GitFreshness.BEHIND, 0, 1)`? No — return the honest unknown by re-raising `BadName`/`ValueError`
  to the caller so it degrades to the existing "may be out of date" warning. `classify_freshness`
  itself does NOT swallow; the async wrapper in T2 catches.

**Config flag (C-F "optional origin compare behind a flag"):**
- `git_freshness_fetch_origin: bool = False` in `config.py` with docstring: "When true,
  `classify_freshness` compares the indexed SHA against `origin/<branch>` (after an offline
  `repo.remotes.origin.fetch`) instead of the local ref, catching a clone that is behind the remote.
  Off by default — a fetch is network I/O and can hang; enable only where the clone auto-pulls."
- Add matching line to `.env.example`: `# GIT_FRESHNESS_FETCH_ORIGIN=false`.
- Provide an internal `async def classify_freshness_async(repo_dir, indexed_sha, branch, *, fetch_origin=False)`
  helper on `GitTracker` that (a) runs the blocking `classify_freshness` via
  `asyncio.to_thread`, (b) when `fetch_origin` is true, does `repo.remotes.origin.fetch()` inside the
  thread first and classifies against `f"origin/{branch}"`. Fetch failure → fall back to local ref
  (log at `warning`, do not raise).

**TDD steps:**
- [ ] Add `test_git_tracker_freshness.py` with a `_tiny_repo(tmp_path)` helper that builds a real
      throwaway repo (no remote needed):
```python
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from git import Repo

from app.knowledge.git_tracker import GitFreshness, classify_freshness


def _commit(repo: Repo, path: Path, name: str, text: str) -> str:
    f = path / name
    f.write_text(text)
    repo.index.add([str(f)])
    return repo.index.commit(f"add {name}").hexsha


@pytest.fixture
def tiny_repo(tmp_path):
    repo = Repo.init(tmp_path)
    repo.config_writer().set_value("user", "email", "t@t.io").release()
    repo.config_writer().set_value("user", "name", "t").release()
    c1 = _commit(repo, tmp_path, "a.txt", "1")
    c2 = _commit(repo, tmp_path, "b.txt", "2")
    return repo, c1, c2


def test_fresh_when_indexed_equals_head(tiny_repo):
    repo, _c1, c2 = tiny_repo
    state, ahead, behind = classify_freshness(repo, c2, repo.active_branch.name)
    assert state is GitFreshness.FRESH
    assert (ahead, behind) == (0, 0)


def test_ahead_when_head_moved_past_indexed(tiny_repo):
    repo, c1, _c2 = tiny_repo  # indexed at c1, HEAD at c2 → 1 commit ahead
    state, ahead, behind = classify_freshness(repo, c1, repo.active_branch.name)
    assert state is GitFreshness.AHEAD
    assert (ahead, behind) == (1, 0)


def test_behind_when_indexed_ahead_of_head(tiny_repo):
    repo, c1, c2 = tiny_repo
    # move HEAD back to c1; indexed stays at c2 → behind by 1
    repo.git.reset("--hard", c1)
    state, ahead, behind = classify_freshness(repo, c2, repo.active_branch.name)
    assert state is GitFreshness.BEHIND
    assert (ahead, behind) == (0, 1)


def test_diverged_uses_iter_commits_counts_mocked():
    # Deterministic diverged case without crafting a real divergent history:
    # HEAD has 2 unique, indexed has 3 unique.
    repo = MagicMock()
    repo.commit.side_effect = lambda rev: MagicMock(hexsha=str(rev))
    def _iter(spec, **kw):
        left, right = spec.split("..")
        # "indexed..head" → ahead ; "head..indexed" → behind
        if left == "isha":
            return [MagicMock(), MagicMock()]        # ahead = 2
        return [MagicMock(), MagicMock(), MagicMock()]  # behind = 3
    repo.iter_commits.side_effect = _iter
    state, ahead, behind = classify_freshness(repo, "isha", "main")
    assert state is GitFreshness.DIVERGED
    assert (ahead, behind) == (2, 3)


def test_bad_sha_reraises_not_false_fresh():
    from git.exc import BadName
    repo = MagicMock()
    repo.commit.side_effect = BadName("no such rev")
    with pytest.raises((BadName, ValueError)):
        classify_freshness(repo, "deadbeef", "main")
```
- [ ] Run — confirm fail (ImportError: `GitFreshness`/`classify_freshness`):
      `cd backend && PYTHONPATH=. .venv/bin/pytest tests/unit/test_git_tracker_freshness.py -v`.
- [ ] Implement `GitFreshness` + `classify_freshness` in `git_tracker.py` per the Interfaces block.
      Resolve `head_rev = branch` when it resolves else `repo.head.commit.hexsha`; let `repo.commit`
      raise `BadName`/`ValueError` on a bad `indexed_sha` (do not catch here). Compute both counts;
      derive state from the 4-way partition; log `merge_base` at debug for diverged.
- [ ] Add `git_freshness_fetch_origin` to `config.py` + `.env.example`; add
      `GitTracker.classify_freshness_async(...)` wrapper (to_thread; optional offline fetch).
- [ ] Add a test asserting `classify_freshness_async` returns the same tuple as sync on the tiny
      repo with `fetch_origin=False`, and that a raising `origin.fetch` degrades to local (mock a
      `MagicMock` repo whose `remotes.origin.fetch` raises → still classifies against local ref, no
      exception escapes).
- [ ] Run all above — confirm pass. `ruff format && ruff check`.
- [ ] Commit: `feat(sync): git classify_freshness ahead/behind/diverged via is_ancestor+iter_commits (SYNC-L3, C-F)`.

**DoD:** `GitFreshness`/`classify_freshness` match the C-F signature verbatim; fresh/ahead/behind/
diverged all asserted (real tiny repo + mocked diverged); bad SHA re-raises (no false-fresh);
`git_freshness_fetch_origin` flag exists + documented; config-sync test (T11) green.

---

### T2 — `knowledge_freshness_service` distinguishes ahead/behind/diverged (SYNC-L3)  [G1, dep T1]

**Files:**
- `backend/app/services/knowledge_freshness_service.py` (git branch of `evaluate`,
  `KnowledgeFreshness` dataclass).
- `backend/tests/unit/test_knowledge_freshness_service.py` (extend — add a new test class; the file
  currently only tests the dataclass, so no collision with T8 which adds a different class).

**Interfaces (Consumes C-F `classify_freshness` / `GitFreshness`; do not redefine):**
```python
from app.knowledge.git_tracker import GitFreshness  # consumed, not redefined
# KnowledgeFreshness gains (additive, back-compat defaults):
git_state: str | None = None       # "fresh"|"ahead"|"behind"|"diverged"|None
git_ahead_commits: int | None = None
# existing git_behind_commits: int | None stays (now populated from classify_freshness behind count)
```
Behavior — replace the `count_commits_ahead` block (current lines ~237-257) with:
- Resolve the branch: use the last-indexed `CommitIndex.branch` if available (via
  `get_last_indexed_record`), else `repo.active_branch.name`, else `"main"`.
- Call `tracker.classify_freshness_async(repo_clone_dir, last_sha, branch, fetch_origin=settings.git_freshness_fetch_origin)`.
- Map state → warning + severity:
  - `FRESH` → no warning (silent).
  - `AHEAD` (indexed behind HEAD) → the existing "N commit(s) behind HEAD; answers may reference
    outdated code" message, `git_behind_commits = ahead`, `git_state="ahead"`.
    (Naming note: from the *knowledge base's* point of view, HEAD being ahead means the KB is
    **behind** the code — keep the user-facing word "behind" but store `git_state="ahead"` to mean
    "HEAD is ahead of index".)
  - `BEHIND` (indexed ahead of HEAD — clone was reset/rolled back) → new message: "Knowledge base
    was indexed from N commit(s) that are no longer on the current branch; the clone may have been
    reset — re-index." severity `warning`.
  - `DIVERGED` → new message: "Knowledge base and the working tree have diverged (KB +{behind}, HEAD
    +{ahead}); re-index to realign." severity `critical`; set both `git_ahead_commits` and
    `git_behind_commits`.
- On `classify_freshness_async` raising / returning unknown → keep the existing generic "Knowledge
  base may be out of date." fallback (honest degradation, no false-fresh).
- Populate `to_dict()` with the two new fields.

**TDD steps:**
- [ ] Add `TestGitFreshnessStates` to `test_knowledge_freshness_service.py`. Use a real tiny repo
      helper (same shape as T1) plus a monkeypatched `GitTracker.get_last_indexed_sha` returning the
      chosen SHA, and an in-memory session double. Assert:
```python
async def test_ahead_reports_behind_message(tmp_path, monkeypatch):
    # indexed at c1, HEAD at c2 → ahead=1 → user sees "behind HEAD", git_state=="ahead"
    ...
    snap = await svc.evaluate(session, project_id="p", connection_id=None, repo_clone_dir=tmp_path)
    assert snap.git_state == "ahead"
    assert snap.git_behind_commits == 1
    assert any("behind HEAD" in w for w in snap.warnings)

async def test_behind_reports_reset_message(tmp_path, monkeypatch):
    # HEAD reset to c1, indexed at c2 → BEHIND → "no longer on the current branch"
    assert snap.git_state == "behind"
    assert any("no longer on the current branch" in w for w in snap.warnings)

async def test_diverged_is_critical(tmp_path, monkeypatch):
    # mock classify_freshness_async → (DIVERGED, 2, 3)
    assert snap.git_state == "diverged"
    assert snap.git_ahead_commits == 2 and snap.git_behind_commits == 3
    assert any(d.severity == "critical" and d.category == "git" for d in snap.details)

async def test_fresh_is_silent(tmp_path, monkeypatch):
    # indexed == HEAD → no git warning at all
    assert snap.git_state == "fresh"
    assert not any(d.category == "git" for d in snap.details)

async def test_classify_raises_degrades_to_generic(tmp_path, monkeypatch):
    # classify_freshness_async raises → generic "may be out of date", never false-fresh/silent
    assert any("may be out of date" in w for w in snap.warnings)
```
      For the diverged/raises cases mock `GitTracker.classify_freshness_async` with
      `AsyncMock(return_value=(GitFreshness.DIVERGED, 2, 3))` / `AsyncMock(side_effect=BadName(...))`.
- [ ] Confirm fail (AttributeError `git_state` / message mismatch).
- [ ] Implement dataclass fields + rewrite the git branch of `evaluate`. Keep the
      `get_head_sha != last_sha` short-circuit only as a cheap "definitely not fresh" pre-check;
      the authoritative classification is `classify_freshness_async`.
- [ ] Confirm pass; `ruff`.
- [ ] Commit: `feat(freshness): distinguish ahead/behind/diverged git states (SYNC-L3)`.

**DoD:** all four states produce distinct, correct warnings + `git_state`; diverged is `critical`;
raise degrades to the generic warning (no false-fresh); `to_dict` carries the new fields; existing
dataclass tests still green.

---

### T3 — `entity_extractor` table-ref + read/write attribution (SYNC-L2)  [G1, parallel]

**Files:**
- `backend/app/knowledge/entity_extractor.py` — ONLY `_scan_table_usage` (~700-719) and the
  `TABLE_REF_SQL`/`WRITE_SQL`/`READ_SQL` regex region (~176-187). Add a small comment/literal
  stripper helper local to this module. Do NOT touch column/enum/symbol extraction (W6).
- `backend/tests/unit/knowledge/test_entity_extractor_table_usage.py` (NEW).

**Interfaces (module-internal; no external contract):**
```python
def _strip_sql_noise(content: str) -> str:
    """Blank out line comments (-- , //, #), block comments (/* */), and single/double/backtick
    string literals BEFORE table-ref scanning, preserving byte offsets by replacing removed spans
    with spaces (so match windows stay aligned). Returns same-length string."""

# _scan_table_usage: prefer AST/graph usage when available on knowledge (entity.used_in_files /
# graph_callers already populated) and only fall back to the regex scan for tables with no
# structured usage. The regex scan runs over _strip_sql_noise(content) and uses a
# statement-scoped window (split on ';' or newline-blank) instead of the fixed ±100 chars.
```
Key fixes:
1. Strip comments + string literals so `-- SELECT * FROM users` and `"... FROM orders ..."` (a
   string literal, e.g. an error message) no longer register as table refs.
2. Statement-scope the read/write window: instead of `content[start-100:end+100]`, take the enclosing
   statement (nearest `;`/blank-line boundaries around the match) so a `SELECT` three statements
   away doesn't tag an `INSERT` target as a reader.
3. Exclude CTE names: a name introduced by `WITH <name> AS (` is a CTE alias, not a table — collect
   CTE names per stripped statement and skip them in `TABLE_REF_SQL`.
4. AST-preference: if `entity.used_in_files` (populated by the ORM scan) already covers a file for a
   table, do not also regex-attribute that file — the AST/ORM signal wins. (Keep regex as the
   fallback for raw-SQL-in-strings files where no ORM symbol exists.)

**TDD steps:**
- [ ] Write tests asserting false positives are excluded and attribution is correct:
```python
from app.knowledge.entity_extractor import ProjectKnowledge, _scan_table_usage


def _scan(content, path="svc.py"):
    k = ProjectKnowledge()
    _scan_table_usage(path, content, k)
    return k


def test_comment_table_ref_excluded():
    k = _scan("-- historical: SELECT * FROM legacy_users\nx = 1\n")
    assert "legacy_users" not in k.table_usage


def test_string_literal_table_ref_excluded():
    k = _scan('msg = "no rows FROM ghost_table were found"\n')
    assert "ghost_table" not in k.table_usage


def test_cte_name_not_treated_as_table():
    sql = 'q = "WITH recent AS (SELECT id FROM orders) SELECT * FROM recent"'
    k = _scan(sql)
    assert "orders" in k.table_usage       # the real table is captured
    assert "recent" not in k.table_usage   # the CTE alias is not


def test_write_vs_read_attribution_statement_scoped():
    sql = (
        'a = "INSERT INTO events (id) VALUES (1)"\n'
        'b = "SELECT * FROM users"\n'
    )
    k = _scan(sql, path="w.py")
    # events is only written, users is only read — the SELECT must not leak onto events
    assert "w.py" in k.table_usage["events"].writers
    assert "w.py" not in k.table_usage["events"].readers
    assert "w.py" in k.table_usage["users"].readers
    assert "w.py" not in k.table_usage["users"].writers
```
- [ ] Confirm fail (current ±100 window + no stripping leaks readers/writers and captures CTE/
      comment refs).
- [ ] Implement `_strip_sql_noise` (offset-preserving), statement-scoped windowing, CTE-name
      collection, and AST-preference gate in `_scan_table_usage`. Keep the `sql_kw` guard.
- [ ] Confirm pass; run the full extractor suite to catch regressions:
      `cd backend && PYTHONPATH=. .venv/bin/pytest tests/unit/knowledge/ -k "entity or extractor" -v`.
- [ ] `ruff`. Commit: `fix(sync): strip comments/literals + statement-scope table-ref attribution (SYNC-L2)`.

**DoD:** comment/string-literal/CTE false positives excluded (asserted); read vs write attribution
is statement-scoped and correct; ORM/AST usage preferred over regex where present; existing
extractor tests green.

---

### T4 — deterministic code↔DB column set-diff (SYNC-L5)  [G1, parallel; runs before T6]

**Files:**
- `backend/app/knowledge/code_db_sync_pipeline.py` — add a static `_compute_column_drift(...)` and
  call it in `_make_matched`/the store step so `mismatch` is a fact, not the LLM's opinion.
- `backend/app/knowledge/code_db_sync_analyzer.py` — `TableSyncAnalysis` gains a
  `column_mismatch_json: str = "{}"` field (factual set-diff), and `sync_status` is OVERRIDDEN by the
  deterministic diff when both column sets are known (LLM `sync_status` kept only when a side is
  empty/unknown).
- `backend/app/services/code_db_sync_service.py` — no schema change needed if we reuse an existing
  Text column; add `column_mismatch_json` to `CodeDbSync` model + a small Alembic migration (Text,
  default `"{}"`) so the fact persists and surfaces in `sync_to_response`.
- `backend/app/models/code_db_sync.py` — add the column.
- `backend/tests/unit/knowledge/test_sync_column_drift.py` (NEW).

**Interfaces:**
```python
@staticmethod
def _compute_column_drift(code_cols: set[str], db_cols: set[str]) -> dict:
    """Deterministic set-diff. Both sets are already in memory (code_columns_json vs the
    DB index column list). Returns:
        {"code_only": sorted(code_cols - db_cols),
         "db_only": sorted(db_cols - code_cols),
         "matched": sorted(code_cols & db_cols)}
    Case-normalized (lower) before diffing. Empty side → that diff is [] (not a spurious mismatch)."""

# Deterministic sync_status rule (replaces LLM self-report when both sides known):
#   both non-empty & no code_only & no db_only  -> "matched"
#   both non-empty & (code_only or db_only)      -> "mismatch"
#   code known, db empty                          -> "code_only"
#   db known, code empty                          -> "db_only"
#   neither                                       -> keep LLM/"unknown"
```
Wire-up: in the store step, before `upsert_table_sync`, compute drift from `mt.code_columns_json`
(names) and the DB entry's column names (parse `entry.column_notes_json` keys or the DB index column
list already loaded), stash `column_mismatch_json` and the deterministic `sync_status` onto
`sync_data`, overriding `analysis.sync_status` per the rule above. The summary counts
(`mismatch_count` etc.) then come from the deterministic status.

**TDD steps:**
- [ ] Tests assert the set-diff is exact and status is derived, not LLM-reported:
```python
from app.knowledge.code_db_sync_pipeline import CodeDbSyncPipeline as P


def test_drift_exact_setdiff():
    d = P._compute_column_drift({"id", "email", "extra_code"}, {"id", "email", "db_only_col"})
    assert d["code_only"] == ["extra_code"]
    assert d["db_only"] == ["db_only_col"]
    assert d["matched"] == ["email", "id"]


def test_drift_case_insensitive():
    d = P._compute_column_drift({"Email"}, {"email"})
    assert d["code_only"] == [] and d["db_only"] == [] and d["matched"] == ["email"]


def test_empty_side_is_not_mismatch():
    d = P._compute_column_drift({"id"}, set())
    assert d["db_only"] == [] and d["code_only"] == ["id"]
```
      Plus a status-derivation test (helper that applies the rule): matched when sets equal, mismatch
      when they differ, code_only / db_only when a side is empty.
- [ ] Confirm fail (no `_compute_column_drift`).
- [ ] Implement helper + status derivation + wire into the store step + model column + migration:
      `cd backend && PYTHONPATH=. .venv/bin/alembic revision --autogenerate -m "code_db_sync column_mismatch_json"`
      then review for PG-safe default (`default="{}"`, no `sa.text` boolean traps) and
      `alembic upgrade head`.
- [ ] Confirm pass; run pipeline test `test_code_db_sync_pipeline_run.py` to catch regressions.
- [ ] `ruff`. Commit: `feat(sync): deterministic code↔DB column set-diff drives sync_status (SYNC-L5)`.

**DoD:** `_compute_column_drift` returns exact, case-insensitive set-diffs; empty side never
produces a spurious mismatch; `sync_status`/`mismatch_count` derive from the fact when both sides
known; `column_mismatch_json` persisted + migration applies clean on SQLite with PG-safe default.

---

### T6 — schema-qualified code↔DB matching (SYNC-L6)  [G1, dep T4 (same file)]

**Files:**
- `backend/app/knowledge/code_db_sync_pipeline.py` — `_match_tables` (~481-550).
- `backend/tests/unit/knowledge/test_sync_match_schema_qualified.py` (NEW).

**Interfaces (internal):** Match code↔DB on `(schema, table)` when the ORM entity carries a schema,
falling back to bare-name only when the code side is unqualified.
- `EntityInfo.table_name` may be `"analytics.orders"` (schema-qualified) or `"orders"` (bare).
- Build the DB lookup keyed on `(schema, bare)` (already done via `db_by_key`). Add a code-side
  qualified index: when `entity.table_name` contains a `.`, split into `(schema, bare)` and match
  the exact `(schema, bare)` DB key first; only fall back to bare-name match when the entity is
  unqualified OR the qualified key misses.
- The existing "ambiguous bare name across multiple schemas" NOTE stays, but a *qualified* code
  entity must NOT cross-contaminate a same-bare-name table in a different schema.

**TDD steps:**
- [ ] Test: two DB tables `public.orders` and `analytics.orders`; a code entity
      `table_name="analytics.orders"`. Assert the code context (columns/entity_name) attaches to the
      `analytics.orders` matched row and NOT to `public.orders`.
- [ ] Test: an unqualified code entity `table_name="orders"` with only `public.orders` in the DB →
      matches by bare name (back-compat preserved).
- [ ] Test: qualified code entity whose schema has no DB match → falls back to bare-name match with
      the ambiguity NOTE (no silent drop).
      Build `ProjectKnowledge` + `list[DbIndex]` doubles (lightweight fakes with `table_name`,
      `table_schema`, minimal columns).
- [ ] Confirm fail (current bare-lowercase join contaminates across schemas).
- [ ] Implement qualified-first matching in `_match_tables`.
- [ ] Confirm pass; `ruff`. Commit: `fix(sync): match code↔DB on (schema,table) when ORM is qualified (SYNC-L6)`.

**DoD:** qualified code entities match the correct schema and do not leak onto same-name tables in
other schemas; bare entities still match; qualified-miss degrades to bare + NOTE.

---

### T7 — uniform bare-suffix keying alias (SYNC-L7)  [G1, parallel]

**Files:**
- `backend/app/services/code_db_sync_service.py` — add a shared static helper
  `bare_suffix(name: str) -> str` and a `get_table_sync` that also tries the bare suffix.
- `backend/app/agents/sql_agent.py` — `_load_sync_filters_and_mappings` (~1514) and
  `_load_sync_for_prompt` (~1476): index guidance under BOTH the stored `table_name` and its bare
  suffix, matching the alias already applied in `_load_required_filters_by_table` (~1589-1593).
- `backend/tests/unit/test_sync_bare_suffix_keying.py` (NEW).

**Interfaces:**
```python
class CodeDbSyncService:
    @staticmethod
    def bare_suffix(name: str) -> str:
        """Return the unqualified table name: 'analytics.orders' -> 'orders'; 'orders' -> 'orders'."""
        return name.split(".")[-1]

    async def get_table_sync(self, session, connection_id, table_name) -> CodeDbSync | None:
        # try exact table_name, then bare_suffix(table_name), then any row whose bare_suffix matches
        ...
```
Wire-up: `sql_agent._load_sync_filters_and_mappings` and `_load_sync_for_prompt` must emit each
table's guidance keyed on both `e.table_name` and `bare_suffix(e.table_name)` so the agent — which
asks by bare name via `get_sync` tool / `get_table_sync` — always resolves the guidance. Uniformly
apply the same `bare_suffix` alias that `_load_required_filters_by_table` already does (do not
diverge the three code paths).

**TDD steps:**
- [ ] `test_get_table_sync_resolves_bare_when_stored_qualified`: seed a `CodeDbSync` row with
      `table_name="analytics.orders"`; `get_table_sync(session, cid, "orders")` returns it (uses an
      in-memory async SQLite session fixture; mirror the pattern in existing service tests).
- [ ] `test_bare_suffix_helper`: `bare_suffix("a.b.orders") == "orders"`, `bare_suffix("orders") == "orders"`.
- [ ] `test_load_sync_filters_keys_both_names`: monkeypatch `CodeDbSyncService.get_sync` to return a
      row with qualified `table_name="analytics.orders"` and a `required_filters_json`; assert the
      returned filters text contains a line for `orders` (bare) AND `analytics.orders`.
- [ ] Confirm fail.
- [ ] Implement `bare_suffix`, extend `get_table_sync`, apply alias in the two `sql_agent` loaders.
- [ ] Confirm pass; run the sql_agent sync tests. `ruff`.
- [ ] Commit: `fix(sync): uniform bare-suffix keying across sync loaders + get_table_sync (SYNC-L7)`.

**DoD:** `get_table_sync` resolves a bare request to a qualified-stored row; both sql_agent loaders
emit guidance under bare + qualified keys; the three code paths share one `bare_suffix` alias
(no divergence).

---

### T8 — gate code-graph "empty" freshness warning (SYNC-L8)  [G1, dep T2 (same file)]

**Files:**
- `backend/app/services/knowledge_freshness_service.py` — the code-graph block (~196-215).
- `backend/tests/unit/test_knowledge_freshness_service.py` (add `TestCodeGraphGate` class).

**Interfaces (consumes existing settings; no new contract):**
- Change the gate from `if settings.code_graph_enabled:` to
  `if settings.lineage_enabled or settings.clustering_enabled:`. Rationale (audit §7 L8): the empty
  graph only matters when a *consumer* (lineage or clustering) is on; `code_graph_enabled` alone
  builds symbols that nothing at query-time reads, so the warning is a false alarm injected into
  every answer.

**TDD steps:**
- [ ] `test_no_codegraph_warning_when_only_code_graph_enabled`: monkeypatch settings
      `code_graph_enabled=True, lineage_enabled=False, clustering_enabled=False`; even with a
      `CodeGraphService.count` returning `(0, ...)`, assert NO `category=="code_graph"` detail and
      `code_graph_stale is False`.
- [ ] `test_codegraph_warning_when_lineage_enabled`: `lineage_enabled=True` + count `(0, ...)` →
      the "Code graph is empty" warning IS emitted.
- [ ] `test_codegraph_warning_when_clustering_enabled`: `clustering_enabled=True` + count `(0, ...)`
      → warning emitted.
      Monkeypatch `app.config.settings` attributes and
      `CodeGraphService.count` = `AsyncMock(return_value=(0, 0))`.
- [ ] Confirm fail (current code warns on `code_graph_enabled`).
- [ ] Flip the gate condition.
- [ ] Confirm pass; `ruff`. Commit: `fix(freshness): gate empty-code-graph warning on lineage/clustering (SYNC-L8)`.

**DoD:** empty-graph warning fires only when `lineage_enabled or clustering_enabled`; silent under
`code_graph_enabled`-only; three cases asserted.

---

### T9 — word-boundary HTTP op-kind + low-confidence name-inference (SYNC-L9)  [G1, parallel]

**Files:**
- `backend/app/knowledge/graph_db_bridge.py` — `classify_op_kind` (~214-234) and `CallerRef`
  (add an `op_kind_confidence` field / low-confidence tag).
- `backend/tests/unit/knowledge/test_graph_db_bridge_op_kind.py` (NEW — do not edit the existing
  `test_graph_db_bridge.py`; add complementary cases in a new file).

**Interfaces:**
```python
# CallerRef gains:
op_kind_source: str = "unknown"      # "verb" | "http_method" | "name_inferred" | "unknown"
# to_dict() emits it. When op_kind was guessed from a name/decorator substring, source is
# "name_inferred" and downstream prompts must present it as low-confidence.

# classify_op_kind: return (op_kind, source). The bridge maps source→CallerRef.op_kind_source.
def classify_op_kind(symbol) -> tuple[str, str]: ...
```
Fixes:
1. Word-boundary the decorator HTTP match: replace `"get" in dec.lower()` (which matches
   `@target_getter`, `@budget`, `@forget_handler`) with a `\b(?:get|list)\b` regex. Same for the
   write-method path (already `_HTTP_WRITE_METHODS` word-boundaried — keep).
2. Verb-prefix matches → source `"verb"` (high confidence). Decorator-method matches → `"http_method"`.
   Anything inferred from a loose name/decorator substring → `"name_inferred"` (low confidence).
3. Update the sole caller in `_walk_callers` (~369-378) to unpack the tuple and set `op_kind_source`;
   update the `code_db_sync_pipeline._build_code_context` caller-line render (~686) to show
   `(op, conf=…, {source})` so `name_inferred` reads as low-confidence in the prompt.

**TDD steps:**
- [ ] Tests:
```python
from app.knowledge.graph_db_bridge import classify_op_kind


class _Sym:
    def __init__(self, name="", decorators=()):
        self.name = name
        self.decorators = decorators


def test_getter_substring_not_read_via_word_boundary():
    # decorator "@target_getter" must NOT word-match "get"
    op, src = classify_op_kind(_Sym(name="x", decorators=("target_getter",)))
    assert op == "unknown" and src == "unknown"


def test_router_get_is_read_word_boundary():
    op, src = classify_op_kind(_Sym(name="x", decorators=("router.get('/u')",)))
    assert op == "read" and src == "http_method"


def test_write_verb_prefix_high_confidence():
    op, src = classify_op_kind(_Sym(name="create_user"))
    assert op == "write" and src == "verb"


def test_post_method_is_write():
    op, src = classify_op_kind(_Sym(name="handler", decorators=("router.post('/u')",)))
    assert op == "write" and src == "http_method"
```
- [ ] Confirm fail (current returns a bare str; `"get" in dec` matches `target_getter`).
- [ ] Implement tuple return + word-boundary regex + `CallerRef.op_kind_source` + caller updates.
      Keep the existing single-file `test_graph_db_bridge.py` green (it calls
      `classify_op_kind` expecting a str) — so add back-compat: existing file asserts on the op-kind
      via `[0]`? No — that file would break. Instead update the two existing tests to unpack
      (they are in the same wave's ownership; a two-line edit) OR keep `classify_op_kind` returning
      a str and add `classify_op_kind_ex` returning the tuple. **Decision: keep `classify_op_kind`
      returning a plain str (back-compat) and add `classify_op_kind_ex(symbol) -> tuple[str, str]`;
      the bridge uses `_ex`.** This avoids editing W-owned existing tests and keeps the contract.
      Update the test file above to import `classify_op_kind_ex`.
- [ ] Confirm pass; run existing `test_graph_db_bridge.py` (must stay green). `ruff`.
- [ ] Commit: `fix(sync): word-boundary HTTP op-kind + low-confidence name-inference tag (SYNC-L9)`.

**DoD:** substring false matches (`target_getter`, `budget`) no longer classified read; `router.get`
→ read/`http_method`, `router.post` → write/`http_method`; verb prefixes tagged `verb`; name-inferred
tagged low-confidence and rendered as such; existing `test_graph_db_bridge.py` still green.

---

### T5 — `_model_name_to_table` inflection vs live DB set (SYNC-L4)  [G1, dep T3 (same file)]

**Files:**
- `backend/app/knowledge/entity_extractor.py` — `_model_name_to_table` (~1127-1130) and
  `_model_to_table` (~1103-1108); add an optional `known_tables: set[str] | None` param.
- `backend/tests/unit/knowledge/test_model_name_to_table.py` (NEW).

**Interfaces:**
```python
def _model_name_to_table(model_name: str, known_tables: set[str] | None = None) -> str:
    """Convert CamelCase model to snake_case, then pick the best candidate:
      1. snake              (e.g. "Person" -> "person")
      2. snake + "s"        ("person" -> "persons")
      3. simple inflection  ("person" -> "people"? -> use a tiny irregular map + y->ies, s/x/z/ch/sh->es)
    If known_tables is given, return the FIRST candidate present in known_tables (case-insensitive);
    else default to the pluralized snake+? — preserving current behavior when no DB set is known
    (append 's') so existing callers don't regress."""

def _model_to_table(model_name, knowledge, known_tables: set[str] | None = None) -> str: ...
```
Rules:
- Build `known_tables` from the DB index / `ProjectKnowledge` where a caller has it; when `None`,
  keep the current append-`"s"` behavior (back-compat) so no existing test breaks.
- Tiny irregular plural map (`person→people`, `child→children`, `datum→data`) + regular rules
  (`y→ies` when preceded by consonant, `s/x/z/ch/sh→es`, else `+s`).
- Candidate order tried against `known_tables`: `[snake, snake+"s", inflect(snake)]`; first hit wins.

**TDD steps:**
- [ ] Tests:
```python
from app.knowledge.entity_extractor import _model_name_to_table


def test_no_known_tables_keeps_append_s():
    assert _model_name_to_table("Order") == "orders"  # back-compat


def test_person_matches_people_when_in_db():
    assert _model_name_to_table("Person", {"people"}) == "people"


def test_prefers_exact_singular_when_present():
    assert _model_name_to_table("Category", {"category"}) == "category"


def test_prefers_plural_s_when_present():
    assert _model_name_to_table("Category", {"categories"}) == "categories"


def test_camel_to_snake_boundary():
    assert _model_name_to_table("UserProfile", {"user_profiles"}) == "user_profiles"
```
- [ ] Confirm fail (current blindly appends "s" → `Person→persons`).
- [ ] Implement candidate list + irregular map; thread optional `known_tables` through
      `_model_to_table`. Keep the `line 548` and `line 987` callers compiling (pass `None` unless a
      table set is readily available at that call site).
- [ ] Confirm pass; run extractor suite. `ruff`.
- [ ] Commit: `fix(sync): _model_name_to_table tries {name,name+s,inflected} vs DB set (SYNC-L4)`.

**DoD:** with a `known_tables` set the correct table name is chosen (`Person→people`,
exact-singular, plural-s, camel boundary); without it, the append-`s` behavior is preserved
(no regression); extractor suite green.

---

### T10 — Low batch: L11, L12, L13, L14  [G2, sequential glue; dep T7, T9]

**Files:**
- L11 — `backend/app/knowledge/code_db_sync_analyzer.py` `_coerce_confidence` (~27-42): a float-like
  confidence (`"4.5"` / `4.5`) currently coerces to the default `3`, silently discarding a
  legitimate high/low signal. **Fix:** round a numeric float to the nearest int, THEN clamp 1-5
  (so `4.5→4` after `round`→`4`; `"4.7"→5`); only truly non-numeric → `3`.
- L12 — `backend/app/knowledge/graph_db_bridge.py` `_estimate_depth` (~385-400) + `CallerRef.depth`:
  the depth is a fabricated `log_0.7(confidence)` inverse presented as if real. **Fix:** rename the
  emitted field intent — set `depth` only when known, else `-1` (unknown), and mark it in `to_dict`
  as `depth_estimated: bool = True`; the sync prompt render (~683-686) must not print a bogus
  precise depth (drop the `int(r.get("depth", 1))` dead line and only show depth when
  `depth_estimated is False`, else omit).
- L13 — `backend/app/knowledge/code_db_sync_pipeline.py` `_build_code_context` enum relevance
  (~688-692): `table_lower in e.name.lower()` substring-links unrelated enums (e.g. table `order`
  links `reorder_reason`). **Fix:** require a word-boundary / token match between the enum name and
  the table (reuse a small `\b` check) instead of raw substring.
- L14 — `backend/app/services/knowledge_freshness_service.py` `DB_INDEX_TTL_HOURS = 24` (~113): the
  fixed 24h TTL is single-value and not configurable. **Fix:** read from a new
  `settings.db_index_ttl_hours: int = 24` (add to `config.py` + `.env.example`); keep 24 default.

**TDD steps:**
- [ ] One test per fix in the owning file's test module (create
      `tests/unit/knowledge/test_sync_low_batch.py` for L11/L13, extend graph/freshness test files
      for L12/L14):
  - L11: `_coerce_confidence("4.5") == 4`; `_coerce_confidence(4.7) == 5`; `_coerce_confidence("x") == 3`;
    `_coerce_confidence(9) == 5` (clamp preserved).
  - L12: a `CallerRef.to_dict()` with an estimated depth has `depth_estimated is True`; the
    `_build_code_context` render for such a caller does NOT contain a `depth=` literal.
  - L13: enum `reorder_reason` does NOT attach to table `order`; enum `order_status` DOES.
  - L14: monkeypatch `settings.db_index_ttl_hours = 1`; a 2h-old index is flagged stale.
- [ ] Confirm fail for each; implement; confirm pass.
- [ ] `ruff`. Commit: `fix(sync): low-batch L11-L14 confidence/depth/enum-link/ttl calibration`.

**DoD:** all four low findings have a failing-then-green test; float confidences preserved (rounded,
clamped); fabricated depth no longer presented as precise; enum links word-boundary-gated; DB-index
TTL configurable (24h default); config-sync test green.

---

### T11 — Integration + docs  [G3]

**Files:** none new; verification + docs only.
- [ ] Full backend suite: `cd backend && make test-all` (unit + integration). All green; coverage
      `--fail-under=72` on the combined run.
- [ ] Lint/type parity: `cd backend && .venv/bin/ruff format --check app/ tests/ && .venv/bin/ruff check app/ tests/ && .venv/bin/mypy app/ --ignore-missing-imports`.
- [ ] Docs in the SAME wave (DoD): update `CHANGELOG.md [Unreleased]` (W5 trust-signals bullet list:
      L2/L3/L4/L5/L6/L7/L8/L9 + low batch); note the two new flags (`git_freshness_fetch_origin`,
      `db_index_ttl_hours`) in `CLAUDE.md` feature-flags section + `backend/.env.example`; if the
      `code_db_sync` migration (T4) changes the schema, note it in the migration list.
- [ ] Re-pull prod freshness/sync signal per spec §8 (n=195 baseline) if authorized — record before/
      after `git_state` distribution and any `sync_status="mismatch"` count change; this is
      observation only, no code.

**DoD:** `make check` green (ruff format+check, mypy, unit+integration, coverage ≥72%); no frontend
touched (skip FE gates); CHANGELOG + CLAUDE.md + `.env.example` updated in-wave.

---

## Human steps (end)
- None required to ship. Enabling `git_freshness_fetch_origin=true` in prod is an operator decision
  (it adds network I/O per freshness check); leave it default-off. Post-deploy prod re-pull (T11
  last box) is operator-run and optional.

## Plan self-review (pre-handoff)
- Every W5 spec §3 finding maps to a task: L2→T3, L3→T1+T2, L4→T5, L5→T4, L6→T6, L7→T7, L8→T8,
  L9→T9, low(L11-L14)→T10. SYNC-L1 explicitly excluded (W1). SYNC-L10 excluded (W6 flag).
- C-F `GitFreshness`/`classify_freshness` consumed VERBATIM in T1 (implement) and T2 (consume).
- No two parallel tasks write the same file: `code_db_sync_pipeline.py` T4→T6 sequenced;
  `knowledge_freshness_service.py` T2→T8 sequenced; `entity_extractor.py` T3→T5 sequenced (distinct
  functions); `code_db_sync_service.py` T7→T10 sequenced. `graph_db_bridge.py` T9 then T10 sequenced.
- No placeholders: every task has real test + impl code, exact commands, and a verifiable DoD.
- Freshness tests: real throwaway git repo in `tmp_path` (T1 fresh/ahead/behind) + mocked
  `iter_commits`/`is_ancestor` for diverged and bad-SHA (no real remote needed).
- Matching tests: comment/string-literal/CTE false positives asserted excluded (T3); drift set-diff
  asserted exact + case-insensitive (T4).
