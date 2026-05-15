"""Back-compat tests for :class:`EntityInfo.graph_callers` (M5).

The field is new in M5; we need to prove (a) round-trip works, and (b) JSON
written by an older version of the codebase (without ``graph_callers``)
still deserializes cleanly.
"""

from __future__ import annotations

from app.knowledge.entity_extractor import ColumnInfo, EntityInfo, ProjectKnowledge


def test_entity_info_default_graph_callers_is_empty():
    e = EntityInfo(name="User")
    assert e.graph_callers == []


def test_entity_info_round_trip_with_graph_callers():
    knowledge = ProjectKnowledge()
    entity = EntityInfo(
        name="User",
        table_name="users",
        file_path="app/models/user.py",
        columns=[ColumnInfo(name="id", col_type="int", is_pk=True)],
        graph_callers=[
            {
                "caller_name": "create_user",
                "caller_file": "app/api/users.py",
                "caller_kind": "function",
                "endpoint_kind": "http",
                "op_kind": "write",
                "depth": 1,
                "confidence": 0.9,
                "decorators": ["router.post('/users')"],
            }
        ],
    )
    knowledge.entities["User"] = entity

    raw = knowledge.to_json()
    restored = ProjectKnowledge.from_json(raw)

    restored_entity = restored.entities["User"]
    assert restored_entity.name == "User"
    assert restored_entity.graph_callers == entity.graph_callers


def test_entity_info_from_json_without_graph_callers_field():
    """Legacy JSON (no graph_callers key) deserializes with an empty default."""
    legacy = (
        '{"entities": {"User": {"name": "User", "table_name": "users", '
        '"file_path": "app/models/user.py", "columns": [], '
        '"relationships": [], "used_in_files": [], '
        '"read_queries": 0, "write_queries": 0}}}'
    )
    restored = ProjectKnowledge.from_json(legacy)
    assert restored.entities["User"].graph_callers == []
