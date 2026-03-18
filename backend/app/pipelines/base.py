"""Base classes for the pipeline plugin system."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from app.llm.base import Tool


@dataclass
class PipelineContext:
    """Shared context passed to pipeline operations."""

    project_id: str
    workflow_id: str
    force_full: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class PipelineResult:
    """Result of a pipeline operation."""

    success: bool = True
    items_processed: int = 0
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PipelineStatus:
    """Current status of a pipeline for a given source."""

    is_indexed: bool = False
    is_synced: bool = False
    is_stale: bool = False
    last_indexed_at: str | None = None
    items_count: int = 0


class DataSourcePipeline(ABC):
    """Plugin interface for data source indexing and synchronisation.

    Each data source type (database, analytics, API, etc.) implements
    this interface to plug into the system's indexing and agent
    infrastructure.
    """

    @property
    @abstractmethod
    def source_type(self) -> str:
        """Identifier matching ``Connection.source_type`` (e.g. 'database')."""

    @abstractmethod
    async def index(
        self,
        source_id: str,
        context: PipelineContext,
    ) -> PipelineResult:
        """Index the data source (e.g. introspect schema, analyse tables)."""

    @abstractmethod
    async def sync_with_code(
        self,
        source_id: str,
        context: PipelineContext,
    ) -> PipelineResult:
        """Synchronise data source metadata with codebase knowledge."""

    @abstractmethod
    async def get_status(self, source_id: str) -> PipelineStatus:
        """Return the current indexing/sync status for a source."""

    @abstractmethod
    def get_agent_tools(self) -> list[Tool]:
        """Return the tools this pipeline makes available to agents."""
