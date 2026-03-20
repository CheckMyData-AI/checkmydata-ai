"""Tool definitions for the InvestigationAgent."""

from app.llm.base import Tool, ToolParameter

GET_ORIGINAL_CONTEXT_TOOL = Tool(
    name="get_original_context",
    description=(
        "Load the original query context: the query that produced the flagged "
        "result, its output, the schema context used, and the user's complaint."
    ),
    parameters=[],
)

RUN_DIAGNOSTIC_QUERY_TOOL = Tool(
    name="run_diagnostic_query",
    description=(
        "Execute a diagnostic SQL query to investigate a specific hypothesis "
        "about what went wrong. Explain what you're checking."
    ),
    parameters=[
        ToolParameter(
            name="query",
            type="string",
            description="The diagnostic SQL query to execute",
        ),
        ToolParameter(
            name="hypothesis",
            type="string",
            description=(
                "What this query is testing (e.g., 'checking if status column has filtered values')"
            ),
        ),
    ],
)

COMPARE_RESULTS_TOOL = Tool(
    name="compare_results",
    description=(
        "Compare the original query result with a new result. "
        "Highlights differences in values per column."
    ),
    parameters=[
        ToolParameter(
            name="original_summary",
            type="string",
            description="Summary of the original result to compare against",
        ),
        ToolParameter(
            name="new_summary",
            type="string",
            description="Summary of the new/corrected result",
        ),
    ],
)

CHECK_COLUMN_FORMATS_TOOL = Tool(
    name="check_column_formats",
    description=(
        "Inspect a specific column: sample values, min/max, data type, "
        "and cross-reference with code-DB sync and DB index."
    ),
    parameters=[
        ToolParameter(
            name="table_name",
            type="string",
            description="Table containing the column",
        ),
        ToolParameter(
            name="column_name",
            type="string",
            description="Column to inspect",
        ),
    ],
)

GET_RELATED_LEARNINGS_TOOL = Tool(
    name="get_related_learnings",
    description=(
        "Find existing agent learnings related to the tables involved "
        "in this investigation. Identifies potentially wrong learnings "
        "that may need contradiction."
    ),
    parameters=[
        ToolParameter(
            name="table_name",
            type="string",
            description="Table to find learnings for",
        ),
    ],
)

RECORD_INVESTIGATION_FINDING_TOOL = Tool(
    name="record_investigation_finding",
    description=(
        "Record the investigation finding: the corrected query, root cause, "
        "and category. This persists the finding and triggers memory updates."
    ),
    parameters=[
        ToolParameter(
            name="corrected_query",
            type="string",
            description="The corrected SQL query that produces accurate results",
        ),
        ToolParameter(
            name="root_cause",
            type="string",
            description="Clear explanation of what was wrong",
        ),
        ToolParameter(
            name="root_cause_category",
            type="string",
            description="Category of the root cause",
            enum=[
                "column_format",
                "missing_filter",
                "wrong_join",
                "wrong_table",
                "aggregation_error",
                "timezone_issue",
                "currency_unit",
                "other",
            ],
        ),
    ],
)


def get_investigation_tools() -> list[Tool]:
    return [
        GET_ORIGINAL_CONTEXT_TOOL,
        RUN_DIAGNOSTIC_QUERY_TOOL,
        COMPARE_RESULTS_TOOL,
        CHECK_COLUMN_FORMATS_TOOL,
        GET_RELATED_LEARNINGS_TOOL,
        RECORD_INVESTIGATION_FINDING_TOOL,
    ]
