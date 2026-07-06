"""Code-database synchronization pipeline — 6-step orchestrator.

Runs AFTER both code indexing and DB indexing are complete.
Cross-references code-level knowledge (entities, table usage, enums,
service functions) with DB-level knowledge (schema, sample data, column
types) to produce per-table sync notes the query agent uses to avoid
data-interpretation errors.
"""

from __future__ import annotations

import json
import logging

from app.config import settings
from app.core.heartbeat import heartbeat
from app.core.workflow_tracker import WorkflowTracker
from app.core.workflow_tracker import tracker as default_tracker
from app.knowledge.code_db_sync_analyzer import (
    CodeDbSyncAnalyzer,
    SyncSummaryResult,
    TableSyncAnalysis,
)
from app.knowledge.custom_rules import CustomRulesEngine
from app.knowledge.entity_extractor import EntityInfo, ProjectKnowledge, TableUsage
from app.llm.router import LLMRouter
from app.models.base import async_session_factory
from app.models.db_index import DbIndex
from app.services.code_db_sync_service import CodeDbSyncService
from app.services.db_index_service import DbIndexService
from app.services.project_cache_service import ProjectCacheService

logger = logging.getLogger(__name__)

BATCH_SIZE = settings.db_index_batch_size


class CodeDbSyncPipeline:
    """Orchestrates the 6-step code-database synchronization."""

    def __init__(
        self,
        llm_router: LLMRouter | None = None,
        workflow_tracker: WorkflowTracker | None = None,
    ) -> None:
        self._llm = llm_router or LLMRouter()
        self._tracker = workflow_tracker or default_tracker
        self._analyzer = CodeDbSyncAnalyzer(self._llm)
        self._sync_svc = CodeDbSyncService()
        self._db_index_svc = DbIndexService()
        self._cache_svc = ProjectCacheService()
        self._rules_engine = CustomRulesEngine()

    async def run(
        self,
        connection_id: str,
        project_id: str,
        *,
        preferred_provider: str | None = None,
        model: str | None = None,
        wf_id: str | None = None,
    ) -> dict:
        """Run the full sync pipeline. Returns status dict."""
        wf_id = wf_id or await self._tracker.begin(
            "code_db_sync",
            {"connection_id": connection_id, "project_id": project_id},
        )

        async def _hb() -> None:
            async with async_session_factory() as s:
                await self._sync_svc.touch_heartbeat(s, connection_id)
                await s.commit()

        async with heartbeat(_hb, interval_seconds=settings.heartbeat_interval_seconds):
            try:
                # H5: owner budget pre-flight + per-run usage sink.
                # Must run INSIDE the heartbeat CM so crashes here don't break the
                # heartbeat contract.
                from app.services.sync_budget import build_sink, preflight_owner_budget

                if settings.sync_budget_enforcement_enabled:
                    async with async_session_factory() as s:
                        ok, reason, owner_id = await preflight_owner_budget(s, project_id)
                    if not ok:
                        async with async_session_factory() as s:
                            await self._sync_svc.set_sync_status(s, connection_id, "failed")
                            await s.commit()
                        await self._tracker.end(wf_id, "code_db_sync", "failed", reason or "budget")
                        return {
                            "status": "failed",
                            "error": reason,
                            "budget_blocked": True,
                            "workflow_id": wf_id,
                        }
                    if owner_id:
                        self._llm = LLMRouter(usage_sink=build_sink(owner_id, project_id))
                        self._analyzer = CodeDbSyncAnalyzer(self._llm)

                # H6: per-connection opt-out + global scrub flag.
                # Must run INSIDE the heartbeat CM so conn-load errors don't crash before
                # the heartbeat opens.
                async with async_session_factory() as s:
                    from app.models.connection import Connection

                    conn = await s.get(Connection, connection_id)
                    send = getattr(conn, "send_sample_data_to_llm", True) if conn else True
                scrub = settings.sync_pii_scrubbing_enabled
                omit_samples = not send

                # Mark as running
                async with async_session_factory() as session:
                    await self._sync_svc.set_sync_status(session, connection_id, "running")
                    await session.commit()

                # Step 1: Load code knowledge
                knowledge: ProjectKnowledge | None = None
                async with self._tracker.step(
                    wf_id,
                    "load_code_knowledge",
                    "Loading code knowledge",
                ):
                    knowledge = await self._load_code_knowledge(project_id)

                if not knowledge:
                    logger.warning(
                        "CODE_DB_SYNC aborted: no code knowledge for project=%s",
                        project_id[:8],
                    )
                    await self._tracker.end(
                        wf_id, "code_db_sync", "failed", "No code knowledge available"
                    )
                    async with async_session_factory() as session:
                        await self._sync_svc.set_sync_status(session, connection_id, "failed")
                        await session.commit()
                    return {
                        "status": "failed",
                        "error": "No code knowledge — index repository first",
                    }
                await self._tracker.emit(
                    wf_id,
                    "load_code_knowledge",
                    "started",
                    f"Loaded {len(knowledge.entities)} entities, "
                    f"{len(knowledge.table_usage)} table usages, "
                    f"{len(knowledge.enums)} enums",
                )

                # Step 2: Load DB index
                db_entries: list[DbIndex] = []
                async with self._tracker.step(
                    wf_id,
                    "load_db_index",
                    "Loading database index",
                ):
                    async with async_session_factory() as session:
                        db_entries = await self._db_index_svc.get_index(session, connection_id)

                if not db_entries:
                    logger.warning(
                        "CODE_DB_SYNC aborted: no DB index for connection=%s",
                        connection_id[:8],
                    )
                    await self._tracker.end(
                        wf_id, "code_db_sync", "failed", "No DB index available"
                    )
                    async with async_session_factory() as session:
                        await self._sync_svc.set_sync_status(session, connection_id, "failed")
                        await session.commit()
                    return {"status": "failed", "error": "No DB index — index database first"}
                await self._tracker.emit(
                    wf_id,
                    "load_db_index",
                    "started",
                    f"Loaded {len(db_entries)} DB index entries",
                )

                # Load custom rules for enriched context
                rules_context = await self._load_rules_context(project_id)

                # Step 3: Match tables
                matched_tables: list[_MatchedTable] = []
                async with self._tracker.step(
                    wf_id,
                    "match_tables",
                    f"Matching {len(db_entries)} DB tables with code entities",
                ):
                    matched_tables = self._match_tables(
                        knowledge,
                        db_entries,
                        rules_context,
                        scrub=scrub,
                        omit_samples=omit_samples,
                    )

                code_info_count = sum(1 for m in matched_tables if m.has_code_info)
                db_only_match = len(matched_tables) - code_info_count
                await self._tracker.emit(
                    wf_id,
                    "match_tables",
                    "started",
                    f"Matched {len(matched_tables)} tables "
                    f"({code_info_count} with code info, {db_only_match} DB-only)",
                )

                # Step 4: LLM analysis per table
                analyses: list[TableSyncAnalysis] = []
                async with self._tracker.step(
                    wf_id,
                    "analyze_sync",
                    f"Analyzing {len(matched_tables)} tables via LLM",
                ):
                    large_tables = [m for m in matched_tables if m.has_code_info]
                    small_tables = [m for m in matched_tables if not m.has_code_info]

                    await self._tracker.emit(
                        wf_id,
                        "analyze_sync",
                        "started",
                        f"Analyzing {len(large_tables)} tables individually, "
                        f"{len(small_tables)} in batches of {BATCH_SIZE}",
                    )

                    # T16: analyse large tables and small-table batches
                    # concurrently. Each ``analyze_table`` / ``analyze_table_batch``
                    # call is independent (different tables, different LLM
                    # requests). Gathering turns an O(N) wait into a single
                    # batched wait bounded by the slowest call.
                    import asyncio as _asyncio

                    async def _one_large(mt):
                        return await self._analyzer.analyze_table(
                            table_name=mt.table_name,
                            db_context=mt.db_context,
                            code_context=mt.code_context,
                            preferred_provider=preferred_provider,
                            model=model,
                        )

                    total_small_batches = (
                        (len(small_tables) + BATCH_SIZE - 1) // BATCH_SIZE if small_tables else 0
                    )

                    small_batch_specs: list[list] = []
                    for batch_start in range(0, len(small_tables), BATCH_SIZE):
                        batch = small_tables[batch_start : batch_start + BATCH_SIZE]
                        small_batch_specs.append(batch)

                    async def _one_small_batch(batch_list):
                        batch_items = [
                            (m.table_name, m.db_context, m.code_context) for m in batch_list
                        ]
                        return await self._analyzer.analyze_table_batch(
                            tables=batch_items,
                            preferred_provider=preferred_provider,
                            model=model,
                        )

                    large_task = _asyncio.gather(*(_one_large(mt) for mt in large_tables))
                    small_task = _asyncio.gather(*(_one_small_batch(b) for b in small_batch_specs))
                    large_results, small_results = await _asyncio.gather(large_task, small_task)

                    large_pairs = zip(large_tables, large_results, strict=False)
                    for i, (mt, analysis) in enumerate(large_pairs, 1):
                        analyses.append(analysis)
                        await self._tracker.emit(
                            wf_id,
                            "analyze_sync",
                            "started",
                            f"[{i}/{len(large_tables)}] {mt.table_name} -> "
                            f"{analysis.sync_status} (confidence={analysis.confidence_score})",
                        )
                    for batch_idx, (batch, batch_results) in enumerate(
                        zip(small_batch_specs, small_results, strict=False), 1
                    ):
                        analyses.extend(batch_results)
                        batch_names = ", ".join(m.table_name for m in batch)
                        await self._tracker.emit(
                            wf_id,
                            "analyze_sync",
                            "started",
                            f"Batch {batch_idx}/{total_small_batches} done "
                            f"({len(batch)} tables): {batch_names}",
                        )

                # H4: all-fallback guard — abort if LLM was degraded.
                total_analyses = len(analyses)
                non_fallback = sum(1 for a in analyses if not a.is_fallback)
                if (
                    total_analyses
                    and (non_fallback / total_analyses) < settings.sync_min_success_ratio_to_persist
                ):
                    logger.warning(
                        "CODE_DB_SYNC kept previous rows: only %d/%d tables analyzed",
                        non_fallback,
                        total_analyses,
                    )
                    async with async_session_factory() as session:
                        await self._sync_svc.set_sync_status(session, connection_id, "failed")
                        await session.commit()
                    await self._tracker.end(
                        wf_id,
                        "code_db_sync",
                        "failed",
                        f"LLM degraded: {non_fallback}/{total_analyses} analyzed; "
                        "kept previous sync",
                    )
                    return {
                        "status": "failed",
                        "error": "llm_degraded_kept_previous",
                        "workflow_id": wf_id,
                    }

                # Step 5: Store results
                async with self._tracker.step(
                    wf_id,
                    "store_sync",
                    "Persisting sync results",
                ):
                    async with async_session_factory() as session:
                        all_table_names = {m.table_name for m in matched_tables}
                        deleted = await self._sync_svc.delete_stale_tables(
                            session, connection_id, all_table_names
                        )
                        if deleted:
                            await self._tracker.emit(
                                wf_id,
                                "store_sync",
                                "started",
                                f"Removed {deleted} stale sync entries",
                            )

                        mt_lookup = {m.table_name: m for m in matched_tables}
                        for analysis in analyses:
                            mt = mt_lookup.get(analysis.table_name)  # type: ignore[assignment]
                            if mt is None:
                                logger.warning(
                                    "store_sync: no matched table for %s — skipped",
                                    analysis.table_name,
                                )
                                continue

                            # SYNC-L5: apply deterministic sync_status override.
                            # The column_mismatch_json on the _MatchedTable was
                            # computed in _make_matched from code entity columns vs
                            # DB column_notes_json keys — no LLM involved.
                            # Override the LLM sync_status only when BOTH sides
                            # are known (non-empty column sets), so we never flip
                            # "code_only" or "db_only" tables to "mismatch" when
                            # one side has no column information.
                            effective_status = analysis.sync_status
                            try:
                                drift = json.loads(mt.column_mismatch_json)
                                has_code_cols = bool(drift.get("code_only") or drift.get("matched"))
                                has_db_cols = bool(drift.get("db_only") or drift.get("matched"))
                                if has_code_cols and has_db_cols:
                                    if drift["code_only"] or drift["db_only"]:
                                        effective_status = "mismatch"
                                    else:
                                        effective_status = "matched"
                                    if effective_status != analysis.sync_status:
                                        logger.debug(
                                            "SYNC-L5 override: %s LLM=%s → det=%s "
                                            "(code_only=%s db_only=%s)",
                                            analysis.table_name,
                                            analysis.sync_status,
                                            effective_status,
                                            drift["code_only"],
                                            drift["db_only"],
                                        )
                            except (json.JSONDecodeError, KeyError, TypeError):
                                pass  # leave LLM opinion intact on parse error

                            sync_data = {
                                "table_name": analysis.table_name,
                                "entity_name": mt.entity_name,
                                "entity_file_path": mt.entity_file_path,
                                "code_columns_json": mt.code_columns_json,
                                "column_mismatch_json": mt.column_mismatch_json,
                                "used_in_files_json": mt.used_in_files_json,
                                "read_count": mt.read_count,
                                "write_count": mt.write_count,
                                "data_format_notes": analysis.data_format_notes,
                                "column_sync_notes_json": analysis.column_sync_notes_json,
                                "business_logic_notes": analysis.business_logic_notes,
                                "conversion_warnings": analysis.conversion_warnings,
                                "query_recommendations": analysis.query_recommendations,
                                "required_filters_json": analysis.required_filters_json,
                                "column_value_mappings_json": analysis.column_value_mappings_json,
                                "sync_status": effective_status,
                                "confidence_score": analysis.confidence_score,
                            }
                            await self._sync_svc.upsert_table_sync(
                                session, connection_id, sync_data
                            )

                        await self._tracker.emit(
                            wf_id,
                            "store_sync",
                            "started",
                            f"Stored {len(analyses)} sync entries",
                        )
                        await session.commit()

                # Step 6: Generate summary
                synced_count = sum(1 for a in analyses if a.sync_status == "matched")
                code_only_count = sum(1 for a in analyses if a.sync_status == "code_only")
                db_only_count = sum(1 for a in analyses if a.sync_status == "db_only")
                mismatch_count = sum(1 for a in analyses if a.sync_status == "mismatch")

                async with self._tracker.step(
                    wf_id,
                    "generate_sync_summary",
                    "Generating sync summary",
                ):
                    await self._tracker.emit(
                        wf_id,
                        "generate_sync_summary",
                        "started",
                        f"Stats: {synced_count} matched, {code_only_count} code-only, "
                        f"{db_only_count} DB-only, {mismatch_count} mismatch",
                    )
                    project_ctx = self._build_project_context(knowledge)
                    fk_ctx = self._build_fk_context(knowledge, db_entries)
                    await self._tracker.emit(
                        wf_id,
                        "generate_sync_summary",
                        "started",
                        "Generating LLM summary with FK relationships",
                    )
                    sink = getattr(self._llm, "_sink", None)
                    if sink is not None and sink.budget_exceeded():
                        summary_result = SyncSummaryResult()  # skip LLM summary
                    else:
                        summary_result = await self._analyzer.generate_summary(
                            analyses=analyses,
                            project_context=project_ctx,
                            fk_relationships=fk_ctx,
                            preferred_provider=preferred_provider,
                            model=model,
                        )

                    async with async_session_factory() as session:
                        await self._sync_svc.upsert_summary(
                            session,
                            connection_id,
                            {
                                "total_tables": len(matched_tables),
                                "synced_tables": synced_count,
                                "code_only_tables": code_only_count,
                                "db_only_tables": db_only_count,
                                "mismatch_tables": mismatch_count,
                                "global_notes": summary_result.global_notes,
                                "data_conventions": summary_result.data_conventions,
                                "query_guidelines": summary_result.query_guidelines,
                                "join_recommendations": summary_result.join_recommendations,
                                "sync_status": "completed",
                            },
                        )
                        await session.commit()

                await self._tracker.end(
                    wf_id,
                    "code_db_sync",
                    "completed",
                    f"{len(matched_tables)} tables synced ({synced_count} matched)",
                )

                return {
                    "status": "completed",
                    "total_tables": len(matched_tables),
                    "synced": synced_count,
                    "code_only": code_only_count,
                    "db_only": db_only_count,
                    "mismatch": mismatch_count,
                    "workflow_id": wf_id,
                }

            except Exception as exc:
                logger.exception("Code-DB sync pipeline failed")
                await self._tracker.end(wf_id, "code_db_sync", "failed", str(exc))
                try:
                    async with async_session_factory() as session:
                        await self._sync_svc.set_sync_status(session, connection_id, "failed")
                        await session.commit()
                except Exception:
                    logger.warning("Failed to set sync status to failed", exc_info=True)
                return {"status": "failed", "error": str(exc), "workflow_id": wf_id}

    # ------------------------------------------------------------------
    # Context helpers
    # ------------------------------------------------------------------

    async def _load_code_knowledge(self, project_id: str) -> ProjectKnowledge | None:
        try:
            async with async_session_factory() as session:
                return await self._cache_svc.load_knowledge(session, project_id)
        except Exception:
            logger.warning(
                "Failed to load code knowledge for project=%s",
                project_id[:8],
                exc_info=True,
            )
            return None

    async def _load_rules_context(self, project_id: str) -> str:
        try:
            file_rules = self._rules_engine.load_rules(project_rules_dir=f"./rules/{project_id}")
            db_rules = await self._rules_engine.load_db_rules(project_id=project_id)
            return self._rules_engine.rules_to_context(file_rules + db_rules)
        except Exception:
            logger.debug("Failed to load rules for sync pipeline", exc_info=True)
            return ""

    def _match_tables(
        self,
        knowledge: ProjectKnowledge,
        db_entries: list[DbIndex],
        rules_context: str = "",
        *,
        scrub: bool = True,
        omit_samples: bool = False,
    ) -> list[_MatchedTable]:
        """Cross-reference code entities/table_usage with DB index entries.

        Matching strategy (SYNC-L6):
        - When a code entity carries a schema-qualified ``table_name``
          (``"analytics.orders"``), it is matched against the exact
          ``(schema, bare_name)`` DB key — no cross-schema contamination.
        - When the code entity is unqualified (``"orders"``), it falls back to
          bare-name match so existing single-schema setups are unaffected.
        - If a qualified code entity's schema isn't found in the DB, it falls
          back to bare-name match and the existing ambiguity NOTE is added.
        """
        from collections import Counter

        results: list[_MatchedTable] = []
        db_by_key: dict[tuple[str, str], DbIndex] = {}
        bare_counts: Counter = Counter()
        for e in db_entries:
            sch = (getattr(e, "table_schema", None) or "public").lower()
            nm = e.table_name.lower()
            db_by_key[(sch, nm)] = e
            bare_counts[nm] += 1

        def _display_name(e: DbIndex) -> str:
            if bare_counts[e.table_name.lower()] > 1:
                return f"{getattr(e, 'table_schema', 'public') or 'public'}.{e.table_name}"
            return e.table_name

        # Build two separate entity indexes:
        # 1. qualified: keyed by (schema, bare_name) — only for schema-qualified table_names.
        # 2. bare: keyed by bare_name — only for unqualified table_names (back-compat).
        # A qualified code entity must NOT fall into the bare index so that it cannot
        # accidentally match a same-bare-name table in a different schema.
        entity_by_qualified: dict[tuple[str, str], EntityInfo] = {}
        entity_by_bare: dict[str, EntityInfo] = {}
        code_table_names: set[str] = set()
        for _, entity in knowledge.entities.items():
            if not entity.table_name:
                continue
            raw = entity.table_name.lower()
            if "." in raw:
                parts = raw.split(".", 1)
                entity_by_qualified[(parts[0], parts[1])] = entity
            else:
                entity_by_bare[raw] = entity
            code_table_names.add(raw)
        for tbl_name in knowledge.table_usage:
            code_table_names.add(tbl_name.lower())

        # Track which (schema, bare) qualified keys have been consumed by a DB match
        # so we don't emit them again in the code-only tail.
        consumed_qualified: set[tuple[str, str]] = set()

        # DB-side first (schema-qualified), then code-only tables with no DB row.
        seen_bare: set[str] = set()
        for (sch, nm), db_entry in sorted(db_by_key.items()):
            seen_bare.add(nm)

            # Prefer exact (schema, bare) match for qualified code entities; fall
            # back to bare-name match for unqualified ones or on qualified miss.
            _qe = entity_by_qualified.get((sch, nm))
            matched_entity: EntityInfo | None
            if _qe is not None:
                matched_entity = _qe
                consumed_qualified.add((sch, nm))
                # Exact schema match — suppress ambiguity NOTE for this row.
                qualified_hit = True
            else:
                matched_entity = entity_by_bare.get(nm)
                qualified_hit = False

            usage = knowledge.table_usage.get(nm) or knowledge.table_usage.get(
                next((k for k in knowledge.table_usage if k.lower() == nm), "")
            )
            ambiguous = bare_counts[nm] > 1
            display = _display_name(db_entry)
            code_context = self._build_code_context(
                matched_entity, usage, knowledge, nm, rules_context
            )
            if ambiguous and not qualified_hit:
                code_context = (
                    f"(NOTE: table name '{nm}' exists in multiple schemas; matched code by "
                    f"bare name — verify schema '{sch}')\n" + code_context
                )
            results.append(
                self._make_matched(
                    display,
                    self._build_db_context(db_entry, scrub=scrub, omit_samples=omit_samples),
                    code_context,
                    matched_entity,
                    usage,
                    knowledge,
                )
            )

        # Code-only tables: entities/table_usage with no matching DB row.
        # Exclude qualified names that were already consumed by a DB match above.
        # Also exclude bare names already seen from the DB-side loop.
        remaining_code: set[str] = set()
        for raw in code_table_names:
            if "." in raw:
                parts = raw.split(".", 1)
                if (parts[0], parts[1]) not in consumed_qualified:
                    remaining_code.add(raw)
            elif raw not in seen_bare:
                remaining_code.add(raw)

        for nm in sorted(remaining_code):
            # For the code-only tail, resolve the entity from the appropriate index.
            tail_entity: EntityInfo | None
            if "." in nm:
                parts = nm.split(".", 1)
                tail_entity = entity_by_qualified.get((parts[0], parts[1]))
            else:
                tail_entity = entity_by_bare.get(nm)
            usage = knowledge.table_usage.get(nm) or knowledge.table_usage.get(
                next((k for k in knowledge.table_usage if k.lower() == nm), "")
            )
            code_context = self._build_code_context(
                tail_entity, usage, knowledge, nm, rules_context
            )
            results.append(self._make_matched(nm, "", code_context, tail_entity, usage, knowledge))
        return results

    @staticmethod
    def _compute_column_drift(code_cols: set[str], db_cols: set[str]) -> dict:
        """Deterministic set-diff between code columns and DB columns.

        Both inputs are case-normalised (lower-cased) before diffing so that
        ``Id`` and ``id`` are treated as the same column.  An empty side means
        the information is unknown — the diff is returned as-is (e.g. all cols
        on the non-empty side appear in the appropriate ``code_only`` or
        ``db_only`` list) but the caller is expected NOT to override the LLM
        ``sync_status`` when one side is empty.

        Returns a dict with three sorted lists::

            {"code_only": sorted(code_cols - db_cols),
             "db_only": sorted(db_cols - code_cols),
             "matched": sorted(code_cols & db_cols)}
        """
        norm_code = {c.lower() for c in code_cols}
        norm_db = {c.lower() for c in db_cols}
        return {
            "code_only": sorted(norm_code - norm_db),
            "db_only": sorted(norm_db - norm_code),
            "matched": sorted(norm_code & norm_db),
        }

    @staticmethod
    def _build_db_context(entry: DbIndex, *, scrub: bool = True, omit_samples: bool = False) -> str:
        from app.knowledge import pii_scrubber

        parts: list[str] = []
        if entry.business_description:
            parts.append(f"Description: {entry.business_description}")
        if entry.row_count is not None:
            parts.append(f"Rows: ~{entry.row_count:,}")
        if entry.column_count:
            parts.append(f"Column count: {entry.column_count}")
        if entry.data_patterns:
            parts.append(f"Data patterns: {entry.data_patterns}")
        if entry.query_hints:
            parts.append(f"Query hints: {entry.query_hints}")
        if entry.column_notes_json and entry.column_notes_json != "{}":
            try:
                notes = json.loads(entry.column_notes_json)
                if notes:
                    parts.append("Column notes:")
                    for col, note in notes.items():
                        parts.append(f"  {col}: {note}")
            except (json.JSONDecodeError, TypeError):
                pass
        if not omit_samples:
            dv_json = getattr(entry, "column_distinct_values_json", None) or "{}"
            if dv_json and dv_json != "{}":
                try:
                    distinct = json.loads(dv_json)
                    if distinct:
                        parts.append("Actual distinct values in DB:")
                        for col, vals in distinct.items():
                            shown = pii_scrubber.scrub_distinct_values(
                                col, vals[:15], enabled=scrub
                            )
                            vals_str = " | ".join(str(v) for v in shown)
                            more = f" (+{len(vals) - 15} more)" if len(vals) > 15 else ""
                            parts.append(f"  {col}: [{vals_str}]{more}")
                except (json.JSONDecodeError, TypeError):
                    pass
            if entry.sample_data_json and entry.sample_data_json != "[]":
                sample = pii_scrubber.scrub_sample_json(entry.sample_data_json, enabled=scrub)
                suffix = "…[truncated]" if len(sample) > 800 else ""
                parts.append(f"Sample data: {sample[:800]}{suffix}")
        return "\n".join(parts)

    @staticmethod
    def _make_matched(
        table_name: str,
        db_context: str,
        code_context: str,
        entity: EntityInfo | None,
        usage: TableUsage | None,
        knowledge: ProjectKnowledge,
    ) -> _MatchedTable:
        has_code = bool(entity or (usage and usage.is_active))
        mt = _MatchedTable(
            table_name=table_name,
            db_context=db_context,
            code_context=code_context,
            has_code_info=has_code,
            entity_name=entity.name if entity else None,
            entity_file_path=entity.file_path if entity else None,
            read_count=len(usage.readers) if usage else 0,
            write_count=len(usage.writers) if usage else 0,
        )
        if entity and entity.columns:
            mt.code_columns_json = json.dumps(
                [
                    {"name": c.name, "type": c.col_type, "fk_target": c.fk_target}
                    for c in entity.columns
                ]
            )

        # --- SYNC-L5: deterministic column set-diff ----------------------------
        # Extract code column names from entity.columns (already in memory).
        # Extract DB column names from the rendered db_context "Column notes:" block
        # (produced by _build_db_context from column_notes_json keys).
        # Both sets are available at this point without any LLM call.
        import re as _re

        code_col_names: set[str] = set()
        if entity and entity.columns:
            code_col_names = {c.name for c in entity.columns}

        db_col_names: set[str] = set()
        if db_context:
            col_note_re = _re.compile(r"^\s{2}(\w+):\s")
            in_col_notes = False
            for line in db_context.splitlines():
                if line.strip() == "Column notes:":
                    in_col_notes = True
                    continue
                if in_col_notes:
                    m = col_note_re.match(line)
                    if m:
                        db_col_names.add(m.group(1))
                    elif line and not line.startswith("  "):
                        in_col_notes = False

        drift = CodeDbSyncPipeline._compute_column_drift(code_col_names, db_col_names)
        mt.column_mismatch_json = json.dumps(drift)
        # -----------------------------------------------------------------------

        if usage:
            all_files = list(set(usage.readers + usage.writers + usage.orm_refs))
            mt.used_in_files_json = json.dumps(all_files[:20])
        return mt

    @staticmethod
    def _build_code_context(
        entity: EntityInfo | None,
        usage: TableUsage | None,
        knowledge: ProjectKnowledge,
        table_lower: str,
        rules_context: str = "",
    ) -> str:
        parts: list[str] = []

        if entity:
            parts.append(f"ORM Model: {entity.name}")
            if entity.file_path:
                parts.append(f"Defined in: {entity.file_path}")
            if entity.columns:
                parts.append("Columns from code:")
                for col in entity.columns:
                    extras = []
                    if col.is_pk:
                        extras.append("PK")
                    if col.is_fk:
                        extras.append(f"FK -> {col.fk_target}")
                    if col.enum_values:
                        extras.append(f"enum: {', '.join(col.enum_values[:8])}")
                    if col.default:
                        extras.append(f"default: {col.default}")
                    extra_str = f" [{', '.join(extras)}]" if extras else ""
                    parts.append(f"  - {col.name}: {col.col_type}{extra_str}")
            if entity.relationships:
                parts.append(f"Relationships: {', '.join(entity.relationships)}")

        if usage:
            if usage.readers:
                parts.append(f"Read by: {', '.join(usage.readers[:10])}")
            if usage.writers:
                parts.append(f"Written by: {', '.join(usage.writers[:10])}")

        # M5 graph-derived lineage: HTTP routes / services / CLI / migrations
        # that ultimately call into this entity. We surface the top callers
        # for the LLM to reason about ``required_filters`` and conversion
        # warnings without forcing it to grep for usages itself.
        if entity and entity.graph_callers:
            grouped: dict[str, list[dict]] = {}
            for ref in entity.graph_callers[:15]:
                grouped.setdefault(ref.get("endpoint_kind", "unknown"), []).append(ref)
            for kind in ("http", "cli", "service", "migration", "unknown"):
                refs = grouped.get(kind)
                if not refs:
                    continue
                parts.append(f"Code callers ({kind}):")
                for r in refs[:5]:
                    op = r.get("op_kind", "unknown")
                    conf = float(r.get("confidence", 0.0))
                    name = r.get("caller_name", "?")
                    file_ = r.get("caller_file", "?")
                    parts.append(f"  - {name} ({op}, conf={conf:.2f}, heuristic) in {file_}")

        # L13: use a word-boundary check so that a table name "order" does not
        # spuriously match an enum named "reorder_reason".  We split the enum
        # name on non-word characters (underscores act as boundaries in Python's
        # \b only between \w and \W, so we tokenise explicitly).
        _enum_tokens_re = __import__("re").compile(r"[^a-z0-9]+")
        relevant_enums = [
            e
            for e in knowledge.enums
            if table_lower in _enum_tokens_re.split(e.name.lower())
            or any(table_lower in v.lower() for v in e.values[:5])
        ]
        if relevant_enums:
            parts.append("Related enums:")
            for en in relevant_enums[:5]:
                parts.append(f"  {en.name}: {', '.join(en.values[:8])}")

        relevant_services = [
            sf
            for sf in knowledge.service_functions
            if table_lower in json.dumps(sf.get("tables", [])).lower()
        ]
        if relevant_services:
            parts.append("Service functions:")
            for sf in relevant_services[:5]:
                snippet = sf.get("snippet", "")
                if snippet:
                    parts.append(f"  {sf['name']} in {sf['file_path']}:")
                    parts.append(f"    {snippet[:300]}")
                else:
                    parts.append(f"  {sf['name']} in {sf['file_path']}")

        relevant_rules = [
            vr
            for vr in knowledge.validation_rules
            if table_lower in vr.model_name.lower() or table_lower in vr.expression.lower()
        ]
        if relevant_rules:
            parts.append("Validation rules:")
            for vr in relevant_rules[:5]:
                parts.append(f"  [{vr.rule_type}] {vr.expression[:100]}")

        relevant_patterns = [
            qp
            for qp in knowledge.query_patterns
            if qp.table.lower() == table_lower or table_lower in qp.table.lower()
        ]
        if relevant_patterns:
            parts.append("Query patterns used in code:")
            seen = set()
            for qp in relevant_patterns[:10]:
                key = f"{qp.table}.{qp.column} {qp.operator} {qp.value}"
                if key not in seen:
                    seen.add(key)
                    parts.append(
                        f"  WHERE {qp.column} {qp.operator} {qp.value} (in {qp.file_path})"
                    )

        relevant_constants = [
            cm
            for cm in knowledge.constant_mappings
            if table_lower in cm.name.lower() or table_lower in cm.context.lower()
        ]
        if relevant_constants:
            parts.append("Constants/status mappings:")
            for cm in relevant_constants[:10]:
                parts.append(f"  {cm.name} = {cm.value} ({cm.file_path})")

        relevant_scopes = [
            sf
            for sf in knowledge.scope_filters
            if sf.table.lower() == table_lower or table_lower in sf.table.lower()
        ]
        if relevant_scopes:
            parts.append("Default scopes/filters:")
            for scope in relevant_scopes[:5]:
                parts.append(f"  {scope.name}: {scope.filter_expression[:200]} ({scope.file_path})")

        if rules_context:
            table_rules = [
                line for line in rules_context.split("\n") if table_lower in line.lower()
            ]
            if table_rules:
                parts.append("Custom project rules:")
                for line in table_rules[:5]:
                    parts.append(f"  {line.strip()[:200]}")

        return "\n".join(parts)

    @staticmethod
    def _build_fk_context(
        knowledge: ProjectKnowledge,
        db_entries: list[DbIndex],
    ) -> str:
        """Build a compact FK relationship list from code entities."""
        fk_lines: list[str] = []
        for _name, entity in knowledge.entities.items():
            if not entity.columns:
                continue
            for col in entity.columns:
                if col.is_fk and col.fk_target:
                    src_table = entity.table_name or _name
                    fk_lines.append(f"  {src_table}.{col.name} -> {col.fk_target}")
        usage_overlap: dict[str, set[str]] = {}
        for tbl_name, usage in knowledge.table_usage.items():
            files = set(usage.readers + usage.writers)
            for f in files:
                usage_overlap.setdefault(f, set()).add(tbl_name)
        co_used: list[str] = []
        for _file, tables in usage_overlap.items():
            if len(tables) >= 2:
                co_used.append(", ".join(sorted(tables)[:4]))
        fk_text = "\n".join(fk_lines[:30]) if fk_lines else "None found"
        parts = [f"FK relationships:\n{fk_text}"]
        if co_used:
            unique_groups = list(set(co_used))[:10]
            parts.append(
                "Tables commonly used together in code:\n"
                + "\n".join(f"  {g}" for g in unique_groups)
            )
        return "\n".join(parts)

    @staticmethod
    def _build_project_context(knowledge: ProjectKnowledge) -> str:
        parts: list[str] = []
        parts.append(f"Entities: {len(knowledge.entities)}")
        parts.append(f"Tables tracked: {len(knowledge.table_usage)}")
        parts.append(f"Enums: {len(knowledge.enums)}")
        parts.append(f"Service functions: {len(knowledge.service_functions)}")
        parts.append(f"Validation rules: {len(knowledge.validation_rules)}")
        if knowledge.dead_tables:
            parts.append(f"Dead/unused tables: {', '.join(knowledge.dead_tables[:10])}")
        return "\n".join(parts)


class _MatchedTable:
    """Internal struct for a table matched between code and DB."""

    __slots__ = (
        "table_name",
        "db_context",
        "code_context",
        "has_code_info",
        "entity_name",
        "entity_file_path",
        "code_columns_json",
        "column_mismatch_json",
        "used_in_files_json",
        "read_count",
        "write_count",
    )

    def __init__(
        self,
        table_name: str,
        db_context: str = "",
        code_context: str = "",
        has_code_info: bool = False,
        entity_name: str | None = None,
        entity_file_path: str | None = None,
        code_columns_json: str = "[]",
        column_mismatch_json: str = "{}",
        used_in_files_json: str = "[]",
        read_count: int = 0,
        write_count: int = 0,
    ) -> None:
        self.table_name = table_name
        self.db_context = db_context
        self.code_context = code_context
        self.has_code_info = has_code_info
        self.entity_name = entity_name
        self.entity_file_path = entity_file_path
        self.code_columns_json = code_columns_json
        self.column_mismatch_json = column_mismatch_json
        self.used_in_files_json = used_in_files_json
        self.read_count = read_count
        self.write_count = write_count
