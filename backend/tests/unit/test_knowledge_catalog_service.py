"""Tests for the Phase 1 Knowledge Catalog read-facade.

Covers:
- ``Artifact`` / ``ContextPack`` DTO serialization (pure data).
- ``FreshnessWarningDetail`` structured ``recommended_action`` mirroring.
- ``KnowledgeCatalogService`` health + context-pack assembly with mocked stores,
  including graceful degradation when an individual store raises.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.knowledge.context_pack import Artifact, ContextPack
from app.services.knowledge_catalog_service import KnowledgeCatalogService


def _clean_freshness() -> AsyncMock:
    """A patched ``_freshness`` returning a fresh (no-warnings) snapshot dict."""
    return AsyncMock(return_value={"overall_stale": False, "warnings": []})


class TestArtifact:
    def test_to_dict_rounds_confidence(self):
        art = Artifact(
            id="table:c1::public.orders",
            type="table",
            title="orders",
            confidence=0.66667,
        )
        d = art.to_dict()
        assert d["id"] == "table:c1::public.orders"
        assert d["type"] == "table"
        assert d["confidence"] == 0.667
        assert d["provenance"] == {} and d["payload"] == {}


class TestContextPack:
    def test_is_empty_true_for_fresh_pack(self):
        assert ContextPack(project_id="p1").is_empty() is True

    def test_is_empty_false_with_one_artifact(self):
        pack = ContextPack(project_id="p1")
        pack.tables.append(Artifact(id="t1", type="table", title="orders"))
        assert pack.is_empty() is False

    def test_to_dict_shape(self):
        pack = ContextPack(project_id="p1", connection_id="c1", question="how many orders?")
        d = pack.to_dict()
        for key in (
            "project_id",
            "connection_id",
            "question",
            "tables",
            "lineage",
            "learnings",
            "rules",
            "insights",
            "rag_chunks",
            "freshness",
            "sources_used",
            "token_budget",
        ):
            assert key in d


class TestFreshnessRecommendedAction:
    def test_to_dict_emits_structured_actions(self):
        """The serialized freshness must carry recommended_action per warning."""
        from app.services.knowledge_freshness_service import (
            FreshnessWarningDetail,
            KnowledgeFreshness,
        )

        snap = KnowledgeFreshness(warnings=["Database index is missing"])
        snap.details.append(
            FreshnessWarningDetail(
                category="db_index",
                message="Database index is missing",
                action_kind="reindex_db",
                action_label="Index database",
                connection_id="c1",
            )
        )
        d = snap.to_dict()
        assert d["overall_stale"] is True
        assert d["warnings"][0]["recommended_action"]["kind"] == "reindex_db"
        assert d["warnings"][0]["recommended_action"]["connection_id"] == "c1"


def _db_row(name: str) -> SimpleNamespace:
    return SimpleNamespace(
        table_name=name,
        table_schema="public",
        business_description=f"{name} table",
        relevance_score=4,
        indexed_at=datetime.now(UTC),
        column_count=5,
        row_count=100,
        code_match_status="matched",
    )


def _sync_row(entity: str, table: str) -> SimpleNamespace:
    return SimpleNamespace(
        entity_name=entity,
        table_name=table,
        data_format_notes="cents stored as int",
        entity_file_path="app/models/order.py",
        synced_at=datetime.now(UTC),
        confidence_score=4,
        read_count=10,
        write_count=2,
        conversion_warnings="",
        business_logic_notes="",
    )


class TestGetKnowledgeHealth:
    @pytest.mark.asyncio
    async def test_health_combines_freshness_and_counts(self):
        svc = KnowledgeCatalogService()
        counts = {"tables": 3, "learnings": 1, "insights": 0, "rules": 2, "lineage": 1}
        with (
            patch.object(svc, "_freshness", new=_clean_freshness()),
            patch.object(svc, "_artifact_counts", new=AsyncMock(return_value=counts)),
        ):
            health = await svc.get_knowledge_health(
                AsyncMock(), project_id="p1", connection_id="c1"
            )
        assert health["project_id"] == "p1"
        assert health["connection_id"] == "c1"
        assert health["freshness"]["overall_stale"] is False
        assert health["artifact_counts"]["tables"] == 3


class TestGetContextPack:
    @pytest.mark.asyncio
    async def test_assembles_tables_lineage_and_sources(self):
        svc = KnowledgeCatalogService()

        with (
            patch("app.services.db_index_service.DbIndexService") as mock_db_cls,
            patch("app.services.code_db_sync_service.CodeDbSyncService") as mock_sync_cls,
            patch("app.services.agent_learning_service.AgentLearningService") as mock_lrn_cls,
            patch("app.core.insight_memory.InsightMemoryService") as mock_ins_cls,
            patch("app.knowledge.custom_rules.CustomRulesEngine") as mock_rules_cls,
            patch.object(svc, "_freshness", new=_clean_freshness()),
        ):
            mock_db_cls.return_value.get_index = AsyncMock(
                return_value=[_db_row("orders"), _db_row("users")]
            )
            mock_sync_cls.return_value.get_sync = AsyncMock(
                return_value=[_sync_row("Order", "orders")]
            )
            mock_lrn_cls.return_value.get_learnings = AsyncMock(return_value=[])
            mock_ins_cls.return_value.get_insights = AsyncMock(return_value=[])
            mock_rules_cls.return_value.load_rules = MagicMock(return_value=[])

            pack = await svc.get_context_pack(
                AsyncMock(), project_id="p1", connection_id="c1", question=""
            )

        assert not pack.is_empty()
        assert {a.title for a in pack.tables} == {"orders", "users"}
        assert pack.tables[0].id.startswith("table:c1::public.")
        assert len(pack.lineage) == 1
        assert pack.lineage[0].payload["entity_name"] == "Order"
        # Sync notes flow through to the matching table's payload.
        orders = next(a for a in pack.tables if a.title == "orders")
        assert "sync_notes" in orders.payload
        assert "db_index" in pack.sources_used
        assert "lineage" in pack.sources_used

    @pytest.mark.asyncio
    async def test_failing_store_degrades_gracefully(self):
        """A raising store yields an empty section, never a 500."""
        svc = KnowledgeCatalogService()
        with (
            patch("app.services.db_index_service.DbIndexService") as mock_db_cls,
            patch("app.services.code_db_sync_service.CodeDbSyncService") as mock_sync_cls,
            patch("app.services.agent_learning_service.AgentLearningService") as mock_lrn_cls,
            patch("app.core.insight_memory.InsightMemoryService") as mock_ins_cls,
            patch("app.knowledge.custom_rules.CustomRulesEngine") as mock_rules_cls,
            patch.object(svc, "_freshness", new=_clean_freshness()),
        ):
            mock_db_cls.return_value.get_index = AsyncMock(side_effect=RuntimeError("boom"))
            mock_sync_cls.return_value.get_sync = AsyncMock(side_effect=RuntimeError("boom"))
            mock_lrn_cls.return_value.get_learnings = AsyncMock(side_effect=RuntimeError("boom"))
            mock_ins_cls.return_value.get_insights = AsyncMock(side_effect=RuntimeError("boom"))
            mock_rules_cls.return_value.load_rules = MagicMock(side_effect=RuntimeError("boom"))

            pack = await svc.get_context_pack(
                AsyncMock(), project_id="p1", connection_id="c1", question=""
            )

        assert pack.is_empty()
        assert pack.sources_used == []

    @pytest.mark.asyncio
    async def test_no_connection_skips_connection_scoped_sections(self):
        svc = KnowledgeCatalogService()
        with (
            patch("app.core.insight_memory.InsightMemoryService") as mock_ins_cls,
            patch("app.knowledge.custom_rules.CustomRulesEngine") as mock_rules_cls,
            patch.object(svc, "_freshness", new=_clean_freshness()),
        ):
            mock_ins_cls.return_value.get_insights = AsyncMock(return_value=[])
            mock_rules_cls.return_value.load_rules = MagicMock(return_value=[])

            pack = await svc.get_context_pack(
                AsyncMock(), project_id="p1", connection_id=None, question=""
            )

        assert pack.tables == []
        assert pack.lineage == []
        assert pack.learnings == []
