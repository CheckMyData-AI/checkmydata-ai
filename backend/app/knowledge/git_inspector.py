"""GitInspector — low-level, read-only Git access for the agent.

Wraps GitPython operations on a project's *local* clone
(``repo_clone_base_dir / project_id``) behind a small, safe, async surface.

Design constraints (senior-secops / senior-backend):
- Read-only only. No write / checkout / config / hook-executing operations.
- Every caller-supplied file path is validated against the repo root to
  prevent path-traversal (``../../etc/passwd``).
- Every textual output is byte-capped so a single huge file/diff cannot blow
  up memory or the LLM context window.
- All GitPython calls run in a worker thread (``asyncio.to_thread``) because
  GitPython is synchronous/blocking IO.
- GitPython is always called with explicit argument lists — never a shell
  string — so there is no shell-injection surface.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from git import Repo
from git.exc import BadName, BadObject, GitCommandError, InvalidGitRepositoryError, NoSuchPathError

from app.config import settings
from app.knowledge.repo_analyzer import BINARY_EXTENSIONS

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------------
# Error taxonomy
# ----------------------------------------------------------------------------


class GitInspectorError(Exception):
    """Base class for all GitInspector errors."""


class RepoNotClonedError(GitInspectorError):
    """The project's repository has not been cloned locally yet."""


class InvalidRefError(GitInspectorError):
    """A commit SHA / ref / tag could not be resolved."""


class PathOutsideRepoError(GitInspectorError):
    """A caller-supplied path resolves outside the repository root."""


class GitCommandFailedError(GitInspectorError):
    """An underlying git command failed for an unexpected reason."""


_TRAILER_RE = {
    "reviewers": re.compile(r"^\s*Reviewed-by:\s*(.+)$", re.IGNORECASE | re.MULTILINE),
    "co_authors": re.compile(r"^\s*Co-authored-by:\s*(.+)$", re.IGNORECASE | re.MULTILINE),
    "signed_off_by": re.compile(r"^\s*Signed-off-by:\s*(.+)$", re.IGNORECASE | re.MULTILINE),
}
_MERGE_BRANCH_RE = re.compile(
    r"Merge branch '([^']+)'(?:\s+of\s+\S+)?(?:\s+into\s+(\S+))?",
    re.IGNORECASE,
)
_MERGE_PR_RE = re.compile(r"Merge pull request #(\d+) from (\S+)", re.IGNORECASE)


def _clamp(value: Any, low: int, high: int, default: int) -> int:
    """Clamp *value* into ``[low, high]``; fall back to *default* on garbage."""
    try:
        return max(low, min(int(value), high))
    except (TypeError, ValueError):
        return default


class GitInspector:
    """Read-only inspector over a single local Git clone."""

    # Hard ceiling on blame line count so a 100k-line file can't flood context.
    _BLAME_MAX_LINES = 2000

    def __init__(
        self,
        repo_dir: Path | str,
        *,
        max_output_bytes: int | None = None,
        max_log_count: int | None = None,
    ) -> None:
        self._repo_dir = Path(repo_dir).resolve()
        self._max_output_bytes = max_output_bytes or settings.git_max_output_bytes
        self._max_log_count = max_log_count or settings.git_max_log_count

    # ------------------------------------------------------------------
    # Internal helpers (sync — always called inside asyncio.to_thread)
    # ------------------------------------------------------------------

    def _open_repo(self) -> Repo:
        if not (self._repo_dir / ".git").exists():
            raise RepoNotClonedError(
                f"Repository for this project has not been cloned yet "
                f"(expected at {self._repo_dir})."
            )
        try:
            return Repo(str(self._repo_dir))
        except (InvalidGitRepositoryError, NoSuchPathError) as exc:
            raise RepoNotClonedError(str(exc)) from exc

    def _safe_relpath(self, path: str) -> str:
        """Validate *path* stays inside the repo and return it relative."""
        if not path:
            raise PathOutsideRepoError("Empty path is not allowed.")
        candidate = (self._repo_dir / path).resolve()
        if candidate != self._repo_dir and not candidate.is_relative_to(self._repo_dir):
            raise PathOutsideRepoError(
                f"Path '{path}' resolves outside the repository and is not allowed."
            )
        return str(candidate.relative_to(self._repo_dir))

    def _truncate(self, text: str) -> str:
        if text is None:
            return ""
        # Byte-accurate cap; slice on characters (cheaper) using the byte
        # budget as a char budget — UTF-8 chars are >=1 byte so this never
        # exceeds the byte limit by more than the trailing notice.
        if len(text.encode("utf-8", errors="replace")) <= self._max_output_bytes:
            return text
        clipped = text[: self._max_output_bytes]
        return clipped + "\n… (truncated — output exceeded the size limit)"

    @staticmethod
    def _ts_to_iso(epoch: int) -> str:
        try:
            return datetime.fromtimestamp(epoch, tz=UTC).isoformat()
        except (OverflowError, OSError, ValueError):
            return ""

    @classmethod
    def _commit_to_dict(cls, commit: Any) -> dict[str, Any]:
        message = commit.message
        if isinstance(message, bytes):
            message = message.decode("utf-8", errors="replace")
        return {
            "sha": commit.hexsha,
            "short_sha": commit.hexsha[:10],
            "author_name": commit.author.name,
            "author_email": commit.author.email,
            "committer_name": commit.committer.name,
            "committer_email": commit.committer.email,
            "message": (message or "").strip(),
            "authored_date": cls._ts_to_iso(commit.authored_date),
            "committed_date": cls._ts_to_iso(commit.committed_date),
            "parents": [p.hexsha[:10] for p in commit.parents],
            "is_merge": len(commit.parents) > 1,
        }

    # ------------------------------------------------------------------
    # Public async API
    # ------------------------------------------------------------------

    async def log(
        self,
        *,
        paths: list[str] | None = None,
        since: str | None = None,
        until: str | None = None,
        author: str | None = None,
        rev: str | None = None,
        max_count: int = 100,
    ) -> list[dict[str, Any]]:
        """Return recent commits (newest first) as plain dicts."""
        count = _clamp(max_count, 1, self._max_log_count, min(100, self._max_log_count))
        safe_paths = [self._safe_relpath(p) for p in paths] if paths else None

        def _run() -> list[dict[str, Any]]:
            repo = self._open_repo()
            # Unborn HEAD (freshly-init'd repo, no commits): nothing to return.
            if (rev is None or rev == "HEAD") and not repo.head.is_valid():
                return []
            kwargs: dict[str, Any] = {"max_count": count}
            if author:
                kwargs["author"] = author
            if since:
                kwargs["since"] = since
            if until:
                kwargs["until"] = until
            try:
                commits = list(
                    repo.iter_commits(rev=rev or "HEAD", paths=safe_paths or [], **kwargs)
                )
            except ValueError:
                # Empty repo / unborn HEAD — no commits to return.
                return []
            except (BadName, BadObject) as exc:
                raise InvalidRefError(f"Could not resolve '{rev}': {exc}") from exc
            except GitCommandError as exc:
                stderr = (exc.stderr or "").lower()
                if "bad revision" in stderr or "unknown revision" in stderr:
                    # Unborn HEAD surfaces here on some git versions.
                    return []
                raise GitCommandFailedError(str(exc)) from exc
            return [self._commit_to_dict(c) for c in commits]

        return await asyncio.to_thread(_run)

    async def show(self, sha: str, path: str | None = None) -> str:
        """Show a commit (diff) or the content of *path* at *sha*."""
        safe = self._safe_relpath(path) if path else None
        if safe and Path(safe).suffix.lower() in BINARY_EXTENSIONS:
            return f"(binary file '{safe}' — content not shown)"

        def _run() -> str:
            repo = self._open_repo()
            try:
                if safe:
                    out = repo.git.show(f"{sha}:{safe}")
                else:
                    out = repo.git.show(sha)
            except GitCommandError as exc:
                stderr = (exc.stderr or "").lower()
                if "exists on disk, but not in" in stderr or "does not exist" in stderr:
                    raise InvalidRefError(
                        f"Path '{safe}' does not exist at commit '{sha}'."
                    ) from exc
                if (
                    "bad revision" in stderr
                    or "unknown revision" in stderr
                    or "invalid object name" in stderr
                    or "bad object" in stderr
                    or "not a valid object name" in stderr
                ):
                    raise InvalidRefError(f"Could not resolve commit '{sha}'.") from exc
                raise GitCommandFailedError(str(exc)) from exc
            return self._truncate(out)

        return await asyncio.to_thread(_run)

    async def diff(
        self,
        a_sha: str,
        b_sha: str = "HEAD",
        *,
        paths: list[str] | None = None,
        unified: int = 3,
    ) -> str:
        """Return a unified diff between *a_sha* and *b_sha*."""
        safe_paths = [self._safe_relpath(p) for p in paths] if paths else None
        ctx = _clamp(unified, 0, 50, 3)

        def _run() -> str:
            repo = self._open_repo()
            args: list[str] = [a_sha, b_sha]
            if safe_paths:
                args.append("--")
                args.extend(safe_paths)
            try:
                out = repo.git.diff(*args, unified=ctx)
            except GitCommandError as exc:
                stderr = (exc.stderr or "").lower()
                if "bad revision" in stderr or "unknown revision" in stderr:
                    raise InvalidRefError(f"Could not resolve '{a_sha}' or '{b_sha}'.") from exc
                raise GitCommandFailedError(str(exc)) from exc
            if not out.strip():
                return f"(no differences between {a_sha} and {b_sha})"
            return self._truncate(out)

        return await asyncio.to_thread(_run)

    async def blame(self, path: str, commit_sha: str = "HEAD") -> list[dict[str, Any]]:
        """Return per-line authorship for *path* at *commit_sha*."""
        safe = self._safe_relpath(path)

        def _run() -> list[dict[str, Any]]:
            repo = self._open_repo()
            try:
                blame_data = repo.blame(commit_sha, safe)
            except (BadName, BadObject) as exc:
                raise InvalidRefError(f"Could not resolve '{commit_sha}': {exc}") from exc
            except GitCommandError as exc:
                stderr = (exc.stderr or "").lower()
                if "no such path" in stderr or "does not exist" in stderr:
                    raise InvalidRefError(
                        f"Path '{safe}' does not exist at '{commit_sha}'."
                    ) from exc
                raise GitCommandFailedError(str(exc)) from exc

            lines: list[dict[str, Any]] = []
            line_no = 1
            truncated = False
            blame_entries = cast(list[tuple[Any, list[Any]]], blame_data or [])
            for commit, blamed_lines in blame_entries:
                for raw in blamed_lines:
                    if line_no > self._BLAME_MAX_LINES:
                        truncated = True
                        break
                    content = (
                        raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
                    )
                    lines.append(
                        {
                            "line_number": line_no,
                            "commit_sha": commit.hexsha[:10],
                            "author_name": commit.author.name,
                            "author_email": commit.author.email,
                            "content": content,
                        }
                    )
                    line_no += 1
                if truncated:
                    break
            if truncated:
                lines.append(
                    {
                        "line_number": -1,
                        "commit_sha": "",
                        "author_name": "",
                        "author_email": "",
                        "content": f"… (truncated at {self._BLAME_MAX_LINES} lines)",
                    }
                )
            return lines

        return await asyncio.to_thread(_run)

    async def list_releases(
        self, tag_prefix: str = "", max_count: int = 100
    ) -> list[dict[str, Any]]:
        """Return tags (releases) sorted newest-first."""
        count = _clamp(max_count, 1, 500, 100)

        def _run() -> list[dict[str, Any]]:
            repo = self._open_repo()
            releases: list[dict[str, Any]] = []
            for tag in repo.tags:
                if tag_prefix and not tag.name.startswith(tag_prefix):
                    continue
                try:
                    commit = tag.commit
                except (ValueError, GitCommandError):
                    continue
                raw_message: str | bytes = ""
                tag_obj = getattr(tag, "tag", None)
                if tag_obj is not None and getattr(tag_obj, "message", None):
                    raw_message = tag_obj.message
                else:
                    raw_message = commit.message
                message = (
                    raw_message.decode("utf-8", errors="replace")
                    if isinstance(raw_message, bytes)
                    else raw_message
                )
                # ``.strip()`` can empty a whitespace-only message, and
                # ``"".splitlines()`` is ``[]`` — guard the index so an empty or
                # blank tag/commit message yields "" instead of IndexError.
                subject_lines = (message or "").strip().splitlines()
                releases.append(
                    {
                        "tag_name": tag.name,
                        "commit_sha": commit.hexsha,
                        "short_sha": commit.hexsha[:10],
                        "commit_date": self._ts_to_iso(commit.committed_date),
                        "message": subject_lines[0] if subject_lines else "",
                    }
                )
            releases.sort(key=lambda r: r["commit_date"], reverse=True)
            return releases[:count]

        return await asyncio.to_thread(_run)

    async def authors_stats(
        self, *, since_date: str | None = None, max_authors: int = 20
    ) -> list[dict[str, Any]]:
        """Return commit counts per author (most active first)."""
        cap = _clamp(max_authors, 1, 200, 20)

        def _run() -> list[dict[str, Any]]:
            repo = self._open_repo()
            kwargs: dict[str, Any] = {"max_count": self._max_log_count}
            if since_date:
                kwargs["since"] = since_date
            counts: dict[str, int] = {}
            try:
                for c in repo.iter_commits(**kwargs):
                    key = c.author.name or c.author.email or "unknown"
                    counts[key] = counts.get(key, 0) + 1
            except ValueError:
                return []
            except GitCommandError as exc:
                raise GitCommandFailedError(str(exc)) from exc
            ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
            return [{"author_name": name, "commit_count": n} for name, n in ranked[:cap]]

        return await asyncio.to_thread(_run)

    async def file_churn(
        self, *, since_date: str | None = None, max_files: int = 20
    ) -> list[dict[str, Any]]:
        """Return the most frequently-changed files."""
        cap = _clamp(max_files, 1, 200, 20)

        def _run() -> list[dict[str, Any]]:
            repo = self._open_repo()
            kwargs: dict[str, Any] = {"max_count": self._max_log_count}
            if since_date:
                kwargs["since"] = since_date
            counts: dict[str, int] = {}
            try:
                for c in repo.iter_commits(**kwargs):
                    # Merge commits have no meaningful single-parent stats.
                    if len(c.parents) > 1:
                        continue
                    for fpath in c.stats.files:
                        key = str(fpath)
                        counts[key] = counts.get(key, 0) + 1
            except ValueError:
                return []
            except GitCommandError as exc:
                raise GitCommandFailedError(str(exc)) from exc
            ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
            return [{"file_path": fp, "change_count": n} for fp, n in ranked[:cap]]

        return await asyncio.to_thread(_run)

    async def commits_touching(
        self, pattern: str, *, case_sensitive: bool = False, max_count: int = 100
    ) -> list[dict[str, Any]]:
        """Return commits whose diff added/removed *pattern* (pickaxe -G)."""
        if not pattern or not pattern.strip():
            raise GitInspectorError("Search pattern must not be empty.")
        count = _clamp(max_count, 1, self._max_log_count, min(100, self._max_log_count))

        def _run() -> list[dict[str, Any]]:
            repo = self._open_repo()
            args = ["--regexp-ignore-case"] if not case_sensitive else []
            try:
                # ``-G<pattern>`` finds commits where the diff contains the
                # regex; explicit arg list = no shell-injection surface.
                raw = repo.git.log(
                    "--format=%H",
                    "-G",
                    pattern,
                    f"--max-count={count}",
                    *args,
                )
            except GitCommandError as exc:
                raise GitCommandFailedError(str(exc)) from exc
            shas = [line.strip() for line in raw.splitlines() if line.strip()]
            out: list[dict[str, Any]] = []
            for sha in shas:
                try:
                    out.append(self._commit_to_dict(repo.commit(sha)))
                except (BadName, BadObject, ValueError):
                    continue
            return out

        return await asyncio.to_thread(_run)

    async def review_signals(self, commit_sha: str) -> dict[str, Any]:
        """Parse review-related trailers and merge info from a commit message."""

        def _run() -> dict[str, Any]:
            repo = self._open_repo()
            try:
                commit = repo.commit(commit_sha)
            except (BadName, BadObject, ValueError) as exc:
                raise InvalidRefError(f"Could not resolve commit '{commit_sha}': {exc}") from exc
            message = commit.message
            if isinstance(message, bytes):
                message = message.decode("utf-8", errors="replace")

            signals: dict[str, Any] = {
                "sha": commit.hexsha,
                "short_sha": commit.hexsha[:10],
                "is_merge_commit": len(commit.parents) > 1,
                "reviewers": [m.strip() for m in _TRAILER_RE["reviewers"].findall(message)],
                "co_authors": [m.strip() for m in _TRAILER_RE["co_authors"].findall(message)],
                "signed_off_by": [m.strip() for m in _TRAILER_RE["signed_off_by"].findall(message)],
                "merge_source_branch": None,
                "merge_target_branch": None,
                "pull_request": None,
            }

            pr_match = _MERGE_PR_RE.search(message)
            if pr_match:
                signals["pull_request"] = pr_match.group(1)
                signals["merge_source_branch"] = pr_match.group(2)
            else:
                branch_match = _MERGE_BRANCH_RE.search(message)
                if branch_match:
                    signals["merge_source_branch"] = branch_match.group(1)
                    signals["merge_target_branch"] = branch_match.group(2)
            return signals

        return await asyncio.to_thread(_run)
