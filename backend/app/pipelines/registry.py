"""Pipeline registry — maps source types to pipeline plugins."""

from __future__ import annotations

from app.pipelines.analytics_pipeline import AnalyticsPipeline
from app.pipelines.base import DataSourcePipeline
from app.pipelines.database_pipeline import DatabasePipeline
from app.pipelines.mcp_pipeline import MCPPipeline

PIPELINE_REGISTRY: dict[str, type[DataSourcePipeline]] = {
    "database": DatabasePipeline,
    "mcp": MCPPipeline,
    # All three analytics vendors share one pipeline: collecting a vendor report
    # is the same work regardless of which vendor it is, and the concrete vendor
    # lives on the connection, not on the pipeline.
    "ga4": AnalyticsPipeline,
    "appstore": AnalyticsPipeline,
    "googleplay": AnalyticsPipeline,
}


def get_pipeline(source_type: str) -> DataSourcePipeline:
    """Instantiate and return a pipeline for the given source type."""
    cls = PIPELINE_REGISTRY.get(source_type.lower())
    if cls is None:
        raise ValueError(
            f"No pipeline registered for source type '{source_type}'. "
            f"Available: {list(PIPELINE_REGISTRY.keys())}"
        )
    return cls()


def register_pipeline(source_type: str, pipeline_cls: type[DataSourcePipeline]) -> None:
    """Register a new pipeline plugin at runtime."""
    PIPELINE_REGISTRY[source_type.lower()] = pipeline_cls
