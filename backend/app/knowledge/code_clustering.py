"""Functional clustering over the code graph (M6).

Uses NetworkX's built-in Louvain community detection on a weighted
undirected projection of the CALLS+IMPORTS edges. The resulting clusters
are then labeled by an LLM (in batches) to produce human-readable names
like ``"Auth & Sessions"`` or ``"Stripe Billing"`` for the SQL agent's
``get_tables_in_cluster`` tool.

Why Louvain and not Leiden?

* The plan called out Leiden; ``networkx.algorithms.community.leiden_communities``
  doesn't exist in the version we ship, and the python-louvain package
  isn't always available on the slim image. Louvain is a single-function
  call with comparable quality for our scale (≤50k symbols).
* If/when we standardise on a Leiden dependency, the only change is swapping
  the ``_run_louvain`` body.

Cluster IDs are stable across runs in the sense that two runs with the same
input graph will produce the same membership; they are NOT stable across
graph rebuilds (a renamed module can shift cluster numbering). Treat the
``cluster_id`` as a per-run handle, not a long-lived identifier.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.knowledge.code_graph import CodeGraph
    from app.knowledge.entity_extractor import ProjectKnowledge
    from app.llm.router import LLMRouter

logger = logging.getLogger(__name__)


# Edge-type weights for the undirected projection. CALLS dominates because
# functional cohesion is what we're trying to surface; IMPORTS is included
# but down-weighted so heavy "fan-in" utility modules don't drown the signal.
_EDGE_WEIGHTS = {
    "CALLS": 1.0,
    "IMPORTS": 0.3,
    "EXTENDS": 0.5,
}

# Skip clusters smaller than this — they're noise (lone helper functions,
# one-off scripts) and clutter the labeling LLM prompt.
_MIN_CLUSTER_SIZE = 3

# Cluster size cap for the symbols-per-cluster aggregation in
# :func:`Cluster.from_members`. Prevents megaclusters dominated by a single
# module from blowing up the prompt context.
_MAX_SYMBOLS_PER_CLUSTER_PROMPT = 40


@dataclass
class Cluster:
    """In-memory representation of a community."""

    cluster_id: str
    member_uids: list[str]
    file_paths: list[str] = field(default_factory=list)
    label: str = ""
    description: str = ""
    table_names: list[str] = field(default_factory=list)

    @property
    def symbol_count(self) -> int:
        return len(self.member_uids)


# ---------------------------------------------------------------------------
# Louvain partition
# ---------------------------------------------------------------------------


def _run_louvain(graph: CodeGraph) -> dict[str, str]:
    """Return ``symbol_uid -> cluster_id`` mapping.

    Builds an undirected weighted projection so call direction doesn't fight
    the modularity objective. ``cluster_id`` is the index of the partition
    in :func:`louvain_communities` — stringified for SQL friendliness.
    """
    import networkx as nx
    from networkx.algorithms.community import louvain_communities

    undirected = nx.Graph()
    for sym_uid in graph.symbols:
        undirected.add_node(sym_uid)
    for u, v, data in graph.networkx.edges(data=True):
        if u == v:
            continue
        edge_type = data.get("edge_type", "")
        weight = _EDGE_WEIGHTS.get(edge_type)
        if weight is None:
            continue
        confidence = float(data.get("confidence", 1.0))
        effective = weight * confidence
        if effective <= 0:
            continue
        if undirected.has_edge(u, v):
            undirected[u][v]["weight"] += effective
        else:
            undirected.add_edge(u, v, weight=effective)

    if undirected.number_of_nodes() == 0:
        return {}

    try:
        # ``seed`` makes the partition deterministic across runs with the
        # same graph — important for tests and for reasoning about diffs.
        communities = louvain_communities(undirected, weight="weight", seed=42)
    except Exception:
        logger.warning("louvain failed; clustering skipped", exc_info=True)
        return {}

    membership: dict[str, str] = {}
    for idx, community in enumerate(communities):
        cid = str(idx)
        for uid in community:
            membership[str(uid)] = cid
    return membership


# ---------------------------------------------------------------------------
# Cluster aggregation
# ---------------------------------------------------------------------------


def _aggregate_clusters(
    code_graph: CodeGraph,
    knowledge: ProjectKnowledge,
    membership: dict[str, str],
) -> list[Cluster]:
    """Group symbol UIDs by cluster + attach derived metadata."""
    # Build a name→tables map from the project knowledge so we can map a
    # cluster's member symbols back to DB tables.
    name_to_tables: dict[str, list[str]] = defaultdict(list)
    for entity in knowledge.entities.values():
        if entity.name and entity.table_name:
            name_to_tables[entity.name].append(entity.table_name)
    file_to_tables: dict[str, list[str]] = defaultdict(list)
    for entity in knowledge.entities.values():
        if entity.file_path and entity.table_name:
            file_to_tables[entity.file_path].append(entity.table_name)

    grouped: dict[str, list[str]] = defaultdict(list)
    for uid, cid in membership.items():
        grouped[cid].append(uid)

    clusters: list[Cluster] = []
    for cid, uids in grouped.items():
        if len(uids) < _MIN_CLUSTER_SIZE:
            continue
        files: set[str] = set()
        tables: set[str] = set()
        for uid in uids:
            sym = code_graph.symbols.get(uid)
            if sym is None:
                continue
            files.add(sym.file_path)
            for tbl in name_to_tables.get(sym.name, ()):
                tables.add(tbl)
            for tbl in file_to_tables.get(sym.file_path, ()):
                tables.add(tbl)
        clusters.append(
            Cluster(
                cluster_id=cid,
                member_uids=sorted(uids),
                file_paths=sorted(files),
                table_names=sorted(tables),
            )
        )
    clusters.sort(key=lambda c: -c.symbol_count)
    return clusters


# ---------------------------------------------------------------------------
# LLM labeling
# ---------------------------------------------------------------------------


def _build_label_prompt(batch: list[Cluster], code_graph: CodeGraph) -> str:
    """Compose a prompt asking the model to name each cluster in the batch."""
    parts: list[str] = [
        "You are labeling functional clusters of code from a single project.",
        "For each cluster, output a JSON object on its own line with:",
        '  {"id": "<cluster_id>", "label": "<3-6 word title>",'
        ' "description": "<1-2 sentence purpose>"}',
        "Use the source files and exemplar symbol names as evidence. Keep",
        "labels short, business-domain oriented, e.g. 'Auth & Sessions',",
        "'Stripe Billing', 'Knowledge Graph Indexing'.",
        "",
    ]
    for cluster in batch:
        sample_syms = []
        for uid in cluster.member_uids[:_MAX_SYMBOLS_PER_CLUSTER_PROMPT]:
            sym = code_graph.symbols.get(uid)
            if sym is None:
                continue
            sample_syms.append(f"{sym.kind}:{sym.name}")
        parts.append(f"## Cluster {cluster.cluster_id}")
        if cluster.file_paths:
            parts.append("Files: " + ", ".join(cluster.file_paths[:10]))
        if cluster.table_names:
            parts.append("Tables: " + ", ".join(cluster.table_names[:10]))
        if sample_syms:
            parts.append("Symbols: " + ", ".join(sample_syms))
        parts.append("")
    parts.append("Respond with one JSON object per cluster, separated by newlines.")
    return "\n".join(parts)


def _parse_label_response(text: str) -> dict[str, tuple[str, str]]:
    """Lenient parser; returns ``{cluster_id: (label, description)}``."""
    out: dict[str, tuple[str, str]] = {}
    if not text:
        return out
    for raw_line in text.strip().splitlines():
        line = raw_line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            parsed = json.loads(line)
        except Exception:
            continue
        cid = str(parsed.get("id") or "").strip()
        label = str(parsed.get("label") or "").strip()
        description = str(parsed.get("description") or "").strip()
        if cid:
            out[cid] = (label or f"Cluster {cid}", description)
    return out


async def label_clusters(
    clusters: list[Cluster],
    code_graph: CodeGraph,
    llm_router: LLMRouter | None,
    *,
    batch_size: int = 10,
) -> None:
    """Mutate ``clusters`` in place with LLM-generated labels.

    Falls back to ``"Cluster N"`` defaults if the router is missing or any
    individual call fails. We don't block on labeling — losing labels for
    one batch shouldn't kill an indexing run.
    """
    if not clusters:
        return
    # Default labels first so any later failure leaves clusters usable.
    for c in clusters:
        if not c.label:
            c.label = f"Cluster {c.cluster_id}"

    if llm_router is None:
        return

    for batch_start in range(0, len(clusters), batch_size):
        batch = clusters[batch_start : batch_start + batch_size]
        prompt = _build_label_prompt(batch, code_graph)
        try:
            from app.llm.base import Message

            response = await llm_router.complete(
                messages=[
                    Message(role="system", content="You are a code labeling assistant."),
                    Message(role="user", content=prompt),
                ],
                temperature=0.2,
            )
            parsed = _parse_label_response(response.content or "")
            for cluster in batch:
                if cluster.cluster_id in parsed:
                    label, description = parsed[cluster.cluster_id]
                    cluster.label = label
                    cluster.description = description
        except Exception:
            logger.warning(
                "cluster labeling batch failed (start=%d); using default labels",
                batch_start,
                exc_info=True,
            )


# ---------------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------------


def cluster_code_graph(
    code_graph: CodeGraph,
    knowledge: ProjectKnowledge,
) -> list[Cluster]:
    """Compute Louvain communities + aggregate metadata.

    Returns an empty list when the graph has no edges (clustering is
    meaningless without connectivity). Labeling happens in a separate
    async step so the pipeline can decide whether to spend LLM tokens.
    """
    if code_graph is None or not code_graph.symbols:
        return []
    membership = _run_louvain(code_graph)
    if not membership:
        return []
    return _aggregate_clusters(code_graph, knowledge, membership)


__all__ = [
    "Cluster",
    "cluster_code_graph",
    "label_clusters",
]
