import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

import app.models.chat_session  # noqa: F401
import app.models.commit_index  # noqa: F401
import app.models.connection  # noqa: F401
import app.models.custom_rule  # noqa: F401
import app.models.indexing_checkpoint  # noqa: F401
import app.models.knowledge_doc  # noqa: F401
import app.models.project  # noqa: F401
import app.models.project_cache  # noqa: F401
import app.models.project_invite  # noqa: F401
import app.models.project_member  # noqa: F401
import app.models.rag_feedback  # noqa: F401
import app.models.ssh_key  # noqa: F401
import app.models.user  # noqa: F401
from app.knowledge.doc_store import DocStore
from app.models.base import Base
from app.models.knowledge_doc import KnowledgeDoc
from app.services.chat_service import ChatService
from app.services.project_service import ProjectService


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session

    await engine.dispose()


class TestProjectService:
    @pytest.mark.asyncio
    async def test_create_and_get(self, db_session):
        svc = ProjectService()
        project = await svc.create(db_session, name="Test Project", description="A test")
        assert project.name == "Test Project"
        assert project.id is not None

        fetched = await svc.get(db_session, project.id)
        assert fetched is not None
        assert fetched.name == "Test Project"

    @pytest.mark.asyncio
    async def test_list(self, db_session):
        svc = ProjectService()
        await svc.create(db_session, name="P1")
        await svc.create(db_session, name="P2")
        projects = await svc.list_all(db_session)
        assert len(projects) == 2

    @pytest.mark.asyncio
    async def test_update(self, db_session):
        svc = ProjectService()
        project = await svc.create(db_session, name="Original")
        updated = await svc.update(db_session, project.id, name="Updated")
        assert updated is not None
        assert updated.name == "Updated"

    @pytest.mark.asyncio
    async def test_delete(self, db_session):
        svc = ProjectService()
        project = await svc.create(db_session, name="ToDelete")
        deleted = await svc.delete(db_session, project.id)
        assert deleted is True

        fetched = await svc.get(db_session, project.id)
        assert fetched is None

    @pytest.mark.asyncio
    async def test_get_nonexistent(self, db_session):
        svc = ProjectService()
        result = await svc.get(db_session, "nonexistent-id")
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_cascades_to_knowledge_docs(self, db_session):
        svc = ProjectService()
        project = await svc.create(db_session, name="CascadeTest")

        doc = KnowledgeDoc(
            project_id=project.id,
            doc_type="orm_model",
            source_path="models/user.py",
            content="class User: pass",
        )
        db_session.add(doc)
        await db_session.commit()

        deleted = await svc.delete(db_session, project.id)
        assert deleted is True

        from sqlalchemy import select

        result = await db_session.execute(
            select(KnowledgeDoc).where(KnowledgeDoc.project_id == project.id)
        )
        assert result.scalars().all() == []


class TestChatService:
    @pytest.mark.asyncio
    async def test_create_session(self, db_session):
        svc = ChatService()
        session = await svc.create_session(db_session, "project-1", "Test Chat")
        assert session.id is not None
        assert session.title == "Test Chat"

    @pytest.mark.asyncio
    async def test_add_message_and_get_history(self, db_session):
        svc = ChatService()
        session = await svc.create_session(db_session, "project-1")
        await svc.add_message(db_session, session.id, "user", "Hello")
        await svc.add_message(db_session, session.id, "assistant", "Hi there!")

        history = await svc.get_history_as_messages(db_session, session.id)
        assert len(history) == 2
        assert history[0].role == "user"
        assert history[0].content == "Hello"
        assert history[1].role == "assistant"

    @pytest.mark.asyncio
    async def test_list_sessions(self, db_session):
        svc = ChatService()
        await svc.create_session(db_session, "project-1", "Chat 1")
        await svc.create_session(db_session, "project-1", "Chat 2")
        await svc.create_session(db_session, "project-2", "Chat 3")

        sessions = await svc.list_sessions(db_session, "project-1")
        assert len(sessions) == 2

    @pytest.mark.asyncio
    async def test_delete_session(self, db_session):
        svc = ChatService()
        session = await svc.create_session(db_session, "project-1")
        await svc.add_message(db_session, session.id, "user", "Hello")

        deleted = await svc.delete_session(db_session, session.id)
        assert deleted is True

        fetched = await svc.get_session(db_session, session.id)
        assert fetched is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, db_session):
        svc = ChatService()
        result = await svc.delete_session(db_session, "nonexistent")
        assert result is False


class TestDocStore:
    @pytest.mark.asyncio
    async def test_upsert_new(self, db_session):
        store = DocStore()
        doc = await store.upsert(
            session=db_session,
            project_id="project-1",
            doc_type="orm_model",
            source_path="models/user.py",
            content="class User: pass",
            commit_sha="abc123",
        )
        assert doc.id is not None
        assert doc.project_id == "project-1"
        assert doc.source_path == "models/user.py"

    @pytest.mark.asyncio
    async def test_upsert_existing(self, db_session):
        store = DocStore()
        doc1 = await store.upsert(
            session=db_session,
            project_id="project-1",
            doc_type="orm_model",
            source_path="models/user.py",
            content="v1",
            commit_sha="abc123",
        )
        doc2 = await store.upsert(
            session=db_session,
            project_id="project-1",
            doc_type="orm_model",
            source_path="models/user.py",
            content="v2",
            commit_sha="abc123",
        )
        assert doc1.id == doc2.id
        assert doc2.content == "v2"

    @pytest.mark.asyncio
    async def test_get_docs_for_project(self, db_session):
        store = DocStore()
        await store.upsert(db_session, "p1", "orm_model", "a.py", "content_a", "sha1")
        await store.upsert(db_session, "p1", "migration", "b.sql", "content_b", "sha1")
        await store.upsert(db_session, "p2", "orm_model", "c.py", "content_c", "sha1")

        docs = await store.get_docs_for_project(db_session, "p1")
        assert len(docs) == 2

        docs_filtered = await store.get_docs_for_project(db_session, "p1", doc_type="orm_model")
        assert len(docs_filtered) == 1

    @pytest.mark.asyncio
    async def test_get_latest_docs(self, db_session):
        store = DocStore()
        await store.upsert(db_session, "p1", "orm_model", "a.py", "old content", "sha1")
        await store.upsert(db_session, "p1", "orm_model", "a.py", "new content", "sha2")
        await store.upsert(db_session, "p1", "orm_model", "b.py", "b content", "sha1")

        latest = await store.get_latest_docs(db_session, "p1")
        paths = {d.source_path for d in latest}
        assert "a.py" in paths
        assert "b.py" in paths
