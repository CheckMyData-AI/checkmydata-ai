import logging

from sqlalchemy import and_, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge_doc import KnowledgeDoc

logger = logging.getLogger(__name__)


class DocStore:
    """Documentation storage keyed by (project_id, source_path).

    Each source file gets exactly one row; re-indexing updates it in place
    and refreshes the commit_sha.
    """

    async def upsert(
        self,
        session: AsyncSession,
        project_id: str,
        doc_type: str,
        source_path: str,
        content: str,
        commit_sha: str | None = None,
        embedding_id: str | None = None,
    ) -> KnowledgeDoc:
        content = content.replace("\x00", "")

        existing = await session.execute(
            select(KnowledgeDoc).where(
                and_(
                    KnowledgeDoc.project_id == project_id,
                    KnowledgeDoc.source_path == source_path,
                )
            )
        )
        doc = existing.scalar_one_or_none()

        if doc:
            doc.content = content
            doc.doc_type = doc_type
            doc.commit_sha = commit_sha
            if embedding_id:
                doc.embedding_id = embedding_id
        else:
            doc = KnowledgeDoc(
                project_id=project_id,
                doc_type=doc_type,
                source_path=source_path,
                content=content,
                commit_sha=commit_sha,
                embedding_id=embedding_id,
            )
            session.add(doc)

        await session.commit()
        await session.refresh(doc)
        return doc

    async def get_docs_for_project(
        self, session: AsyncSession, project_id: str, doc_type: str | None = None
    ) -> list[KnowledgeDoc]:
        stmt = select(KnowledgeDoc).where(KnowledgeDoc.project_id == project_id)
        if doc_type:
            stmt = stmt.where(KnowledgeDoc.doc_type == doc_type)
        result = await session.execute(stmt.order_by(KnowledgeDoc.updated_at.desc()))
        return list(result.scalars().all())

    async def delete_docs_for_paths(
        self,
        session: AsyncSession,
        project_id: str,
        source_paths: list[str],
    ) -> int:
        """Delete all knowledge docs whose source_path is in *source_paths*."""
        if not source_paths:
            return 0
        result = await session.execute(
            delete(KnowledgeDoc).where(
                and_(
                    KnowledgeDoc.project_id == project_id,
                    KnowledgeDoc.source_path.in_(source_paths),
                )
            )
        )
        await session.commit()
        count = result.rowcount  # type: ignore[union-attr]
        logger.debug(
            "Deleted %d knowledge docs for %d paths in project %s",
            count,
            len(source_paths),
            project_id,
        )
        return count

    async def get_doc_by_path(
        self,
        session: AsyncSession,
        project_id: str,
        source_path: str,
    ) -> KnowledgeDoc | None:
        result = await session.execute(
            select(KnowledgeDoc).where(
                and_(
                    KnowledgeDoc.project_id == project_id,
                    KnowledgeDoc.source_path == source_path,
                )
            )
        )
        return result.scalar_one_or_none()

    async def get_latest_docs(
        self,
        session: AsyncSession,
        project_id: str,
    ) -> list[KnowledgeDoc]:
        """Return all docs for a project.

        Since upsert keys on ``(project_id, source_path)`` there is always
        exactly one row per source file, so this is equivalent to
        ``get_docs_for_project``.
        """
        return await self.get_docs_for_project(session, project_id)
