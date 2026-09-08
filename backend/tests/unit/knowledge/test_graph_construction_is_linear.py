"""Building a `CodeGraph` must not be quadratic in its edge count.

Measured on production 2026-09-08, and this is what killed the catch-up index for the
one real project — three times, on three different days:

    20:49:26  graph_build: started (Building code graph from 82 parsed files)
    20:49:27  code_graph: built 408 symbols, 516 edges
              ...fourteen and a half minutes of complete silence...
    20:55:09  Reaper: reset stale runs — repo=1 runs=2 (timeout=300s)
    21:03:57  graph_build: re-parsing 231 reverse-dependent file(s)   <- STILL ALIVE
    21:03:59  code_graph: built 1378 symbols, 2299 edges

The run was reaped at 20:55 and was still working at 21:03. Between those two log lines
`pipeline_runner` does exactly two things: `CodeGraphService.load_graph`, and
`CodeGraphBuilder.reverse_dependents` over what it returned. The second measures
**0.009 s** against the production graph, so all of it is the first — and inside it,
`CodeGraph.__init__`.

The cause is one expression, `code_graph.py:158`:

    key=f"{e.edge_type}:{len(self._graph.edges)}",

`G.edges` is a view, and `len()` on it walks the adjacency structure — O(V + E) — so
calling it once per edge added makes construction O(E·(V+E)). The key value itself is
never read by anything; it exists only to keep parallel edges distinct in a
`MultiDiGraph`, which a plain counter does for free.

Measured at the production shape (25,695 symbols, 68,263 edges) on a 2026 laptop:
**209.6 s**. A Heroku Standard dyno core is materially slower, which is how 3.5 minutes
becomes the observed ~14. And it is pure synchronous Python with no `await` in it, so
for its whole duration the event loop is blocked — the run's heartbeat coroutine cannot
be scheduled, `IndexingRun.heartbeat_at` goes stale, and `StaleRunReaper` kills a run
that is working perfectly.

That last part is why this is not merely a performance ticket. T10.1 gave the run a
heartbeat on the row the reaper reads; a beat that cannot be scheduled is worth exactly
as much as no beat at all.
"""

from __future__ import annotations

import time

from app.knowledge.code_graph import CodeGraph, GraphEdge, Symbol


def _graph_of(n_symbols: int, n_edges: int) -> tuple[list[Symbol], list[GraphEdge]]:
    symbols = [
        Symbol(
            uid=f"u{i}",
            kind="function",
            name=f"n{i}",
            file_path=f"f{i % 500}.php",
            start_line=1,
            end_line=2,
            language="php",
        )
        for i in range(n_symbols)
    ]
    edges = [
        GraphEdge(
            src_uid=f"u{i % n_symbols}",
            dst_uid=f"u{(i * 7 + 3) % n_symbols}",
            edge_type="CALLS",
            confidence=1.0,
            attrs={},
        )
        for i in range(n_edges)
    ]
    return symbols, edges


def _build_seconds(n_symbols: int, n_edges: int) -> float:
    symbols, edges = _graph_of(n_symbols, n_edges)
    start = time.monotonic()
    CodeGraph(symbols=symbols, edges=edges)
    return time.monotonic() - start


class TestConstructionScales:
    def test_the_edge_view_is_not_measured_once_per_edge(self) -> None:
        """The defect mechanically, independent of how fast the machine is.

        A timing ratio was the first version of this test and it passed against the
        defect: predicting the ratio requires knowing what `len()` on the view costs at a
        given shape, and that depends on how many DISTINCT (src, dst) pairs the fixture
        happens to produce. Counting the calls needs no such model — asking an O(V+E)
        view for its length once per edge is the defect, whatever each call costs.

        This names a networkx internal deliberately. The interaction with that internal
        IS the subject; if the class is renamed the test errors loudly, which is the
        outcome to want over passing silently.
        """
        from networkx.classes.reportviews import OutMultiEdgeView

        calls = 0
        original = OutMultiEdgeView.__len__

        def counting_len(self):  # noqa: ANN001, ANN202
            nonlocal calls
            calls += 1
            return original(self)

        n_edges = 2_000
        OutMultiEdgeView.__len__ = counting_len
        try:
            symbols, edges = _graph_of(600, n_edges)
            CodeGraph(symbols=symbols, edges=edges)
        finally:
            OutMultiEdgeView.__len__ = original

        assert calls < n_edges / 10, (
            f"the edge view was measured {calls} times while adding {n_edges} edges; "
            "each measurement walks the whole adjacency structure, so construction is "
            "O(E x (V+E)) — fourteen minutes at production scale, on the event loop, "
            "with the run's heartbeat unable to be scheduled for any of it"
        )

    def test_a_production_sized_graph_builds_promptly(self) -> None:
        """An absolute ceiling, because a ratio alone would pass if BOTH sizes were slow.

        40,000 edges is well under production's 68,263 and takes ~60 s with the quadratic
        expression in place. The ceiling is generous enough that only the defect trips it.
        """
        elapsed = _build_seconds(15_000, 40_000)
        assert elapsed < 10.0, (
            f"building a 40,000-edge graph took {elapsed:.1f}s; production carries 68,263 "
            "edges and this runs on the event loop with no await in it"
        )


class TestParallelEdgesSurvive:
    """The key exists to keep parallel edges distinct. Making it cheap must not make it
    collide — a collision does not raise, it silently overwrites one edge with another."""

    def test_repeated_pairs_are_all_kept(self) -> None:
        symbols = [
            Symbol(
                uid=u,
                kind="function",
                name=u,
                file_path="a.php",
                start_line=1,
                end_line=2,
                language="php",
            )
            for u in ("a", "b")
        ]
        edges = [
            GraphEdge(src_uid="a", dst_uid="b", edge_type="CALLS", confidence=c, attrs={})
            for c in (0.1, 0.5, 0.9)
        ]
        graph = CodeGraph(symbols=symbols, edges=edges)
        assert graph.networkx.number_of_edges("a", "b") == 3, (
            "parallel edges collapsed — the key stopped being unique"
        )

    def test_every_edge_reaches_the_networkx_view(self) -> None:
        symbols, edges = _graph_of(300, 2_000)
        graph = CodeGraph(symbols=symbols, edges=edges)
        assert graph.networkx.number_of_edges() == len(edges)
        assert len(graph.edges) == len(edges)

    def test_edges_of_different_types_between_one_pair_coexist(self) -> None:
        symbols = [
            Symbol(
                uid=u,
                kind="class",
                name=u,
                file_path="a.php",
                start_line=1,
                end_line=2,
                language="php",
            )
            for u in ("a", "b")
        ]
        edges = [
            GraphEdge(src_uid="a", dst_uid="b", edge_type=t, confidence=1.0, attrs={})
            for t in ("CALLS", "IMPORTS", "EXTENDS")
        ]
        graph = CodeGraph(symbols=symbols, edges=edges)
        assert graph.networkx.number_of_edges("a", "b") == 3
