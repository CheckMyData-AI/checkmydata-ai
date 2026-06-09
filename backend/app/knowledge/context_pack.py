"""ContextPack — structured, traceable knowledge bundle for the orchestrator.

Implements the artifact envelope and ``ContextPack`` contract defined in
``docs/KNOWLEDGE_CATALOG.md``. This module is **pure data** (no I/O); the
:class:`~app.services.knowledge_catalog_service.KnowledgeCatalogService`
assembles it from the existing stores as a read-facade.

Every artifact carries its own provenance, freshness, and confidence so the
orchestrator (Phase 4 ContextPlanner) and the UI Knowledge Health panel can
reason about *what* is known and *how much to trust it* — vision invariants
#2 (traceability) and #5 (graceful degradation).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Artifact:
    """Canonical envelope for a single knowledge artifact.

    See ``docs/KNOWLEDGE_CATALOG.md`` §2 for field semantics.
    """

    id: str
    type: str  # table | code_entity | lineage_edge | learning | insight | rule | rag_chunk | metric
    title: str
    summary: str = ""
    provenance: dict[str, Any] = field(default_factory=dict)
    freshness: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    payload: dict[str, Any] = field(default_factory=dict)
    # Phase 4: trust-layer view (confidence_label, freshness_label, badge).
    # Populated by KnowledgeCatalogService via TrustService; empty until then.
    trust: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "title": self.title,
            "summary": self.summary,
            "provenance": self.provenance,
            "freshness": self.freshness,
            "confidence": round(self.confidence, 3),
            "trust": self.trust,
            "payload": self.payload,
        }

    def source_ref(self) -> str:
        """Short citeable reference (source:source_ref) for the reasoning panel."""
        src = self.provenance.get("source", "unknown")
        ref = self.provenance.get("source_ref") or self.id
        return f"{src}:{ref}"


@dataclass
class ContextPack:
    """A budget-aware, citeable bundle the orchestrator consumes in place of
    the previous 6+ ad-hoc lazy loads.
    """

    project_id: str
    connection_id: str | None = None
    question: str = ""
    tables: list[Artifact] = field(default_factory=list)
    lineage: list[Artifact] = field(default_factory=list)
    learnings: list[Artifact] = field(default_factory=list)
    rules: list[Artifact] = field(default_factory=list)
    insights: list[Artifact] = field(default_factory=list)
    rag_chunks: list[Artifact] = field(default_factory=list)
    freshness: dict[str, Any] = field(default_factory=dict)
    sources_used: list[str] = field(default_factory=list)
    token_budget: dict[str, Any] = field(default_factory=dict)
    # Phase 4: the plan that produced this pack (categories requested, budget,
    # rationale) — surfaced in the reasoning panel for transparency.
    plan: dict[str, Any] = field(default_factory=dict)

    def is_empty(self) -> bool:
        return not any(
            (
                self.tables,
                self.lineage,
                self.learnings,
                self.rules,
                self.insights,
                self.rag_chunks,
            )
        )

    def all_artifacts(self) -> list[Artifact]:
        """Flat view of every artifact across sections (stable order)."""
        return [
            *self.tables,
            *self.lineage,
            *self.learnings,
            *self.rules,
            *self.insights,
            *self.rag_chunks,
        ]

    def provenance_summary(self) -> list[dict[str, Any]]:
        """Per-block provenance for the reasoning panel (vision #2 traceability).

        One entry per non-empty section, each listing its source refs and the
        trust badge distribution so the UI can show *where* each context block
        came from and *how much to trust it*.
        """
        sections = {
            "tables": self.tables,
            "lineage": self.lineage,
            "learnings": self.learnings,
            "rules": self.rules,
            "insights": self.insights,
            "rag_chunks": self.rag_chunks,
        }
        summary: list[dict[str, Any]] = []
        for name, arts in sections.items():
            if not arts:
                continue
            badges: dict[str, int] = {}
            for a in arts:
                label = a.trust.get("confidence_label", "unknown")
                badges[label] = badges.get(label, 0) + 1
            summary.append(
                {
                    "block": name,
                    "count": len(arts),
                    "source_refs": [a.source_ref() for a in arts[:10]],
                    "confidence_labels": badges,
                }
            )
        return summary

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "connection_id": self.connection_id,
            "question": self.question,
            "tables": [a.to_dict() for a in self.tables],
            "lineage": [a.to_dict() for a in self.lineage],
            "learnings": [a.to_dict() for a in self.learnings],
            "rules": [a.to_dict() for a in self.rules],
            "insights": [a.to_dict() for a in self.insights],
            "rag_chunks": [a.to_dict() for a in self.rag_chunks],
            "freshness": self.freshness,
            "sources_used": self.sources_used,
            "token_budget": self.token_budget,
            "plan": self.plan,
            "provenance_summary": self.provenance_summary(),
        }
