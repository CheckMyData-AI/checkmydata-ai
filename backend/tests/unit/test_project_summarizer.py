from app.knowledge.entity_extractor import (
    ColumnInfo,
    EntityInfo,
    EnumDefinition,
    ProjectKnowledge,
    TableUsage,
)
from app.knowledge.project_profiler import ProjectProfile
from app.knowledge.project_summarizer import (
    build_project_summary,
    build_schema_cross_reference,
)


class TestBuildProjectSummary:
    def test_empty_knowledge(self):
        knowledge = ProjectKnowledge()
        result = build_project_summary(knowledge)
        assert "# Project Data Model Summary" in result

    def test_entities_section(self):
        knowledge = ProjectKnowledge()
        knowledge.entities["User"] = EntityInfo(
            name="User",
            table_name="users",
            file_path="models/user.py",
            columns=[
                ColumnInfo(name="id", col_type="Integer"),
                ColumnInfo(name="name", col_type="String"),
            ],
            relationships=["roles.user_id"],
        )
        result = build_project_summary(knowledge)
        assert "### User" in result
        assert "`users`" in result
        assert "| id | Integer" in result
        assert "roles.user_id" in result

    def test_table_usage_section(self):
        knowledge = ProjectKnowledge()
        knowledge.table_usage["orders"] = TableUsage(
            table_name="orders",
            readers=["api/orders.py"],
            writers=["services/order_svc.py"],
            orm_refs=["models/order.py"],
        )
        result = build_project_summary(knowledge)
        assert "| orders" in result
        assert "active" in result

    def test_dead_tables_section(self):
        knowledge = ProjectKnowledge()
        knowledge.table_usage["legacy"] = TableUsage(table_name="legacy")
        result = build_project_summary(knowledge)
        assert "Potentially Dead Tables" in result
        assert "`legacy`" in result

    def test_enums_section(self):
        knowledge = ProjectKnowledge()
        knowledge.enums.append(
            EnumDefinition(name="Status", values=["active", "inactive"], file_path="enums.py")
        )
        result = build_project_summary(knowledge)
        assert "**Status**" in result
        assert "active" in result

    def test_service_functions_section(self):
        knowledge = ProjectKnowledge()
        knowledge.service_functions.append({
            "name": "create_user",
            "file_path": "services/users.py",
            "tables": ["users"],
        })
        result = build_project_summary(knowledge)
        assert "`create_user`" in result

    def test_profile_included(self):
        knowledge = ProjectKnowledge()
        profile = ProjectProfile(
            frameworks=["fastapi"],
            orms=["sqlalchemy"],
            primary_language="python",
        )
        result = build_project_summary(knowledge, profile)
        assert "fastapi" in result
        assert "sqlalchemy" in result

    def test_enum_values_in_columns(self):
        knowledge = ProjectKnowledge()
        knowledge.entities["User"] = EntityInfo(
            name="User",
            table_name="users",
            file_path="models.py",
            columns=[
                ColumnInfo(
                    name="status",
                    col_type="String",
                    enum_values=["active", "suspended"],
                ),
            ],
        )
        result = build_project_summary(knowledge)
        assert "active, suspended" in result


class TestBuildSchemaCrossReference:
    def test_all_match(self):
        knowledge = ProjectKnowledge()
        knowledge.table_usage["users"] = TableUsage(table_name="users")
        result = build_schema_cross_reference(knowledge, ["users"])
        assert "All tables in the database match" in result

    def test_orphan_tables(self):
        knowledge = ProjectKnowledge()
        result = build_schema_cross_reference(knowledge, ["users", "logs"])
        assert "Orphan Tables" in result
        assert "`users`" in result
        assert "`logs`" in result

    def test_phantom_tables(self):
        knowledge = ProjectKnowledge()
        knowledge.table_usage["phantom_table"] = TableUsage(table_name="phantom_table")
        result = build_schema_cross_reference(knowledge, [])
        assert "Phantom Tables" in result
        assert "`phantom_table`" in result

    def test_mixed_orphan_and_phantom(self):
        knowledge = ProjectKnowledge()
        knowledge.entities["User"] = EntityInfo(
            name="User", table_name="users",
        )
        result = build_schema_cross_reference(
            knowledge, ["users", "audit_log"],
        )
        assert "Orphan Tables" in result
        assert "`audit_log`" in result
