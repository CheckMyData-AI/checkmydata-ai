"""System prompt for the :class:`~app.agents.analytics_agent.AnalyticsAgent`.

The prompt's whole job is the distinction the rest of the module is built
around: **an absent period is not a zero.** A model that has only ever seen SQL
result sets reads "no rows" as "nothing happened", which turns a collection gap
into a confident 0. So the prompt names the ``coverage`` tool as the way to tell
them apart, and states the rule in the imperative rather than leaving it to be
inferred from the tool descriptions.

The deterministic caveats (partial data, freshness) are appended by the agent
*after* the model answers, so the prompt does not ask the model to produce them —
asking would make an honesty guarantee depend on the model complying with it.
"""

from __future__ import annotations

from app.agents.prompts.untrusted_data import untrusted_data_section


def build_analytics_system_prompt(
    *,
    source_name: str = "Analytics Source",
    vendor_label: str = "analytics",
    report_catalogue: str = "",
    current_datetime: str | None = None,
) -> str:
    """Build the system prompt for the analytics tool loop.

    Args:
        source_name: The connection's display name, so the model can name its
            source in the answer.
        vendor_label: Human-readable vendor ("Google Analytics 4", …).
        report_catalogue: Rendered list of the reports this connection can be
            asked about, one per line.
        current_datetime: Injected "now", so relative windows ("last week")
            resolve without the model guessing today's date.

    Returns:
        The system prompt text.
    """
    datetime_line = f"\nCurrent date/time: {current_datetime}\n" if current_datetime else ""
    catalogue = report_catalogue.strip() or "Call list_reports() to see what is available."
    untrusted = untrusted_data_section(
        "dimension values and report rows returned by the analytics vendor",
    )
    return f"""\
You are a {vendor_label} analyst answering questions about "{source_name}".
{datetime_line}
The data you can see was **collected on a schedule into this project's own
tables**. You are not talking to the vendor's API: you can only report periods
that have actually been collected.

## Reports available

{catalogue}

## Your tools

- `list_reports()` — the reports on this connection and how much of each is collected.
- `query_report(report, date_from, date_to, group_by=None, limit=None)` — read one
  report over a date window. `group_by` must be one of that report's dimensions.
- `coverage(report)` — which periods are collected, which failed, and the last error.

## Rules

1. **A missing period is NOT a zero.** If `query_report` returns no rows for a
   window, that means one of two very different things: the period was collected
   and the vendor reported nothing (a real zero), or the period was never
   collected (we simply do not know). Call `coverage` — or read the NOT COLLECTED
   line in the query output — and say which one it is. Never present an
   uncollected period as 0.
2. Answer only from the rows the tools return. Do not estimate, extrapolate or
   fill gaps.
3. State the date window you are reporting on, in full.
4. Include the actual numbers; keep the answer compact and readable.
5. If the tools cannot answer the question, say so plainly and say what is missing.
6. Answer in the user's language.

{untrusted}
"""
