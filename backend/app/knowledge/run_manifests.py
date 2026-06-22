"""Weighted, ordered step manifests per background-run kind.

``total_steps`` and ``progress_for`` give the UI honest "N of M" + percent. Manifest
keys match the step names already emitted by the pipelines (see ActiveTasksWidget
STEP_LABELS).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Step:
    key: str
    label: str
    weight: int = 1


_BASE: dict[str, list[Step]] = {
    "index_repo": [
        Step("resolve_ssh_key", "SSH Key"),
        Step("clone_or_pull", "Git Clone/Pull", weight=2),
        Step("detect_changes", "Detect Changes"),
        Step("cleanup_deleted", "Cleanup Deleted"),
        Step("analyze_files", "Analyze Files", weight=3),
        Step("project_profile", "Project Profile"),
        Step("cross_file_analysis", "Cross-File Analysis", weight=2),
        Step("generate_docs", "Generate Docs", weight=3),
        Step("record_index", "Record Index"),
    ],
    "db_index": [
        Step("introspect_schema", "Introspect Schema"),
        Step("fetch_samples", "Fetch Samples"),
        Step("load_context", "Load Context"),
        Step("validate_tables", "LLM Analysis", weight=3),
        Step("store_results", "Store Results"),
        Step("generate_summary", "Generate Summary"),
    ],
    "code_db_sync": [
        Step("load_code_knowledge", "Load Code Knowledge"),
        Step("load_db_index", "Load DB Index"),
        Step("match_tables", "Match Tables", weight=2),
        Step("analyze_sync", "Analyze Code-DB", weight=2),
        Step("store_sync", "Store Results"),
        Step("generate_sync_summary", "Generate Summary"),
    ],
    "daily_sync": [
        Step("plan_targets", "Plan Targets"),
        Step("db_index", "Database Index", weight=3),
        Step("code_db_sync", "Code-DB Sync", weight=3),
        Step("freshness_reconcile", "Freshness Reconcile"),
        Step("summarize", "Summarize"),
    ],
}

# Flag-gated steps appended to index_repo when the corresponding flag is on.
_INDEX_REPO_FLAG_STEPS: list[tuple[str, Step]] = [
    ("code_graph_enabled", Step("ast_parse", "AST Parse", weight=2)),
    ("code_graph_enabled", Step("graph_build", "Build Code Graph", weight=2)),
    ("hybrid_retrieval_enabled", Step("bm25_build", "Build BM25")),
    ("schema_retrieval_enabled", Step("schema_embed", "Embed Schema")),
    ("lineage_enabled", Step("graph_db_bridge", "Code→DB Lineage")),
    ("clustering_enabled", Step("graph_clustering", "Cluster Communities")),
]


def resolve_manifest(kind: str, *, flags: dict[str, bool] | None = None) -> list[Step]:
    if kind not in _BASE:
        raise KeyError(f"unknown run kind: {kind}")
    steps = list(_BASE[kind])
    if kind == "index_repo":
        flags = flags or {}
        steps += [step for flag, step in _INDEX_REPO_FLAG_STEPS if flags.get(flag)]
    return steps


def total_steps(manifest: list[Step]) -> int:
    return len(manifest)


def progress_for(manifest: list[Step], completed: int) -> int:
    total_weight = sum(s.weight for s in manifest) or 1
    bounded = max(0, min(completed, len(manifest)))
    done_weight = sum(s.weight for s in manifest[:bounded])
    return round(done_weight / total_weight * 100)


def step_position(manifest: list[Step], key: str) -> int:
    for idx, step in enumerate(manifest, start=1):
        if step.key == key:
            return idx
    raise KeyError(f"step {key!r} not in manifest")
