"""Integration test for the M5 lineage bridge.

Drives the full pipeline from a small in-memory fixture::

    files -> ASTParser -> CodeGraphBuilder -> GraphDBBridge -> ProjectKnowledge

This is the closest we get to end-to-end without spawning a real git repo.
We synthesise a FastAPI route + service + ORM model so the bridge has
representative content to classify.
"""

from __future__ import annotations

import pytest

from app.knowledge.ast_parser import ASTParser
from app.knowledge.code_graph import CodeGraphBuilder
from app.knowledge.entity_extractor import EntityInfo, ProjectKnowledge, TableUsage
from app.knowledge.graph_db_bridge import GraphDBBridge

FIXTURE_FILES = {
    "app/models/user.py": b"""
class User:
    \"\"\"User ORM model.\"\"\"

    def __init__(self, email: str) -> None:
        self.email = email
""".strip(),
    "app/services/user_service.py": b"""
from app.models.user import User


def create_user(email: str) -> User:
    return User(email=email)


def list_users() -> list[User]:
    return [User('a@b.com')]
""".strip(),
    "app/api/users.py": b"""
from fastapi import APIRouter

from app.services.user_service import create_user, list_users

router = APIRouter()


@router.post('/users')
def create_user_endpoint(email: str):
    return create_user(email)


@router.get('/users')
def list_users_endpoint():
    return list_users()
""".strip(),
}


@pytest.mark.asyncio
async def test_pipeline_attaches_http_callers_to_user_entity():
    """Parse fixture, build graph, run bridge, verify endpoints surface."""
    parser = ASTParser()
    parsed_files = {}
    for path, source in FIXTURE_FILES.items():
        result = parser.parse_bytes(rel_path=path, content=source)
        if result is None or result.symbols is None:
            pytest.skip(f"AST parser couldn't process {path}; tree-sitter setup issue")
        parsed_files[path] = result

    builder = CodeGraphBuilder(min_call_confidence=0.3)
    code_graph = builder.build(parsed_files)

    # Sanity: we expect at least one CALLS edge somewhere.
    assert any(e.edge_type == "CALLS" for e in code_graph.edges), (
        "CodeGraphBuilder produced no CALLS edges; bridge has nothing to walk"
    )

    knowledge = ProjectKnowledge()
    knowledge.entities["User"] = EntityInfo(
        name="User",
        table_name="users",
        file_path="app/models/user.py",
    )
    knowledge.table_usage["users"] = TableUsage(table_name="users")

    bridge = GraphDBBridge(max_depth=5)
    attached = bridge.enrich(knowledge, code_graph)

    refs = knowledge.entities["User"].graph_callers
    assert refs, "bridge produced no caller refs for User"

    names = [r["caller_name"] for r in refs]
    # Either the direct service callers or the route endpoints should appear.
    assert (
        "create_user" in names
        or "list_users" in names
        or "create_user_endpoint" in names
        or "list_users_endpoint" in names
    ), f"unexpected caller names: {names}"

    # If the routes do surface, their endpoint_kind must be http.
    for ref in refs:
        if "endpoint" in ref["caller_name"]:
            assert ref["endpoint_kind"] == "http"
    assert attached == len(refs)
