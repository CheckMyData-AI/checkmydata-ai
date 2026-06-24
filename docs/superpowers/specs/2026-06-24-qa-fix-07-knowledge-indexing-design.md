# Spec — QA Fix Module 07: Knowledge & Indexing

**Date:** 2026-06-24 · **Source:** [`docs/qa-audit/reports/07-knowledge-indexing.md`](../../qa-audit/reports/07-knowledge-indexing.md)
**Branch:** `fix/security-audit-2026-06-24`

## Already fixed by `e642c67` (on `origin/main`) — do not redo
- **F-KNOW-01 🔴 RCE** — `validate_repo_url()` allowlist (`app/knowledge/repo_url.py`) +
  `GIT_ALLOW_PROTOCOL=http:https:ssh` pinned into git env; applied at API boundary and in
  `RepoAnalyzer`. Rejects `ext::`/`fd::`/`file://`/`git://` and leading-dash.
- **F-KNOW-02 🟡 host-key** — git-SSH `StrictHostKeyChecking=no` → `accept-new` (TOFU), now
  consistent with the Module-04 default policy. (Full shared-known_hosts policy left as a future
  enhancement; the blind-accept hole is closed.)

## In scope this module

### C1 — F-KNOW-05 🟢 Validate `branch` (option-injection smell)
`branch` is user-supplied (`routes/repos.py:786,797` `Field("main", max_length=200)`) and passed to
`repo.git.checkout(branch)` / `clone_from(branch=branch)` (`repo_analyzer.py:414,422`) with no
pattern. GitPython uses arg-lists (no shell), but a leading `-` or `--upload-pack=` is an option-
injection smell. Add `validate_git_ref()` to `app/knowledge/repo_url.py`:
```python
_GIT_REF_RE = re.compile(r"^[A-Za-z0-9._][A-Za-z0-9._/-]*$")
def validate_git_ref(ref: str) -> str:
    r = (ref or "").strip()
    if not r or r.startswith("-") or ".." in r or r.endswith("/") or r.endswith(".lock"):
        raise ValueError("Invalid branch/ref name")
    if not _GIT_REF_RE.match(r):
        raise ValueError("Branch/ref may contain only letters, digits, '.', '_', '-', '/'")
    return r
```
Apply at the API boundary (`RepoCheckRequest`/repo create+update field validator) **and** in
`RepoAnalyzer.clone_or_pull` / `ls_remote` (defense-in-depth), mirroring how `validate_repo_url`
is applied in both places.

### C2 — F-KNOW-03 🟡 Re-point clone when `repo_url` changes
`repo_analyzer.py:419-426` (existing-clone branch) fetches `repo.remotes.origin` (the *original*
URL) and ignores the passed `repo_url`. On reuse, reconcile:
```python
if repo_dir.exists() and (repo_dir / ".git").exists():
    repo = Repo(str(repo_dir))
    try:
        current = repo.remotes.origin.url
    except Exception:
        current = None
    if current != repo_url:
        repo.remotes.origin.set_url(repo_url)
        logger.info("Re-pointed clone for %s: %s -> %s", project_id, current, repo_url)
    with repo.git.custom_environment(**env):
        repo.remotes.origin.fetch()
        repo.git.checkout(branch)
        repo.remotes.origin.pull()
```

## Deferred (later iterations / backlog) — with rationale
- **F-KNOW-04 🟢 temp key on disk** — prefer `mkdtemp(0700)` + scrub; small, next chunk.
- **F-KNOW-06 🟢 pickle→safe format** — replace `pickle` BM25 snapshot with JSON/safe arrays;
  must do **before** F-KNOW-07 (shared storage). Moderate; own chunk with back-compat (old `.pkl`
  → treat as miss + rebuild).
- **F-KNOW-07 🟡 BM25 on ephemeral disk** — full fix = shared object storage (new dep/config/
  deploy): a deliberate architecture change → **backlog item**, not a quick fix. This module adds
  the *observability* half now (metric/log on `load()` miss) so the silent dense-only degradation
  is visible; the storage migration is tracked in `BACKLOG.md`.

## Test plan
- `tests/unit/test_repo_url.py` — `validate_git_ref` accepts `main`, `feature/x`, `v1.2.3`;
  rejects ``, `-x`, `--upload-pack=y`, `a..b`, `foo/`, `x.lock`.
- `tests/unit/test_repo_analyzer*.py` (or new) — changing `repo_url` on an existing clone calls
  `set_url` (mock `Repo`); branch checkout uses the validated ref.

## DoD
C1+C2 implemented + tested; `make check` green; report F-KNOW-03/05 annotated fixed; F-KNOW-04/06/07
status recorded (deferred/backlog). Then push (PR) — prod merge remains the gated human step.
