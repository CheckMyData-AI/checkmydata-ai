"""Cross-source intelligence primitives (Phase 5).

Two foundation utilities that let the system reason *across* data sources
rather than one connection at a time:

* :class:`CrossSourceJoinPlanner` — proposes candidate join keys between tables
  living in **different** database connections (multi-DB JOIN, BACKLOG #22). It
  does not execute anything; it returns ranked, explainable join candidates the
  orchestrator/SQLAgent can use to plan a federated query or warn the user.
* :class:`CrossSourceCausalGraph` — unions intra-DB foreign-key edges with
  code↔DB lineage edges into one directed graph (cross-source causal graph,
  BACKLOG #11), answering "what feeds X?" / "what consumes X?" across the
  code/DB boundary.

Both are **pure** (no I/O, no model coupling): they consume plain dict/struct
inputs so they are trivially testable and reusable from any call site.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field

# --------------------------------------------------------------------------- #
# Multi-DB JOIN planner
# --------------------------------------------------------------------------- #

# Coarse type families so e.g. ``int4``/``bigint``/``integer`` are joinable but
# an int column won't be matched to a free-text column.
_TYPE_FAMILIES: dict[str, str] = {
    "int": "int",
    "integer": "int",
    "bigint": "int",
    "smallint": "int",
    "int2": "int",
    "int4": "int",
    "int8": "int",
    "serial": "int",
    "bigserial": "int",
    "number": "int",
    "numeric": "int",
    "decimal": "int",
    "uuid": "uuid",
    "guid": "uuid",
    "varchar": "text",
    "text": "text",
    "char": "text",
    "string": "text",
    "nvarchar": "text",
    "citext": "text",
    "timestamp": "time",
    "timestamptz": "time",
    "datetime": "time",
    "date": "time",
}


def _type_family(data_type: str) -> str:
    dt = (data_type or "").strip().lower()
    # Strip length/precision, e.g. "varchar(255)" -> "varchar".
    base = dt.split("(", 1)[0].strip()
    return _TYPE_FAMILIES.get(base, base or "unknown")


def _norm_col(name: str) -> str:
    return (name or "").strip().lower()


@dataclass(frozen=True)
class ColumnRef:
    connection_id: str
    table: str
    column: str
    data_type: str = ""

    def qualified(self) -> str:
        return f"{self.connection_id}:{self.table}.{self.column}"


@dataclass(frozen=True)
class JoinCandidate:
    left: ColumnRef
    right: ColumnRef
    confidence: float
    reason: str

    def to_dict(self) -> dict:
        return {
            "left": self.left.qualified(),
            "right": self.right.qualified(),
            "confidence": round(self.confidence, 3),
            "reason": self.reason,
        }


class CrossSourceJoinPlanner:
    """Proposes join keys between tables in *different* connections.

    Input ``schemas`` shape::

        {
          connection_id: [
            {"name": "orders",
             "columns": [{"name": "customer_id", "data_type": "int",
                          "is_primary_key": False}, ...],
             "foreign_keys": [{"column": "customer_id",
                               "references_table": "customers",
                               "references_column": "id"}]},
            ...
          ],
          ...
        }
    """

    # Names that are too generic to be a confident join key on their own.
    _WEAK_NAMES = {"id", "name", "type", "status", "created_at", "updated_at"}

    def plan(
        self,
        schemas: dict[str, list[dict]],
        *,
        min_confidence: float = 0.4,
        max_candidates: int = 50,
    ) -> list[JoinCandidate]:
        # Build an index of columns keyed by normalized name.
        by_name: dict[str, list[tuple[ColumnRef, bool, bool]]] = defaultdict(list)
        for conn_id, tables in schemas.items():
            for table in tables or []:
                tname = table.get("name", "")
                pk_cols = {
                    _norm_col(c["name"])
                    for c in table.get("columns", [])
                    if c.get("is_primary_key")
                }
                fk_cols = {_norm_col(fk["column"]) for fk in table.get("foreign_keys", [])}
                for col in table.get("columns", []):
                    cname = _norm_col(col.get("name", ""))
                    if not cname:
                        continue
                    ref = ColumnRef(
                        connection_id=conn_id,
                        table=tname,
                        column=col.get("name", ""),
                        data_type=col.get("data_type", ""),
                    )
                    by_name[cname].append((ref, cname in pk_cols, cname in fk_cols))

        candidates: list[JoinCandidate] = []
        for cname, refs in by_name.items():
            # Only cross-connection pairs are interesting here.
            for i in range(len(refs)):
                for j in range(i + 1, len(refs)):
                    left, l_pk, l_fk = refs[i]
                    right, r_pk, r_fk = refs[j]
                    if left.connection_id == right.connection_id:
                        continue
                    if _type_family(left.data_type) != _type_family(right.data_type):
                        continue
                    conf, reason = self._score(cname, l_pk, l_fk, r_pk, r_fk)
                    if conf >= min_confidence:
                        candidates.append(
                            JoinCandidate(left=left, right=right, confidence=conf, reason=reason)
                        )

        candidates.sort(key=lambda c: c.confidence, reverse=True)
        return candidates[:max_candidates]

    def _score(
        self,
        cname: str,
        l_pk: bool,
        l_fk: bool,
        r_pk: bool,
        r_fk: bool,
    ) -> tuple[float, str]:
        score = 0.5
        reasons: list[str] = ["name+type match"]

        # ``<entity>_id`` style keys are strong join signals.
        if cname.endswith("_id"):
            score += 0.2
            reasons.append("id-suffix")
        elif cname in self._WEAK_NAMES:
            score -= 0.2
            reasons.append("generic-name")

        # A PK↔FK pairing across sources is the canonical join.
        if (l_pk and r_fk) or (r_pk and l_fk):
            score += 0.25
            reasons.append("pk↔fk")
        elif l_fk and r_fk:
            score += 0.1
            reasons.append("shared-fk")

        return max(0.0, min(1.0, score)), ", ".join(reasons)


# --------------------------------------------------------------------------- #
# Cross-source causal graph
# --------------------------------------------------------------------------- #


@dataclass
class CrossSourceCausalGraph:
    """Directed graph unioning FK edges + code→DB lineage edges.

    Node id conventions:

    * ``db:{connection_id}:{schema.table}`` — a database table.
    * ``code:{entity}`` — a code entity (model/repository/etc).

    Edge direction is *data flow*: ``A -> B`` means "A feeds/produces B" (a FK
    child references its parent; code that writes a table feeds that table).
    """

    _out: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    _in: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    _labels: dict[str, str] = field(default_factory=dict)

    @staticmethod
    def db_node(connection_id: str, table: str) -> str:
        return f"db:{connection_id}:{table}"

    @staticmethod
    def code_node(entity: str) -> str:
        return f"code:{entity}"

    def _edge(self, src: str, dst: str) -> None:
        if src == dst:
            return
        self._out[src].add(dst)
        self._in[dst].add(src)

    def add_fk_edges(self, connection_id: str, tables: Iterable[dict]) -> None:
        """Add intra-DB foreign-key edges (child table -> referenced table)."""
        for table in tables or []:
            tname = table.get("name", "")
            if not tname:
                continue
            child = self.db_node(connection_id, tname)
            self._labels[child] = tname
            for fk in table.get("foreign_keys", []):
                ref_table = fk.get("references_table")
                if not ref_table:
                    continue
                parent = self.db_node(connection_id, ref_table)
                self._labels.setdefault(parent, ref_table)
                # Child references parent → parent feeds child.
                self._edge(parent, child)

    def add_lineage_edges(self, connection_id: str, sync_rows: Iterable) -> None:
        """Add code→DB lineage edges from CodeDbSync rows.

        Each row exposes ``entity_name``, ``table_name`` and read/write counts.
        A write means code *feeds* the table (code -> table); a read-only
        relationship means the table *feeds* the code (table -> code).
        """
        for row in sync_rows or []:
            entity = getattr(row, "entity_name", None)
            table = getattr(row, "table_name", None)
            if not entity or not table:
                continue
            code = self.code_node(entity)
            tbl = self.db_node(connection_id, table)
            self._labels.setdefault(code, entity)
            self._labels.setdefault(tbl, table)
            writes = int(getattr(row, "write_count", 0) or 0)
            reads = int(getattr(row, "read_count", 0) or 0)
            if writes > 0:
                self._edge(code, tbl)
            if reads > 0 or writes == 0:
                self._edge(tbl, code)

    def upstream(self, node: str, *, max_depth: int = 5) -> set[str]:
        """All nodes that (transitively) feed ``node``."""
        return self._walk(node, self._in, max_depth)

    def downstream(self, node: str, *, max_depth: int = 5) -> set[str]:
        """All nodes ``node`` (transitively) feeds."""
        return self._walk(node, self._out, max_depth)

    def _walk(self, start: str, adj: dict[str, set[str]], max_depth: int) -> set[str]:
        seen: set[str] = set()
        frontier = {start}
        depth = 0
        while frontier and depth < max_depth:
            nxt: set[str] = set()
            for n in frontier:
                for m in adj.get(n, set()):
                    if m not in seen and m != start:
                        seen.add(m)
                        nxt.add(m)
            frontier = nxt
            depth += 1
        return seen

    def label(self, node: str) -> str:
        return self._labels.get(node, node)

    def node_count(self) -> int:
        return len({*self._out, *self._in})

    def edge_count(self) -> int:
        return sum(len(v) for v in self._out.values())


__all__ = [
    "ColumnRef",
    "CrossSourceCausalGraph",
    "CrossSourceJoinPlanner",
    "JoinCandidate",
]
