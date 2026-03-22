"""Unit tests for the pipeline registry."""

import pytest

from app.pipelines.base import DataSourcePipeline
from app.pipelines.database_pipeline import DatabasePipeline
from app.pipelines.mcp_pipeline import MCPPipeline
from app.pipelines.registry import PIPELINE_REGISTRY, get_pipeline, register_pipeline


class TestGetPipeline:
    def test_get_pipeline_database(self):
        p = get_pipeline("database")
        assert isinstance(p, DatabasePipeline)

    def test_get_pipeline_mcp(self):
        p = get_pipeline("mcp")
        assert isinstance(p, MCPPipeline)

    def test_get_pipeline_unknown(self):
        with pytest.raises(ValueError, match="No pipeline registered"):
            get_pipeline("ftp")

    def test_get_pipeline_case_insensitive(self):
        p = get_pipeline("DATABASE")
        assert isinstance(p, DatabasePipeline)


class TestRegistryEntries:
    def test_registry_has_expected_entries(self):
        assert "database" in PIPELINE_REGISTRY
        assert "mcp" in PIPELINE_REGISTRY
        assert PIPELINE_REGISTRY["database"] is DatabasePipeline
        assert PIPELINE_REGISTRY["mcp"] is MCPPipeline

    def test_all_entries_are_datasource_pipelines(self):
        for key, cls in PIPELINE_REGISTRY.items():
            assert issubclass(cls, DataSourcePipeline), f"{key} → {cls} is not a DataSourcePipeline"


class TestRegisterPipeline:
    def test_register_new_pipeline(self):
        register_pipeline("dummy", DatabasePipeline)
        assert PIPELINE_REGISTRY["dummy"] is DatabasePipeline
        p = get_pipeline("dummy")
        assert isinstance(p, DatabasePipeline)
        del PIPELINE_REGISTRY["dummy"]
