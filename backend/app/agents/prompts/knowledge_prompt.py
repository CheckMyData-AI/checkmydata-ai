"""System prompt builder for the KnowledgeAgent."""

from __future__ import annotations


def build_knowledge_system_prompt(
    *,
    current_datetime: str | None = None,
    hybrid_retrieval_enabled: bool = False,
    lineage_enabled: bool = False,
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

    if hybrid_retrieval_enabled:
        sections.append(
            "\nRETRIEVAL MODEL:\n"
            "- `search_knowledge` runs hybrid retrieval (M3): a BM25 lexical "
            "index for exact symbol / identifier matches PLUS dense semantic "
            "vectors, fused via Reciprocal Rank Fusion. Treat the returned "
            "`score` field as a relative ranking signal — higher is better "
            "but the absolute value is not a probability.\n"
            "- Prefer specific identifiers (class names, function names, error "
            "strings) over generic phrasing — BM25 leg rewards exact matches."
        )

    if lineage_enabled:
        sections.append(
            "\nLINEAGE:\n"
            "- When `get_entity_info` returns a 'Code lineage (top callers)' "
            "section for an entity, those rows are from the code knowledge "
            "graph (M5). Use them to answer 'who reads/writes this table' "
            "questions; quote the caller file + endpoint kind verbatim."
        )

    return "\n".join(sections)
