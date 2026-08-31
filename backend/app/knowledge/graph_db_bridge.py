"""Code → DB lineage bridge (M5).

Walks the in-memory :class:`CodeGraph` outward from each ORM entity to
discover the HTTP endpoints, services, CLI commands, and migrations that
ultimately read or write its table. Results are attached as
``EntityInfo.graph_callers`` so :class:`CodeDbSyncAnalyzer` and
:class:`SQLAgent` can show the user "this table is touched by these
endpoints".

Design notes:

* **Heuristic classification.** We don't try to be exhaustive — we look for
  decorators / file paths that *strongly imply* an endpoint kind. Anything
  ambiguous lands in the ``"service"`` / ``"unknown"`` buckets.
* **Confidence decay.** Each hop multiplies the upstream confidence by the
  edge's confidence (already 0..1 from the call resolver). Top-N callers
  per entity are kept so a single chatty utility doesn't drown the signal.
* **Bounded walk.** Reverse BFS bounded by :class:`Settings.lineage_max_depth`
  (default 5). The :class:`CodeGraph.callers_of` already implements this
  contract; we drive it here once per entity symbol.
* **In-place enrichment.** The bridge mutates the passed
  :class:`ProjectKnowledge` so callers don't have to rewire the pipeline
  state. Idempotent: re-running clears prior ``graph_callers`` first.
"""

from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING

from app.knowledge.code_graph import EDGE_CALLS

if TYPE_CHECKING:
    from app.knowledge.ast_parser import Symbol
    from app.knowledge.code_graph import CodeGraph
    from app.knowledge.entity_extractor import EntityInfo, ProjectKnowledge

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Classification heuristics
# ---------------------------------------------------------------------------

# File-path fragments that mark a symbol's origin layer. Matched against the
# normalised forward-slash path so they work cross-platform.
_HTTP_PATH_FRAGMENTS = (
    "/routes/",
    "/api/",
    "/controllers/",
    "/handlers/",
    "/views/",
    "/endpoints/",
    "/router/",
)
_MIGRATION_PATH_FRAGMENTS = (
    "/migrations/",
    "/alembic/versions/",
    "/db/migrate/",
    "/database/migrations/",
)
_CLI_PATH_FRAGMENTS = (
    "/cli/",
    "/cmd/",
    "/commands/",
    "/scripts/",
)
_SERVICE_PATH_FRAGMENTS = (
    "/services/",
    "/service/",
    "/usecases/",
    "/use_cases/",
    "/business/",
    "/domain/",
)

# Decorator name patterns. We compare on the *short* decorator name (no
# arguments). Tree-sitter strips parens for us via
# :func:`_extract_python_decorators` etc.
_HTTP_DECORATORS = re.compile(
    r"^(?:app|router|api|blueprint|bp|rest|controller|"
    r"get|post|put|patch|delete|options|head)\b",
    re.IGNORECASE,
)
_HTTP_DECORATORS_FULL = re.compile(
    r"\.(?:get|post|put|patch|delete|options|head|route|api_route)\b",
    re.IGNORECASE,
)
_CLI_DECORATORS = re.compile(
    r"^(?:click|cli|typer|app|command|cmd)\.(?:command|argument|option)\b"
    r"|^(?:click|typer)_command\b"
    r"|^command\b",
    re.IGNORECASE,
)

# Operation kind, matched against the caller's *short name* (after stripping
# a verb-like prefix). Order matters: write verbs first so e.g. ``update_user``
# isn't misclassified as read because of trailing ``user``.
_WRITE_VERBS = (
    "create_",
    "insert_",
    "update_",
    "upsert_",
    "delete_",
    "remove_",
    "drop_",
    "save_",
    "store_",
    "persist_",
    "write_",
    "post_",
    "put_",
    "patch_",
    "modify_",
    "submit_",
    "approve_",
    "reject_",
    "cancel_",
    "transfer_",
    "issue_",
    "refund_",
)
_READ_VERBS = (
    "get_",
    "find_",
    "fetch_",
    "list_",
    "show_",
    "query_",
    "search_",
    "count_",
    "exists_",
    "has_",
    "load_",
    "read_",
    "view_",
    "describe_",
    "summarize_",
    "export_",
)
# Verbs that could imply either read or write depending on context —
# classified as "unknown" rather than guessing.
_AMBIGUOUS_VERBS = (
    "process_",
    "handle_",
    "sync_",
    "set_",
    "add_",
    "register_",
)

# Tokens in HTTP route decorators that hint at the op kind.
# ``GET`` / ``LIST`` → read; ``POST`` / ``PUT`` / ``PATCH`` / ``DELETE`` → write.
#
# IMPORTANT: use ``\b`` word-boundary anchors so that decorators containing the
# method name as a *substring* (e.g. ``@budget_gettable``, ``@postmark_send``,
# ``@listable_resource``) do NOT match.  Only whole tokens such as ``.get(``,
# ``@app.get``, a bare ``get`` decorator, etc. produce a hit.
_HTTP_WRITE_METHODS = re.compile(r"\b(?:post|put|patch|delete)\b", re.IGNORECASE)
_HTTP_READ_METHODS = re.compile(r"\b(?:get|list)\b", re.IGNORECASE)


#: A caller matched on nothing but a method name — the weakest tier `_resolve_call`
#: emits. On its own that is thin evidence; across an application boundary it is none.
_CONF_NAME_ONLY_MAX = 0.3


def _path_proximity(caller_file: str, anchor_files: list[str] | tuple[str, ...]) -> int:
    """How many leading path segments the caller shares with the nearest anchor.

    The first segment is what separates applications in a repository that holds several
    (`api/…` beside `sendmail/…`), so a score of 0 means "different application" — which
    is exactly the shape of the noise this ranking exists to remove.
    """
    if not anchor_files:
        return 0
    caller_parts = [p for p in caller_file.split("/") if p]
    best = 0
    for anchor in anchor_files:
        anchor_parts = [p for p in anchor.split("/") if p]
        shared = 0
        for a, b in zip(caller_parts, anchor_parts, strict=False):
            if a != b:
                break
            shared += 1
        best = max(best, shared)
    return best


def rank_callers(
    callers: list[CallerRef],
    anchor_files: list[str] | tuple[str, ...],
    *,
    max_callers: int,
) -> list[CallerRef]:
    """Order callers by evidence, then by nearness, and drop the ones that are neither.

    Confidence leads, because a resolver that proved an edge outranks one that matched a
    name however close it sat. Proximity breaks the tie — and it decides nearly every
    tie, since name-only resolution gives every ref the same 0.3.

    A ref that is BOTH name-only AND in a different top-level directory is dropped rather
    than demoted. Demotion does not help: with ten slots and four genuine callers, a
    demoted ref still occupies slot five, which is how 29 of 54 entities ended up padded
    to exactly the cap. With no anchor files there is no proximity signal at all, so
    nothing is dropped — a missing input must not become a missing answer.
    """
    if not callers:
        return []
    scored = [(c, _path_proximity(c.caller_file, anchor_files)) for c in callers]
    if anchor_files:
        scored = [(c, prox) for c, prox in scored if prox > 0 or c.confidence > _CONF_NAME_ONLY_MAX]
    scored.sort(key=lambda cp: (cp[0].confidence, cp[1], -cp[0].depth), reverse=True)
    return [c for c, _ in scored[:max_callers]]


@dataclass
class CallerRef:
    """One caller of an entity, ranked by transitive call confidence."""

    caller_name: str
    caller_file: str
    caller_kind: str  # function | method | class
    endpoint_kind: str  # http | cli | migration | service | unknown
    op_kind: str  # read | write | unknown
    depth: int  # -1 when depth is estimated (see depth_estimated)
    confidence: float
    decorators: tuple[str, ...] = field(default_factory=tuple)
    # How the op_kind was inferred: "high" = HTTP decorator (strong signal),
    # "low" = name-prefix heuristic only (weak guess).
    op_kind_confidence: str = "low"
    # True when depth was estimated via log-inverse heuristic rather than
    # measured by a real BFS-depth-returning traversal.  Consumers MUST NOT
    # surface depth as a precise number when this flag is True.
    depth_estimated: bool = True

    def to_dict(self) -> dict:
        d = asdict(self)
        # Tuples lose type info through JSON anyway; emit a list.
        d["decorators"] = list(d["decorators"])
        return d


def _normalize_path(path: str) -> str:
    return path.replace("\\", "/")


def classify_endpoint_kind(symbol: Symbol) -> str:
    """Best-effort classification of where ``symbol`` lives in the stack."""
    file_path = _normalize_path(symbol.file_path or "")
    decorators = tuple(symbol.decorators or ())

    # 1) Path-based signals (cheapest, highest precision when present).
    for frag in _MIGRATION_PATH_FRAGMENTS:
        if frag in file_path:
            return "migration"
    for frag in _HTTP_PATH_FRAGMENTS:
        if frag in file_path:
            return "http"
    for frag in _CLI_PATH_FRAGMENTS:
        if frag in file_path:
            return "cli"

    # 2) Decorator-based signals.
    for dec in decorators:
        if _HTTP_DECORATORS.match(dec) or _HTTP_DECORATORS_FULL.search(dec):
            return "http"
        if _CLI_DECORATORS.match(dec):
            return "cli"

    # 3) Service-layer file paths.
    for frag in _SERVICE_PATH_FRAGMENTS:
        if frag in file_path:
            return "service"

    return "unknown"


def classify_op_kind_ex(symbol: Symbol) -> tuple[str, str]:
    """Extended heuristic classification — returns ``(op_kind, confidence)``.

    Confidence levels:

    * ``"high"``  — HTTP method inferred from a decorator token (e.g.
      ``@router.get(...)``).  The signal is unambiguous.
    * ``"low"``   — op-kind inferred solely from the function's name prefix
      (e.g. ``get_user`` → read).  This is a heuristic guess; the caller might
      not actually perform a DB read.

    The ``confidence`` value is intentionally a string (not a float) so it
    serialises cleanly in JSON/prompts without precision noise, and to avoid
    confusion with the numeric edge-confidence stored on :class:`CallerRef`.

    .. note::
        HTTP-method matching uses ``\\b`` word-boundary anchors, so decorators
        that merely *contain* a method name as a substring (e.g.
        ``@budget_gettable``, ``@postmark_send``) are **not** matched.
    """
    name = (symbol.name or "").lower()
    for verb in _WRITE_VERBS:
        if name.startswith(verb):
            return "write", "low"
    for verb in _READ_VERBS:
        if name.startswith(verb):
            return "read", "low"
    for verb in _AMBIGUOUS_VERBS:
        if name.startswith(verb):
            return "unknown", "low"

    # HTTP method hint via decorator (e.g. ``@router.post('/users')``).
    # Word-boundary regex prevents substring false-positives.
    for dec in symbol.decorators or ():
        if _HTTP_WRITE_METHODS.search(dec):
            return "write", "high"
        if _HTTP_READ_METHODS.search(dec):
            return "read", "high"

    return "unknown", "low"


def classify_op_kind(symbol: Symbol) -> str:
    """Heuristic read/write classification using verb prefix + decorators.

    Returns a plain ``str`` (``"read"`` | ``"write"`` | ``"unknown"``).

    .. deprecated::
        Prefer :func:`classify_op_kind_ex` when you need the confidence level.
        This function is kept for back-compat (existing tests assert a plain
        ``str`` return type).
    """
    op_kind, _confidence = classify_op_kind_ex(symbol)
    return op_kind


# ---------------------------------------------------------------------------
# Bridge
# ---------------------------------------------------------------------------


class GraphDBBridge:
    """Enrich :class:`ProjectKnowledge` with graph-derived caller lineage.

    Parameters:
        max_depth: how many CALLS hops to walk outward from each entity
            symbol. Should match ``settings.lineage_max_depth``.
        max_callers_per_entity: hard cap on stored callers per entity. Keeps
            ``graph_callers`` JSON-stable across runs and bounds context cost.
        min_confidence: skip callers whose multiplied confidence falls below
            this threshold (after decay). 0.05 means "5% of full strength".
    """

    def __init__(
        self,
        max_depth: int = 5,
        max_callers_per_entity: int = 10,
        min_confidence: float = 0.05,
    ) -> None:
        self._max_depth = max(1, int(max_depth))
        self._max_callers = max(1, int(max_callers_per_entity))
        self._min_confidence = max(0.0, float(min_confidence))

    def enrich(
        self,
        knowledge: ProjectKnowledge,
        code_graph: CodeGraph,
    ) -> int:
        """Populate ``EntityInfo.graph_callers`` for every entity in-place.

        Returns the total number of caller refs attached across all entities
        (handy for tracker emit + tests).
        """
        if knowledge is None or code_graph is None:
            return 0
        if not knowledge.entities:
            return 0

        # Build a single (name, file_path)-indexed lookup over the code
        # graph's symbols so we don't pay O(N) per entity.
        symbol_by_name_file: dict[tuple[str, str], list[Symbol]] = {}
        for sym in code_graph.symbols.values():
            key = (sym.name, _normalize_path(sym.file_path or ""))
            symbol_by_name_file.setdefault(key, []).append(sym)

        total_attached = 0
        for entity in knowledge.entities.values():
            entity.graph_callers = []  # idempotency
            anchors = self._resolve_entity_symbols(entity, code_graph, symbol_by_name_file)
            if not anchors:
                continue

            collected: dict[str, CallerRef] = {}
            for anchor in anchors:
                self._walk_callers(anchor, code_graph, collected)
            if not collected:
                continue

            anchor_files = [a.file_path for a in anchors if getattr(a, "file_path", None)]
            ranked = rank_callers(
                list(collected.values()), anchor_files, max_callers=self._max_callers
            )
            entity.graph_callers = [c.to_dict() for c in ranked]
            total_attached += len(ranked)

        logger.info(
            "graph_db_bridge: attached %d caller refs across %d entities",
            total_attached,
            len(knowledge.entities),
        )
        return total_attached

    # ---- internals ---------------------------------------------------------

    def _resolve_entity_symbols(
        self,
        entity: EntityInfo,
        code_graph: CodeGraph,
        symbol_by_name_file: dict[tuple[str, str], list[Symbol]],
    ) -> list[Symbol]:
        """Find the code graph symbol(s) that represent this entity."""
        if not entity.name:
            return []

        candidates: list[Symbol] = []

        # Prefer the (name, file) hit — that's the entity's defining class.
        if entity.file_path:
            key = (entity.name, _normalize_path(entity.file_path))
            candidates.extend(symbol_by_name_file.get(key, []))

        # Fall back to a name-only match across the whole graph. We only do
        # this when the file-path lookup missed because the names are often
        # ambiguous (e.g. ``User`` exists in 50 files).
        if not candidates:
            candidates.extend(code_graph.query_by_name(entity.name))

        # Keep only class/function-ish symbols (skip imports, variables).
        anchors = [s for s in candidates if s.kind in {"class", "function", "method"}]

        # A class is never the destination of a CALLS edge — a call resolves to the
        # METHOD being called, and the class merely owns it. Anchoring on the class
        # alone therefore walks an empty set, and did: measured in production on
        # 2026-08-30, with 49 268 CALLS edges in the graph,
        #
        #     CALLS edges pointing at a class symbol     0
        #     CALLS edges pointing at a method/function  45 832
        #     model classes 26, with any inbound edge     0
        #
        # so `graph_db_bridge` reported "Attached 0 caller refs across 179 entities"
        # and would have reported it against a perfect call graph too. "Who uses this
        # model" means who calls any of its methods, so the class's members join the
        # anchor set.
        for class_uid in [s.uid for s in anchors if s.kind == "class"]:
            anchors.extend(
                m for m in code_graph.members_of(class_uid) if m.kind in {"method", "function"}
            )
        return anchors

    def _walk_callers(
        self,
        anchor: Symbol,
        code_graph: CodeGraph,
        collected: dict[str, CallerRef],
    ) -> None:
        """Reverse-BFS from ``anchor`` along CALLS edges and accumulate refs."""
        try:
            caller_tuples = code_graph.callers_of(
                anchor.uid,
                edge_type=EDGE_CALLS,
                min_confidence=self._min_confidence,
                max_depth=self._max_depth,
            )
        except Exception:
            logger.debug("callers_of failed for anchor %s", anchor.uid, exc_info=True)
            return

        if not caller_tuples:
            return

        # callers_of does not return per-hop BFS depth, so we cannot report a
        # precise depth.  Set depth=-1 (sentinel: unknown) and depth_estimated=True
        # so consumers know not to surface the value as a precise number.
        for sym, conf in caller_tuples:
            op_kind, op_kind_conf = classify_op_kind_ex(sym)
            ref = CallerRef(
                caller_name=sym.name or "<anon>",
                caller_file=sym.file_path,
                caller_kind=sym.kind,
                endpoint_kind=classify_endpoint_kind(sym),
                op_kind=op_kind,
                depth=-1,
                confidence=round(conf, 4),
                decorators=tuple(sym.decorators or ()),
                op_kind_confidence=op_kind_conf,
                depth_estimated=True,
            )
            # Dedupe across multiple anchors of the same entity — keep the
            # highest-confidence ref for the same caller symbol.
            existing = collected.get(sym.uid)
            if existing is None or ref.confidence > existing.confidence:
                collected[sym.uid] = ref

    @staticmethod
    def _estimate_depth(confidence: float) -> int:  # pragma: no cover
        """Deprecated — no longer called.

        ``callers_of`` does not return BFS depth, so we cannot derive a
        reliable number.  Kept for external callers that may reference it;
        returns -1 (unknown sentinel) instead of a fabricated log-inverse.
        """
        return -1


__all__ = [
    "CallerRef",
    "GraphDBBridge",
    "classify_endpoint_kind",
    "classify_op_kind",
    "classify_op_kind_ex",
]
