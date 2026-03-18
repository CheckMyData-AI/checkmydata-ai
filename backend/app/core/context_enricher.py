"""Builds enriched context for the LLM query repair step."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from app.connectors.base import SchemaInfo
from app.core.query_validation import QueryAttempt, QueryError, QueryErrorType
from app.core.retry_strategy import RetryStrategy
from app.core.schema_hints import get_table_detail, list_all_tables_summary

if TYPE_CHECKING:
    from app.knowledge.vector_store import VectorStore

logger = logging.getLogger(__name__)


class ContextEnricher:
    """When validation fails, builds enriched context for the LLM repair step."""

    def __init__(
        self,
        schema: SchemaInfo,
        vector_store: VectorStore | None = None,
        db_index_context: str = "",
        sync_context: str = "",
        rules_context: str = "",
        distinct_values: dict[str, dict[str, list[str]]] | None = None,
        learnings_context: str = "",
    ):
        self._schema = schema
        self._vector_store = vector_store
        self._db_index_context = db_index_context
        self._sync_context = sync_context
        self._rules_context = rules_context
        self._distinct_values = distinct_values or {}
        self._learnings_context = learnings_context
        self._retry_strategy = RetryStrategy()

    async def build_repair_context(
        self,
        error: QueryError,
        original_question: str,
        failed_query: str,
        attempt_history: list[QueryAttempt],
        project_id: str | None = None,
    ) -> str:
        sections: list[str] = []

        sections.append(f"## Original Question\n{original_question}")
        sections.append(f"## Failed Query\n```sql\n{failed_query}\n```")
        sections.append(
            f"## Error\n"
            f"Type: {error.error_type.value}\n"
            f"Message: {error.message}\n"
            f"Raw: {error.raw_error}"
        )

        repair_hints = self._retry_strategy.get_repair_hints(
            error,
            self._schema,
        )
        sections.append(f"## Repair Hints\n{repair_hints}")

        if error.schema_hint:
            sections.append(f"## Schema Excerpt\n{error.schema_hint}")

        schema_detail = self._get_error_schema_detail(error)
        if not schema_detail:
            schema_detail = self._get_query_tables_schema(failed_query)
        if schema_detail:
            sections.append(f"## Relevant Schema\n{schema_detail}")

        if self._sync_context:
            sections.append(f"## Data Format Warnings\n{self._sync_context[:1500]}")

        dv_section = self._get_distinct_values_for_query(failed_query)
        if dv_section:
            sections.append(f"## Column Distinct Values\n{dv_section}")

        if self._rules_context:
            sections.append(f"## Business Rules\n{self._rules_context[:1000]}")

        if self._learnings_context:
            sections.append(f"## Agent Learnings (past experience)\n{self._learnings_context}")

        if self._db_index_context:
            sections.append(f"## Database Index Hints\n{self._db_index_context}")

        if self._vector_store and project_id:
            doc_context = await self._lookup_docs(error, project_id)
            if doc_context:
                sections.append(f"## Relevant Documentation\n{doc_context}")

        if len(attempt_history) > 1:
            history_lines = ["## Previous Attempts"]
            for prev in attempt_history[:-1]:
                err_msg = prev.error.message if prev.error else "OK"
                history_lines.append(
                    f"Attempt {prev.attempt_number}: `{prev.query[:200]}` → {err_msg}"
                )
            sections.append("\n".join(history_lines))

        return "\n\n".join(sections)

    def _get_query_tables_schema(self, query: str) -> str | None:
        """Extract full schema for all tables referenced in the SQL query."""
        import re

        table_names_in_schema = {t.name.lower(): t.name for t in self._schema.tables}

        mentioned: list[str] = []
        for pattern in [
            r'\bFROM\s+["`]?(?:\w+["`]?\s*\.\s*)?["`]?(\w+)["`]?',
            r'\bJOIN\s+["`]?(?:\w+["`]?\s*\.\s*)?["`]?(\w+)["`]?',
            r'\bINTO\s+["`]?(?:\w+["`]?\s*\.\s*)?["`]?(\w+)["`]?',
            r'\bUPDATE\s+["`]?(?:\w+["`]?\s*\.\s*)?["`]?(\w+)["`]?',
        ]:
            for match in re.finditer(pattern, query, re.IGNORECASE):
                name = match.group(1).lower()
                if name in table_names_in_schema and name not in mentioned:
                    mentioned.append(name)

        if not mentioned:
            return None

        details: list[str] = []
        for tbl_lower in mentioned[:5]:
            details.append(get_table_detail(table_names_in_schema[tbl_lower], self._schema))

        return "\n\n".join(details) if details else None

    def _get_distinct_values_for_query(self, query: str) -> str | None:
        """Format distinct values for columns likely relevant to the failed query."""
        if not self._distinct_values:
            return None

        import re

        query_lower = query.lower()
        table_refs = set()
        for pattern in [
            r'\bFROM\s+["`]?(?:\w+["`]?\s*\.\s*)?["`]?(\w+)["`]?',
            r'\bJOIN\s+["`]?(?:\w+["`]?\s*\.\s*)?["`]?(\w+)["`]?',
        ]:
            for match in re.finditer(pattern, query, re.IGNORECASE):
                table_refs.add(match.group(1).lower())

        lines: list[str] = []
        for tbl_name, col_vals in self._distinct_values.items():
            if tbl_name.lower() not in table_refs:
                continue
            for col, vals in col_vals.items():
                if re.search(r'\b' + re.escape(col.lower()) + r'\b', query_lower):
                    vals_str = " | ".join(str(v) for v in vals[:20])
                    lines.append(f"- {tbl_name}.{col}: [{vals_str}]")

        return "\n".join(lines) if lines else None

    def _get_error_schema_detail(self, error: QueryError) -> str | None:
        et = error.error_type

        if et == QueryErrorType.TABLE_NOT_FOUND:
            return list_all_tables_summary(self._schema)

        if et in {
            QueryErrorType.COLUMN_NOT_FOUND,
            QueryErrorType.AMBIGUOUS_COLUMN,
            QueryErrorType.TYPE_MISMATCH,
        }:
            table_hints: list[str] = []
            if error.suggested_tables:
                for tbl in error.suggested_tables[:3]:
                    table_hints.append(get_table_detail(tbl, self._schema))
            if not table_hints:
                for tbl in self._schema.tables[:5]:
                    table_hints.append(get_table_detail(tbl.name, self._schema))
            return "\n\n".join(table_hints) if table_hints else None

        return None

    RAG_RELEVANCE_THRESHOLD = 0.7

    async def _lookup_docs(
        self,
        error: QueryError,
        project_id: str,
    ) -> str | None:
        if not self._vector_store:
            return None

        search_terms: list[str] = []
        if error.suggested_columns:
            search_terms.extend(f"column {col}" for col in error.suggested_columns[:2])
        if error.suggested_tables:
            search_terms.extend(f"table {tbl}" for tbl in error.suggested_tables[:2])
        if not search_terms:
            search_terms.append(error.message[:100])

        all_docs: list[str] = []
        for term in search_terms[:3]:
            try:
                results = await asyncio.to_thread(
                    self._vector_store.query,
                    project_id,
                    term,
                    n_results=2,
                )
                for r in results:
                    distance = r.get("distance")
                    if distance is not None and distance > self.RAG_RELEVANCE_THRESHOLD:
                        continue
                    doc = r.get("document", "")
                    if doc and doc not in all_docs:
                        all_docs.append(doc)
            except Exception:
                logger.debug("RAG lookup failed for term: %s", term)

        if all_docs:
            return "\n---\n".join(all_docs[:4])
        return None
