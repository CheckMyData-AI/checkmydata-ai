"""An incremental graph save must write the delta, not the whole graph.

Measured on production 2026-09-08. `esim-php` holds **25,695 symbols and 68,263 edges**.
An incremental run that produced 408 symbols and 516 edges took longer than five minutes
in persistence alone, which is what let the reaper kill it (T10 fixed the heartbeat; this
is the other half — why the window was long enough to matter).

`save_incremental` loads the whole graph, loads the symbols a second time for cluster
membership, merges in memory, and hands the union to `save()` — which
`DELETE`s every symbol and every edge of the project and bulk-inserts the union back.
For a 408-symbol delta that is roughly **188,000 row writes and 120,000 row reads**.

The merge SEMANTICS must not change, and two of them are subtle enough to be worth
naming, because a naive delta write loses both:

* an edge is kept from the existing graph only when its **source file** is unaffected
  (`file:<path>` pseudo-sources are attributed to `<path>`);
* R3-1: after the merge, an edge from an *unchanged* file may point at a symbol that was
  renamed or deleted in a *changed* one. Those danglers have no foreign key to catch them
  and corrupt traversal and clustering, so they are pruned against the **whole** symbol
  set — not just the delta's.

So the delta write keeps the second as a set-wise `DELETE` the database evaluates, rather
than as a Python pass over a graph it no longer has in memory.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.knowledge.code_graph import CodeGraph, CodeGraphBuilder, GraphEdge, Symbol
from app.models.base import Base
from app.models.code_graph import CodeGraphEdge, CodeGraphSymbol
from app.services.code_graph_service import CodeGraphService


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


def _sym(uid: str, path: str, name: str | None = None) -> Symbol:
    return Symbol(
        uid=uid,
        kind="function",
        name=name or uid.split(":")[-1],
        file_path=path,
        start_line=1,
        end_line=2,
        parent_uid=None,
        language="python",
        decorators=[],
        signature="",
        docstring="",
    )


def _edge(src: str, dst: str) -> GraphEdge:
    return GraphEdge(src_uid=src, dst_uid=dst, edge_type="CALLS", confidence=1.0, attrs={})


async def _seed(db: AsyncSession, project: str, n_files: int = 12) -> CodeGraph:
    """A graph with several files, cross-file edges, and one `file:` import source."""
    symbols = [_sym(f"py:f{i}:fn", f"src/f{i}.py") for i in range(n_files)]
    edges = [_edge(f"py:f{i}:fn", f"py:f{i + 1}:fn") for i in range(n_files - 1)]
    edges.append(_edge("file:src/f0.py", "py:f3:fn"))
    graph = CodeGraph(symbols=symbols, edges=edges)
    await CodeGraphService().save(db, project, graph)
    await db.commit()
    return graph


class _DmlCounter:
    """Counts INSERT/DELETE statements and the parameter values the INSERTs carry.

    Statement count alone would not catch the defect: the full replace is only two
    DELETEs and a handful of chunked INSERTs. What distinguishes a delta from a rewrite
    is the VOLUME moved, and parameter values are what the driver actually ships.

    Parameters, not rows, and the distinction is deliberate rather than sloppy:
    SQLAlchemy's insertmanyvalues sends one statement with a flat parameter list, so ten
    symbol rows arrive as `executemany=True` with `len(parameters) == 140` — fourteen
    columns each — while a single row arrives as `executemany=False`. Deriving a row
    count from that means dividing by a column count parsed out of the statement, which
    would be a fragile measurement of a quantity this test does not need. Measured at the
    production shape: the full replace ships **837,571** parameter values, a 36-symbol
    delta ships **1,176**.
    """

    def __init__(self) -> None:
        self.deletes = 0
        self.inserts = 0
        self.insert_params = 0

    def attach(self, session: AsyncSession):
        bind = session.get_bind()
        # Depending on how the session was bound this is already the sync Engine.
        sync_engine = getattr(bind, "sync_engine", bind)

        @event.listens_for(sync_engine, "before_cursor_execute")
        def _before(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
            head = statement.lstrip()[:6].upper()
            if head.startswith("DELETE"):
                self.deletes += 1
            elif head.startswith("INSERT"):
                self.inserts += 1
                self.insert_params += len(parameters) if executemany else 1

        return _before


class TestTheWriteIsProportionalToTheChange:
    async def test_an_incremental_save_does_not_reinsert_the_world(self, db) -> None:
        project = "p-delta"
        await _seed(db, project, n_files=12)

        counter = _DmlCounter()
        counter.attach(db)

        # One file changed, one symbol in it.
        delta = CodeGraph(symbols=[_sym("py:f5:fn", "src/f5.py", "renamed")], edges=[])
        await CodeGraphService().save_incremental(db, project, delta, {"src/f5.py"})
        await db.commit()

        assert counter.insert_params <= 20, (
            f"{counter.insert_params} parameter values shipped for a ONE-symbol delta "
            "(one row is fourteen of them) — the whole graph is being rewritten. At the "
            "production shape that is 837,571 values for a change of a few hundred"
        )

    async def test_unaffected_rows_are_left_alone(self, db) -> None:
        """The proof that it is a delta and not a coincidence: rows the change does not
        touch keep their identity. A full replace gives every surviving symbol a new
        primary key."""
        project = "p-ids"
        await _seed(db, project, n_files=8)
        before = dict(
            (
                await db.execute(
                    select(CodeGraphSymbol.uid, CodeGraphSymbol.id).where(
                        CodeGraphSymbol.project_id == project
                    )
                )
            ).all()
        )

        delta = CodeGraph(symbols=[_sym("py:f2:fn", "src/f2.py")], edges=[])
        await CodeGraphService().save_incremental(db, project, delta, {"src/f2.py"})
        await db.commit()

        after = dict(
            (
                await db.execute(
                    select(CodeGraphSymbol.uid, CodeGraphSymbol.id).where(
                        CodeGraphSymbol.project_id == project
                    )
                )
            ).all()
        )
        untouched = {u for u in before if u != "py:f2:fn"}
        assert untouched <= set(after), "symbols outside the changed file disappeared"
        assert all(before[u] == after[u] for u in untouched), (
            "symbols outside the changed file were deleted and reinserted"
        )


class TestTheMergeSemanticsAreUnchanged:
    """Everything here held before the delta write and must hold after. These are the
    rules a naive delta silently breaks."""

    async def test_changed_file_symbols_are_replaced_not_duplicated(self, db) -> None:
        project = "p-replace"
        await _seed(db, project, n_files=6)
        delta = CodeGraph(symbols=[_sym("py:f1:fn2", "src/f1.py")], edges=[])
        await CodeGraphService().save_incremental(db, project, delta, {"src/f1.py"})
        await db.commit()

        rows = (
            (
                await db.execute(
                    select(CodeGraphSymbol.uid).where(
                        CodeGraphSymbol.project_id == project,
                        CodeGraphSymbol.file_path == "src/f1.py",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert set(rows) == {"py:f1:fn2"}, "the old symbol of a changed file survived"

    async def test_a_deleted_file_vanishes(self, db) -> None:
        project = "p-deleted"
        await _seed(db, project, n_files=6)
        await CodeGraphService().save_incremental(
            db, project, CodeGraph(symbols=[], edges=[]), {"src/f4.py"}
        )
        await db.commit()

        left = await db.scalar(
            select(func.count(CodeGraphSymbol.id)).where(
                CodeGraphSymbol.project_id == project,
                CodeGraphSymbol.file_path == "src/f4.py",
            )
        )
        assert left == 0

    async def test_dangling_edges_from_unchanged_files_are_pruned(self, db) -> None:
        """R3-1, and the rule a delta write is most likely to lose.

        `src/f2.py` is unchanged and holds an edge into `src/f3.py`. `src/f3.py` changes
        and its symbol goes away. The edge now points at nothing — and edges have no
        foreign key, so nothing else would catch it.
        """
        project = "p-dangle"
        await _seed(db, project, n_files=6)
        await CodeGraphService().save_incremental(
            db, project, CodeGraph(symbols=[], edges=[]), {"src/f3.py"}
        )
        await db.commit()

        dangling = await db.scalar(
            select(func.count(CodeGraphEdge.id)).where(
                CodeGraphEdge.project_id == project,
                CodeGraphEdge.dst_uid == "py:f3:fn",
            )
        )
        assert dangling == 0, (
            "an edge from an unchanged file still points at a symbol deleted with its "
            "file; this corrupts traversal and clustering and has no FK to catch it"
        )

    async def test_file_pseudo_sources_are_attributed_to_their_path(self, db) -> None:
        """A `file:<path>` IMPORTS source belongs to `<path>`: when that file changes,
        its edges go with it, and when it does not, they stay."""
        project = "p-file-src"
        await _seed(db, project, n_files=6)

        # f0 is unaffected -> its file: edge survives.
        await CodeGraphService().save_incremental(
            db, project, CodeGraph(symbols=[_sym("py:f1:fn", "src/f1.py")], edges=[]), {"src/f1.py"}
        )
        await db.commit()
        assert await db.scalar(
            select(func.count(CodeGraphEdge.id)).where(
                CodeGraphEdge.project_id == project,
                CodeGraphEdge.src_uid == "file:src/f0.py",
            )
        )

        # f0 changes and supplies no edges -> its file: edge goes.
        await CodeGraphService().save_incremental(
            db, project, CodeGraph(symbols=[], edges=[]), {"src/f0.py"}
        )
        await db.commit()
        assert not await db.scalar(
            select(func.count(CodeGraphEdge.id)).where(
                CodeGraphEdge.project_id == project,
                CodeGraphEdge.src_uid == "file:src/f0.py",
            )
        )

    async def _cluster_of(self, db, project: str, uid: str) -> str | None:
        return await db.scalar(
            select(CodeGraphSymbol.cluster_id).where(
                CodeGraphSymbol.project_id == project,
                CodeGraphSymbol.uid == uid,
            )
        )

    async def test_cluster_membership_survives_outside_the_change(self, db) -> None:
        """R3-2, the easy half: a symbol in a file the run did not re-parse."""
        project = "p-cluster"
        await _seed(db, project, n_files=6)
        await db.execute(
            CodeGraphSymbol.__table__.update()
            .where(
                CodeGraphSymbol.project_id == project,
                CodeGraphSymbol.uid == "py:f0:fn",
            )
            .values(cluster_id="c-42")
        )
        await db.commit()

        await CodeGraphService().save_incremental(
            db, project, CodeGraph(symbols=[_sym("py:f1:fn", "src/f1.py")], edges=[]), {"src/f1.py"}
        )
        await db.commit()

        assert await self._cluster_of(db, project, "py:f0:fn") == "c-42"

    async def test_cluster_membership_survives_inside_the_change(self, db) -> None:
        """R3-2 INSIDE the change — the half that actually broke, and the reason this test
        exists at all is that the first version of the one above passed while it did.

        A re-parsed file usually yields the same uids: the file changed, most of its
        symbols did not. The full replace carried their membership through a project-wide
        `cluster_map`; a delta deletes and reinserts exactly these rows, so it must carry
        it too. Reasoning that "a surviving symbol is not rewritten" is true only of
        symbols outside the affected set, and stating it about all of them silently
        nulled the cluster of every symbol in every changed file — which is where
        clustering is most likely to still be right.
        """
        project = "p-cluster-in"
        await _seed(db, project, n_files=6)
        await db.execute(
            CodeGraphSymbol.__table__.update()
            .where(
                CodeGraphSymbol.project_id == project,
                CodeGraphSymbol.uid == "py:f3:fn",
            )
            .values(cluster_id="c-7")
        )
        await db.commit()

        # `src/f3.py` is re-parsed and still contains `py:f3:fn`.
        await CodeGraphService().save_incremental(
            db, project, CodeGraph(symbols=[_sym("py:f3:fn", "src/f3.py")], edges=[]), {"src/f3.py"}
        )
        await db.commit()

        assert await self._cluster_of(db, project, "py:f3:fn") == "c-7", (
            "a re-parsed symbol lost its cluster; the next clustering pass is what would "
            "have to notice, and nothing reports the gap in between"
        )

    async def test_a_genuinely_new_symbol_is_unclustered(self, db) -> None:
        """The boundary of the rule above: membership is carried by uid, never invented.
        A uid that did not exist before belongs to no cluster until clustering runs."""
        project = "p-cluster-new"
        await _seed(db, project, n_files=4)
        await CodeGraphService().save_incremental(
            db,
            project,
            CodeGraph(symbols=[_sym("py:f1:brand_new", "src/f1.py")], edges=[]),
            {"src/f1.py"},
        )
        await db.commit()
        assert await self._cluster_of(db, project, "py:f1:brand_new") is None

    async def test_another_project_is_never_touched(self, db) -> None:
        await _seed(db, "p-a", n_files=4)
        await _seed(db, "p-b", n_files=4)
        before = await db.scalar(
            select(func.count(CodeGraphSymbol.id)).where(CodeGraphSymbol.project_id == "p-b")
        )
        await CodeGraphService().save_incremental(
            db, "p-a", CodeGraph(symbols=[], edges=[]), {"src/f1.py"}
        )
        await db.commit()
        assert (
            await db.scalar(
                select(func.count(CodeGraphSymbol.id)).where(CodeGraphSymbol.project_id == "p-b")
            )
            == before
        )

    async def test_an_empty_project_still_falls_back_to_a_full_save(self, db) -> None:
        """The documented degradation: no persisted graph yet -> plain `save`."""
        graph = CodeGraph(symbols=[_sym("py:x:fn", "src/x.py")], edges=[])
        syms, edges = await CodeGraphService().save_incremental(db, "p-empty", graph, set())
        await db.commit()
        assert syms == 1 and edges == 0


@pytest.mark.parametrize("n", [1, 3])
async def test_the_returned_counts_describe_the_whole_graph(db, n: int) -> None:
    """Callers log these as "the project's graph", and `pipeline_end` reports them, so a
    delta write must not start returning the size of the delta."""
    project = f"p-counts-{n}"
    await _seed(db, project, n_files=10)
    delta = CodeGraph(symbols=[_sym(f"py:f{n}:fn", f"src/f{n}.py")], edges=[])
    syms, _edges = await CodeGraphService().save_incremental(db, project, delta, {f"src/f{n}.py"})
    await db.commit()

    total = await db.scalar(
        select(func.count(CodeGraphSymbol.id)).where(CodeGraphSymbol.project_id == project)
    )
    assert syms == total


class TestSpecificationsInheritedFromTheMergeFunction:
    """`CodeGraphService._merge_graphs` and `_prune_dangling_edges` were the in-memory
    merge the delta write replaced, and they carried two specifications worth more than
    the functions did: R3-1's five dangling-edge shapes, and CODEIDX-C4.

    Their tests were passing against code production no longer called — which is the
    worst state for a test to be in, because green reads as covered. Ported here against
    `save_incremental` itself, then the two functions were deleted.
    """

    async def test_a_delta_leaves_alone_what_it_did_not_invalidate(self, db) -> None:
        """The five edge shapes from the old `_prune_dangling_edges` table — and the
        verdict on three of them is now the opposite, deliberately.

        That function dropped every edge with an unresolved endpoint, and the merge ran
        it over the WHOLE project on every incremental run. It reads as hygiene. It was
        not: `CodeGraph` keeps edges to unresolved UIDs on purpose — "Allow edges to
        dangling UIDs (unresolved external references) so the graph remains queryable",
        `code_graph.py:153` — and `save`, the full rebuild, stores them. So the two write
        paths disagreed about what a stored graph contains, and every incremental run
        silently deleted external references that the last full run had just written.
        Nothing could depend on the swept state either, since the next full rebuild
        restored it.

        R3-1's actual requirement is narrower and is unchanged: an edge must not survive
        pointing at a symbol THIS run removed. That is
        `test_dangling_edges_from_unchanged_files_are_pruned` above, and it still passes.
        Here nothing was removed, so nothing may be dropped.
        """
        project = "p-shapes"
        a = _sym("py:a:fn", "src/a.py")
        b = _sym("py:b:fn", "src/b.py")
        edges = [
            _edge(a.uid, b.uid),  # both endpoints resolve
            _edge(a.uid, "py:gone:x"),  # unresolved dst — an external reference
            _edge("py:gone:y", b.uid),  # unresolved src, not a `file:` pseudo-source
            GraphEdge(  # `file:` pseudo-source, resolved dst
                src_uid="file:src/a.py",
                dst_uid=b.uid,
                edge_type="IMPORTS",
                confidence=1.0,
                attrs={},
            ),
            GraphEdge(  # `file:` pseudo-source, unresolved dst
                src_uid="file:src/a.py",
                dst_uid="py:gone:z",
                edge_type="IMPORTS",
                confidence=1.0,
                attrs={},
            ),
        ]
        await CodeGraphService().save(db, project, CodeGraph(symbols=[a, b], edges=edges))
        await db.commit()

        # A delta on a file holding nothing: no symbol disappears, so no edge may.
        await CodeGraphService().save_incremental(
            db, project, CodeGraph(symbols=[], edges=[]), {"src/c.py"}
        )
        await db.commit()

        kept = {
            (src, dst)
            for src, dst in (
                await db.execute(
                    select(CodeGraphEdge.src_uid, CodeGraphEdge.dst_uid).where(
                        CodeGraphEdge.project_id == project
                    )
                )
            ).all()
        }
        assert kept == {(src, dst) for src, dst in ((e.src_uid, e.dst_uid) for e in edges)}, (
            "an incremental run deleted edges it did not invalidate; a full rebuild "
            "writes these, so the two write paths would disagree about the same repo"
        )

    async def test_an_edge_to_a_renamed_symbol_does_not_survive(self, db) -> None:
        """R3-1 proper: `src/a.py` is untouched, so its edge is never considered for
        deletion by the affected-files rule — only the dangling prune can catch it."""
        project = "p-renamed"
        caller = _sym("py:a:caller", "src/a.py")
        old = _sym("py:b:old", "src/b.py")
        await CodeGraphService().save(
            db, project, CodeGraph(symbols=[caller, old], edges=[_edge(caller.uid, old.uid)])
        )
        await db.commit()

        await CodeGraphService().save_incremental(
            db,
            project,
            CodeGraph(symbols=[_sym("py:b:new", "src/b.py")], edges=[]),
            {"src/b.py"},
        )
        await db.commit()

        uids = set(
            (
                await db.execute(
                    select(CodeGraphSymbol.uid).where(CodeGraphSymbol.project_id == project)
                )
            )
            .scalars()
            .all()
        )
        assert uids == {"py:a:caller", "py:b:new"}
        assert (
            await db.scalar(
                select(func.count(CodeGraphEdge.id)).where(CodeGraphEdge.project_id == project)
            )
        ) == 0, "the stale edge to the renamed symbol survived"

    async def test_a_reparsed_caller_relinks_to_the_renamed_callee(self, db) -> None:
        """CODEIDX-C4, end to end.

        `helper.py` changed; `caller.py` did not, but it imports from it, so
        `reverse_dependents` puts it in the re-parse set and therefore in
        `affected_files`. Its stale edges are dropped with it and the freshly resolved
        ones splice in. Without the reverse-dep expansion the caller would keep pointing
        at a symbol that no longer exists — which the prune would then delete, leaving the
        call graph silently short an edge rather than wrong.
        """
        project = "p-c4"
        caller = _sym("caller.py:caller", "caller.py")
        old_helper = _sym("helper.py:old_helper", "helper.py")
        existing = CodeGraph(
            symbols=[caller, old_helper],
            edges=[
                _edge(caller.uid, old_helper.uid),
                GraphEdge(
                    src_uid="file:caller.py",
                    dst_uid=old_helper.uid,
                    edge_type="IMPORTS",
                    confidence=1.0,
                    attrs={},
                ),
            ],
        )
        await CodeGraphService().save(db, project, existing)
        await db.commit()

        # The step `pipeline_runner` performs before calling `save_incremental`. This
        # function is still live production code, so the assertion stays with the case
        # that explains why it exists.
        extra = CodeGraphBuilder.reverse_dependents(existing, {"helper.py"})
        assert "caller.py" in extra, "reverse_dependents must flag the importer for re-parse"

        new_helper = _sym("helper.py:new_helper", "helper.py")
        await CodeGraphService().save_incremental(
            db,
            project,
            CodeGraph(
                symbols=[new_helper, caller],
                edges=[
                    _edge(caller.uid, new_helper.uid),
                    GraphEdge(
                        src_uid="file:caller.py",
                        dst_uid=new_helper.uid,
                        edge_type="IMPORTS",
                        confidence=1.0,
                        attrs={},
                    ),
                ],
            ),
            {"helper.py"} | extra,
        )
        await db.commit()

        uids = set(
            (
                await db.execute(
                    select(CodeGraphSymbol.uid).where(CodeGraphSymbol.project_id == project)
                )
            )
            .scalars()
            .all()
        )
        assert uids == {"caller.py:caller", "helper.py:new_helper"}
        calls_in = (
            await db.scalar(
                select(func.count(CodeGraphEdge.id)).where(
                    CodeGraphEdge.project_id == project,
                    CodeGraphEdge.dst_uid == "helper.py:new_helper",
                    CodeGraphEdge.edge_type == "CALLS",
                )
            )
        ) or 0
        assert calls_in == 1, "the re-parsed caller lost its CALLS edge to the renamed callee"
