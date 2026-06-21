"""Unit tests for touch_heartbeat on DbIndexService, CodeDbSyncService, CheckpointService."""

from unittest.mock import AsyncMock, MagicMock

from app.models.code_db_sync import CodeDbSyncSummary
from app.models.db_index import DbIndexSummary
from app.services.checkpoint_service import CheckpointService
from app.services.code_db_sync_service import CodeDbSyncService
from app.services.db_index_service import DbIndexService


def _mock_session(scalar_one_or_none=None):
    session = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = scalar_one_or_none
    session.execute = AsyncMock(return_value=result_mock)
    return session


# ---------------------------------------------------------------------------
# DbIndexService
# ---------------------------------------------------------------------------


async def test_touch_heartbeat_sets_db_index_heartbeat_existing():
    """touch_heartbeat sets heartbeat_at on an existing DbIndexSummary row."""
    svc = DbIndexService()
    summary = MagicMock(spec=DbIndexSummary)
    summary.heartbeat_at = None
    session = _mock_session(scalar_one_or_none=summary)

    await svc.touch_heartbeat(session, "conn-1")

    assert summary.heartbeat_at is not None
    session.flush.assert_awaited_once()


async def test_touch_heartbeat_creates_db_index_summary_when_missing():
    """touch_heartbeat creates DbIndexSummary row when none exists."""
    svc = DbIndexService()
    session = _mock_session(scalar_one_or_none=None)
    session.add = MagicMock()

    await svc.touch_heartbeat(session, "conn-new")

    session.add.assert_called_once()
    added = session.add.call_args[0][0]
    assert isinstance(added, DbIndexSummary)
    assert added.heartbeat_at is not None


# ---------------------------------------------------------------------------
# CodeDbSyncService
# ---------------------------------------------------------------------------


async def test_touch_heartbeat_sets_sync_heartbeat_existing():
    """touch_heartbeat sets heartbeat_at on an existing CodeDbSyncSummary row."""
    svc = CodeDbSyncService()
    summary = MagicMock(spec=CodeDbSyncSummary)
    summary.heartbeat_at = None
    session = _mock_session(scalar_one_or_none=summary)

    await svc.touch_heartbeat(session, "conn-1")

    assert summary.heartbeat_at is not None
    session.flush.assert_awaited_once()


async def test_touch_heartbeat_creates_sync_summary_when_missing():
    """touch_heartbeat creates CodeDbSyncSummary row when none exists."""
    svc = CodeDbSyncService()
    session = _mock_session(scalar_one_or_none=None)
    session.add = MagicMock()

    await svc.touch_heartbeat(session, "conn-new")

    session.add.assert_called_once()
    added = session.add.call_args[0][0]
    assert isinstance(added, CodeDbSyncSummary)
    assert added.heartbeat_at is not None


# ---------------------------------------------------------------------------
# CheckpointService
# ---------------------------------------------------------------------------


async def test_touch_heartbeat_checkpoint_executes_update():
    """touch_heartbeat on CheckpointService issues an UPDATE and flushes."""
    svc = CheckpointService()
    session = AsyncMock()

    await svc.touch_heartbeat(session, "cp-abc-123")

    session.execute.assert_awaited_once()
    session.flush.assert_awaited_once()
