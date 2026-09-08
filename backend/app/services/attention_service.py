"""What needs the user, on their return.

Every input here already existed and none of it was surfaced when somebody came back.
Production ran 143 failed indexing runs and `index_repo` completed 16 times in 94 runs;
neither fact was learnable from the interface without going looking for it. `SCN-150`.

Three properties, each with a failure mode that reads as success:

**Absent is not empty.** A source that cannot be read is named in ``degraded`` rather
than dropped, because "nothing needs you" and "I could not check" must never render the
same line. Dropping it is the version that looks fine and is wrong.

**Short and ordered.** Capped at :attr:`AttentionService.MAX_ITEMS` with the remainder
counted, most severe first. An uncapped list becomes a second inbox and stops being
read, and a silent truncation reads as "that is everything".

**Cheap.** This runs on every sign-in, so every source is a plain indexed read against
tables the request already has a session for. Nothing here opens a database connection,
clones a repository or calls an LLM — the freshness service does some of that, which is
why this deliberately re-derives the two cheap signals it needs instead of calling it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.metrics import get_metrics_collector
from app.models.connection import Connection
from app.models.db_index import DbIndexSummary
from app.models.indexing_run import IndexingRun
from app.models.project import Project

logger = logging.getLogger(__name__)

#: Severity order. The rail shows the top of this list, so the order IS the product
#: decision about what a returning user should see first.
_SEVERITY_RANK = {"critical": 0, "warning": 1, "info": 2}


def index_quota_exceeded(*, used_bytes: int | None, quota_bytes: int) -> bool:
    """Has this project's index passed what its plan sells?

    Three ways to answer "no", and each is a decision:

    * ``quota_bytes == 0`` — unlimited, which is what `0` means in every other column of
      `plans`. `enterprise` would otherwise be permanently over its own quota.
    * ``used_bytes is None`` — the measurement could not be taken, which is not evidence
      of a breach. A rail line saying "over quota" that the reader cannot verify is worse
      than no line.
    * strictly greater, not `>=`. A project exactly at its ceiling has not passed it, and
      the meter is an estimate built from row counts rather than a storage query — its
      precision does not justify a warning on the boundary.
    """
    if quota_bytes <= 0 or used_bytes is None:
        return False
    return used_bytes > quota_bytes


@dataclass
class AttentionItem:
    """One line of the rail: what it is, what happened, when, and where to go."""

    kind: str
    subject: str
    what: str
    severity: str
    route: str
    at: datetime | None = None


@dataclass
class AttentionReport:
    items: list[AttentionItem] = field(default_factory=list)
    more: int = 0
    #: Sources that could not be read. Named, never silently dropped.
    degraded: list[str] = field(default_factory=list)


class AttentionService:
    #: Five is what fits in a rail without becoming a list to scroll.
    MAX_ITEMS = 5

    #: A failure older than this is history, not news. Left in, the group never empties
    #: and stops being read — which costs more than missing an old failure.
    FAILURE_WINDOW = timedelta(days=7)

    async def for_project(self, db: AsyncSession, project_id: str) -> AttentionReport:
        report = AttentionReport()
        collected: list[AttentionItem] = []

        for name, source in (
            ("runs", self._failed_runs),
            ("sources", self._never_indexed),
            ("schedule", self._schedule_withheld),
            ("index_size", self._index_over_quota),
        ):
            try:
                collected.extend(await source(self, db, project_id))
            except Exception:
                # Named, not swallowed. The caller renders "could not check <name>",
                # which is a different sentence from "nothing needs you" — and the whole
                # point of this service is that those two must not look alike.
                report.degraded.append(name)
                logger.warning(
                    "attention: source %r failed for project %s",
                    name,
                    project_id[:8],
                    exc_info=True,
                )

        collected.sort(key=lambda i: (_SEVERITY_RANK.get(i.severity, 9), i.subject))
        report.items = collected[: self.MAX_ITEMS]
        report.more = max(0, len(collected) - self.MAX_ITEMS)
        return report

    @staticmethod
    async def _failed_runs(
        self: AttentionService, db: AsyncSession, project_id: str
    ) -> list[AttentionItem]:
        """Recent failures, per kind, and only when nothing has succeeded since.

        Per kind rather than per run: five consecutive nightly failures of the same job
        are one thing that needs the user, not five. And "has anything succeeded since"
        is the question — the rail answers *does this need me now*, not *did anything
        ever fail*.
        """
        from app.services.stale_run_reaper import REAP_ERROR

        cutoff = datetime.now(UTC) - self.FAILURE_WINDOW
        rows = (
            await db.execute(
                select(IndexingRun)
                .where(
                    IndexingRun.project_id == project_id,
                    IndexingRun.status.in_(("failed", "completed")),
                    IndexingRun.finished_at.is_not(None),
                )
                .order_by(IndexingRun.finished_at.desc())
                .limit(50)
            )
        ).scalars()

        latest: dict[str, IndexingRun] = {}
        for run in rows:
            latest.setdefault(run.kind, run)

        items: list[AttentionItem] = []
        for kind, run in latest.items():
            if run.status != "failed":
                continue
            finished = run.finished_at
            if finished is not None and finished.tzinfo is None:
                finished = finished.replace(tzinfo=UTC)
            if finished is not None and finished < cutoff:
                continue
            reaped = (run.error or "") == REAP_ERROR
            step = f" at {run.current_step}" if run.current_step else ""
            what = (
                f"reaped as stale{step} — it may not have been dead" if reaped else f"failed{step}"
            )
            items.append(
                AttentionItem(
                    kind="index_failed",
                    subject=kind.replace("_", " "),
                    what=what,
                    severity="critical",
                    route="panel=logs",
                    at=finished,
                )
            )
        return items

    @staticmethod
    async def _never_indexed(
        self: AttentionService, db: AsyncSession, project_id: str
    ) -> list[AttentionItem]:
        """A source configured and never indexed contributes nothing to an answer.

        Never-indexed rather than stale: the first is a setup step the user did not
        finish, the second is a maintenance question, and only the first is worth the
        rail's space on a return.
        """
        items: list[AttentionItem] = []

        project = (
            await db.execute(select(Project).where(Project.id == project_id))
        ).scalar_one_or_none()
        if project is not None and project.repo_url:
            done = (
                await db.execute(
                    select(IndexingRun.id).where(
                        IndexingRun.project_id == project_id,
                        IndexingRun.kind == "index_repo",
                        IndexingRun.status == "completed",
                    )
                )
            ).first()
            if done is None:
                items.append(
                    AttentionItem(
                        kind="repo_never_indexed",
                        subject=project.name,
                        what=(
                            "the repository has never finished indexing — "
                            "code answers are unavailable"
                        ),
                        severity="warning",
                        route="panel=overview",
                    )
                )

        conns = (
            (
                await db.execute(
                    select(Connection).where(
                        Connection.project_id == project_id,
                        Connection.is_active.is_(True),
                    )
                )
            )
            .scalars()
            .all()
        )
        if conns:
            indexed = set(
                (
                    await db.execute(
                        select(DbIndexSummary.connection_id).where(
                            DbIndexSummary.connection_id.in_([c.id for c in conns])
                        )
                    )
                )
                .scalars()
                .all()
            )
            for conn in conns:
                if conn.id in indexed:
                    continue
                items.append(
                    AttentionItem(
                        kind="connection_never_indexed",
                        subject=conn.name,
                        what="never indexed — the agent has no schema for it",
                        severity="warning",
                        route="panel=connections",
                    )
                )
        return items

    @staticmethod
    async def _schedule_withheld(
        self: AttentionService, db: AsyncSession, project_id: str
    ) -> list[AttentionItem]:
        """`SCN-147`: the absence of automation is visible where the automation would be.

        Until the data workspace exists this is that place, and it is the honest one —
        a user whose nightly sync will never run should not have to open a billing page
        to find that out.
        """
        from app.entitlements import may_run_scheduled_work

        project = (
            await db.execute(select(Project).where(Project.id == project_id))
        ).scalar_one_or_none()
        if project is None or project.owner_id is None:
            return []
        if await may_run_scheduled_work(db, project.owner_id):
            return []
        return [
            AttentionItem(
                kind="schedule_withheld",
                subject=project.name,
                what="scheduled syncs need a subscription — indexing by hand still works",
                severity="info",
                route="panel=settings",
            )
        ]

    @staticmethod
    async def _index_over_quota(
        self: AttentionService, db: AsyncSession, project_id: str
    ) -> list[AttentionItem]:
        """`SCN-152` (D5, option a): the tier sells "1 GB index" — say when it is spent.

        `plans.max_index_bytes` has been sold since 2026-08-31 and `estimate_index_bytes`
        has existed beside it, called from a test and from nothing else. The promise, the
        column and the meter all existed; nothing compared them.

        Warn, never block. Refusing to index would make the product unevaluable for the
        account most likely to be over — and the same reasoning already settled the
        scheduled-work gate. `severity="warning"` rather than `critical`: nothing has
        stopped working.

        Measured from row counts rather than a storage query, because the index spans
        Postgres, a vector store that may be pgvector or Chroma, and gzip snapshots on an
        ephemeral disk. Anchor: `esim-php` measures ~460 MB against `base`'s 1 GB.
        """
        from app.entitlements import index_quota_bytes
        from app.models.code_graph import CodeGraphEdge, CodeGraphSymbol
        from app.models.knowledge_doc import KnowledgeDoc
        from app.services.plan_catalogue import estimate_index_bytes

        project = (
            await db.execute(select(Project).where(Project.id == project_id))
        ).scalar_one_or_none()
        if project is None or project.owner_id is None:
            return []

        quota = await index_quota_bytes(db, project.owner_id)
        if quota <= 0:
            # Unlimited. Skipped before the counting queries rather than after, so an
            # `enterprise` project pays nothing for a question with a known answer.
            return []

        docs_bytes = int(
            await db.scalar(
                select(func.coalesce(func.sum(func.length(KnowledgeDoc.content)), 0)).where(
                    KnowledgeDoc.project_id == project_id
                )
            )
            or 0
        )
        symbols = int(
            await db.scalar(
                select(func.count(CodeGraphSymbol.id)).where(
                    CodeGraphSymbol.project_id == project_id
                )
            )
            or 0
        )
        edges = int(
            await db.scalar(
                select(func.count(CodeGraphEdge.id)).where(CodeGraphEdge.project_id == project_id)
            )
            or 0
        )
        used = estimate_index_bytes(
            docs_bytes=docs_bytes,
            symbols=symbols,
            edges=edges,
            # One embedding per symbol is the shape `code_symbol_embed` produces. Counting
            # the vector store itself would mean asking pgvector or Chroma depending on
            # deployment, which is the coupling `estimate_index_bytes` exists to avoid.
            embeddings=symbols,
        )
        if not index_quota_exceeded(used_bytes=used, quota_bytes=quota):
            return []

        get_metrics_collector().record_index_over_quota()
        logger.warning(
            "index quota: project %s holds ~%.2f GB of index against a %.2f GB plan "
            "limit — indexing continues, this is a warning",
            project_id[:8],
            used / (1024**3),
            quota / (1024**3),
        )
        return [
            AttentionItem(
                kind="index_over_quota",
                subject=project.name,
                what=(
                    f"index is ~{used / (1024**3):.1f} GB against a "
                    f"{quota / (1024**3):.0f} GB plan limit — indexing still runs"
                ),
                severity="warning",
                route="panel=settings",
            )
        ]
