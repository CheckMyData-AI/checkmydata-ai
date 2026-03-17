"""Tests for incremental indexing improvements:
- ProjectKnowledge serialization
- ProjectProfile serialization and caching
- _incremental_update with deleted_files
- GitTracker new methods
"""

import tempfile
from pathlib import Path

from app.knowledge.entity_extractor import (
    ColumnInfo,
    EntityInfo,
    EnumDefinition,
    ProjectKnowledge,
    TableUsage,
    build_project_knowledge,
)
from app.knowledge.project_profiler import ProjectProfile, detect_project_profile


class TestProjectKnowledgeSerialization:
    def test_round_trip_empty(self):
        pk = ProjectKnowledge()
        raw = pk.to_json()
        restored = ProjectKnowledge.from_json(raw)
        assert restored.entities == {}
        assert restored.table_usage == {}
        assert restored.enums == []
        assert restored.service_functions == []

    def test_round_trip_with_data(self):
        pk = ProjectKnowledge()
        pk.entities["User"] = EntityInfo(
            name="User",
            table_name="users",
            file_path="models/user.py",
            columns=[
                ColumnInfo(name="id", col_type="Integer", is_pk=True),
                ColumnInfo(name="name", col_type="String"),
            ],
            relationships=["has_many:Order"],
            used_in_files=["services/auth.py"],
        )
        pk.table_usage["users"] = TableUsage(
            table_name="users",
            readers=["queries.py"],
            writers=["services/auth.py"],
            orm_refs=["models/user.py"],
        )
        pk.enums.append(
            EnumDefinition(
                name="Status",
                values=["active", "inactive"],
                file_path="enums.py",
            )
        )
        pk.service_functions.append(
            {
                "name": "create_user",
                "file_path": "services/auth.py",
                "tables": ["users"],
                "snippet": "def create_user(): pass",
            }
        )

        raw = pk.to_json()
        restored = ProjectKnowledge.from_json(raw)

        assert "User" in restored.entities
        assert restored.entities["User"].table_name == "users"
        assert len(restored.entities["User"].columns) == 2
        assert restored.entities["User"].columns[0].is_pk is True
        assert "users" in restored.table_usage
        assert restored.table_usage["users"].readers == ["queries.py"]
        assert len(restored.enums) == 1
        assert restored.enums[0].name == "Status"
        assert len(restored.service_functions) == 1

    def test_dead_tables_property_survives_round_trip(self):
        pk = ProjectKnowledge()
        pk.table_usage["orphan"] = TableUsage(table_name="orphan")
        pk.table_usage["active"] = TableUsage(
            table_name="active",
            readers=["some.py"],
        )
        assert "orphan" in pk.dead_tables
        assert "active" not in pk.dead_tables

        restored = ProjectKnowledge.from_json(pk.to_json())
        assert "orphan" in restored.dead_tables
        assert "active" not in restored.dead_tables


class TestProjectProfileSerialization:
    def test_round_trip(self):
        p = ProjectProfile(
            frameworks=["django"],
            orms=["sqlalchemy"],
            primary_language="python",
            model_dirs=["models"],
            migration_dirs=["alembic"],
            service_dirs=["services"],
            config_files=["config"],
            test_dirs=["tests"],
        )
        raw = p.to_json()
        restored = ProjectProfile.from_json(raw)
        assert restored.frameworks == ["django"]
        assert restored.orms == ["sqlalchemy"]
        assert restored.primary_language == "python"
        assert restored.model_dirs == ["models"]
        assert restored.summary == p.summary

    def test_marker_files(self):
        p = ProjectProfile()
        markers = p.marker_files
        assert "package.json" in markers
        assert "requirements.txt" in markers
        assert "manage.py" in markers


class TestIncrementalUpdateWithDeletedFiles:
    def _make_repo(self, files: dict[str, str]) -> Path:
        d = Path(tempfile.mkdtemp())
        for name, content in files.items():
            fp = d / name
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(content)
        return d

    def test_deleted_file_entities_removed(self):
        repo = self._make_repo(
            {
                "models/order.py": "class Order: pass\n",
            }
        )
        cached = ProjectKnowledge()
        cached.entities["User"] = EntityInfo(
            name="User",
            table_name="users",
            file_path="models/user.py",
        )
        cached.entities["Order"] = EntityInfo(
            name="Order",
            table_name="orders",
            file_path="models/order.py",
        )
        cached.enums.append(
            EnumDefinition(
                name="UserStatus",
                values=["active"],
                file_path="models/user.py",
            )
        )
        cached.service_functions.append(
            {
                "name": "register_user",
                "file_path": "models/user.py",
                "tables": ["users"],
                "snippet": "...",
            }
        )

        knowledge = build_project_knowledge(
            repo,
            schemas=[],
            changed_files=["models/order.py"],
            deleted_files=["models/user.py"],
            cached_knowledge=cached,
        )
        assert "User" not in knowledge.entities
        assert "Order" in knowledge.entities
        enum_names = [e.name for e in knowledge.enums]
        assert "UserStatus" not in enum_names
        func_names = [sf["name"] for sf in knowledge.service_functions]
        assert "register_user" not in func_names

    def test_deleted_file_table_usage_cleaned(self):
        repo = self._make_repo({})
        cached = ProjectKnowledge()
        cached.table_usage["users"] = TableUsage(
            table_name="users",
            readers=["models/user.py", "services/auth.py"],
            writers=["models/user.py"],
        )

        knowledge = build_project_knowledge(
            repo,
            schemas=[],
            changed_files=[],
            deleted_files=["models/user.py"],
            cached_knowledge=cached,
        )
        usage = knowledge.table_usage.get("users")
        assert usage is not None
        assert "models/user.py" not in usage.readers
        assert "services/auth.py" in usage.readers
        assert "models/user.py" not in usage.writers

    def test_no_deleted_files_unchanged_behavior(self):
        repo = self._make_repo(
            {
                "models/user.py": "class User: pass\n",
            }
        )
        cached = ProjectKnowledge()
        cached.entities["User"] = EntityInfo(
            name="User",
            file_path="models/user.py",
        )
        cached.service_functions.append(
            {
                "name": "old_func",
                "file_path": "services/old.py",
                "tables": [],
                "snippet": "...",
            }
        )

        knowledge = build_project_knowledge(
            repo,
            schemas=[],
            changed_files=["models/user.py"],
            deleted_files=[],
            cached_knowledge=cached,
        )
        func_names = [sf["name"] for sf in knowledge.service_functions]
        assert "old_func" in func_names


class TestProfileCacheLogic:
    def test_marker_file_overlap_detection(self):
        p = ProjectProfile(frameworks=["django"])
        markers = p.marker_files
        assert bool(markers & {"package.json", "requirements.txt"})
        assert not bool(markers & {"random_file.py", "utils.py"})

    def test_detect_project_profile_basic(self):
        d = Path(tempfile.mkdtemp())
        (d / "requirements.txt").write_text("sqlalchemy\nflask\n")
        (d / "app.py").write_text("from flask import Flask\napp = Flask(__name__)\n")
        (d / "models.py").write_text("from sqlalchemy import Column\n")

        profile = detect_project_profile(d)
        assert "sqlalchemy" in profile.orms
        assert profile.primary_language == "python"
        assert profile.to_json()
        restored = ProjectProfile.from_json(profile.to_json())
        assert restored.orms == profile.orms
