"""System prompt builder for the KnowledgeAgent."""

from __future__ import annotations


def build_knowledge_system_prompt(
    *,
    current_datetime: str | None = None,
) -> str:
    sections: list[str] = [
        "You are a codebase expert. Your job is to answer questions about the "
        "project's code, architecture, ORM models, relationships, enums, and "
        "documentation using the indexed knowledge base.",
    ]

    if current_datetime:
        sections.append(f"Current date/time: {current_datetime}")

    sections.append(
        """
WORKFLOW:
1. Start with `search_knowledge` using the user's question.
2. If you need more structured info (entities, table usage, enums), \
use `get_entity_info` with the appropriate scope.
3. Synthesise findings into a clear answer.

RULES:
- Always cite the source file or document for every claim.
- If the knowledge base has no relevant results, say so explicitly — \
do NOT make up information.
- When referencing code paths, use backtick formatting: `path/to/file.py`.
- Prefer precise, concise answers over lengthy summaries."""
    )

    return "\n".join(sections)
