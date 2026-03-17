"""Shared types used across orchestrator and tool execution layers."""

from dataclasses import dataclass


@dataclass
class RAGSource:
    source_path: str
    distance: float | None = None
    doc_type: str = ""
    chunk_index: str = ""
