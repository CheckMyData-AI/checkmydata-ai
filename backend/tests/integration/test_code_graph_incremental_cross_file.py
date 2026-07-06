"""Integration test: incremental graph merge re-resolves cross-file CALLS/IMPORTS (CODEIDX-C4).

Verifies the full fix path end-to-end against a real in-memory database:
1. Full index: b.py's driver() calls helper() imported from a.py — CALLS edge persisted.
2. a.py changes (comment added, helper() body updated).  b.py is UNCHANGED.
3. reverse_dependents identifies b.py as a caller of a.py.
4. After incremental merge (with b.py in reparse + affected set), driver() still has
   a CALLS edge to the current helper() uid.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.knowledge.ast_parser import ASTParser
from app.knowledge.code_graph import EDGE_CALLS, CodeGraph, CodeGraphBuilder
from app.models.project import Project
from app.models.user import User
from app.services.code_graph_service import CodeGraphService

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def project_id(db_session: AsyncSession) -> str:
    """Create a minimal user + project to satisfy FK constraints."""
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
        name="C4 test project",
        owner_id=user.id,
        repo_url="git@example.com:c4/test.git",
    )
    db_session.add(project)
    await db_session.flush()
    return project.id


def _build(parser: ASTParser, files: dict[str, bytes]) -> CodeGraph:
    parsed = {p: parser.parse_bytes(p, src) for p, src in files.items()}
    builder = CodeGraphBuilder()
    return builder.build({p: pf for p, pf in parsed.items() if pf is not None})


async def test_unchanged_caller_relinks_after_incremental_change(
    db_session: AsyncSession, project_id: str
) -> None:
    """CODEIDX-C4: an unchanged caller retains its CALLS edge after the callee changes."""
    parser = ASTParser()
    svc = CodeGraphService()

    # --- Full index: b.py's driver() calls helper() from a.py ---
    a_v1 = b"def helper():\n    return 1\n"
    b_src = b"from a import helper\n\ndef driver():\n    return helper()\n"
    full = _build(parser, {"a.py": a_v1, "b.py": b_src})
    await svc.save(db_session, project_id, full)
    await db_session.commit()

    # Verify baseline: driver → helper CALLS edge exists.
    baseline = await svc.load_graph(db_session, project_id)
    assert baseline is not None
    helper_uids_v1 = [u for u, s in baseline.symbols.items() if s.name == "helper"]
    assert helper_uids_v1, "baseline must have helper symbol"

    # --- Incremental: a.py changed, b.py UNCHANGED ---
    a_v2 = b"# new top comment\ndef helper():\n    return 2\n"
    changed = {"a.py"}

    existing = await svc.load_graph(db_session, project_id)
    assert existing is not None

    # C4 fix: expand parse set with reverse-dependents.
    rdeps = CodeGraphBuilder.reverse_dependents(existing, changed)
    assert "b.py" in rdeps, "C4: b.py must be identified as a reverse-dependent of a.py"

    reparse = changed | rdeps  # {"a.py", "b.py"}
    partial = _build(parser, {"a.py": a_v2, "b.py": b_src})

    await svc.save_incremental(db_session, project_id, partial, reparse)
    await db_session.commit()

    # --- Assert: driver() still has a CALLS edge to the current helper() ---
    graph = await svc.load_graph(db_session, project_id)
    assert graph is not None

    helper_uids = [u for u, s in graph.symbols.items() if s.name == "helper"]
    assert len(helper_uids) == 1, "exactly one helper symbol must exist after merge"

    driver_uids = [u for u, s in graph.symbols.items() if s.name == "driver"]
    assert driver_uids, "driver symbol must survive the incremental merge"
    driver_uid = driver_uids[0]

    calls = [
        e
        for e in graph.edges
        if e.edge_type == EDGE_CALLS and e.src_uid == driver_uid and e.dst_uid == helper_uids[0]
    ]
    assert calls, (
        "CODEIDX-C4: unchanged caller (driver) lost its CALLS edge to helper after incremental "
        "change — reverse-dep re-parse did not fire correctly"
    )
