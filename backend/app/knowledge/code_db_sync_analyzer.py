"""LLM-powered code-database synchronization analyzer.

Analyzes how code uses each database table: data formats (money in cents
vs dollars), date handling, enum values, soft-delete patterns, and
business logic context.  Produces structured notes the query agent uses
to avoid common data-interpretation errors.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from app.llm.base import Message, Tool, ToolParameter
from app.llm.router import LLMRouter

logger = logging.getLogger(__name__)

SYNC_ANALYSIS_TOOL = Tool(
    name="table_sync_analysis",
    description="Return a structured analysis of how code uses this database table",
    parameters=[
        ToolParameter(
            name="data_format_notes",
            type="string",
            description=(
                "Detailed notes on data storage formats: money (cents vs dollars, "
                "decimal precision), dates (UTC vs local, unix timestamp vs ISO), "
                "booleans (0/1 vs true/false), enums (string vs int), JSON fields"
            ),
        ),
        ToolParameter(
            name="column_sync_notes",
            type="string",
            description=(
                "JSON object: per-column notes about format, conversion rules, "
                'and gotchas. E.g. {"amount": "stored in cents, divide by 100", '
                '"status": "enum: active|inactive|suspended"}'
            ),
        ),
        ToolParameter(
            name="business_logic_notes",
            type="string",
            description=(
                "How this table's data flows through the app: CRUD patterns, "
                "computed fields, state machines, aggregation logic"
            ),
        ),
        ToolParameter(
            name="conversion_warnings",
            type="string",
            description=(
                "Critical warnings about data interpretation: "
                "e.g. 'amount is in cents not dollars', 'timestamps are UTC+0', "
                "'soft-deleted rows have deleted_at != NULL'"
            ),
        ),
        ToolParameter(
            name="query_recommendations",
            type="string",
            description=(
                "Specific SQL query tips: recommended WHERE filters, "
                "JOIN patterns, date range handling, NULL handling"
            ),
        ),
        ToolParameter(
            name="sync_status",
            type="string",
            description="How well code and database align for this table",
            enum=["matched", "code_only", "db_only", "mismatch"],
        ),
        ToolParameter(
            name="confidence_score",
            type="integer",
            description="1-5 confidence in the analysis accuracy",
        ),
    ],
)

SYNC_SUMMARY_TOOL = Tool(
    name="sync_summary",
    description="Return a project-wide summary of code-database synchronization",
    parameters=[
        ToolParameter(
            name="global_notes",
            type="string",
            description=(
                "Overview of the project's data layer: which tables are central, "
                "how entities relate, overall data flow"
            ),
        ),
        ToolParameter(
            name="data_conventions",
            type="string",
            description=(
                "Project-wide data conventions discovered from code: "
                "currency format (cents/dollars), timestamp timezone, "
                "soft-delete pattern, enum handling, naming conventions"
            ),
        ),
        ToolParameter(
            name="query_guidelines",
            type="string",
            description=(
                "Bullet-point query guidelines for the SQL agent: "
                "common JOIN patterns, date filters, amount conversions, "
                "which tables to prefer, what to avoid"
            ),
        ),
    ],
)


@dataclass
class TableSyncAnalysis:
    table_name: str
    data_format_notes: str = ""
    column_sync_notes_json: str = "{}"
    business_logic_notes: str = ""
    conversion_warnings: str = ""
    query_recommendations: str = ""
    sync_status: str = "unknown"
    confidence_score: int = 3


@dataclass
class SyncSummaryResult:
    global_notes: str = ""
    data_conventions: str = ""
    query_guidelines: str = ""


class CodeDbSyncAnalyzer:
    """Uses LLM to analyze code-database alignment per table."""

    def __init__(self, llm_router: LLMRouter | None = None) -> None:
        self._llm = llm_router or LLMRouter()

    async def analyze_table(
        self,
        table_name: str,
        db_context: str,
        code_context: str,
        *,
        preferred_provider: str | None = None,
        model: str | None = None,
    ) -> TableSyncAnalysis:
        prompt = self._build_prompt(table_name, db_context, code_context)

        messages = [
            Message(role="system", content=self._system_prompt()),
            Message(role="user", content=prompt),
        ]

        try:
            resp = await self._llm.complete(
                messages=messages,
                tools=[SYNC_ANALYSIS_TOOL],
                preferred_provider=preferred_provider,
                model=model,
                temperature=0.0,
                max_tokens=2048,
            )

            if resp.tool_calls:
                args = resp.tool_calls[0].arguments
                col_notes = args.get("column_sync_notes", "{}")
                if isinstance(col_notes, dict):
                    col_notes = json.dumps(col_notes)

                return TableSyncAnalysis(
                    table_name=table_name,
                    data_format_notes=args.get("data_format_notes", ""),
                    column_sync_notes_json=col_notes,
                    business_logic_notes=args.get("business_logic_notes", ""),
                    conversion_warnings=args.get("conversion_warnings", ""),
                    query_recommendations=args.get("query_recommendations", ""),
                    sync_status=args.get("sync_status", "unknown"),
                    confidence_score=max(1, min(5, int(args.get("confidence_score", 3)))),
                )

            return self._fallback_analysis(table_name)

        except Exception:
            logger.warning("LLM sync analysis failed for table %s", table_name, exc_info=True)
            return self._fallback_analysis(table_name)

    async def analyze_table_batch(
        self,
        tables: list[tuple[str, str, str]],
        *,
        preferred_provider: str | None = None,
        model: str | None = None,
    ) -> list[TableSyncAnalysis]:
        """Analyze multiple tables in a single LLM call.

        Each tuple is (table_name, db_context, code_context).
        """
        if not tables:
            return []

        prompt_parts = [
            "Analyze each of the following tables and call "
            "`table_sync_analysis` once per table.\n"
        ]
        for table_name, db_ctx, code_ctx in tables:
            prompt_parts.append(
                self._build_prompt(table_name, db_ctx, code_ctx)
            )
            prompt_parts.append("---\n")

        messages = [
            Message(role="system", content=self._system_prompt()),
            Message(role="user", content="\n".join(prompt_parts)),
        ]

        results: list[TableSyncAnalysis] = []
        try:
            resp = await self._llm.complete(
                messages=messages,
                tools=[SYNC_ANALYSIS_TOOL],
                preferred_provider=preferred_provider,
                model=model,
                temperature=0.0,
                max_tokens=4096,
            )

            tool_idx = 0
            for tc in resp.tool_calls:
                if tc.name == "table_sync_analysis" and tool_idx < len(tables):
                    args = tc.arguments
                    tbl_name = tables[tool_idx][0]
                    col_notes = args.get("column_sync_notes", "{}")
                    if isinstance(col_notes, dict):
                        col_notes = json.dumps(col_notes)
                    results.append(TableSyncAnalysis(
                        table_name=tbl_name,
                        data_format_notes=args.get("data_format_notes", ""),
                        column_sync_notes_json=col_notes,
                        business_logic_notes=args.get("business_logic_notes", ""),
                        conversion_warnings=args.get("conversion_warnings", ""),
                        query_recommendations=args.get("query_recommendations", ""),
                        sync_status=args.get("sync_status", "unknown"),
                        confidence_score=max(1, min(5, int(args.get("confidence_score", 3)))),
                    ))
                    tool_idx += 1

        except Exception:
            logger.warning("Batch sync analysis failed", exc_info=True)

        for i in range(len(results), len(tables)):
            results.append(self._fallback_analysis(tables[i][0]))

        return results

    async def generate_summary(
        self,
        analyses: list[TableSyncAnalysis],
        project_context: str,
        *,
        preferred_provider: str | None = None,
        model: str | None = None,
    ) -> SyncSummaryResult:
        prompt_parts = [project_context, ""]
        prompt_parts.append(f"Tables analyzed: {len(analyses)}\n")

        for a in sorted(analyses, key=lambda x: -x.confidence_score):
            warn = f" ⚠ {a.conversion_warnings}" if a.conversion_warnings else ""
            prompt_parts.append(
                f"- {a.table_name} (status={a.sync_status}, "
                f"confidence={a.confidence_score}){warn}"
            )
            if a.data_format_notes:
                prompt_parts.append(f"  Format: {a.data_format_notes[:120]}")

        prompt_parts.append(
            "\nGenerate a project-wide summary with data conventions "
            "and query guidelines for the SQL agent."
        )

        messages = [
            Message(role="system", content=self._system_prompt()),
            Message(role="user", content="\n".join(prompt_parts)),
        ]

        try:
            resp = await self._llm.complete(
                messages=messages,
                tools=[SYNC_SUMMARY_TOOL],
                preferred_provider=preferred_provider,
                model=model,
                temperature=0.0,
                max_tokens=2048,
            )

            if resp.tool_calls:
                args = resp.tool_calls[0].arguments
                return SyncSummaryResult(
                    global_notes=args.get("global_notes", ""),
                    data_conventions=args.get("data_conventions", ""),
                    query_guidelines=args.get("query_guidelines", ""),
                )

            return SyncSummaryResult(
                global_notes=resp.content[:500] if resp.content else "",
            )

        except Exception:
            logger.warning("LLM sync summary generation failed", exc_info=True)
            return SyncSummaryResult(
                global_notes=f"Analyzed {len(analyses)} tables.",
            )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _system_prompt() -> str:
        return (
            "You are a code-database synchronization analyst. You compare database "
            "schemas and sample data with application source code to understand how "
            "data is stored, formatted, and used.\n\n"
            "Your primary goal is to discover DATA FORMAT DETAILS that would trip up "
            "a SQL query agent:\n"
            "- Money/currency: stored in cents (integer) vs dollars (decimal)? "
            "What precision?\n"
            "- Dates/timestamps: UTC or local? Unix epoch or ISO 8601? "
            "What timezone conventions?\n"
            "- Enums: what are the valid string values? Are they stored as "
            "integers or strings?\n"
            "- Soft deletes: is there a deleted_at or is_deleted column?\n"
            "- JSON columns: what structure is expected?\n"
            "- Booleans: stored as 0/1, true/false, or 'Y'/'N'?\n"
            "- Status fields: what are the valid states and transitions?\n\n"
            "Always use the provided tool to return structured results. "
            "Be specific and actionable — the query agent will use your notes "
            "to write correct SQL."
        )

    @staticmethod
    def _build_prompt(
        table_name: str,
        db_context: str,
        code_context: str,
    ) -> str:
        parts: list[str] = [f"## Table: {table_name}\n"]

        if db_context:
            parts.append("### Database Schema & Sample Data\n")
            parts.append(db_context)
            parts.append("")

        if code_context:
            parts.append("### Code Context\n")
            parts.append(code_context)
            parts.append("")
        else:
            parts.append("### Code Context\nNo code references found for this table.\n")

        parts.append(
            "Analyze the relationship between the database schema/data and "
            "the code. Focus on data format details, conversion warnings, "
            "and practical query recommendations."
        )

        return "\n".join(parts)

    @staticmethod
    def _fallback_analysis(table_name: str) -> TableSyncAnalysis:
        return TableSyncAnalysis(
            table_name=table_name,
            sync_status="unknown",
            confidence_score=1,
            data_format_notes="LLM analysis unavailable — using fallback.",
        )
