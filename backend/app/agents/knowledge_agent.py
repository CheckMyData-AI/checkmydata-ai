"""KnowledgeAgent — RAG / codebase specialist.

Searches the vector store and entity index to answer questions about the
project's code, architecture, documentation, and ORM structure.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from app.agents.base import AgentContext, AgentResult, BaseAgent
from app.agents.prompts import get_current_datetime_str
from app.agents.prompts.knowledge_prompt import build_knowledge_system_prompt
from app.agents.tools.knowledge_tools import get_knowledge_tools
from app.config import settings
from app.core.history_trimmer import trim_loop_messages
from app.core.ttl_cache import TTLCache
from app.core.types import RAGSource
from app.knowledge.entity_extractor import ProjectKnowledge
from app.knowledge.vector_store import VectorStore
from app.llm.base import LLMResponse, Message, ToolCall
from app.services.project_cache_service import ProjectCacheService

logger = logging.getLogger(__name__)


@dataclass
class KnowledgeResult(AgentResult):
    """Typed result from the knowledge agent."""

    answer: str = ""
    sources: list[RAGSource] = field(default_factory=list)
    tool_call_log: list[dict[str, Any]] = field(default_factory=list)


class KnowledgeAgent(BaseAgent):
    """Codebase / RAG specialist agent."""

    def __init__(
        self,
        vector_store: VectorStore | None = None,
    ) -> None:
        self._vector_store = vector_store or VectorStore()
        self._cache_svc = ProjectCacheService()
        self._knowledge_cache: TTLCache[ProjectKnowledge] = TTLCache(ttl=300.0, max_size=128)

    @property
    def name(self) -> str:
        return "knowledge"

    @staticmethod
    def _messages_preview(msgs: list[Message], max_len: int = 500) -> str:
        parts: list[str] = []
        for m in reversed(msgs):
            if m.role in ("user", "assistant"):
                parts.append(f"[{m.role}] {(m.content or '')[:200]}")
                if len("\n".join(parts)) > max_len:
                    break
        return "\n".join(reversed(parts))[:max_len]

    async def run(  # type: ignore[override]
        self,
        context: AgentContext,
        *,
        question: str = "",
    ) -> KnowledgeResult:
        question = question or context.user_question

        tools = get_knowledge_tools()
        system_prompt = build_knowledge_system_prompt(
            current_datetime=get_current_datetime_str(),
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

        result = KnowledgeResult()
        tool_call_log: list[dict[str, Any]] = []
        self._collected_sources: list[RAGSource] = []

        tracker = context.tracker
        wf_id = context.workflow_id
        kb_loop_budget = context.llm_router.get_context_window(context.model)

        max_kb_iters = settings.max_knowledge_iterations
        for iteration in range(max_kb_iters):
            messages, _ = trim_loop_messages(messages, kb_loop_budget)
            await tracker.emit(
                wf_id,
                "thinking",
                "in_progress",
                f"Knowledge Agent thinking (step {iteration + 1}/{max_kb_iters})…",
            )
            _sd_kllm: dict[str, Any] = {}
            async with tracker.step(
                wf_id,
                "knowledge:llm_call",
                f"Knowledge LLM call ({iteration + 1}/{max_kb_iters})",
                step_data=_sd_kllm,
            ):
                llm_resp: LLMResponse = await context.llm_router.complete(
                    messages=messages,
                    tools=tools,
                    preferred_provider=context.preferred_provider,
                    model=context.model,
                )
                _sd_kllm["input_preview"] = self._messages_preview(messages)
                _sd_kllm["output_preview"] = (llm_resp.content or "")[:500]
                if llm_resp.model:
                    _sd_kllm["model"] = llm_resp.model
                for _uk in ("prompt_tokens", "completion_tokens", "total_tokens"):
                    if _uk in (llm_resp.usage or {}):
                        _sd_kllm[_uk] = llm_resp.usage[_uk]

            self.accum_usage(total_usage, llm_resp.usage)

            if not llm_resp.tool_calls:
                await tracker.emit(
                    wf_id,
                    "thinking",
                    "in_progress",
                    "Knowledge Agent composing answer…",
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
                    f"Knowledge Agent → {tc.name}",
                )
                _sd_ktool: dict[str, Any] = {
                    "input_preview": str(tc.arguments or {})[:500],
                }
                async with tracker.step(
                    wf_id,
                    f"knowledge:tool:{tc.name}",
                    f"Knowledge tool: {tc.name}",
                    step_data=_sd_ktool,
                ):
                    result_text = await self._dispatch_tool(tc, context)
                    _sd_ktool["output_preview"] = (result_text or "")[:500]

                tool_call_log.append(
                    {
                        "tool": tc.name,
                        "arguments": tc.arguments,
                        "result_preview": result_text[:200],
                    }
                )

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
                    "I found some relevant information but couldn't compose "
                    "a complete answer. Please try rephrasing your question."
                )

        result.token_usage = total_usage
        result.tool_call_log = tool_call_log
        result.sources = self._collected_sources
        result.status = "success" if result.answer else "no_result"
        return result

    # ------------------------------------------------------------------
    # Tool dispatch
    # ------------------------------------------------------------------

    async def _dispatch_tool(self, tool_call: ToolCall, context: AgentContext) -> str:
        handler = {
            "search_knowledge": self._handle_search_knowledge,
            "get_entity_info": self._handle_get_entity_info,
        }.get(tool_call.name)

        if handler is None:
            return f"Error: unknown tool '{tool_call.name}'"

        try:
            return await handler(tool_call.arguments, context)
        except Exception as exc:
            logger.exception("Knowledge tool %s failed", tool_call.name)
            return f"Error executing {tool_call.name}: {exc}"

    # ------------------------------------------------------------------
    # Tool handlers
    # ------------------------------------------------------------------

    async def _handle_search_knowledge(self, args: dict, ctx: AgentContext) -> str:
        query: str = args.get("query", "")
        try:
            max_results = min(max(1, int(args.get("max_results", 5))), 50)
        except (ValueError, TypeError):
            max_results = 5

        results = await asyncio.to_thread(
            self._vector_store.query,
            project_id=ctx.project_id,
            query_text=query,
            n_results=max_results,
        )

        if not results:
            return "No relevant documents found in the knowledge base."

        filtered = [
            r
            for r in results
            if r.get("distance") is None or r["distance"] <= settings.rag_relevance_threshold
        ]

        if not filtered:
            return "No sufficiently relevant documents found in the knowledge base."

        doc_cap = 2000
        total_cap = 8000
        parts: list[str] = []
        total_len = 0
        for r in filtered:
            meta = r.get("metadata", {})
            source = meta.get("source_path", "unknown")
            doc = r.get("document", "")
            if len(doc) > doc_cap:
                doc = doc[:doc_cap] + "… (truncated)"
            distance = r.get("distance")
            sim = f" (similarity: {1 - distance:.2f})" if distance is not None else ""
            chunk = f"### {source}{sim}\n{doc}"
            if total_len + len(chunk) > total_cap:
                parts.append("... (remaining documents omitted to save context)")
                break
            parts.append(chunk)
            total_len += len(chunk)

            self._collected_sources.append(
                RAGSource(
                    source_path=source,
                    distance=distance,
                    doc_type=meta.get("doc_type", ""),
                    chunk_index=str(meta.get("chunk_index", "")),
                )
            )

        await ctx.tracker.emit(
            ctx.workflow_id,
            "thinking",
            "in_progress",
            f"Found {len(filtered)} relevant document(s)",
        )
        return f"Found {len(filtered)} relevant document(s):\n\n" + "\n\n".join(parts)

    async def _handle_get_entity_info(self, args: dict, ctx: AgentContext) -> str:
        scope: str = args.get("scope", "list")
        entity_name: str | None = args.get("entity_name")

        knowledge = await self._load_knowledge(ctx.project_id)

        if knowledge is None:
            return "No entity information available. The repository may not be indexed yet."

        if scope == "list":
            return self._format_entity_list(knowledge)
        if scope == "detail":
            if not entity_name:
                return "Error: entity_name is required when scope is 'detail'."
            return self._format_entity_detail(knowledge, entity_name)
        if scope == "table_map":
            return self._format_table_map(knowledge)
        if scope == "enums":
            return self._format_enums(knowledge)
        return f"Error: unknown scope '{scope}'. Use 'list', 'detail', 'table_map', or 'enums'."

    # ------------------------------------------------------------------
    # Knowledge loading
    # ------------------------------------------------------------------

    async def _load_knowledge(self, project_id: str) -> ProjectKnowledge | None:
        cached = self._knowledge_cache.get(project_id)
        if cached is not None:
            return cached

        from app.models.base import async_session_factory

        async with async_session_factory() as session:
            knowledge = await self._cache_svc.load_knowledge(session, project_id)
        if knowledge is not None:
            self._knowledge_cache.put(project_id, knowledge)
        return knowledge

    # ------------------------------------------------------------------
    # Entity formatting (extracted from ToolExecutor)
    # ------------------------------------------------------------------

    @staticmethod
    def _format_entity_list(knowledge: ProjectKnowledge) -> str:
        if not knowledge.entities:
            return "No entities found in the indexed codebase."
        lines = [
            f"Found {len(knowledge.entities)} entities:\n",
            "| Entity | Table | File | Columns | Relationships |",
            "|--------|-------|------|---------|---------------|",
        ]
        for name, entity in sorted(knowledge.entities.items()):
            tbl = entity.table_name or "-"
            fp = entity.file_path or "-"
            cols = len(entity.columns)
            rels = len(entity.relationships)
            lines.append(f"| {name} | {tbl} | {fp} | {cols} | {rels} |")
        return "\n".join(lines)

    @staticmethod
    def _format_entity_detail(knowledge: ProjectKnowledge, entity_name: str) -> str:
        entity = knowledge.entities.get(entity_name)
        if not entity:
            low = entity_name.lower()
            for k, v in knowledge.entities.items():
                if k.lower() == low or (v.table_name and v.table_name.lower() == low):
                    entity = v
                    break
        if not entity:
            available = ", ".join(sorted(knowledge.entities.keys())[:30])
            return f"Entity '{entity_name}' not found. Available: {available}"

        lines = [f"## {entity.name}"]
        if entity.table_name:
            lines.append(f"Table: `{entity.table_name}`")
        if entity.file_path:
            lines.append(f"File: `{entity.file_path}`")
        lines.append("")

        if entity.columns:
            lines.append("| Column | Type | FK | FK Target | Enum Values |")
            lines.append("|--------|------|----|-----------|-------------|")
            for col in entity.columns:
                fk = "YES" if col.is_fk else ""
                fk_tgt = col.fk_target or ""
                enums = ", ".join(col.enum_values[:8]) if col.enum_values else ""
                lines.append(f"| {col.name} | {col.col_type} | {fk} | {fk_tgt} | {enums} |")
        else:
            lines.append("No column information extracted.")

        if entity.relationships:
            lines.append(f"\nRelationships: {', '.join(entity.relationships)}")
        if entity.used_in_files:
            lines.append(
                f"\nUsed in {len(entity.used_in_files)} file(s): "
                + ", ".join(f"`{f}`" for f in entity.used_in_files[:10])
            )
        return "\n".join(lines)

    @staticmethod
    def _format_table_map(knowledge: ProjectKnowledge) -> str:
        if not knowledge.table_usage:
            return "No table usage data available."
        lines = [
            f"Table usage map ({len(knowledge.table_usage)} tables):\n",
            "| Table | Readers | Writers | ORM Refs | Status |",
            "|-------|---------|---------|----------|--------|",
        ]
        for tbl_name, usage in sorted(knowledge.table_usage.items()):
            status = "active" if usage.is_active else "UNUSED"
            lines.append(
                f"| {tbl_name} | {len(usage.readers)} | {len(usage.writers)} "
                f"| {len(usage.orm_refs)} | {status} |"
            )
        dead = knowledge.dead_tables
        if dead:
            lines.append(f"\nPotentially unused tables: {', '.join(dead)}")
        return "\n".join(lines)

    @staticmethod
    def _format_enums(knowledge: ProjectKnowledge) -> str:
        if not knowledge.enums:
            return "No enum or constant definitions found."
        lines = [f"Found {len(knowledge.enums)} enum/constant definitions:\n"]
        for enum_def in knowledge.enums:
            vals = ", ".join(enum_def.values[:12])
            if len(enum_def.values) > 12:
                vals += f" ... (+{len(enum_def.values) - 12} more)"
            lines.append(f"- **{enum_def.name}** (`{enum_def.file_path}`): {vals}")
        if knowledge.service_functions:
            lines.append(f"\nAlso found {len(knowledge.service_functions)} service functions:")
            for sf in knowledge.service_functions[:30]:
                tables = ", ".join(sf.get("tables") or [])
                lines.append(f"- `{sf['name']}` in `{sf['file_path']}` -> tables: {tables}")
        return "\n".join(lines)
