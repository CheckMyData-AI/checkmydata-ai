"""GitAgent — live, read-only Git history specialist.

Mirrors :class:`KnowledgeAgent`'s bounded tool-calling loop, but its tools are
backed by :class:`GitInspector` (GitPython on the local clone) instead of the
vector store. It can also persist durable code findings to Insight Memory.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.agents.base import AgentContext, AgentResult, BaseAgent
from app.agents.prompts import get_current_datetime_str
from app.agents.prompts.git_prompt import build_git_system_prompt
from app.agents.tools.git_tools import get_git_tools
from app.config import settings
from app.core.history_trimmer import trim_loop_messages
from app.knowledge.git_inspector import GitInspector, GitInspectorError
from app.knowledge.git_tracker import GitTracker
from app.knowledge.repo_analyzer import RepoAnalyzer
from app.llm.base import LLMResponse, Message, ToolCall

logger = logging.getLogger(__name__)


@dataclass
class GitAgentResult(AgentResult):
    """Typed result from the Git agent."""

    answer: str = ""
    tool_call_log: list[dict[str, Any]] = field(default_factory=list)
    raw_git_output: str | None = None


class GitAgent(BaseAgent):
    """Read-only Git history specialist agent."""

    def __init__(
        self,
        repo_analyzer: RepoAnalyzer | None = None,
        git_tracker: GitTracker | None = None,
    ) -> None:
        self._repo_analyzer = repo_analyzer or RepoAnalyzer(settings.repo_clone_base_dir)
        self._git_tracker = git_tracker or GitTracker()

    @property
    def name(self) -> str:
        return "git"

    @staticmethod
    def _messages_preview(msgs: list[Message], max_len: int = 500) -> str:
        parts: list[str] = []
        for m in reversed(msgs):
            if m.role in ("user", "assistant"):
                parts.append(f"[{m.role}] {(m.content or '')[:200]}")
                if len("\n".join(parts)) > max_len:
                    break
        return "\n".join(reversed(parts))[:max_len]

    def _repo_dir(self, project_id: str) -> Path:
        return self._repo_analyzer.get_repo_dir(project_id)

    def has_repo(self, project_id: str) -> bool:
        return (self._repo_dir(project_id) / ".git").exists()

    # ------------------------------------------------------------------
    # Deterministic helpers (no LLM loop) — used by the orchestrator
    # dispatcher and the pipeline stage executor.
    # ------------------------------------------------------------------

    async def get_release_timeline(
        self,
        project_id: str,
        *,
        tag_prefix: str = "",
        max_count: int = 50,
    ) -> str:
        """Return the release timeline as a markdown table (no LLM call)."""
        repo_dir = self._repo_dir(project_id)
        if not (repo_dir / ".git").exists():
            return (
                "No cloned Git repository is available for this project, so there "
                "is no release timeline to return."
            )
        inspector = GitInspector(repo_dir)
        try:
            releases = await inspector.list_releases(tag_prefix=tag_prefix, max_count=max_count)
        except GitInspectorError as exc:
            return f"Error reading release timeline: {exc}"
        return self._format_releases(releases)

    async def write_code_note(self, project_id: str, subject: str, note: str) -> str:
        """Persist a durable code finding to project insight memory."""
        subject = (subject or "").strip()
        note = (note or "").strip()
        if not subject or not note:
            return "Error executing write_code_note: both 'subject' and 'note' are required."

        from app.core.insight_memory import InsightMemoryService
        from app.models.base import async_session_factory

        try:
            async with async_session_factory() as session:
                await InsightMemoryService().store_insight(
                    session,
                    project_id,
                    insight_type="code_finding",
                    title=subject[:200],
                    description=note,
                    severity="info",
                    evidence=[{"subject": subject}],
                )
        except Exception as exc:  # noqa: BLE001
            logger.exception("write_code_note failed")
            return f"Error executing write_code_note: {exc}"
        return f"Saved code note about '{subject}'. It will be recalled in future questions."

    # ------------------------------------------------------------------
    # Freshness / optional auto-pull
    # ------------------------------------------------------------------

    async def _freshness_warning(self, project_id: str, repo_dir: Path) -> str | None:
        """Warn when the local clone has fallen behind the indexed HEAD."""
        from app.models.base import async_session_factory

        try:
            async with async_session_factory() as session:
                last_sha = await self._git_tracker.get_last_indexed_sha(session, project_id)
        except Exception:  # noqa: BLE001 — freshness is best-effort
            logger.debug("Freshness check: could not load last indexed sha", exc_info=True)
            return None

        if not last_sha:
            return None

        ahead = await self._git_tracker.count_commits_ahead(repo_dir, last_sha)
        if ahead >= settings.git_staleness_warn_commits:
            return (
                f"The local clone is ~{ahead} commits ahead of the last indexed "
                f"commit ({last_sha[:10]}). Git history is live so this is fine, "
                "but the semantic knowledge base may be behind."
            )
        return None

    async def _maybe_auto_pull(self, project_id: str) -> None:
        """Optionally refresh the local clone before answering (opt-in)."""
        if not settings.git_agent_auto_pull:
            return
        from app.models.base import async_session_factory
        from app.models.project import Project
        from app.services.ssh_key_service import SshKeyService

        try:
            async with async_session_factory() as session:
                project = await session.get(Project, project_id)
                if project is None or not project.repo_url:
                    return
                ssh_content: str | None = None
                ssh_pass: str | None = None
                if project.ssh_key_id:
                    decrypted = await SshKeyService().get_decrypted(session, project.ssh_key_id)
                    if decrypted:
                        ssh_content, ssh_pass = decrypted
                repo_url = project.repo_url
                branch = project.repo_branch or "main"

            await asyncio.wait_for(
                asyncio.to_thread(
                    self._repo_analyzer.clone_or_pull,
                    repo_url=repo_url,
                    project_id=project_id,
                    branch=branch,
                    ssh_key_content=ssh_content,
                    ssh_key_passphrase=ssh_pass,
                ),
                timeout=settings.git_clone_pull_timeout_s,
            )
        except (TimeoutError, Exception):  # noqa: BLE001 — auto-pull is best-effort
            logger.warning("GitAgent auto-pull failed for %s", project_id, exc_info=True)

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def run(  # type: ignore[override]
        self,
        context: AgentContext,
        *,
        question: str = "",
    ) -> GitAgentResult:
        question = question or context.user_question
        repo_dir = self._repo_dir(context.project_id)

        result = GitAgentResult()

        if not (repo_dir / ".git").exists():
            result.answer = (
                "This project does not have a cloned Git repository available, so "
                "I cannot inspect its commit history. Connect a repository and index "
                "it first."
            )
            result.status = "no_result"
            return result

        await self._maybe_auto_pull(context.project_id)

        inspector = GitInspector(repo_dir)
        freshness = await self._freshness_warning(context.project_id, repo_dir)

        tools = get_git_tools()
        system_prompt = build_git_system_prompt(
            current_datetime=get_current_datetime_str(),
            freshness_warning=freshness,
        )
        messages: list[Message] = [
            Message(role="system", content=system_prompt),
            Message(role="user", content=question),
        ]

        total_usage: dict[str, int] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }
        tool_call_log: list[dict[str, Any]] = []

        tracker = context.tracker
        wf_id = context.workflow_id
        loop_budget = context.llm_router.get_context_window(context.model)

        max_iters = settings.max_git_iterations
        for iteration in range(max_iters):
            messages, _ = trim_loop_messages(messages, loop_budget)
            await tracker.emit(
                wf_id,
                "thinking",
                "in_progress",
                f"Git Agent thinking (step {iteration + 1}/{max_iters})…",
            )
            _sd_llm: dict[str, Any] = {}
            async with tracker.step(
                wf_id,
                "git:llm_call",
                f"Git LLM call ({iteration + 1}/{max_iters})",
                step_data=_sd_llm,
                span_type="llm_call",
            ):
                llm_resp: LLMResponse = await context.llm_router.complete(
                    messages=messages,
                    tools=tools,
                    preferred_provider=context.preferred_provider,
                    model=context.model,
                )
                _sd_llm["input_preview"] = self._messages_preview(messages)
                _sd_llm["output_preview"] = (llm_resp.content or "")[:500]
                if llm_resp.model:
                    _sd_llm["model"] = llm_resp.model
                for _uk in ("prompt_tokens", "completion_tokens", "total_tokens"):
                    if _uk in (llm_resp.usage or {}):
                        _sd_llm[_uk] = llm_resp.usage[_uk]

            self.accum_usage(total_usage, llm_resp.usage)

            if not llm_resp.tool_calls:
                await tracker.emit(
                    wf_id,
                    "thinking",
                    "in_progress",
                    "Git Agent composing answer…",
                )
                result.answer = llm_resp.content or ""
                break

            messages.append(
                Message(
                    role="assistant",
                    content=llm_resp.content or "",
                    tool_calls=llm_resp.tool_calls,
                )
            )

            for tc in llm_resp.tool_calls:
                await tracker.emit(
                    wf_id,
                    "thinking",
                    "in_progress",
                    f"Git Agent → {tc.name}",
                )
                _sd_tool: dict[str, Any] = {"input_preview": str(tc.arguments or {})[:500]}
                async with tracker.step(
                    wf_id,
                    f"git:tool:{tc.name}",
                    f"Git tool: {tc.name}",
                    step_data=_sd_tool,
                    span_type="rag",
                ):
                    result_text = await self._dispatch_tool(tc, context, inspector)
                    _sd_tool["output_preview"] = (result_text or "")[:500]

                tool_call_log.append(
                    {
                        "tool": tc.name,
                        "arguments": tc.arguments,
                        "result_preview": result_text[:200],
                    }
                )
                result.raw_git_output = result_text

                messages.append(
                    Message(
                        role="tool",
                        content=result_text,
                        tool_call_id=tc.id,
                        name=tc.name,
                    )
                )
        else:
            if not result.answer:
                last_assistant = ""
                for msg in reversed(messages):
                    if msg.role == "assistant" and msg.content:
                        last_assistant = msg.content
                        break
                result.answer = last_assistant or (
                    "I inspected the Git history but couldn't compose a complete "
                    "answer. Please try rephrasing your question."
                )

        result.token_usage = total_usage
        result.tool_call_log = tool_call_log
        result.status = "success" if result.answer else "no_result"
        return result

    # ------------------------------------------------------------------
    # Tool dispatch
    # ------------------------------------------------------------------

    async def _dispatch_tool(
        self,
        tool_call: ToolCall,
        context: AgentContext,
        inspector: GitInspector,
    ) -> str:
        name = tool_call.name
        args = tool_call.arguments or {}
        try:
            if name == "git_log":
                return self._format_commits(
                    await inspector.log(
                        paths=args.get("paths"),
                        author=args.get("author"),
                        since=args.get("since"),
                        until=args.get("until"),
                        max_count=args.get("max_count", 50),
                    )
                )
            if name == "git_show":
                return await inspector.show(args["sha"], path=args.get("path"))
            if name == "git_diff":
                return await inspector.diff(
                    args["a_sha"],
                    args.get("b_sha", "HEAD"),
                    paths=args.get("paths"),
                )
            if name == "git_blame":
                return self._format_blame(
                    await inspector.blame(args["path"], args.get("commit_sha", "HEAD"))
                )
            if name == "list_releases":
                return self._format_releases(
                    await inspector.list_releases(
                        tag_prefix=args.get("tag_prefix", ""),
                        max_count=args.get("max_count", 50),
                    )
                )
            if name == "file_history":
                return self._format_commits(
                    await inspector.log(
                        paths=[args["path"]],
                        max_count=args.get("max_count", 50),
                    )
                )
            if name == "who_changed":
                return self._format_commits(
                    await inspector.commits_touching(
                        args["pattern"],
                        case_sensitive=bool(args.get("case_sensitive", False)),
                        max_count=args.get("max_count", 50),
                    )
                )
            if name == "review_signals":
                return self._format_review_signals(
                    await inspector.review_signals(args["commit_sha"])
                )
            if name == "write_code_note":
                return await self._handle_write_code_note(args, context)
            return f"Error: unknown tool '{name}'"
        except KeyError as exc:
            return f"Error executing {name}: missing required argument {exc}"
        except GitInspectorError as exc:
            return f"Error executing {name}: {exc}"
        except Exception as exc:  # noqa: BLE001 — surface to the LLM, don't crash
            logger.exception("Git tool %s failed", name)
            return f"Error executing {name}: {exc}"

    # ------------------------------------------------------------------
    # Handlers / formatters
    # ------------------------------------------------------------------

    async def _handle_write_code_note(self, args: dict, ctx: AgentContext) -> str:
        return await self.write_code_note(
            ctx.project_id,
            args.get("subject") or "",
            args.get("note") or "",
        )

    @staticmethod
    def _format_commits(commits: list[dict[str, Any]]) -> str:
        if not commits:
            return "No commits found for the given criteria."
        lines: list[str] = [f"Found {len(commits)} commit(s):", ""]
        for c in commits:
            first_line = (c.get("message") or "").splitlines()[0] if c.get("message") else ""
            merge = " (merge)" if c.get("is_merge") else ""
            lines.append(
                f"- {c['short_sha']}{merge} | {c.get('author_name', '?')} | "
                f"{c.get('committed_date', '')} | {first_line}"
            )
        return "\n".join(lines)

    @staticmethod
    def _format_releases(releases: list[dict[str, Any]]) -> str:
        if not releases:
            return "No release tags found in this repository."
        lines: list[str] = [
            f"Found {len(releases)} release(s):",
            "",
            "| tag | commit | date | summary |",
            "| --- | --- | --- | --- |",
        ]
        for r in releases:
            summary = (r.get("message") or "").replace("|", "/")
            lines.append(
                f"| {r['tag_name']} | {r['short_sha']} | {r.get('commit_date', '')} | {summary} |"
            )
        return "\n".join(lines)

    @staticmethod
    def _format_blame(lines: list[dict[str, Any]]) -> str:
        if not lines:
            return "No blame information available for that file."
        out: list[str] = []
        for ln in lines:
            if ln.get("line_number") == -1:
                out.append(ln.get("content", ""))
                continue
            out.append(
                f"{ln['line_number']:>5} {ln['commit_sha']} "
                f"{ln.get('author_name', '?'):<20} | {ln.get('content', '')}"
            )
        return "\n".join(out)

    @staticmethod
    def _format_review_signals(sig: dict[str, Any]) -> str:
        parts: list[str] = [f"Review signals for {sig.get('short_sha', '?')}:"]
        parts.append(f"- merge commit: {sig.get('is_merge_commit', False)}")
        if sig.get("pull_request"):
            parts.append(f"- pull request: #{sig['pull_request']}")
        if sig.get("merge_source_branch"):
            parts.append(f"- merged from branch: {sig['merge_source_branch']}")
        if sig.get("merge_target_branch"):
            parts.append(f"- merged into branch: {sig['merge_target_branch']}")
        for label, key in (
            ("reviewers", "reviewers"),
            ("co-authors", "co_authors"),
            ("signed-off-by", "signed_off_by"),
        ):
            vals = sig.get(key) or []
            if vals:
                parts.append(f"- {label}: {', '.join(vals)}")
        if len(parts) == 2 and not sig.get("is_merge_commit"):
            parts.append("- no review trailers or merge metadata found.")
        return "\n".join(parts)
