"""Deterministic schema-completeness gate (DBIDX-D10).

This module provides a pure, LLM-free function that verifies the structural
integrity of an introspected SchemaInfo.  It is intentionally separate from
``db_index_validator.py``, which is an LLM-enrichment / classification step,
NOT a structural validator.

Checks performed
----------------
* ``no_columns``       — every table must have at least one column.
* ``empty_type``       — every column must have a non-empty ``data_type``.
* ``fk_target_missing``— every FK ``references_table`` must resolve to a table
                         present in the schema (case-insensitive; schema-
                         qualified references like ``public.users`` are matched
                         against the bare table name).
* ``no_pk``            — every *table* (not view / matview) must have at least
                         one column with ``is_primary_key=True``.  When no
                         introspected PK is found, the table is *noted* as
                         PK-less (a common evidence gap, not necessarily a real
                         schema defect, but worth surfacing).

Severity guidance for callers
------------------------------
* ``no_columns`` / ``fk_target_missing`` → treat as *partial* evidence; the
  index entry should be marked ``partial=True``.
* ``empty_type`` / ``no_pk``            → informational warning; surface but
  do not force ``partial`` on their own.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.connectors.base import SchemaInfo


@dataclass
class CompletenessIssue:
    """A single structural completeness issue found in an introspected schema."""

    table: str
    kind: Literal["no_columns", "empty_type", "fk_target_missing", "no_pk"]
    detail: str


# Issues whose presence constitutes a *partial* evidence gap (used by the
# pipeline when deciding whether to set ``partial=True``).
PARTIAL_EVIDENCE_KINDS: frozenset[str] = frozenset({"no_columns", "fk_target_missing"})


def check_schema_completeness(schema: SchemaInfo) -> list[CompletenessIssue]:
    """Run deterministic completeness checks on *schema*.

    Returns a flat list of :class:`CompletenessIssue` records.  An empty list
    means the schema passed all checks.  The function is a pure function — it
    never performs I/O, never calls an LLM, and is safe to call from tests
    with hand-built fixtures.

    Parameters
    ----------
    schema:
        The :class:`~app.connectors.base.SchemaInfo` returned by a connector's
        ``introspect_schema()`` call.

    Returns
    -------
    list[CompletenessIssue]
        Zero or more issues, one per (table, kind) pair.  Multiple issues of
        the same kind can appear for different tables, but a single table+kind
        pair is only emitted once.
    """
    if not schema.tables:
        return []

    issues: list[CompletenessIssue] = []

    # Build a case-insensitive lookup set of all table names in this schema so
    # FK target resolution is O(1).
    table_names_lower: set[str] = {t.name.lower() for t in schema.tables}

    for table in schema.tables:
        tname = table.name

        # --- Check: no_columns -------------------------------------------
        if not table.columns:
            issues.append(
                CompletenessIssue(
                    table=tname,
                    kind="no_columns",
                    detail=f"Table '{tname}' has no columns; introspection may be incomplete.",
                )
            )
            # A column-less table can't contribute to the other column-level
            # checks, but we still check FKs and PKs below.

        # --- Check: empty_type -------------------------------------------
        for col in table.columns:
            if not col.data_type or not col.data_type.strip():
                issues.append(
                    CompletenessIssue(
                        table=tname,
                        kind="empty_type",
                        detail=(
                            f"Column '{tname}.{col.name}' has an empty data_type; "
                            "schema introspection may have missed the type."
                        ),
                    )
                )

        # --- Check: fk_target_missing ------------------------------------
        for fk in table.foreign_keys:
            ref = fk.references_table

            # Support schema-qualified references: "public.users" → "users".
            bare_ref = ref.split(".")[-1] if "." in ref else ref

            if bare_ref.lower() not in table_names_lower:
                issues.append(
                    CompletenessIssue(
                        table=tname,
                        kind="fk_target_missing",
                        detail=(
                            f"FK '{tname}.{fk.column}' references '{ref}' "
                            "which is not present in the captured schema."
                        ),
                    )
                )

        # --- Check: no_pk ------------------------------------------------
        # Views and materialised views have no PK by definition — skip them.
        if table.object_kind not in ("view", "matview"):
            has_pk = any(col.is_primary_key for col in table.columns)
            if not has_pk:
                issues.append(
                    CompletenessIssue(
                        table=tname,
                        kind="no_pk",
                        detail=(
                            f"Table '{tname}' has no primary-key column; "
                            "either the connector did not capture it or the table truly has no PK."
                        ),
                    )
                )

    return issues
