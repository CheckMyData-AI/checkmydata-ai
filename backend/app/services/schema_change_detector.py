"""SchemaChangeDetector — proactive schema-drift alerts (Phase 5).

When a DB re-index runs, the pipeline already computes the new schema
fingerprint (``SchemaInfo.fingerprint()``) and loads the previously persisted
one. This service turns that diff into a **proactive insight**: instead of the
user discovering a dropped column when a query breaks, the system surfaces a
``schema_change`` insight the moment drift is detected, with a concrete
recommended action (re-enrich the affected tables).

Design:

* **Pure diff, no I/O for the comparison** — :func:`diff_fingerprints` works on
  the ``{qualified_table: signature}`` maps the pipeline already has, so it is
  trivially testable and reusable.
* **Graceful** — alert emission is best-effort; a failure to store an insight
  never breaks indexing (vision invariant #5).
* **Trust-aware** — the emitted insight's confidence/severity reflects the
  nature of the change (removals are higher-severity than additions).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SchemaDiff:
    """Result of comparing two schema fingerprints."""

    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return bool(self.added or self.removed or self.changed)

    @property
    def affected(self) -> list[str]:
        """Tables that exist now and need re-enrichment (added + changed)."""
        return sorted({*self.added, *self.changed})

    def severity(self) -> str:
        """Removals are the dangerous case (queries/lineage break)."""
        if self.removed:
            return "warning"
        if self.changed:
            return "info"
        return "positive"

    def summary(self) -> str:
        parts: list[str] = []
        if self.added:
            parts.append(f"{len(self.added)} added")
        if self.removed:
            parts.append(f"{len(self.removed)} removed")
        if self.changed:
            parts.append(f"{len(self.changed)} changed")
        return ", ".join(parts) or "no changes"


def diff_fingerprints(
    previous: dict[str, str],
    current: dict[str, str],
) -> SchemaDiff:
    """Compare two ``{qualified_table: column_signature}`` maps.

    Mirrors :meth:`SchemaInfo.diff` but operates on the persisted fingerprint
    dicts the pipeline already holds, so no re-introspection is needed.
    """
    prev_keys = set(previous or {})
    cur_keys = set(current or {})
    added = sorted(cur_keys - prev_keys)
    removed = sorted(prev_keys - cur_keys)
    changed = sorted(t for t in (cur_keys & prev_keys) if previous[t] != current[t])
    return SchemaDiff(added=added, removed=removed, changed=changed)


class SchemaChangeDetector:
    """Detects schema drift and emits a proactive ``schema_change`` insight."""

    # Cap how many table names we list in the human-readable description.
    _MAX_LISTED = 15

    async def detect_and_alert(
        self,
        session: AsyncSession,
        *,
        project_id: str,
        connection_id: str,
        previous_fingerprint: dict[str, str],
        current_fingerprint: dict[str, str],
    ) -> SchemaDiff:
        """Compute the diff and, if anything changed, store an insight.

        Returns the :class:`SchemaDiff` regardless of whether an insight was
        stored (callers may want to act on ``affected`` for re-enrichment).
        A first-time index (empty previous fingerprint) is *not* an alert.
        """
        diff = diff_fingerprints(previous_fingerprint, current_fingerprint)
        if not previous_fingerprint:
            # Baseline run — nothing to compare against.
            return diff
        if not diff.has_changes:
            return diff

        try:
            await self._store_insight(
                session,
                project_id=project_id,
                connection_id=connection_id,
                diff=diff,
            )
            # Bust the per-agent schema cache so the next SQL query
            # re-introspects the changed schema immediately (DBIDX-D12).
            try:
                from app.core.schema_cache_registry import invalidate_connection

                invalidate_connection(connection_id)
            except Exception:
                logger.debug(
                    "schema_change_detector: schema cache invalidation failed for conn=%s",
                    connection_id[:8],
                    exc_info=True,
                )
        except Exception:
            logger.warning(
                "schema_change_detector: failed to store insight for conn=%s",
                connection_id[:8],
                exc_info=True,
            )
        return diff

    async def _store_insight(
        self,
        session: AsyncSession,
        *,
        project_id: str,
        connection_id: str,
        diff: SchemaDiff,
    ) -> None:
        from app.core.insight_memory import InsightMemoryService

        def _fmt(names: list[str]) -> str:
            shown = names[: self._MAX_LISTED]
            extra = len(names) - len(shown)
            tail = f" (+{extra} more)" if extra > 0 else ""
            return ", ".join(shown) + tail

        desc_parts: list[str] = []
        if diff.removed:
            desc_parts.append(f"Removed tables: {_fmt(diff.removed)}.")
        if diff.added:
            desc_parts.append(f"New tables: {_fmt(diff.added)}.")
        if diff.changed:
            desc_parts.append(f"Changed tables: {_fmt(diff.changed)}.")
        description = " ".join(desc_parts)

        if diff.removed:
            action = (
                "Review code/queries referencing the removed tables; re-run "
                "code↔DB sync to refresh lineage."
            )
        elif diff.affected:
            action = (
                "Re-enrich the affected tables (added/changed) so descriptions, "
                "patterns, and query hints reflect the new schema."
            )
        else:
            action = "No action required."

        # Removals reduce confidence in existing lineage; additions are clean.
        confidence = 0.85 if diff.removed else 0.7

        await InsightMemoryService().store_insight(
            session,
            project_id,
            "schema_change",
            f"Schema drift detected ({diff.summary()})",
            description,
            connection_id=connection_id,
            severity=diff.severity(),
            recommended_action=action,
            expected_impact=(
                "Prevents stale schema knowledge from producing wrong SQL or broken lineage."
            ),
            confidence=confidence,
            source_metrics=["schema_fingerprint"],
            trust_sources=["db_index"],
            trust_validation_method="schema_fingerprint_diff",
        )
        logger.info(
            "schema_change_detector: alert stored conn=%s (%s)",
            connection_id[:8],
            diff.summary(),
        )


__all__ = ["SchemaChangeDetector", "SchemaDiff", "diff_fingerprints"]
