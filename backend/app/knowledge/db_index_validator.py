"""LLM-powered per-table validator for database indexing.

Analyzes each table's schema + sample data against project knowledge
and produces a structured assessment.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.config import settings
from app.connectors.base import ColumnInfo, QueryResult, SchemaInfo, TableInfo
from app.llm.base import Message, Tool, ToolParameter
from app.llm.router import LLMRouter
from app.llm.tool_args import as_bool, as_int, as_text, tool_call_truncated

logger = logging.getLogger(__name__)

_VALID_CODE_MATCH = {"matched", "orphan", "mismatch", "no_code_info"}


def nullability_suffix(is_nullable: bool | None) -> str:
    """``" NULL"`` / ``" NOT NULL"`` / silence.

    This read `" NULL" if col.is_nullable else " NOT NULL"`, so a column whose
    nullability nobody established was written down as NOT NULL — an assertion
    made from a default. Unlike the prompt builder, this reader states both known
    cases, so it keeps them and stays quiet on the third.
    """
    if is_nullable is True:
        return " NULL"
    if is_nullable is False:
        return " NOT NULL"
    return ""


def _clamp_code_match(raw: str) -> str:
    return raw if raw in _VALID_CODE_MATCH else "no_code_info"


ANALYZE_TABLE_TOOL = Tool(
    name="table_analysis",
    description="Return a structured analysis of the database table",
    parameters=[
        # FIRST, and required (B-16, audit 2026-09-23 F-K1): the batch path maps each
        # call to its table by this name. It used to map by position, and one call with
        # unparseable arguments shifted every later analysis onto the table before it.
        # First for the reason `SYNC_ANALYSIS_TOOL` puts identity first: arguments are
        # emitted in schema order, so a completion cap cuts prose, never the key.
        ToolParameter(
            name="table_name",
            type="string",
            description=(
                "The EXACT table name being analyzed, copied verbatim from the "
                "'## Table: <name>' header (prefix it with the 'Schema:' value as "
                "'schema.table' when one is shown). Required so results map to the right table."
            ),
        ),
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
                "One-sentence description of what this table stores and its business purpose"
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
                "Explanation of any discrepancies between live schema and code expectations"
            ),
            required=False,
        ),
        ToolParameter(
            name="numeric_format_notes",
            type="string",
            description=(
                "JSON object documenting every numeric column: storage format "
                "(cents vs whole units, integer vs decimal), currency (which currency, "
                "single or multi-currency, column holding currency code), decimal precision, "
                "unit of measurement, value ranges from sample data. "
                'E.g. {"price": "cents (integer), divide by 100 for USD", '
                '"weight_kg": "kilograms, decimal(10,2), range 0.5-150", '
                '"discount_percent": "whole percentage 0-100"}'
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
                "2-4 sentence overview of the database: what domain, key entity groups, data volume"
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
    numeric_format_notes: str = "{}"


@dataclass
class ConnectionSummaryResult:
    summary_text: str = ""
    recommendations: str = ""


#: How many measured values are worth spending prompt tokens on. Above this the list
#: stops being evidence and becomes a sample of a sample.
_PROMPT_VALUE_CAP = 12

#: Column names that carry the unit a money column is denominated in. Matched as a whole
#: name or a `_currency` suffix, never as a substring, so `currency_rate` — which holds a
#: number, not a unit — is not one of these.
_CURRENCY_COLUMNS = ("currency", "currency_code", "ccy")

#: Money columns whose value is meaningless without the unit beside them.
_AMOUNT_HINTS = ("amount", "price", "total", "cost", "revenue", "fee", "balance", "sum")


#: The prefix every measured caveat carries, so a later run can tell its own additions
#: from the model's prose and rebuild them instead of stacking them.
MEASURED_PREFIX = "MEASURED"

#: …and the kind, because the two caveats are rebuilt by different steps and a run can
#: produce one without the other. Stripping both when only one was recomputed is how a
#: true warning disappears — see `strip_measured_lines`.
MEASURED_UNITS = "MEASURED (units):"
MEASURED_RIVALRY = "MEASURED (rivalry):"


def strip_measured_lines(hints: str, kind: str | None = None) -> str:
    """The generated advice with any previously-added measured caveat removed.

    A measured line is **rebuilt** from the current run rather than kept, and that is the
    difference between a caveat and a leak: the reuse path clones a stored `query_hints`
    verbatim for a table whose schema has not changed, so without this a table surviving
    twenty nights unchanged accumulates twenty copies of one warning, each quoting a
    total from a different month.

    **`kind` is what keeps the rebuild from erasing a true warning.** The two caveats are
    produced by different steps and a run can produce one without the other: measured on
    production 2026-09-16, a `completed_partial` index spent its sampling budget before
    reaching `purchases.currency`, so the units caveat had nothing to rebuild from — and
    an unconditional strip removed the correct one the night before had established. A
    caveat is replaced when there is a measurement to replace it with, and kept when
    there is not.

    Only whole lines beginning with the prefix are dropped: a sentence the model wrote
    that happens to contain the word is prose, and prose is not this function's to edit.
    """
    marker = kind or MEASURED_PREFIX
    kept = [ln for ln in (hints or "").splitlines() if not ln.lstrip().startswith(marker)]
    return "\n".join(kept).strip()


def _measured_suffix(col: ColumnInfo) -> str:
    """What is known about this column's values because it was counted, not inferred.

    Silence where nothing was measured — an empty string rather than "0 values" or
    "unknown", because a column the sampler skipped and a column with no values are
    different facts and only one of them is a fact about the data.

    The distinct COUNT leads, because it is the part that settles a question: no model
    calls a column single-valued while reading that it holds fourteen. The values follow
    when they are few enough to be evidence rather than a list.
    """
    bits: list[str] = []
    if col.distinct_count is not None:
        bits.append(f"{col.distinct_count} distinct")
    values = col.distinct_values or []
    if values and len(values) <= _PROMPT_VALUE_CAP:
        bits.append("values: " + ", ".join(str(v) for v in values))
    elif values:
        shown = ", ".join(str(v) for v in values[:_PROMPT_VALUE_CAP])
        bits.append(f"values incl.: {shown}, …")
    return f" [measured: {'; '.join(bits)}]" if bits else ""


def _multi_currency_columns(table: TableInfo) -> tuple[str, int] | None:
    """A currency column this index MEASURED as holding more than one value."""
    for col in table.columns:
        name = col.name.lower()
        if name in _CURRENCY_COLUMNS or name.endswith("_currency"):
            if isinstance(col.distinct_count, int) and col.distinct_count > 1:
                return col.name, col.distinct_count
    return None


def apply_measured_corrections(analysis: TableAnalysis, table: TableInfo) -> TableAnalysis:
    """Put a measured fact in front of generated advice that contradicts it.

    **Structure outranks the model** — the rule `resolve_sync_status` already states for
    the code↔DB map, applied here to the schema index. The prompt now carries the
    measurement (`_measured_suffix`), and a prompt is a request rather than a guarantee.

    Production, 2026-09-15. `purchases.query_hints` read *"The 'amount' column should be
    divided by 100 to convert from cents to dollars"* while `column_stats_json` for the
    same row recorded `currency`: `distinct_count: 14`, spanning `BRL` to `VND`. `amount`
    is minor units **of `currency`**; there is no dollar column anywhere. Summed as
    dollars, fourteen currencies become one wrong number — stated confidently, because
    the index told the agent to.

    Additive on purpose. Rewriting model prose by pattern is how a correct sentence gets
    corrupted by a guard aimed at a different one; this prepends what was counted and
    leaves the rest to be read in its light. It fires only where there is a measurement
    to stand on: a currency column whose distinct count was actually taken and is > 1.
    """
    measured = _multi_currency_columns(table)
    if measured is None:
        # Nothing measured THIS run. The hints keep whatever a previous run established —
        # a sampler that ran out of budget has learned nothing, and forgetting a true
        # warning on the strength of having not looked is the defect, not the fix.
        return analysis
    money = [c.name for c in table.columns if any(h in c.name.lower() for h in _AMOUNT_HINTS)]
    if not money:
        return analysis

    col, count = measured
    caveat = (
        f"{MEASURED_UNITS} `{col}` holds {count} distinct values in this table, so "
        f"{', '.join(f'`{m}`' for m in money)} is denominated per row and is NOT a single "
        f"currency. Any SUM or comparison across rows must group by `{col}` or convert "
        f"through a rate; a bare total mixes currencies and is wrong."
    )
    # Rebuilt, not appended, and only THIS kind: the stored hints may already carry this
    # caveat from a previous run, and a reused analysis certainly does — but a rivalry
    # caveat beside it was produced by a different step and is not ours to remove.
    analysis.query_hints = (
        f"{caveat}\n{strip_measured_lines(analysis.query_hints, MEASURED_UNITS)}"
    ).strip()
    return analysis


def _map_calls_to_tables(
    tool_calls: list, tables: list[tuple[TableInfo, QueryResult | None]]
) -> dict[int, dict]:
    """Decide which ``table_analysis`` call describes which table of a batch.

    Returns ``{table index: arguments}``; a table absent from it gets the fallback.

    By NAME whenever any call names a table (B-16, audit 2026-09-23 F-K1 —
    ``docs/audits/2026-09-23-recent-work-audit.md`` §3.1). Mapping by position alone
    let one call with empty arguments shift every later analysis onto the table before
    it, and nothing failed: the index described the wrong tables. A name matches the
    table's bare name when that is unique in the batch, or ``schema.name`` always;
    case-insensitive. An unknown or ambiguous name is dropped, and a second analysis
    of one table keeps the first — the same rules ``CodeDbSyncAnalyzer`` applies.

    By POSITION only when no call names anything (a model that ignores the required
    parameter), and then every ``table_analysis`` call consumes its slot, empty or
    not — so an unusable call costs its own table, never the ones after it.
    """
    calls = [tc for tc in tool_calls if tc.name == "table_analysis"]
    named = [tc for tc in calls if tc.arguments and str(tc.arguments.get("table_name", "")).strip()]

    if not named:
        return {i: tc.arguments for i, tc in enumerate(calls[: len(tables)]) if tc.arguments}

    bare_counts: dict[str, int] = {}
    for tbl, _ in tables:
        bare_counts[tbl.name.lower()] = bare_counts.get(tbl.name.lower(), 0) + 1
    index_by_key: dict[str, int] = {}
    for i, (tbl, _) in enumerate(tables):
        if tbl.schema:
            index_by_key[f"{tbl.schema}.{tbl.name}".lower()] = i
        if bare_counts[tbl.name.lower()] == 1:
            index_by_key[tbl.name.lower()] = i

    mapped: dict[int, dict] = {}
    for tc in named:
        raw = str(tc.arguments.get("table_name", "")).strip()
        idx = index_by_key.get(raw.lower())
        if idx is None:
            logger.warning(
                "Batch table analysis: call for unknown or ambiguous table %r — dropped", raw
            )
            continue
        if idx in mapped:
            logger.warning("Batch table analysis: duplicate analysis for %r — keeping first", raw)
            continue
        mapped[idx] = tc.arguments
    return mapped


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
        scrub: bool = True,
        preferred_provider: str | None = None,
        model: str | None = None,
    ) -> TableAnalysis:
        prompt = self._build_table_prompt(
            table, sample_data, code_context, rules_context, scrub=scrub
        )

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
                max_tokens=settings.db_index_analysis_max_tokens,
            )

            if tool_call_truncated(resp):
                logger.warning(
                    "LLM analysis for table %s truncated at %d completion tokens — "
                    "using the deterministic fallback rather than a half-read answer",
                    table.name,
                    settings.db_index_analysis_max_tokens,
                )
                return self._fallback_analysis(table, sample_data)

            if resp.tool_calls and resp.tool_calls[0].arguments:
                args = resp.tool_calls[0].arguments
                col_notes = as_text(args.get("column_notes", "{}"), "{}")
                numeric_notes = as_text(args.get("numeric_format_notes", "{}"), "{}")

                # Every field, not the two that happened to get a guard. Five of
                # these land in `DbIndex` columns (`models/db_index.py:49-66`) and a
                # dict reaching any of them raises inside `store_results`, rolling
                # back the whole connection's index — 213 tables lost for one row.
                # `relevance_score` was the quiet one: `int({})` raised inside the
                # try, discarding the analysis of this table AND of every table
                # after it in the batch.
                return apply_measured_corrections(
                    TableAnalysis(
                        table_name=table.name,
                        is_active=as_bool(args.get("is_active", True), True),
                        relevance_score=as_int(args.get("relevance_score", 3), 3, lo=1, hi=5),
                        business_description=as_text(args.get("business_description", "")),
                        data_patterns=as_text(args.get("data_patterns", "")),
                        column_notes_json=col_notes,
                        query_hints=as_text(args.get("query_hints", "")),
                        code_match_status=_clamp_code_match(
                            args.get("code_match_status", "no_code_info"),
                        ),
                        code_match_details=as_text(args.get("code_match_details", "")),
                        numeric_format_notes=numeric_notes,
                    ),
                    table,
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
        scrub: bool = True,
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
                    table,
                    sample,
                    code_context,
                    rules_context,
                    scrub=scrub,
                )
            )
            prompt_parts.append("---\n")

        messages = [
            Message(role="system", content=self._system_prompt()),
            Message(role="user", content="\n".join(prompt_parts)),
        ]

        results_by_index: dict[int, TableAnalysis] = {}
        try:
            resp = await self._llm.complete(
                messages=messages,
                tools=[ANALYZE_TABLE_TOOL],
                preferred_provider=preferred_provider,
                model=model,
                temperature=0.0,
                max_tokens=settings.sync_analysis_batch_max_tokens,
            )

            if tool_call_truncated(resp):
                logger.warning(
                    "Batch table analysis truncated at %d completion tokens over "
                    "%d table(s) — every one falls back",
                    settings.sync_analysis_batch_max_tokens,
                    len(tables),
                )
                resp.tool_calls = []

            analysed = _map_calls_to_tables(resp.tool_calls, tables)
            for i, (tbl, _sample) in enumerate(tables):
                args = analysed.get(i)
                if args is None:
                    continue
                col_notes = as_text(args.get("column_notes", "{}"), "{}")
                numeric_notes = as_text(args.get("numeric_format_notes", "{}"), "{}")
                results_by_index[i] = apply_measured_corrections(
                    TableAnalysis(
                        table_name=tbl.name,
                        is_active=as_bool(args.get("is_active", True), True),
                        relevance_score=as_int(args.get("relevance_score", 3), 3, lo=1, hi=5),
                        business_description=as_text(args.get("business_description", "")),
                        data_patterns=as_text(args.get("data_patterns", "")),
                        column_notes_json=col_notes,
                        query_hints=as_text(args.get("query_hints", "")),
                        code_match_status=_clamp_code_match(
                            args.get("code_match_status", "no_code_info"),
                        ),
                        code_match_details=as_text(args.get("code_match_details", "")),
                        numeric_format_notes=numeric_notes,
                    ),
                    tbl,
                )

        except Exception:
            logger.warning("Batch LLM analysis failed", exc_info=True)

        results: list[TableAnalysis] = []
        for i, (tbl, sample) in enumerate(tables):
            analysis = results_by_index.get(i)
            results.append(
                analysis if analysis is not None else self._fallback_analysis(tbl, sample)
            )
        fallbacks = len(tables) - len(results_by_index)
        if fallbacks:
            logger.info("Batch table analysis: %d/%d used fallback", fallbacks, len(tables))

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
                f"Phantom tables (in code, not in DB): {', '.join(sorted(phantom))}"
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
                max_tokens=settings.db_index_analysis_max_tokens,
            )

            if tool_call_truncated(resp):
                logger.warning(
                    "Connection summary truncated at %d completion tokens — "
                    "returning an empty summary rather than a partial one",
                    settings.db_index_analysis_max_tokens,
                )
                return ConnectionSummaryResult()

            if resp.tool_calls and resp.tool_calls[0].arguments:
                args = resp.tool_calls[0].arguments
                # Both are declared ``string`` and both land in ``Text`` columns
                # (``db_index.py:89``). Found by walking the REQ ladder after PRJ-01,
                # not by a failure: this writer runs in a step the nightly db_index
                # reaches every night and has simply not met an object yet.
                return ConnectionSummaryResult(
                    summary_text=as_text(args.get("summary_text", "")),
                    recommendations=as_text(args.get("recommendations", "")),
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
            "and common filter patterns.\n\n"
            "PAY SPECIAL ATTENTION TO NUMERIC COLUMNS:\n"
            "- Monetary values: determine if stored in cents/minor units (integer) "
            "or whole currency units (decimal). Infer from column type AND sample data.\n"
            "- Currency: identify the currency (USD, EUR, etc.) or if multiple "
            "currencies are used. Look for a companion currency-code column.\n"
            "- Decimal precision: note the precision for financial columns "
            "(e.g. decimal(10,2) means 2 decimal places).\n"
            "- Percentages: determine if stored as 0-100 or 0.0-1.0.\n"
            "- Units of measurement: document units (grams, kg, seconds, minutes, etc.).\n"
            "- Value ranges: use sample data to infer typical ranges and flag outliers.\n"
            "Return these findings in the `numeric_format_notes` field as a JSON object."
        )

    @staticmethod
    def _build_table_prompt(
        table: TableInfo,
        sample_data: QueryResult | None,
        code_context: str,
        rules_context: str,
        *,
        scrub: bool = True,
    ) -> str:
        from app.config import settings as _settings

        parts: list[str] = [f"## Table: {table.name}"]

        if table.schema and table.schema != "public":
            parts.append(f"Schema: {table.schema}")
        if table.row_count is not None:
            parts.append(f"Row count (estimated): {table.row_count:,}")
        if table.comment:
            parts.append(f"Comment: {table.comment}")

        # DBIDX-D16: cap the number of columns in the prompt to avoid unbounded
        # prompts on very wide tables. Columns beyond the cap are replaced with
        # a note so the LLM knows more columns exist without consuming tokens.
        col_cap: int = _settings.db_index_max_prompt_columns
        columns_to_show = table.columns[:col_cap]
        hidden_count = len(table.columns) - len(columns_to_show)

        parts.append("\nColumns:")
        for col in columns_to_show:
            pk = " [PK]" if col.is_primary_key else ""
            nullable = nullability_suffix(col.is_nullable)
            default = f" DEFAULT {col.default}" if col.default else ""
            comment = f" — {col.comment}" if col.comment else ""
            # B-08: what `fetch_samples` MEASURED about this column, beside its type. It
            # was measured, persisted and shown to nobody — this line ended at the
            # comment, so the model writing `query_hints` described a column whose values
            # the indexer had already counted. Production: `purchases.currency` measured
            # `distinct_count: 14` spanning BRL to VND, and the note generated for it read
            # "Currency code, likely USD". The guess was not the model's failure;
            # withholding the measurement was ours.
            parts.append(
                f"  - {col.name}: {col.data_type}{pk}{nullable}{default}"
                f"{_measured_suffix(col)}{comment}"
            )
        if hidden_count > 0:
            parts.append(f"  (… {hidden_count} more columns)")

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
            from app.knowledge import pii_scrubber

            rows = pii_scrubber.scrub_row_cells(
                sample_data.columns, sample_data.rows, enabled=scrub
            )
            parts.append(f"\nSample data ({len(rows)} newest rows):")
            parts.append("| " + " | ".join(sample_data.columns) + " |")
            parts.append("| " + " | ".join(["---"] * len(sample_data.columns)) + " |")
            for row in rows:
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
