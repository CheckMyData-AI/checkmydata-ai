# Module 08 — GitAgent (live Git) — Audit Report

**Round 1** · 2026-06-24 · Scope: `knowledge/git_inspector.py`, `agents/git_agent.py`.

Documented contract (`git_inspector.py:7-15` + CLAUDE.md): **read-only only** — no
write/checkout/config/hook-executing operations; every caller-supplied **file path** validated
against the repo root (path-traversal guard); every output byte-capped; GitPython always called
with explicit argument lists (no shell). Optional `git_agent_auto_pull`.

**Positive notes (verified):**
- Path-traversal guard is solid: `_safe_relpath` does `(_repo_dir / path).resolve()` +
  `is_relative_to(_repo_dir)` (symlink-following resolve closes the symlink-escape variant)
  (`git_inspector.py:113-122`).
- Output caps everywhere: `_truncate` (byte cap), `_clamp` on counts/context, `_BLAME_MAX_LINES`.
- `diff` correctly inserts `--` before paths (`:258`) so a path can't be parsed as a rev.
- GitPython arg-lists → no shell-injection; binary files are skipped in `show`; operations are
  read-only (no checkout/config/hook execution).
- Good error classification (`InvalidRefError` vs `GitCommandFailedError`).

Severity: 🔴 Critical · 🟠 High · 🟡 Medium · 🟢 Low · ⚪ Info

---

## F-GIT-01 — 🟡 Medium — Option injection via unvalidated rev/sha → arbitrary file write (breaks the read-only invariant)

**Type:** Security (read-only bypass / file write)
**Location:** `git_inspector.py:220/222` (`repo.git.show(sha)`), `:256-261`
(`repo.git.diff(a_sha, b_sha, …)`), `:280` (`repo.blame(commit_sha, …)`), `:193`
(`iter_commits(rev=…)`). The values are **LLM-authored tool arguments** passed straight through
from `git_agent.py:362-396` (`inspector.show(args["sha"])`, `inspector.diff(args["a_sha"],
args.get("b_sha","HEAD"))`, etc.). There is **no rev validation anywhere** (no regex, no
`rev_parse`, no leading-`-` rejection — confirmed by search).

**Description.** The path guard protects file paths, but the **rev/sha** arguments are not
guarded and are passed positionally to `git`. `git show` and `git diff` both accept
`--output=<file>` (and other diff options), so a rev value like `--output=/app/evil` yields:

```
git show --output=/app/evil      # writes attacker-chosen content to an arbitrary file
git diff --output=/app/evil HEAD
```

That is an **arbitrary file-write primitive**, directly contradicting the module's "read-only
only — no write operations" guarantee. The rev is chosen by the LLM, which is itself steerable
via indirect prompt injection (repo content / question — see F-SQL-01), so this is reachable, not
purely theoretical. The `--` separator used in `diff` only separates *paths* from revs; it does
**not** stop a rev itself from being parsed as an option.

**Impact.** Read-only invariant bypass; arbitrary file write on the indexing/agent host (config
overwrite, planting files), plus information disclosure via other diff options.

**Proposed fix.** Validate every rev/sha before use: reject any value beginning with `-`,
allowlist a safe charset (`^[0-9A-Za-z][0-9A-Za-z._/\-^~@{}]*$`), and resolve it to a concrete
object via `repo.rev_parse(rev)` (raising on failure) before passing to `git`. Additionally pass
`--end-of-options` after the subcommand where supported (`git show --end-of-options <rev>`), so a
rev can never be interpreted as an option.

---

## F-GIT-02 — 🟢 Low — `git_agent_auto_pull` makes a "read-only" agent perform network fetch + working-tree update (inherits F-KNOW-02 MITM)

**Type:** Security / consistency
**Location:** `agents/git_agent.py:149-183` (`_maybe_auto_pull` → `repo_analyzer.clone_or_pull`).

**Description.** When `git_agent_auto_pull` is enabled, the GitAgent calls `clone_or_pull`, which
fetches over the network and updates the working tree — a write/network operation under an agent
documented as read-only. That path uses `GIT_SSH_COMMAND … StrictHostKeyChecking=no`
(F-KNOW-02), so an enabled auto-pull is MITM-exposed and can import a tampered tree that then
feeds the agent's answers.

**Proposed fix.** Keep auto-pull clearly gated (it is, default off), route it through the shared
host-key policy (fix F-KNOW-02), and document that enabling it relaxes the read-only stance to
"read + fast-forward pull".

---

## F-GIT-03 — 🟢 Low — `except (TimeoutError, Exception)` swallows all auto-pull errors (redundant + over-broad)

**Type:** Cleanliness / observability
**Location:** `agents/git_agent.py:182` (`except (TimeoutError, Exception): … best-effort`).

**Description.** `Exception` already covers `TimeoutError`, so the tuple is redundant, and catching
`Exception` broadly as "best-effort" hides real failures (ties to the cross-cutting silent-handler
theme, F-CHAT-05 / obs 21209). It does `logger.warning(..., exc_info=True)` (better than `pass`),
but masks classification (e.g. auth vs network vs MITM-rejection).

**Proposed fix.** Catch specific exceptions; let unexpected ones propagate or be logged at error
with classification. Drop the redundant `TimeoutError`.

---

## Test gaps (⚪ Info)

- No test that a rev/sha like `--output=/tmp/x` is **rejected** before reaching git (F-GIT-01) —
  high-value regression test.
- No test that `auto_pull` honours a host-key policy (F-GIT-02).

## Summary

| id | sev | one-line |
|----|-----|----------|
| F-GIT-01 | 🟡 | Unvalidated rev/sha → `git show/diff --output=<file>` arbitrary file write (read-only bypass) |
| F-GIT-02 | 🟢 | `auto_pull` does network fetch + tree update with `StrictHostKeyChecking=no` (cf F-KNOW-02) |
| F-GIT-03 | 🟢 | `except (TimeoutError, Exception)` redundant + over-broad on auto-pull |

**Next-round focus:** `commits_touching` / `review_signals` arg handling (more LLM-authored
revs); whether `log(rev=…)` with `iter_commits` can be option-injected; the `has_repo` probe and
freshness-warning accuracy; tag_prefix/path interactions in `list_releases`.
