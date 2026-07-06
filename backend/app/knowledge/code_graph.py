"""Code knowledge graph (M2).

Consumes :class:`app.knowledge.ast_parser.ParsedFile` objects and emits a
:class:`CodeGraph` of symbols + typed edges (CALLS / IMPORTS / EXTENDS /
DEFINES). Inspired by GitNexus' approach but implemented entirely with OSS
Python libraries (NetworkX); no GitNexus code is reused.

Design notes:
    * **Two-pass resolution.** Pass A builds a global symbol table keyed by
      ``(file, name)`` and a per-file local table for fast lookup. Pass B
      resolves each :class:`CallSite` against (a) imports in the same file,
      (b) symbols in the same file, (c) global symbol table, in that order.
      Confidence is attached per edge so consumers can filter.
    * **Cycle tolerance.** ``EXTENDS`` cycles are detected eagerly via NetworkX
      and the lowest-confidence edge is dropped.
    * **Size cap.** When the global symbol count exceeds
      ``code_graph_max_symbols``, private/underscore symbols are pruned first.
    * **No SQL dependency.** This module is pure in-memory. Persistence lives
      in :mod:`app.services.code_graph_service`.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import networkx as nx

from app.knowledge.ast_parser import ImportRef, ParsedFile, Symbol

logger = logging.getLogger(__name__)

EDGE_CALLS = "CALLS"
EDGE_IMPORTS = "IMPORTS"
EDGE_EXTENDS = "EXTENDS"
EDGE_DEFINES = "DEFINES"

# Confidence levels for resolved CALLS edges.
_CONF_EXACT_LOCAL = 1.0
_CONF_VIA_IMPORT = 0.8
_CONF_GLOBAL_UNIQUE = 0.7
_CONF_AMBIGUOUS = 0.4
_CONF_NAME_ONLY = 0.3

# Tokens that should never resolve to a code symbol (built-ins, control flow).
_CALL_BLOCKLIST: frozenset[str] = frozenset(
    {
        "print",
        "len",
        "range",
        "str",
        "int",
        "float",
        "list",
        "dict",
        "set",
        "tuple",
        "bool",
        "type",
        "isinstance",
        "issubclass",
        "getattr",
        "setattr",
        "hasattr",
        "open",
        "super",
        "any",
        "all",
        "map",
        "filter",
        "zip",
        "sorted",
        "enumerate",
        "next",
        "iter",
        "min",
        "max",
        "sum",
        "abs",
        "round",
        "repr",
        "format",
        "console",
        "require",
        "Object",
        "Array",
        "JSON",
        "Math",
        "String",
        "Number",
        "Boolean",
    }
)


@dataclass(frozen=True)
class GraphEdge:
    """A typed directed edge in the code graph.

    Attributes:
        src_uid: Source symbol UID.
        dst_uid: Destination symbol UID.
        edge_type: One of ``CALLS`` / ``IMPORTS`` / ``EXTENDS`` / ``DEFINES``.
        confidence: 0..1; 1.0 = exact match, 0.3 = name-only guess.
        attrs: Edge metadata (e.g. ``{"line": 42, "via_import": True}``).
    """

    src_uid: str
    dst_uid: str
    edge_type: str
    confidence: float = 1.0
    attrs: dict[str, Any] = field(default_factory=dict)


class CodeGraph:
    """In-memory wrapper around a NetworkX MultiDiGraph.

    Stores symbols as graph nodes (keyed by UID) and edges by type. Provides
    query helpers for callers/callees/class members.
    """

    def __init__(self, symbols: list[Symbol], edges: list[GraphEdge]) -> None:
        self._symbols: dict[str, Symbol] = {s.uid: s for s in symbols}
        self._edges: list[GraphEdge] = edges
        self._graph: nx.MultiDiGraph = nx.MultiDiGraph()
        for sym in symbols:
            self._graph.add_node(sym.uid, kind=sym.kind, name=sym.name, file=sym.file_path)
        for e in edges:
            # Allow edges to dangling UIDs (unresolved external references)
            # so the graph remains queryable.
            self._graph.add_edge(
                e.src_uid,
                e.dst_uid,
                key=f"{e.edge_type}:{len(self._graph.edges)}",
                edge_type=e.edge_type,
                confidence=e.confidence,
                attrs=e.attrs,
            )

    @property
    def symbols(self) -> dict[str, Symbol]:
        return self._symbols

    @property
    def edges(self) -> list[GraphEdge]:
        return self._edges

    @property
    def networkx(self) -> nx.MultiDiGraph:
        return self._graph

    def callers_of(
        self,
        uid: str,
        edge_type: str = EDGE_CALLS,
        min_confidence: float = 0.0,
        max_depth: int = 1,
    ) -> list[tuple[Symbol, float]]:
        """Symbols that directly or transitively reference ``uid``.

        Uses reverse BFS bounded by ``max_depth``. Returns ``(symbol, confidence)``
        tuples; transitive confidence is multiplied along the path.
        """
        if uid not in self._graph:
            return []
        results: dict[str, float] = {}
        frontier: dict[str, float] = {uid: 1.0}
        for _ in range(max_depth):
            next_frontier: dict[str, float] = {}
            for target, conf_so_far in frontier.items():
                for src, _, data in self._graph.in_edges(target, data=True):
                    if data.get("edge_type") != edge_type:
                        continue
                    edge_conf = float(data.get("confidence", 0.0))
                    if edge_conf < min_confidence:
                        continue
                    combined = conf_so_far * edge_conf
                    prev = results.get(src, 0.0)
                    if combined > prev:
                        results[src] = combined
                        next_frontier[src] = combined
            frontier = next_frontier
            if not frontier:
                break
        out: list[tuple[Symbol, float]] = []
        for src_uid, conf in results.items():
            sym = self._symbols.get(src_uid)
            if sym is not None:
                out.append((sym, conf))
        return sorted(out, key=lambda x: x[1], reverse=True)

    def callees_of(
        self,
        uid: str,
        edge_type: str = EDGE_CALLS,
        min_confidence: float = 0.0,
        max_depth: int = 1,
    ) -> list[tuple[Symbol, float]]:
        """Symbols that ``uid`` calls (forward BFS, mirrored from callers_of)."""
        if uid not in self._graph:
            return []
        results: dict[str, float] = {}
        frontier: dict[str, float] = {uid: 1.0}
        for _ in range(max_depth):
            next_frontier: dict[str, float] = {}
            for source, conf_so_far in frontier.items():
                for _, dst, data in self._graph.out_edges(source, data=True):
                    if data.get("edge_type") != edge_type:
                        continue
                    edge_conf = float(data.get("confidence", 0.0))
                    if edge_conf < min_confidence:
                        continue
                    combined = conf_so_far * edge_conf
                    prev = results.get(dst, 0.0)
                    if combined > prev:
                        results[dst] = combined
                        next_frontier[dst] = combined
            frontier = next_frontier
            if not frontier:
                break
        out: list[tuple[Symbol, float]] = []
        for dst_uid, conf in results.items():
            sym = self._symbols.get(dst_uid)
            if sym is not None:
                out.append((sym, conf))
        return sorted(out, key=lambda x: x[1], reverse=True)

    def members_of(self, class_uid: str) -> list[Symbol]:
        """Direct child symbols of a class (methods, nested types)."""
        return [s for s in self._symbols.values() if s.parent_uid == class_uid]

    def query_by_name(self, name: str) -> list[Symbol]:
        """All symbols matching the given short name."""
        return [s for s in self._symbols.values() if s.name == name]


class CodeGraphBuilder:
    """Builds a :class:`CodeGraph` from a set of parsed files.

    Usage::

        builder = CodeGraphBuilder(max_symbols=50_000, min_call_confidence=0.3)
        graph = builder.build(parsed_files)
    """

    def __init__(
        self,
        max_symbols: int = 50_000,
        min_call_confidence: float = 0.3,
    ) -> None:
        self._max_symbols = max_symbols
        self._min_call_confidence = min_call_confidence

    def build(self, parsed_files: dict[str, ParsedFile]) -> CodeGraph:
        # Pass A: collect all symbols. Apply size cap (prune private/_underscore).
        all_symbols: list[Symbol] = []
        for pf in parsed_files.values():
            all_symbols.extend(pf.symbols)
        if len(all_symbols) > self._max_symbols:
            kept = [s for s in all_symbols if not s.name.startswith("_")]
            if len(kept) > self._max_symbols:
                kept = kept[: self._max_symbols]
            logger.warning(
                "code_graph: symbol cap %d exceeded (%d), pruned to %d",
                self._max_symbols,
                len(all_symbols),
                len(kept),
            )
            all_symbols = kept

        symbols_by_uid: dict[str, Symbol] = {s.uid: s for s in all_symbols}

        # Per-file index: file -> {name -> [Symbol]}
        per_file_index: dict[str, dict[str, list[Symbol]]] = defaultdict(lambda: defaultdict(list))
        # Global index: name -> [Symbol]
        global_index: dict[str, list[Symbol]] = defaultdict(list)
        for s in all_symbols:
            per_file_index[s.file_path][s.name].append(s)
            global_index[s.name].append(s)

        edges: list[GraphEdge] = []

        # Pass B: per-file IMPORTS edges, EXTENDS edges, CALLS resolution.
        for file_path, pf in parsed_files.items():
            import_map = self._build_import_map(pf.imports)
            file_local = per_file_index.get(file_path, {})
            # IMPORTS edges: resolve module path to a file when possible.
            edges.extend(self._resolve_imports(pf.imports, file_path, per_file_index))
            # EXTENDS edges: extracted via grammar-specific heritage walk.
            # Currently a stub; emitted from class signatures via name match.
            edges.extend(self._resolve_extends(pf.symbols, file_local, global_index))
            # CALLS edges: scope-aware resolution.
            for call in pf.call_sites:
                if call.callee_name in _CALL_BLOCKLIST:
                    continue
                resolved = self._resolve_call(
                    call_callee=call.callee_name,
                    call_target=call.attr_target,
                    caller_uid=call.caller_uid,
                    file_local=file_local,
                    import_map=import_map,
                    global_index=global_index,
                    symbols_by_uid=symbols_by_uid,
                )
                for dst_uid, confidence in resolved:
                    if confidence < self._min_call_confidence:
                        continue
                    edges.append(
                        GraphEdge(
                            src_uid=call.caller_uid,
                            dst_uid=dst_uid,
                            edge_type=EDGE_CALLS,
                            confidence=confidence,
                            attrs={"line": call.line},
                        )
                    )

        edges = self._break_inheritance_cycles(edges)
        logger.info(
            "code_graph: built %d symbols, %d edges (%d CALLS, %d IMPORTS, %d EXTENDS)",
            len(all_symbols),
            len(edges),
            sum(1 for e in edges if e.edge_type == EDGE_CALLS),
            sum(1 for e in edges if e.edge_type == EDGE_IMPORTS),
            sum(1 for e in edges if e.edge_type == EDGE_EXTENDS),
        )
        return CodeGraph(all_symbols, edges)

    @staticmethod
    def _build_import_map(imports: list[ImportRef]) -> dict[str, str]:
        """Local-name -> source module string.

        For ``from X import Y`` and ``from X import Y as Z`` both ``Y`` and
        ``Z`` map to ``X``. For ``import X as Z``, ``Z`` maps to ``X``.
        """
        m: dict[str, str] = {}
        for imp in imports:
            if imp.imported_names:
                for n in imp.imported_names:
                    m[n] = imp.source_module
            elif imp.alias:
                m[imp.alias] = imp.source_module
            else:
                # Plain `import X`: the local name is the module's last segment.
                tail = imp.source_module.rsplit(".", 1)[-1].rsplit("/", 1)[-1]
                if tail:
                    m[tail] = imp.source_module
        return m

    @staticmethod
    def _resolve_imports(
        imports: list[ImportRef],
        from_file: str,
        per_file_index: dict[str, dict[str, list[Symbol]]],
    ) -> list[GraphEdge]:
        """Best-effort IMPORTS edges to symbols in the target file.

        Resolution is intentionally lossy: we only match when the imported
        symbol exists at the target path. Relative paths are normalized in a
        very limited way (drop leading ``./``).
        """
        edges: list[GraphEdge] = []
        for imp in imports:
            candidates = _candidate_module_paths(imp.source_module, from_file)
            for cand in candidates:
                target_index = per_file_index.get(cand)
                if not target_index:
                    continue
                if imp.imported_names:
                    for name in imp.imported_names:
                        for sym in target_index.get(name, []):
                            edges.append(
                                GraphEdge(
                                    src_uid=f"file:{from_file}",
                                    dst_uid=sym.uid,
                                    edge_type=EDGE_IMPORTS,
                                    confidence=1.0,
                                    attrs={"line": imp.line},
                                )
                            )
                break
        return edges

    @staticmethod
    def _resolve_extends(
        symbols: list[Symbol],
        file_local: dict[str, list[Symbol]],
        global_index: dict[str, list[Symbol]],
    ) -> list[GraphEdge]:
        """EXTENDS edges parsed from a class signature suffix.

        Lossy heuristic over :attr:`Symbol.signature`: looks for ``extends X``,
        ``implements X``, ``(X)`` (Python style), or ``: X`` (TS interfaces).
        """
        edges: list[GraphEdge] = []
        for sym in symbols:
            if sym.kind not in ("class", "interface"):
                continue
            # Prefer AST-extracted bases (CODEIDX-C6); fall back to signature
            # parsing for graphs loaded from pre-C6 DB rows where bases is ().
            base_names = list(sym.bases) or _extract_base_names(sym.signature)
            for base_name in base_names:
                local_matches = file_local.get(base_name, [])
                if len(local_matches) == 1:
                    edges.append(
                        GraphEdge(
                            src_uid=sym.uid,
                            dst_uid=local_matches[0].uid,
                            edge_type=EDGE_EXTENDS,
                            confidence=1.0,
                            attrs={"base_name": base_name},
                        )
                    )
                    continue
                global_matches = global_index.get(base_name, [])
                if len(global_matches) == 1:
                    edges.append(
                        GraphEdge(
                            src_uid=sym.uid,
                            dst_uid=global_matches[0].uid,
                            edge_type=EDGE_EXTENDS,
                            confidence=_CONF_GLOBAL_UNIQUE,
                            attrs={"base_name": base_name},
                        )
                    )
        return edges

    def _resolve_call(
        self,
        *,
        call_callee: str,
        call_target: str | None,
        caller_uid: str,
        file_local: dict[str, list[Symbol]],
        import_map: dict[str, str],
        global_index: dict[str, list[Symbol]],
        symbols_by_uid: dict[str, Symbol],
    ) -> list[tuple[str, float]]:
        """Return possible (dst_uid, confidence) targets for a call site.

        Resolution order:
            1. Local file scope (single match -> 1.0; ambiguous -> 0.4 each).
            2. Imported names (target resolved via import map -> 0.8).
            3. Same-class methods (when call_target is ``self``/``this``).
            4. Global name match (unique -> 0.7; ambiguous -> 0.3 each).
        """
        results: list[tuple[str, float]] = []
        # Local file scope.
        locals_ = file_local.get(call_callee, [])
        if len(locals_) == 1:
            return [(locals_[0].uid, _CONF_EXACT_LOCAL)]
        if len(locals_) > 1:
            return [(s.uid, _CONF_AMBIGUOUS) for s in locals_]

        # Imported: only useful if the caller's file imported the callee.
        # We can't easily get the caller file here without UID parsing, so we
        # parse it back from the UID for a low-cost check.
        if call_target is None and call_callee in import_map:
            module = import_map[call_callee]
            # Try to find the symbol in any file matching that module.
            # This is best-effort; cross-file resolution is fully handled by
            # IMPORTS edges built elsewhere.
            for sym in global_index.get(call_callee, []):
                if _file_matches_module(sym.file_path, module):
                    return [(sym.uid, _CONF_VIA_IMPORT)]

        # `self.x` / `this.x`: resolve within enclosing class.
        if call_target in ("self", "this"):
            caller = symbols_by_uid.get(caller_uid)
            if caller is not None and caller.parent_uid is not None:
                # Find method ``call_callee`` whose parent is caller.parent_uid.
                for s in global_index.get(call_callee, []):
                    if s.parent_uid == caller.parent_uid:
                        return [(s.uid, _CONF_EXACT_LOCAL)]

        # Fall back to global name match.
        globals_ = global_index.get(call_callee, [])
        if len(globals_) == 1:
            return [(globals_[0].uid, _CONF_GLOBAL_UNIQUE)]
        if len(globals_) > 1:
            return [(s.uid, _CONF_NAME_ONLY) for s in globals_]
        return results

    @staticmethod
    def reverse_dependents(existing: CodeGraph, changed_files: set[str]) -> set[str]:
        """Files that import a symbol defined in any ``changed_files`` path.

        Used on incremental runs so an *unchanged* caller whose imported symbols
        changed (rename / new symbol) is re-parsed against the callee's current
        symbols — fixing CODEIDX-C4 cross-file CALLS/IMPORTS drift.

        Only IMPORTS edges are examined because they are the static dependency
        declarations that drive CALLS resolution.  Excludes the changed files
        themselves; they will already be in the parse set.
        """
        if not changed_files:
            return set()
        sym_file: dict[str, str] = {uid: sym.file_path for uid, sym in existing.symbols.items()}
        dependents: set[str] = set()
        for edge in existing.edges:
            if edge.edge_type != EDGE_IMPORTS:
                continue
            dst_file = sym_file.get(edge.dst_uid)
            if dst_file is None or dst_file not in changed_files:
                continue
            if edge.src_uid.startswith("file:"):
                src_file: str | None = edge.src_uid[len("file:") :]
            else:
                src_file = sym_file.get(edge.src_uid)
            if src_file and src_file not in changed_files:
                dependents.add(src_file)
        return dependents

    @staticmethod
    def _break_inheritance_cycles(edges: list[GraphEdge]) -> list[GraphEdge]:
        """Detect cycles in EXTENDS edges; drop the lowest-confidence edge per cycle."""
        ext_graph = nx.DiGraph()
        index: dict[tuple[str, str], GraphEdge] = {}
        for e in edges:
            if e.edge_type != EDGE_EXTENDS:
                continue
            ext_graph.add_edge(e.src_uid, e.dst_uid)
            index[(e.src_uid, e.dst_uid)] = e
        dropped: set[tuple[str, str]] = set()
        try:
            cycles = list(nx.simple_cycles(ext_graph))
        except Exception:
            cycles = []
        for cycle in cycles:
            if len(cycle) < 2:
                continue
            cycle_edges: list[tuple[str, str]] = []
            for i in range(len(cycle)):
                u = cycle[i]
                v = cycle[(i + 1) % len(cycle)]
                if (u, v) in index:
                    cycle_edges.append((u, v))
            if not cycle_edges:
                continue
            weakest = min(cycle_edges, key=lambda uv: index[uv].confidence)
            dropped.add(weakest)
            logger.warning(
                "code_graph: EXTENDS cycle detected, dropping %s -> %s",
                weakest[0],
                weakest[1],
            )
        if not dropped:
            return edges
        return [
            e
            for e in edges
            if not (e.edge_type == EDGE_EXTENDS and (e.src_uid, e.dst_uid) in dropped)
        ]


def _extract_base_names(signature: str) -> list[str]:
    """Pull plausible base-class identifiers from a class signature string.

    Examples handled (best-effort, not exhaustive):
        * ``class A(B, C):`` -> ``["B", "C"]``           (Python)
        * ``class A extends B implements C, D {`` -> ``["B", "C", "D"]``  (TS/JS/Java)
        * ``interface I extends J { ... }`` -> ``["J"]``
    """
    if not signature:
        return []
    bases: list[str] = []
    # Java/TS style: extends X, implements Y. Each keyword can appear at most
    # once and is terminated by the next keyword or a structural token.
    for keyword in ("extends ", "implements "):
        if keyword in signature:
            tail = signature.split(keyword, 1)[1]
            cut = len(tail)
            for stop in ("{", "(", ":", " extends ", " implements "):
                idx = tail.find(stop)
                if 0 <= idx < cut:
                    cut = idx
            piece = tail[:cut]
            for raw in piece.split(","):
                name = raw.strip().split("<", 1)[0].strip()
                if name and name.isidentifier():
                    bases.append(name)
    # Python style: class A(B, C):
    if "class " in signature and "(" in signature and ")" in signature:
        inside = signature[signature.index("(") + 1 : signature.rindex(")")]
        for raw in inside.split(","):
            name = raw.strip().split("=", 1)[0].strip()
            # Strip kwargs/metaclass directives.
            if "metaclass" in name.lower():
                continue
            name = name.split(".")[-1]
            if name and name.isidentifier() and name not in ("object",):
                bases.append(name)
    return bases


def _candidate_module_paths(module: str, from_file: str) -> list[str]:
    """Generate candidate repo-relative file paths a module string might map to.

    Handles a few common cases:
        * Python dotted module ``a.b.c`` -> ``a/b/c.py``, ``a/b/c/__init__.py``.
        * Relative JS/TS paths ``./auth`` or ``../models/user`` resolved against
          ``from_file``'s directory; tries ``.ts``, ``.tsx``, ``.js``, ``.jsx``,
          and ``/index.{ts,tsx,js,jsx}``.
    """
    candidates: list[str] = []
    if not module:
        return candidates
    if module.startswith("."):
        # Relative path. Walk up the directory tree.
        parts = from_file.split("/")
        base_dir = parts[:-1] if len(parts) > 1 else []
        m = module
        while m.startswith("."):
            m = m[1:]
            if m.startswith("/"):
                m = m[1:]
                break
            if base_dir:
                base_dir = base_dir[:-1]
        target_base = "/".join(base_dir + [m]) if m else "/".join(base_dir)
        for ext in (".ts", ".tsx", ".js", ".jsx", ".py"):
            candidates.append(target_base + ext)
        for ext in ("/index.ts", "/index.tsx", "/index.js", "/index.jsx"):
            candidates.append(target_base + ext)
        return candidates
    if "/" in module:
        # JS-style absolute-ish: "src/lib/x"
        for ext in (".ts", ".tsx", ".js", ".jsx", ".py"):
            candidates.append(module + ext)
        return candidates
    # Python dotted module.
    base = module.replace(".", "/")
    candidates.append(base + ".py")
    candidates.append(base + "/__init__.py")
    return candidates


def _file_matches_module(file_path: str, module: str) -> bool:
    """Cheap check that a Python/JS file path corresponds to a module string."""
    for cand in _candidate_module_paths(module, from_file=""):
        if file_path.endswith(cand):
            return True
    if module and module in file_path:
        return True
    return False


__all__ = [
    "CodeGraph",
    "CodeGraphBuilder",
    "EDGE_CALLS",
    "EDGE_DEFINES",
    "EDGE_EXTENDS",
    "EDGE_IMPORTS",
    "GraphEdge",
]
