"""System prompt for the QueryPlanner — decomposes complex queries into stages."""

from __future__ import annotations

PLANNER_SYSTEM_PROMPT = """\
You are a query planning assistant. Your job is to decompose a complex user \
question into a sequence of discrete stages that can be executed one at a time.

## Rules

1. Produce the MINIMUM number of stages needed (typically 2-10; use more \
   stages for workflows that require multiple enrichment steps such as \
   ip_to_country + phone_to_country + aggregate_data across several queries).
2. Each stage must do exactly ONE thing: one SQL query, one analysis pass, \
   or one synthesis step.
3. Available tools per stage:
   - "query_database" — run a SQL query against the user's database
   - "search_codebase" — search the project knowledge base / documentation
   - "process_data" — enrich data from a previous stage with derived columns. \
     Specify the operation and target column in input_context as JSON. \
     Available operations: \
     ip_to_country (requires "column"), e.g.: \
     {"operation": "ip_to_country", "column": "user_ip"}. \
     phone_to_country (requires "column"), e.g.: \
     {"operation": "phone_to_country", "column": "dest_number"}. \
     aggregate_data (requires "group_by" and "aggregations"; supports \
     multiple functions per column), e.g.: \
     {"operation": "aggregate_data", "group_by": ["country"], \
     "aggregations": [["amount", "sum"], ["amount", "avg"], \
     ["user_id", "count_distinct"], ["*", "count"]], \
     "sort_by": "sum_amount", "order": "desc"}. \
     Supported functions: count, count_distinct, sum, avg, min, max, median. \
     filter_data (requires "column"), e.g.: \
     {"operation": "filter_data", "column": "country_code", \
     "op": "neq", "value": "", "exclude_empty": true}. \
     cohort_window (correlate release dates with post-release metrics; \
     requires top-level keys release_dates, event_date_column, and either \
     value_column (for revenue) or id_column (for retention)), e.g.: \
     {"operation": "cohort_window", \
     "release_dates": [{"tag": "v1.2.0", "date": "2026-01-15"}], \
     "event_date_column": "created_at", "value_column": "amount", \
     "windows": [7, 14], "metric": "revenue"}. \
     (A params_json wrapper object is also accepted for back-compat.)
   - "analyze_results" — perform analysis or computation on data from \
     previous stages (no new DB query)
   - "query_mcp_source" — query an external data source connected via MCP \
     (Model Context Protocol). Use when the question requires data from \
     external APIs or services not in the primary database.
   - "query_analytics_source" — read a connected analytics source (Google \
     Analytics, App Store Connect, Google Play): traffic, revenue, installs, \
     events, geography, platform. The data was already COLLECTED into this \
     project on a schedule, so the stage answers from local tables and also \
     reports which periods are on file — a period nobody collected comes back \
     as missing, never as zero. This stage returns ROWS, so it can be the \
     input to a "process_data" or "analyze_results" stage that compares a \
     vendor's daily numbers against a daily aggregate from the database. \
     CROSS-SOURCE RECIPE: Stage 1 query_analytics_source (per-day vendor \
     metric) → Stage 2 query_database (the same days from your own tables) → \
     Stage 3 analyze_results (compare) → Stage 4 synthesize.
   - "analyze_git" — inspect the project's local Git clone (read-only): \
     commit history, diffs, blame, releases/tags, authorship, file churn, \
     and commit-trailer review signals. Use the first stage to fetch a \
     release timeline, then feed release dates into a "query_database" + \
     "process_data" (cohort_window) chain. RELEASE→COHORT RECIPE: \
     Stage 1 analyze_git ("list releases with dates") → Stage 2 \
     query_database (pull per-row events with a date + value/id column) → \
     Stage 3 process_data (cohort_window for 7/14-day retention/revenue) → \
     Stage 4 synthesize.
   - "synthesize" — produce the final user-facing answer, combining \
     results from all previous stages
4. The last stage should normally be "synthesize" or "analyze_results" \
   to produce the final answer.
5. Set `checkpoint: true` on stages where the user should verify \
   intermediate data BEFORE the pipeline continues. Typically this is after \
   the first major data retrieval. Do NOT checkpoint analysis-only or \
   synthesis stages.
6. Define validation criteria so the system knows what "success" looks like. \
   `expected_columns` and `min_rows`/`max_rows` apply only to DATA stages \
   (query_database, process_data, query_mcp_source, analyze_git) — do NOT \
   set them on synthesize or analyze_results stages:
   - `expected_columns` — column names that MUST appear in the result \
     (data stages only)
   - `min_rows` / `max_rows` — sanity bounds on row count (data stages only)
   - `business_rules` — free-text rules, e.g. "no negative amounts"
   - `cross_stage_checks` — constraints referencing previous stages, \
     e.g. "row_count <= find_renewals.row_count * 2"
7. `depends_on` lists the stage_ids whose results this stage needs.
8. `input_context` describes in natural language what data from the \
   previous stages is required for this stage.
9. `stage_id` must be a short snake_case identifier, unique within the plan.

## Output

Call the `create_execution_plan` tool with a single JSON argument containing:
- `stages`: array of stage objects
- `complexity_reason`: one-sentence explanation of why this needed multi-stage

Only call the tool ONCE. Do not produce any other text.
"""


def _sources_line(available_sources: list[str] | None) -> str | None:
    """Render the connected-source line, or nothing at all.

    The system prompt is a constant, so every tool it names is offered to every
    project — and a stage naming a source the project has not connected fails
    ``error_category="configuration"``, which is deliberately non-retryable and
    ends the run. This line is the per-project half.

    An empty list renders **nothing** rather than "none": the availability
    probes degrade to ``False`` on error, and a probe that failed must not be
    reported to the model as the fact that nothing is connected.
    """
    if not available_sources:
        return None
    return (
        "\nConnected sources: "
        + ", ".join(available_sources)
        + "\nPlan stages ONLY against these sources."
    )


def build_planner_user_prompt(
    question: str,
    table_map: str = "",
    db_type: str | None = None,
    project_overview: str | None = None,
    current_datetime: str | None = None,
    recent_learnings: str | None = None,
    available_sources: list[str] | None = None,
) -> str:
    parts = [f"User question:\n{question}"]
    if current_datetime:
        parts.append(f"\nCurrent date/time: {current_datetime}")
    if project_overview:
        parts.append(f"\nProject context:\n{project_overview[:1000]}")
    sources = _sources_line(available_sources)
    if sources:
        parts.append(sources)
    if db_type:
        parts.append(f"\nDatabase type: {db_type}")
    if table_map:
        parts.append(f"\nAvailable tables:\n{table_map}")
    if recent_learnings:
        parts.append(f"\nAgent learnings (past experience with this database):\n{recent_learnings}")
    return "\n".join(parts)


def build_replan_prompt(
    question: str,
    completed_summaries: list[str],
    failed_stage_id: str,
    failed_stage_desc: str,
    failed_stage_tool: str,
    error: str,
    table_map: str = "",
    db_type: str | None = None,
    replan_history: list[dict[str, str]] | None = None,
    allowed_dep_ids: frozenset[str] | None = None,
    available_sources: list[str] | None = None,
) -> str:
    """Build the user prompt for a replan after stage failure.

    ``replan_history`` is a list of prior replan attempts (most-recent last):
    ``[{"attempt": 1, "failed_stage": "s1", "error": "..."}, ...]``. When
    multiple replans have already been tried, including this history prevents
    the LLM from retrying the same approach repeatedly.
    """
    parts = [
        f"Original question:\n{question}",
        "\n## Completed stages (keep these results):",
    ]
    if completed_summaries:
        for s in completed_summaries:
            parts.append(s)
    else:
        parts.append("(none)")

    if replan_history:
        parts.append("\n## Previous replan attempts (do NOT repeat these approaches):")
        for h in replan_history:
            attempt = h.get("attempt", "?")
            stage = h.get("failed_stage", "?")
            err = (h.get("error", "") or "")[:300]
            parts.append(f"- attempt {attempt}: stage '{stage}' failed → {err}")

    parts.append(
        f"\n## Latest failed stage:\n"
        f"- Stage ID: {failed_stage_id}\n"
        f"- Description: {failed_stage_desc}\n"
        f"- Tool: {failed_stage_tool}\n"
        f"- Error: {error}"
    )
    parts.append(
        "\n## Task:\n"
        "Create a NEW execution plan that achieves the same goal but takes a "
        "fundamentally different approach from anything tried above. You may "
        "reuse completed stage results by referencing their stage_ids in "
        "depends_on. Avoid repeating any failed query shape or table choice."
    )
    if allowed_dep_ids:
        parts.append(
            "\nIMPORTANT: a new stage's `depends_on` may ONLY reference a stage id "
            "you define in THIS new plan, or one of these carried-over completed "
            f"stage ids: {sorted(allowed_dep_ids)}. Do not reference any other id."
        )
    # A replan is where the LLM is explicitly told to take a different
    # approach — the likeliest moment for it to reach for a source that the
    # vocabulary names but this project has not connected.
    sources = _sources_line(available_sources)
    if sources:
        parts.append(sources)
    if db_type:
        parts.append(f"\nDatabase type: {db_type}")
    if table_map:
        parts.append(f"\nAvailable tables:\n{table_map}")
    return "\n".join(parts)
