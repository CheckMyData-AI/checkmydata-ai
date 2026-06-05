"""Integration tests for :class:`CodeGraphService` (M2).

Exercise the full-replace + read paths against an in-memory SQLite database
created by the shared ``db_session`` fixture.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.knowledge.ast_parser import Symbol
from app.knowledge.code_graph import (
    EDGE_CALLS,
    EDGE_EXTENDS,
    CodeGraph,
    GraphEdge,
)
from app.models.project import Project
from app.models.user import User
from app.services.code_graph_service import CodeGraphService


@pytest_asyncio.fixture
async def project_id(db_session: AsyncSession) -> str:
    """Create a user + project to satisfy FK constraints on code_graph_symbols."""
    user = User(
        id=str(uuid.uuid4()),
        email=f"user-{uuid.uuid4().hex[:6]}@test.example",
        password_hash="x",
        display_name="Test",
    )
    db_session.add(user)
    await db_session.flush()

    project = Project(
        id=str(uuid.uuid4()),
        name="Test project",
        owner_id=user.id,
        repo_url="git@example.com:foo/bar.git",
    )
    db_session.add(project)
    await db_session.flush()
    return project.id


def _make_graph() -> CodeGraph:
    symbols = [
        Symbol(
            uid="python:a.py:function:helper:1",
            kind="function",
            name="helper",
            file_path="a.py",
            start_line=1,
            end_line=2,
            language="python",
        ),
        Symbol(
            uid="python:a.py:class:Worker:5",
            kind="class",
            name="Worker",
            file_path="a.py",
            start_line=5,
            end_line=15,
            language="python",
            decorators=("dataclass",),
            signature="class Worker(Base):",
        ),
        Symbol(
            uid="python:a.py:method:run:7",
            kind="method",
            name="run",
            file_path="a.py",
            start_line=7,
            end_line=10,
            parent_uid="python:a.py:class:Worker:5",
            language="python",
        ),
    ]
    edges = [
        GraphEdge(
            src_uid="python:a.py:method:run:7",
            dst_uid="python:a.py:function:helper:1",
            edge_type=EDGE_CALLS,
            confidence=1.0,
            attrs={"line": 8},
        ),
        GraphEdge(
            src_uid="python:a.py:class:Worker:5",
            dst_uid="python:a.py:function:helper:1",  # synthetic
            edge_type=EDGE_EXTENDS,
            confidence=0.7,
        ),
    ]
    return CodeGraph(symbols=symbols, edges=edges)


@pytest.mark.asyncio
async def test_save_replaces_existing_rows(db_session: AsyncSession, project_id: str):
    svc = CodeGraphService()
    g1 = _make_graph()
    sym_count, edge_count = await svc.save(db_session, project_id, g1)
    assert sym_count == 3
    assert edge_count == 2

    sym_total, edge_total = await svc.count(db_session, project_id)
    assert sym_total == 3
    assert edge_total == 2

    # Second save should fully replace.
    smaller = CodeGraph(symbols=list(g1.symbols.values())[:1], edges=[])
    sym_count2, edge_count2 = await svc.save(db_session, project_id, smaller)
    assert sym_count2 == 1
    assert edge_count2 == 0

    sym_total2, edge_total2 = await svc.count(db_session, project_id)
    assert sym_total2 == 1
    assert edge_total2 == 0


@pytest.mark.asyncio
async def test_save_incremental_preserves_unchanged_files(
    db_session: AsyncSession, project_id: str
):
    """An incremental run must merge, not wipe, the persisted graph."""
    svc = CodeGraphService()
    # Full index: a.py (3 symbols) + b.py (1 symbol).
    base = _make_graph()
    b_symbol = Symbol(
        uid="python:b.py:function:other:1",
        kind="function",
        name="other",
        file_path="b.py",
        start_line=1,
        end_line=2,
        language="python",
    )
    full = CodeGraph(
        symbols=[*base.symbols.values(), b_symbol],
        edges=list(base.edges),
    )
    await svc.save(db_session, project_id, full)
    sym_total, _ = await svc.count(db_session, project_id)
    assert sym_total == 4

    # Incremental run that only re-parsed a.py (b.py untouched). The new
    # subset graph contains only a.py's symbols.
    changed_only = CodeGraph(symbols=list(base.symbols.values()), edges=list(base.edges))
    await svc.save_incremental(db_session, project_id, changed_only, {"a.py"})

    rows = await svc.load_symbols(db_session, project_id)
    files = {r.file_path for r in rows}
    # b.py must survive the incremental run.
    assert "b.py" in files
    assert any(r.uid == "python:b.py:function:other:1" for r in rows)
    assert len(rows) == 4


@pytest.mark.asyncio
async def test_save_incremental_preserves_cluster_membership(
    db_session: AsyncSession, project_id: str
):
    """R3-2: an incremental run must not null the cluster_id of symbols in
    files it did not touch."""
    from app.knowledge.code_clustering import Cluster

    svc = CodeGraphService()
    base = _make_graph()
    b_symbol = Symbol(
        uid="python:b.py:function:other:1",
        kind="function",
        name="other",
        file_path="b.py",
        start_line=1,
        end_line=2,
        language="python",
    )
    full = CodeGraph(symbols=[*base.symbols.values(), b_symbol], edges=list(base.edges))
    await svc.save(db_session, project_id, full)

    # Cluster every symbol so we can detect membership loss.
    await svc.save_clusters(
        db_session,
        project_id,
        [
            Cluster(
                cluster_id="0",
                member_uids=[s.uid for s in base.symbols.values()],
                file_paths=["a.py"],
                label="A cluster",
            ),
            Cluster(
                cluster_id="1",
                member_uids=["python:b.py:function:other:1"],
                file_paths=["b.py"],
                label="B cluster",
            ),
        ],
    )
    await db_session.commit()

    # Incremental run that only re-parsed a.py.
    changed_only = CodeGraph(symbols=list(base.symbols.values()), edges=list(base.edges))
    await svc.save_incremental(db_session, project_id, changed_only, {"a.py"})

    rows = await svc.load_symbols(db_session, project_id)
    by_uid = {r.uid: r for r in rows}
    # Unchanged file b.py keeps its cluster.
    assert by_uid["python:b.py:function:other:1"].cluster_id == "1"
    # Re-parsed a.py symbols (stable uids) also keep their cluster.
    assert by_uid["python:a.py:function:helper:1"].cluster_id == "0"


@pytest.mark.asyncio
async def test_save_incremental_drops_deleted_files(db_session: AsyncSession, project_id: str):
    """Symbols for files in the affected set with no replacement are removed."""
    svc = CodeGraphService()
    base = _make_graph()
    b_symbol = Symbol(
        uid="python:b.py:function:other:1",
        kind="function",
        name="other",
        file_path="b.py",
        start_line=1,
        end_line=2,
        language="python",
    )
    full = CodeGraph(symbols=[*base.symbols.values(), b_symbol], edges=list(base.edges))
    await svc.save(db_session, project_id, full)

    # b.py was deleted: empty new graph, b.py in affected set.
    empty = CodeGraph(symbols=[], edges=[])
    await svc.save_incremental(db_session, project_id, empty, {"b.py"})

    rows = await svc.load_symbols(db_session, project_id)
    files = {r.file_path for r in rows}
    assert "b.py" not in files
    assert "a.py" in files


@pytest.mark.asyncio
async def test_save_incremental_falls_back_to_full_when_empty(
    db_session: AsyncSession, project_id: str
):
    """With no persisted graph, save_incremental behaves like save."""
    svc = CodeGraphService()
    g = _make_graph()
    sym_count, edge_count = await svc.save_incremental(db_session, project_id, g, {"a.py"})
    assert sym_count == 3
    assert edge_count == 2


@pytest.mark.asyncio
async def test_get_callers_and_callees(db_session: AsyncSession, project_id: str):
    svc = CodeGraphService()
    await svc.save(db_session, project_id, _make_graph())
    helper_uid = "python:a.py:function:helper:1"
    run_uid = "python:a.py:method:run:7"

    callers = await svc.get_callers(db_session, project_id, helper_uid)
    assert len(callers) == 1
    assert callers[0].uid == run_uid

    callees = await svc.get_callees(db_session, project_id, run_uid)
    assert len(callees) == 1
    assert callees[0].uid == helper_uid


@pytest.mark.asyncio
async def test_query_by_name(db_session: AsyncSession, project_id: str):
    svc = CodeGraphService()
    await svc.save(db_session, project_id, _make_graph())
    rows = await svc.query_by_name(db_session, project_id, "Worker")
    assert len(rows) == 1
    assert rows[0].kind == "class"
    assert rows[0].decorators_json == '["dataclass"]'


@pytest.mark.asyncio
async def test_min_confidence_filter(db_session: AsyncSession, project_id: str):
    svc = CodeGraphService()
    await svc.save(db_session, project_id, _make_graph())
    # The EXTENDS edge has confidence 0.7; ask for 0.8 -> excluded.
    callers = await svc.get_callers(
        db_session,
        project_id,
        "python:a.py:function:helper:1",
        edge_type=EDGE_EXTENDS,
        min_confidence=0.8,
    )
    assert callers == []
    callers = await svc.get_callers(
        db_session,
        project_id,
        "python:a.py:function:helper:1",
        edge_type=EDGE_EXTENDS,
        min_confidence=0.5,
    )
    assert len(callers) == 1


# ---------------------------------------------------------------------------
# M6: cluster persistence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_and_get_clusters_round_trip(db_session, project_id):
    """Persist clusters, then read them back via the service helpers."""
    from app.knowledge.code_clustering import Cluster

    # First save some symbols so cluster_id updates have rows to target.
    graph = _make_graph()
    svc = CodeGraphService()
    await svc.save(db_session, project_id, graph)

    clusters = [
        Cluster(
            cluster_id="0",
            member_uids=[
                "python:a.py:function:helper:1",
                "python:a.py:class:Worker:5",
            ],
            file_paths=["a.py"],
            label="Workers & helpers",
            description="Background workers and helpers",
            table_names=["workers"],
        ),
        Cluster(
            cluster_id="1",
            member_uids=["python:a.py:method:run:7"],
            file_paths=["a.py"],
            label="Run loop",
            description="Hot path",
            table_names=[],
        ),
    ]
    saved = await svc.save_clusters(db_session, project_id, clusters)
    await db_session.commit()
    assert saved == 2

    rows = await svc.get_clusters(db_session, project_id)
    assert len(rows) == 2
    by_id = {r.cluster_id: r for r in rows}
    assert by_id["0"].label == "Workers & helpers"
    assert by_id["1"].label == "Run loop"
    assert by_id["0"].symbol_count == 2

    # Label-substring lookup.
    matches = await svc.get_cluster_by_label(db_session, project_id, "worker")
    assert any(m.cluster_id == "0" for m in matches)

    # get_tables_in_cluster resolves both cluster_id and label substring.
    tables_by_id = await svc.get_tables_in_cluster(db_session, project_id, "0")
    assert tables_by_id == ["workers"]
    tables_by_label = await svc.get_tables_in_cluster(db_session, project_id, "Workers")
    assert tables_by_label == ["workers"]

    # cluster_id was applied to the affected symbols.
    symbols = await svc.load_symbols(db_session, project_id)
    by_uid = {s.uid: s for s in symbols}
    assert by_uid["python:a.py:function:helper:1"].cluster_id == "0"
    assert by_uid["python:a.py:class:Worker:5"].cluster_id == "0"
    assert by_uid["python:a.py:method:run:7"].cluster_id == "1"


@pytest.mark.asyncio
async def test_save_clusters_replaces_previous(db_session, project_id):
    from app.knowledge.code_clustering import Cluster

    svc = CodeGraphService()
    await svc.save(db_session, project_id, _make_graph())

    await svc.save_clusters(
        db_session,
        project_id,
        [
            Cluster(
                cluster_id="9",
                member_uids=["python:a.py:function:helper:1"],
                label="Legacy",
            )
        ],
    )
    await db_session.commit()

    # Replace with empty — symbols should reset cluster_id.
    await svc.save_clusters(db_session, project_id, [])
    await db_session.commit()
    rows = await svc.get_clusters(db_session, project_id)
    assert rows == []
    symbols = await svc.load_symbols(db_session, project_id)
    assert all(s.cluster_id is None for s in symbols)


@pytest.mark.asyncio
async def test_get_tables_in_cluster_returns_empty_for_unknown(db_session, project_id):
    svc = CodeGraphService()
    tables = await svc.get_tables_in_cluster(db_session, project_id, "nope")
    assert tables == []
