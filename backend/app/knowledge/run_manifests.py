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
        Step("repo_index", "Repository Index", weight=2),
        Step("db_index", "Database Index", weight=3),
        Step("code_db_sync", "Code-DB Sync", weight=3),
        Step("summarize", "Summarize"),
    ],
}

#: `index_repo`, in the order the pipeline actually runs it, each step carrying the flag
#: that gates it (``None`` = always).
#:
#: Order matters because `progress_for` weighs the manifest PREFIX up to the completed
#: step's position. Flag-gated steps used to be appended after the unconditional ones, so
#: the list bore no relation to execution and the bar moved accordingly. Read from the
#: journal of a live rebuild on 2026-08-31 (run `3a0fdd16`), which reported:
#:
#:     resolve_ssh_key 5 → clone_or_pull 14 → detect_changes 18 → project_profile 41
#:     → ast_parse 77 → graph_build 86 → code_symbol_embed 86 (absent, so no move)
#:     → analyze_files 36  ← backwards, from 86
#:     → cross_file_analysis 50 → graph_db_bridge 100
#:     → generate_docs 100  ← and it stayed there for the 2.6 h that stage takes
#:
#: The order below is that journal's, not the source file's: several steps are emitted
#: from helpers defined far from where they are called, so reading line numbers gives a
#: different and wrong answer.
_INDEX_REPO_STEPS: list[tuple[str | None, Step]] = [
    (None, Step("resolve_ssh_key", "SSH Key")),
    (None, Step("clone_or_pull", "Git Clone/Pull", weight=2)),
    (None, Step("detect_changes", "Detect Changes")),
    (None, Step("cleanup_deleted", "Cleanup Deleted")),
    (None, Step("project_profile", "Project Profile")),
    ("code_graph_enabled", Step("ast_parse", "AST Parse", weight=2)),
    ("code_graph_enabled", Step("graph_build", "Build Code Graph", weight=2)),
    # 2 300 s measured on the 9 981-file repository, 26.5 min on the 2026-08-31 rebuild —
    # the second-longest step, and it was in no manifest at all, so `_record` journalled
    # it without touching `current_step` and the bar stood still throughout.
    ("hybrid_retrieval_enabled", Step("code_symbol_embed", "Embed Code Symbols", weight=3)),
    (None, Step("analyze_files", "Analyze Files", weight=3)),
    (None, Step("cross_file_analysis", "Cross-File Analysis", weight=2)),
    ("lineage_enabled", Step("graph_db_bridge", "Code→DB Lineage")),
    ("clustering_enabled", Step("graph_clustering", "Cluster Communities")),
    # The longest step in the pipeline: ~9 375 s at ~4.8 docs/min over 758 documents.
    (None, Step("generate_docs", "Generate Docs", weight=8)),
    ("hybrid_retrieval_enabled", Step("bm25_build", "Build BM25")),
    ("schema_retrieval_enabled", Step("schema_embed", "Embed Schema")),
    (None, Step("record_index", "Record Index")),
]


def resolve_manifest(kind: str, *, flags: dict[str, bool] | None = None) -> list[Step]:
    if kind == "index_repo":
        flags = flags or {}
        return [step for flag, step in _INDEX_REPO_STEPS if flag is None or flags.get(flag)]
    if kind not in _BASE:
        raise KeyError(f"unknown run kind: {kind}")
    return list(_BASE[kind])


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
