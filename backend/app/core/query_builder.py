import json
import logging

from app.llm.base import Message, Tool, ToolParameter
from app.llm.router import LLMRouter

logger = logging.getLogger(__name__)

DIALECT_HINTS = {
    "mysql": (
        "- Use backtick quoting for identifiers: `table`.`column`\n"
        "- Date functions: DATE_FORMAT(), NOW(), CURDATE(), DATE_SUB()\n"
        "- String: CONCAT(), IFNULL(), GROUP_CONCAT()\n"
        "- Use LIMIT N at end (no OFFSET required unless paginating)"
    ),
    "postgres": (
        "- Use double-quote quoting for identifiers if needed\n"
        "- Date functions: NOW(), CURRENT_DATE, date_trunc(), age()\n"
        "- String: CONCAT(), COALESCE(), string_agg()\n"
        "- Use LIMIT N OFFSET M for pagination"
    ),
    "clickhouse": (
        "- ClickHouse SQL dialect: use toDate(), toDateTime(), formatDateTime()\n"
        "- Aggregations: countIf(), sumIf(), argMax(), argMin()\n"
        "- For large tables prefer approximate functions: uniq() over COUNT(DISTINCT)\n"
        "- Arrays: arrayJoin(), groupArray()\n"
        "- Use LIMIT N at end"
    ),
    "mongodb": (
        "- Generate a JSON query spec with keys: operation, collection, "
        "filter, projection, sort, limit\n"
        "- operation: find | aggregate | count\n"
        "- For aggregations use pipeline with $match, $group, $sort, $limit stages"
    ),
}

SYSTEM_PROMPT_TEMPLATE = """\
You are a database query expert. Generate precise, efficient queries using the provided schema.

RULES:
1. Only generate SELECT/read queries unless explicitly told otherwise.
2. Use the EXACT table and column names from the schema below.
3. Use Foreign Key relationships to determine correct JOINs between tables.
4. When a question involves multiple tables, use JOINs based on FK relationships.
5. Handle ambiguous column names by qualifying them with the table name (e.g. table.column).
6. Consider indexes listed in the schema -- prefer indexed columns in WHERE and ORDER BY.
7. Include LIMIT (default 100) for potentially large result sets.
8. Explain your query logic briefly.

DB DIALECT: {db_type}
{dialect_hints}

When you have enough context, call the `execute_query` tool with the generated query."""


def _build_system_prompt(db_type: str) -> str:
    hints = DIALECT_HINTS.get(db_type, "- Standard SQL dialect")
    return SYSTEM_PROMPT_TEMPLATE.format(db_type=db_type, dialect_hints=hints)


EXECUTE_QUERY_TOOL = Tool(
    name="execute_query",
    description=(
        "Execute a database query. For SQL databases, provide SQL."
        " For MongoDB, provide a JSON spec."
    ),
    parameters=[
        ToolParameter(
            name="query", type="string", description="The SQL query or MongoDB JSON spec to execute"
        ),
        ToolParameter(
            name="explanation",
            type="string",
            description="Brief explanation of what this query does and why",
        ),
    ],
)

VISUALIZATION_TOOL = Tool(
    name="recommend_visualization",
    description="Recommend the best visualization for the query results",
    parameters=[
        ToolParameter(
            name="viz_type",
            type="string",
            description="Visualization type",
            enum=["table", "bar_chart", "line_chart", "pie_chart", "scatter", "text", "number"],
        ),
        ToolParameter(
            name="config",
            type="string",
            description="JSON config for the visualization (labels, axes, colors, etc.)",
        ),
        ToolParameter(
            name="summary", type="string", description="Human-readable summary of the results"
        ),
    ],
)


class QueryBuilder:
    """Translates natural language questions into database queries using LLM."""

    def __init__(self, llm_router: LLMRouter):
        self._llm = llm_router

    async def build_query(
        self,
        question: str,
        schema_context: str,
        rules_context: str,
        db_type: str,
        chat_history: list[Message] | None = None,
        preferred_provider: str | None = None,
        model: str | None = None,
    ) -> dict:
        """Build a query from a natural language question.

        Returns dict with 'query', 'explanation', and optionally 'error'.
        """
        messages: list[Message] = [
            Message(role="system", content=_build_system_prompt(db_type)),
            Message(
                role="system",
                content=f"DATABASE SCHEMA:\n{schema_context}",
            ),
        ]
        if rules_context:
            messages.append(Message(role="system", content=rules_context))

        if chat_history:
            messages.extend(chat_history)

        messages.append(Message(role="user", content=question))

        response = await self._llm.complete(
            messages=messages,
            tools=[EXECUTE_QUERY_TOOL],
            preferred_provider=preferred_provider,
            model=model,
        )

        usage = response.usage or {}

        if response.tool_calls:
            execute_calls = [tc for tc in response.tool_calls if tc.name == "execute_query"]
            if len(execute_calls) > 1:
                logger.warning(
                    "LLM returned %d execute_query tool calls; using the first one",
                    len(execute_calls),
                )
            if execute_calls:
                tc = execute_calls[0]
                return {
                    "query": tc.arguments.get("query", ""),
                    "explanation": tc.arguments.get("explanation", ""),
                    "usage": usage,
                }

        return {
            "query": "",
            "explanation": response.content,
            "error": "LLM did not generate a query. It responded with text instead.",
            "usage": usage,
        }

    async def interpret_results(
        self,
        question: str,
        query: str,
        results_summary: str,
        db_type: str,
        preferred_provider: str | None = None,
        model: str | None = None,
    ) -> dict:
        """Interpret query results and recommend visualization."""
        messages = [
            Message(
                role="system",
                content=(
                    "You are a data analyst. Given a user's question, the query that was executed, "
                    "and the results, provide a clear interpretation "
                    "and recommend the best visualization."
                ),
            ),
            Message(
                role="user",
                content=f"Question: {question}\nQuery: {query}\nResults:\n{results_summary}",
            ),
        ]

        response = await self._llm.complete(
            messages=messages,
            tools=[VISUALIZATION_TOOL],
            preferred_provider=preferred_provider,
            model=model,
        )

        usage = response.usage or {}

        if response.tool_calls:
            for tc in response.tool_calls:
                if tc.name == "recommend_visualization":
                    config = tc.arguments.get("config", "{}")
                    if isinstance(config, str):
                        try:
                            config = json.loads(config)
                        except json.JSONDecodeError:
                            config = {}
                    return {
                        "viz_type": tc.arguments.get("viz_type", "table"),
                        "config": config,
                        "summary": tc.arguments.get("summary", response.content),
                        "usage": usage,
                    }

        return {
            "viz_type": "text",
            "config": {},
            "summary": response.content,
            "usage": usage,
        }
