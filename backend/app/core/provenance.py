"""How old is a claim the system inferred rather than measured?

Lives apart from any agent or service so both can import it without either depending
on the other: the SQL agent renders `code_db_sync` conventions, `DbIndexService`
renders `db_index` descriptions, and a reader should not have to learn two conventions
for the same idea.

**This module imports nothing from ``app``.**
"""

from __future__ import annotations

from datetime import UTC, datetime


def format_derived_age(derived_at: datetime | None) -> str:
    """Render how old an *inferred* claim is, for the system prompt.

    `db_index` and `code_db_sync` carry two kinds of content in the same fields:
    introspected fact (column counts, enum labels) and an LLM's reading of the
    codebase (data conventions, conversion warnings, required filters). Both used to
    reach the prompt in the same voice, so a guess from six months ago was
    indistinguishable from a value read off the database this morning.

    Silent under a week on purpose. A marker printed on every prompt is noise, and
    noise is what teaches a model to skip the marker on the one occasion it matters.

    The stakes are not cosmetic: a stale `required_filters` entry -- soft-delete
    removed from the code, no re-index since -- has the agent dutifully adding a
    filter that no longer exists and under-reporting the answer. Nothing else in this
    layer produces a confident wrong number.
    """
    # Anything that is not a real datetime is treated as "unknown age" and stays
    # silent. Being liberal here is load-bearing: the caller wraps this in a broad
    # `except`, so a TypeError raised from a prompt helper would not surface as a
    # crash -- it would silently empty the critical-warnings block and hand the agent
    # a prompt with the safety notes missing. Found exactly that way.
    if not isinstance(derived_at, datetime):
        return ""
    # SQLite hands back naive datetimes; treat them as UTC rather than raising.
    if derived_at.tzinfo is None:
        derived_at = derived_at.replace(tzinfo=UTC)
    days = (datetime.now(UTC) - derived_at).days
    if days < 7:
        return ""
    if days >= 90:
        return f" [inferred {days} days ago — verify before relying on it]"
    return f" [inferred {days} days ago]"
