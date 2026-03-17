import tempfile
from pathlib import Path

from app.knowledge.entity_extractor import (
    ColumnInfo,
    EntityInfo,
    ProjectKnowledge,
    TableUsage,
)
from app.knowledge.indexing_pipeline import (
    EnrichedDoc,
    generate_summary_doc,
    run_pass1_profile,
    run_pass2_3_knowledge,
    run_pass4_enrich,
)
from app.knowledge.project_profiler import ProjectProfile
from app.knowledge.repo_analyzer import ExtractedSchema


class TestRunPass1Profile:
    def test_returns_profile(self):
        tmp = Path(tempfile.mkdtemp())
        (tmp / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()")
        (tmp / "requirements.txt").write_text("sqlalchemy\n")
        profile = run_pass1_profile(tmp)
        assert isinstance(profile, ProjectProfile)
        assert "fastapi" in profile.frameworks


class TestRunPassTwoThreeKnowledge:
    def test_returns_knowledge(self):
        tmp = Path(tempfile.mkdtemp())
        (tmp / "models.py").write_text("class User(Base):\n    __tablename__ = 'users'\n")
        schemas = [
            ExtractedSchema(
                file_path="models.py",
                doc_type="orm_model",
                content="class User(Base):\n    __tablename__ = 'users'\n",
                models=["User"],
            ),
        ]
        knowledge = run_pass2_3_knowledge(tmp, schemas)
        assert isinstance(knowledge, ProjectKnowledge)
        assert "User" in knowledge.entities


class TestRunPass4Enrich:
    def test_enrichment_with_relationships(self):
        schemas = [
            ExtractedSchema(
                file_path="models/order.py",
                doc_type="orm_model",
                content="class Order: pass",
                models=["Order"],
                tables=["orders"],
            ),
        ]
        knowledge = ProjectKnowledge()
        knowledge.entities["Order"] = EntityInfo(
            name="Order",
            table_name="orders",
            file_path="models/order.py",
            relationships=["users.id"],
            used_in_files=["services/order_svc.py"],
            columns=[
                ColumnInfo(name="status", col_type="String", enum_values=["pending", "shipped"]),
            ],
        )
        knowledge.table_usage["orders"] = TableUsage(
            table_name="orders",
            readers=["api/orders.py"],
        )
        profile = ProjectProfile(
            frameworks=["fastapi"],
            orms=["sqlalchemy"],
            primary_language="python",
        )
        docs = run_pass4_enrich(schemas, knowledge, profile)
        assert len(docs) >= 1
        enriched = docs[0]
        assert isinstance(enriched, EnrichedDoc)
        assert "users.id" in enriched.enrichment_context
        assert "pending" in enriched.enrichment_context
        assert "order_svc.py" in enriched.enrichment_context

    def test_dead_table_warning(self):
        schemas = [
            ExtractedSchema(
                file_path="migrations/001.sql",
                doc_type="raw_sql",
                content="CREATE TABLE dead_table (id INT);",
                tables=["dead_table"],
            ),
        ]
        knowledge = ProjectKnowledge()
        knowledge.table_usage["dead_table"] = TableUsage(table_name="dead_table")
        docs = run_pass4_enrich(schemas, knowledge)
        assert any("no active references" in d.enrichment_context for d in docs)

    def test_service_function_context(self):
        schemas = [
            ExtractedSchema(
                file_path="models/user.py",
                doc_type="orm_model",
                content="class User: pass",
                models=["User"],
                tables=["users"],
            ),
        ]
        knowledge = ProjectKnowledge()
        knowledge.entities["User"] = EntityInfo(
            name="User",
            table_name="users",
        )
        knowledge.table_usage["users"] = TableUsage(
            table_name="users",
            orm_refs=["models/user.py"],
        )
        knowledge.service_functions.append(
            {
                "name": "create_user",
                "file_path": "services/users.py",
                "tables": ["users"],
            }
        )
        docs = run_pass4_enrich(schemas, knowledge)
        assert any("create_user" in d.enrichment_context for d in docs)

    def test_empty_schemas(self):
        docs = run_pass4_enrich([], ProjectKnowledge())
        assert docs == []


class TestGenerateSummaryDoc:
    def test_summary_doc_type(self):
        knowledge = ProjectKnowledge()
        knowledge.table_usage["users"] = TableUsage(table_name="users")
        doc = generate_summary_doc(knowledge)
        assert doc.file_path == "__project_summary__"
        assert doc.doc_type == "project_summary"
        assert "users" in doc.tables

    def test_summary_with_profile(self):
        knowledge = ProjectKnowledge()
        profile = ProjectProfile(frameworks=["django"], primary_language="python")
        doc = generate_summary_doc(knowledge, profile)
        assert "django" in doc.content

    def test_summary_content_is_markdown(self):
        knowledge = ProjectKnowledge()
        knowledge.entities["User"] = EntityInfo(
            name="User",
            table_name="users",
        )
        doc = generate_summary_doc(knowledge)
        assert doc.content.startswith("# Project Data Model Summary")
