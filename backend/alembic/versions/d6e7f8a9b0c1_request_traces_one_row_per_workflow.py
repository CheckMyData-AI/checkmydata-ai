"""One request_traces row per workflow (PRJ-04).

Two writers produce a trace: the buffer flush at ``pipeline_end`` (duration, spans)
and the chat route's ``finalize_trace`` (session, message, tokens, cost, routing).
The second looked the first up with ``SELECT … LIMIT 1`` and inserted when it found
nothing — which it did whenever the flush, a fire-and-forget task, had not committed
yet. Production, 2026-09-17: **242 rows for 177 workflows**.

The duplicates are merged, not dropped, because each half carries columns the other
lacks: the row with spans keeps its spans and duration, and takes session, message,
tokens, cost, model and routing from its twin wherever it has none. A run any row
says completed is completed, and then a ``Stale: …`` note on it is removed — the
eviction guessed at a death that did not happen. Then ``workflow_id`` becomes unique,
under the index name the model already declared, so the next race fails loudly and
the writers' ``IntegrityError`` branch turns it into an update.

Revision ID: d6e7f8a9b0c1
Revises: c5d6e7f8a2b3
"""

from __future__ import annotations

from decimal import Decimal

import sqlalchemy as sa
from alembic import op

revision = "d6e7f8a9b0c1"
down_revision = "c5d6e7f8a2b3"
branch_labels = None
depends_on = None

_INDEX = "ix_request_traces_workflow_id"

#: Columns taken from a twin when the kept row has no value of its own. "No value"
#: is NULL, ``""``, ``0`` or ``"unknown"`` — the defaults a writer leaves behind.
_FILL = (
    "session_id",
    "message_id",
    "assistant_message_id",
    "failure_kind",
    "total_duration_ms",
    "total_tokens",
    "estimated_cost_usd",
    "llm_provider",
    "llm_model",
    "steps_used",
    "steps_total",
    "route",
    "complexity",
    "estimated_queries",
    "plan_json",
    "question",
)


def _is_empty(value: object) -> bool:
    if value is None or value in ("", "unknown"):
        return True
    return isinstance(value, (int, float, Decimal)) and not isinstance(value, bool) and value == 0


def _merge_duplicates(bind: sa.engine.Connection) -> None:
    traces = sa.table(
        "request_traces",
        sa.column("id"),
        sa.column("workflow_id"),
        sa.column("status"),
        sa.column("error_message"),
        sa.column("response_type"),
        sa.column("created_at"),
        *(sa.column(c) for c in _FILL),
    )
    spans = sa.table("trace_spans", sa.column("id"), sa.column("trace_id"))

    dup_ids = [
        r[0]
        for r in bind.execute(
            sa.select(traces.c.workflow_id)
            .group_by(traces.c.workflow_id)
            .having(sa.func.count() > 1)
        )
    ]
    for wf in dup_ids:
        rows = [
            dict(r._mapping)
            for r in bind.execute(
                sa.select(traces).where(traces.c.workflow_id == wf).order_by(traces.c.created_at)
            )
        ]
        span_counts = {
            r["id"]: bind.execute(
                sa.select(sa.func.count()).select_from(spans).where(spans.c.trace_id == r["id"])
            ).scalar_one()
            for r in rows
        }
        keep = max(rows, key=lambda r: (span_counts[r["id"]], r["total_duration_ms"] or 0))
        others = [r for r in rows if r["id"] != keep["id"]]

        values: dict[str, object] = {}
        for col in _FILL:
            if _is_empty(keep[col]):
                for other in others:
                    if not _is_empty(other[col]):
                        values[col] = other[col]
                        break
        # The chat route's row states the outcome it served; the flush only measured.
        finalized = [o for o in others if o["session_id"]] or others
        if any(r["status"] == "completed" for r in rows):
            values["status"] = "completed"
            values["failure_kind"] = None
            if (keep["error_message"] or "").startswith("Stale:"):
                values["error_message"] = None
        elif finalized and finalized[0]["status"]:
            values["status"] = finalized[0]["status"]
        if keep["response_type"] in (None, "", "text") and finalized:
            if finalized[0]["response_type"] not in (None, "", "text"):
                values["response_type"] = finalized[0]["response_type"]

        if values:
            bind.execute(sa.update(traces).where(traces.c.id == keep["id"]).values(**values))
        other_ids = [o["id"] for o in others]
        bind.execute(sa.delete(spans).where(spans.c.trace_id.in_(other_ids)))
        bind.execute(sa.delete(traces).where(traces.c.id.in_(other_ids)))


def upgrade() -> None:
    bind = op.get_bind()
    _merge_duplicates(bind)
    existing = {ix["name"] for ix in sa.inspect(bind).get_indexes("request_traces")}
    if _INDEX in existing:
        op.drop_index(_INDEX, table_name="request_traces")
    op.create_index(_INDEX, "request_traces", ["workflow_id"], unique=True)


def downgrade() -> None:
    op.drop_index(_INDEX, table_name="request_traces")
    op.create_index(_INDEX, "request_traces", ["workflow_id"], unique=False)
