import logging

from sqlalchemy import and_, delete, func, select, update
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
        content_hash: str | None = None,
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
            # Written unconditionally, `None` included: a caller that did not compute a
            # hash has not verified one, and leaving the previous value would claim this
            # content was generated from inputs nobody compared it against.
            doc.content_hash = content_hash
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
                content_hash=content_hash,
            )
            session.add(doc)

        await session.commit()
        await session.refresh(doc)
        return doc

    async def touch_reused(
        self,
        session: AsyncSession,
        project_id: str,
        source_paths: list[str],
        commit_sha: str | None,
    ) -> int:
        """Mark documents whose inputs did not change as current for this commit.

        A cache hit still has to say WHEN it was last confirmed: `commit_sha` and
        `updated_at` are what freshness reporting and `sync-history` read, and a document
        left at an old sha reads as stale when it is merely unchanged.

        One statement per batch rather than one per document. A rebuild of the one real
        project reuses ~700 of 758, and 700 round trips is its own cost.
        """
        if not source_paths:
            return 0
        result = await session.execute(
            update(KnowledgeDoc)
            .where(
                and_(
                    KnowledgeDoc.project_id == project_id,
                    KnowledgeDoc.source_path.in_(source_paths),
                )
            )
            .values(commit_sha=commit_sha, updated_at=func.now())
        )
        return int(getattr(result, "rowcount", 0) or 0)

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
        count = result.rowcount  # type: ignore[attr-defined]
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
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[KnowledgeDoc]:
        """Return docs for a project, one page at a time when asked.

        Since upsert keys on ``(project_id, source_path)`` there is always exactly
        one row per source file, so an unbounded call is equivalent to
        ``get_docs_for_project``.

        The bounds are optional and default to absent because the indexing pipeline
        genuinely wants every row. What they fix is the HTTP side (API-09), where
        `?limit=1` used to load all 763 rows of this table — `content` is `Text`, and
        it holds the generated prose — to return one object of five scalar fields.
        """
        stmt = select(KnowledgeDoc).where(KnowledgeDoc.project_id == project_id)
        stmt = stmt.order_by(KnowledgeDoc.updated_at.desc())
        if offset:
            stmt = stmt.offset(offset)
        if limit is not None:
            stmt = stmt.limit(limit)
        result = await session.execute(stmt)
        return list(result.scalars().all())
