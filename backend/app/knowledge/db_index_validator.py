"""LLM-powered per-table validator for database indexing.

Analyzes each table's schema + sample data against project knowledge
and produces a structured assessment.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from app.connectors.base import QueryResult, SchemaInfo, TableInfo
from app.llm.base import Message, Tool, ToolParameter
from app.llm.router import LLMRouter

logger = logging.getLogger(__name__)

_VALID_CODE_MATCH = {"matched", "orphan", "mismatch", "no_code_info"}


def _clamp_code_match(raw: str) -> str:
    return raw if raw in _VALID_CODE_MATCH else "no_code_info"


ANALYZE_TABLE_TOOL = Tool(
    name="table_analysis",
    description="Return a structured analysis of the database table",
    parameters=[
        ToolParameter(
            name="is_active",
            type="boolean",
            description="Whether this table has meaningful data and appears actively used",
        ),
        ToolParameter(
            name="relevance_score",
            type="integer",
            description="1-5 relevance score for analytics queries (5 = core business data)",
        ),
        ToolParameter(
            name="business_description",
            type="string",
            description=(
                "One-sentence description of what this table stores"
                " and its business purpose"
            ),
        ),
        ToolParameter(
            name="data_patterns",
            type="string",
            description=(
                "Notable data patterns: enum-like columns,"
                " null patterns, date formats, value ranges"
            ),
        ),
        ToolParameter(
            name="column_notes",
            type="string",
            description=(
                "JSON object with per-column notes: observed"
                " enum values, null rates, type observations"
            ),
        ),
        ToolParameter(
            name="query_hints",
            type="string",
            description=(
                "Tips for the query agent: recommended filters,"
                " join keys, date column to use, gotchas"
            ),
        ),
        ToolParameter(
            name="code_match_status",
            type="string",
            description="How well the live schema matches code knowledge",
            enum=["matched", "orphan", "mismatch", "no_code_info"],
        ),
        ToolParameter(
            name="code_match_details",
            type="string",
            description=(
                "Explanation of any discrepancies between"
                " live schema and code expectations"
            ),
            required=False,
        ),
    ],
)

GENERATE_SUMMARY_TOOL = Tool(
    name="connection_summary",
    description="Return an overall summary of the database",
    parameters=[
        ToolParameter(
            name="summary_text",
            type="string",
            description=(
                "2-4 sentence overview of the database:"
                " what domain, key entity groups, data volume"
            ),
        ),
        ToolParameter(
            name="recommendations",
            type="string",
            description=(
                "Bullet-point recommendations for the query agent:"
                " common join patterns, date handling,"
                " naming conventions, key tables for analytics"
            ),
        ),
    ],
)


@dataclass
class TableAnalysis:
    table_name: str
    is_active: bool = True
    relevance_score: int = 3
    business_description: str = ""
    data_patterns: str = ""
    column_notes_json: str = "{}"
    query_hints: str = ""
    code_match_status: str = "no_code_info"
    code_match_details: str = ""


@dataclass
class ConnectionSummaryResult:
    summary_text: str = ""
    recommendations: str = ""


class DbIndexValidator:
    """Uses LLM to analyze individual tables and generate connection summaries."""

    def __init__(self, llm_router: LLMRouter | None = None) -> None:
        self._llm = llm_router or LLMRouter()

    async def analyze_table(
        self,
        table: TableInfo,
        sample_data: QueryResult | None,
        code_context: str,
        rules_context: str,
        *,
        preferred_provider: str | None = None,
        model: str | None = None,
    ) -> TableAnalysis:
        prompt = self._build_table_prompt(table, sample_data, code_context, rules_context)

        messages = [
            Message(role="system", content=self._system_prompt()),
            Message(role="user", content=prompt),
        ]

        try:
            resp = await self._llm.complete(
                messages=messages,
                tools=[ANALYZE_TABLE_TOOL],
                preferred_provider=preferred_provider,
                model=model,
                temperature=0.0,
                max_tokens=2048,
            )

            if resp.tool_calls:
                args = resp.tool_calls[0].arguments
                col_notes = args.get("column_notes", "{}")
                if isinstance(col_notes, dict):
                    col_notes = json.dumps(col_notes)

                return TableAnalysis(
                    table_name=table.name,
                    is_active=args.get("is_active", True),
                    relevance_score=max(1, min(5, int(args.get("relevance_score", 3)))),
                    business_description=args.get("business_description", ""),
                    data_patterns=args.get("data_patterns", ""),
                    column_notes_json=col_notes,
                    query_hints=args.get("query_hints", ""),
                    code_match_status=_clamp_code_match(
                        args.get("code_match_status", "no_code_info"),
                    ),
                    code_match_details=args.get("code_match_details", ""),
                )

            return self._fallback_analysis(table, sample_data)

        except Exception:
            logger.warning("LLM analysis failed for table %s", table.name, exc_info=True)
            return self._fallback_analysis(table, sample_data)

    async def analyze_table_batch(
        self,
        tables: list[tuple[TableInfo, QueryResult | None]],
        code_context: str,
        rules_context: str,
        *,
        preferred_provider: str | None = None,
        model: str | None = None,
    ) -> list[TableAnalysis]:
        """Analyze multiple small/empty tables in a single LLM call."""
        if not tables:
            return []

        prompt_parts = [
            "Analyze each of the following tables and call `table_analysis` once per table.\n"
        ]
        for table, sample in tables:
            prompt_parts.append(
                self._build_table_prompt(
                    table, sample, code_context, rules_context,
                )
            )
            prompt_parts.append("---\n")

        messages = [
            Message(role="system", content=self._system_prompt()),
            Message(role="user", content="\n".join(prompt_parts)),
        ]

        results: list[TableAnalysis] = []
        try:
            resp = await self._llm.complete(
                messages=messages,
                tools=[ANALYZE_TABLE_TOOL],
                preferred_provider=preferred_provider,
                model=model,
                temperature=0.0,
                max_tokens=4096,
            )

            tool_idx = 0
            for tc in resp.tool_calls:
                if tc.name == "table_analysis" and tool_idx < len(tables):
                    args = tc.arguments
                    tbl = tables[tool_idx][0]
                    col_notes = args.get("column_notes", "{}")
                    if isinstance(col_notes, dict):
                        col_notes = json.dumps(col_notes)
                    results.append(TableAnalysis(
                        table_name=tbl.name,
                        is_active=args.get("is_active", True),
                        relevance_score=max(1, min(5, int(args.get("relevance_score", 3)))),
                        business_description=args.get("business_description", ""),
                        data_patterns=args.get("data_patterns", ""),
                        column_notes_json=col_notes,
                        query_hints=args.get("query_hints", ""),
                        code_match_status=_clamp_code_match(
                            args.get("code_match_status", "no_code_info"),
                        ),
                        code_match_details=args.get("code_match_details", ""),
                    ))
                    tool_idx += 1

        except Exception:
            logger.warning("Batch LLM analysis failed", exc_info=True)

        for i in range(len(results), len(tables)):
            tbl, sample = tables[i]
            results.append(self._fallback_analysis(tbl, sample))

        return results

    async def generate_summary(
        self,
        analyses: list[TableAnalysis],
        schema: SchemaInfo,
        code_tables: set[str],
        *,
        preferred_provider: str | None = None,
        model: str | None = None,
    ) -> ConnectionSummaryResult:
        live_tables = {t.name.lower() for t in schema.tables}
        code_lower = {t.lower() for t in code_tables}
        orphan = live_tables - code_lower
        phantom = code_lower - live_tables

        active = [a for a in analyses if a.is_active]
        empty = [a for a in analyses if not a.is_active]

        prompt_parts = [
            f"Database: {schema.db_name} ({schema.db_type})",
            f"Total tables: {len(analyses)}",
            f"Active tables: {len(active)}, Empty/inactive: {len(empty)}",
        ]
        if orphan:
            prompt_parts.append(f"Orphan tables (in DB, not in code): {', '.join(sorted(orphan))}")
        if phantom:
            prompt_parts.append(
                "Phantom tables (in code, not in DB): "
                f"{', '.join(sorted(phantom))}"
            )

        prompt_parts.append("\nPer-table summaries:")
        for a in sorted(analyses, key=lambda x: -x.relevance_score):
            prompt_parts.append(
                f"- {a.table_name} (relevance={a.relevance_score}, "
                f"active={a.is_active}): {a.business_description}"
            )

        prompt_parts.append(
            "\nGenerate an overall summary and practical recommendations "
            "for a query agent working with this database."
        )

        messages = [
            Message(role="system", content=self._system_prompt()),
            Message(role="user", content="\n".join(prompt_parts)),
        ]

        try:
            resp = await self._llm.complete(
                messages=messages,
                tools=[GENERATE_SUMMARY_TOOL],
                preferred_provider=preferred_provider,
                model=model,
                temperature=0.0,
                max_tokens=2048,
            )

            if resp.tool_calls:
                args = resp.tool_calls[0].arguments
                return ConnectionSummaryResult(
                    summary_text=args.get("summary_text", ""),
                    recommendations=args.get("recommendations", ""),
                )

            return ConnectionSummaryResult(
                summary_text=resp.content[:500] if resp.content else "",
            )

        except Exception:
            logger.warning("LLM summary generation failed", exc_info=True)
            return ConnectionSummaryResult(
                summary_text=(
                    f"{schema.db_name} ({schema.db_type}) with "
                    f"{len(active)} active and {len(empty)} inactive tables."
                ),
            )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _system_prompt() -> str:
        return (
            "You are a database analyst. You analyze database tables by examining "
            "their schema, sample data, and project code context. Provide concise, "
            "actionable insights. Always use the provided tool to return structured "
            "results. Focus on practical information that helps a query agent write "
            "correct SQL: column purposes, enum values, join keys, date handling, "
            "and common filter patterns."
        )

    @staticmethod
    def _build_table_prompt(
        table: TableInfo,
        sample_data: QueryResult | None,
        code_context: str,
        rules_context: str,
    ) -> str:
        parts: list[str] = [f"## Table: {table.name}"]

        if table.schema and table.schema != "public":
            parts.append(f"Schema: {table.schema}")
        if table.row_count is not None:
            parts.append(f"Row count (estimated): {table.row_count:,}")
        if table.comment:
            parts.append(f"Comment: {table.comment}")

        parts.append("\nColumns:")
        for col in table.columns:
            pk = " [PK]" if col.is_primary_key else ""
            nullable = " NULL" if col.is_nullable else " NOT NULL"
            default = f" DEFAULT {col.default}" if col.default else ""
            comment = f" — {col.comment}" if col.comment else ""
            parts.append(f"  - {col.name}: {col.data_type}{pk}{nullable}{default}{comment}")

        if table.foreign_keys:
            parts.append("\nForeign Keys:")
            for fk in table.foreign_keys:
                parts.append(f"  - {fk.column} → {fk.references_table}.{fk.references_column}")

        if table.indexes:
            parts.append("\nIndexes:")
            for idx in table.indexes:
                u = "UNIQUE " if idx.is_unique else ""
                parts.append(f"  - {u}{idx.name}({', '.join(idx.columns)})")

        if sample_data and sample_data.rows:
            parts.append(f"\nSample data ({len(sample_data.rows)} newest rows):")
            parts.append("| " + " | ".join(sample_data.columns) + " |")
            parts.append("| " + " | ".join(["---"] * len(sample_data.columns)) + " |")
            for row in sample_data.rows:
                vals = [str(v)[:60] for v in row]
                parts.append("| " + " | ".join(vals) + " |")
        elif sample_data and not sample_data.rows:
            parts.append("\nSample data: (empty table — no rows)")

        if code_context:
            parts.append(f"\nCode context:\n{code_context}")

        if rules_context:
            parts.append(f"\nCustom rules:\n{rules_context}")

        return "\n".join(parts)

    @staticmethod
    def _fallback_analysis(table: TableInfo, sample_data: QueryResult | None) -> TableAnalysis:
        """Deterministic fallback when LLM is unavailable."""
        has_data = sample_data is not None and bool(sample_data.rows)
        row_count = table.row_count or 0

        is_active = has_data or row_count > 0
        relevance = 3
        if row_count == 0 and not has_data:
            relevance = 1
            is_active = False
        elif row_count > 10000:
            relevance = 4

        desc = f"Table with {len(table.columns)} columns"
        if table.comment:
            desc = table.comment

        hints_parts: list[str] = []
        for col in table.columns:
            if col.is_primary_key:
                hints_parts.append(f"PK: {col.name}")
        for fk in table.foreign_keys:
            hints_parts.append(f"FK: {fk.column} → {fk.references_table}")

        return TableAnalysis(
            table_name=table.name,
            is_active=is_active,
            relevance_score=relevance,
            business_description=desc,
            data_patterns="",
            column_notes_json="{}",
            query_hints="; ".join(hints_parts) if hints_parts else "",
            code_match_status="no_code_info",
            code_match_details="",
        )
