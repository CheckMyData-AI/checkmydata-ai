from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.knowledge.git_tracker import ChangedFilesResult, GitTracker


@pytest.fixture
def tracker():
    return GitTracker()


class TestChangedFilesResult:
    def test_defaults(self):
        r = ChangedFilesResult()
        assert r.changed == []
        assert r.deleted == []

    def test_with_values(self):
        r = ChangedFilesResult(changed=["a.py"], deleted=["b.py"])
        assert r.changed == ["a.py"]
        assert r.deleted == ["b.py"]


class TestGetHeadSha:
    def test_returns_head_hexsha(self, tracker):
        mock_repo = MagicMock()
        mock_repo.head.commit.hexsha = "abc123def"
        with patch("app.knowledge.git_tracker.Repo", return_value=mock_repo):
            result = tracker.get_head_sha(Path("/repo"))
        assert result == "abc123def"


class TestGetChangedFiles:
    def test_full_index_when_from_sha_is_none(self, tracker):
        blob1 = MagicMock()
        blob1.type = "blob"
        blob1.path = "src/a.py"
        blob2 = MagicMock()
        blob2.type = "blob"
        blob2.path = "src/b.py"
        tree_item = MagicMock()
        tree_item.type = "tree"

        mock_repo = MagicMock()
        mock_repo.commit.return_value.tree.traverse.return_value = [
            blob1,
            tree_item,
            blob2,
        ]

        with patch("app.knowledge.git_tracker.Repo", return_value=mock_repo):
            result = tracker.get_changed_files(Path("/repo"), None, "abc123")

        assert set(result.changed) == {"src/a.py", "src/b.py"}
        assert result.deleted == []

    def test_diff_returns_changed_and_deleted(self, tracker):
        diff_entry_modified = MagicMock()
        diff_entry_modified.deleted_file = False
        diff_entry_modified.a_path = "src/mod.py"
        diff_entry_modified.b_path = "src/mod.py"

        diff_entry_deleted = MagicMock()
        diff_entry_deleted.deleted_file = True
        diff_entry_deleted.a_path = "src/old.py"
        diff_entry_deleted.b_path = None

        diff_entry_renamed = MagicMock()
        diff_entry_renamed.deleted_file = False
        diff_entry_renamed.a_path = "src/before.py"
        diff_entry_renamed.b_path = "src/after.py"

        mock_commit_from = MagicMock()
        mock_commit_from.diff.return_value = [
            diff_entry_modified,
            diff_entry_deleted,
            diff_entry_renamed,
        ]

        mock_repo = MagicMock()
        mock_repo.commit.side_effect = lambda sha: mock_commit_from if sha == "aaa" else MagicMock()

        with patch("app.knowledge.git_tracker.Repo", return_value=mock_repo):
            result = tracker.get_changed_files(Path("/repo"), "aaa", "bbb")

        assert "src/mod.py" in result.changed
        assert "src/before.py" in result.changed
        assert "src/after.py" in result.changed
        assert "src/old.py" in result.deleted

    def test_diff_exception_falls_back_to_full_index(self, tracker):
        blob = MagicMock()
        blob.type = "blob"
        blob.path = "fallback.py"

        mock_commit_from = MagicMock()
        mock_commit_from.diff.side_effect = Exception("bad diff")

        mock_commit_to = MagicMock()
        mock_commit_to.tree.traverse.return_value = [blob]

        mock_repo = MagicMock()
        mock_repo.commit.side_effect = lambda sha: (
            mock_commit_from if sha == "old" else mock_commit_to
        )

        with patch("app.knowledge.git_tracker.Repo", return_value=mock_repo):
            result = tracker.get_changed_files(Path("/repo"), "old", "new")

        assert "fallback.py" in result.changed
        assert result.deleted == []


class TestGetLastIndexedSha:
    async def test_returns_sha_when_record_exists(self, tracker):
        mock_row = MagicMock()
        mock_row.commit_sha = "sha_xyz"
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_row

        session = AsyncMock()
        session.execute.return_value = mock_result

        sha = await tracker.get_last_indexed_sha(session, "proj1")
        assert sha == "sha_xyz"

    async def test_returns_none_when_no_record(self, tracker):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        session = AsyncMock()
        session.execute.return_value = mock_result

        sha = await tracker.get_last_indexed_sha(session, "proj1")
        assert sha is None

    async def test_filters_by_branch(self, tracker):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        session = AsyncMock()
        session.execute.return_value = mock_result

        await tracker.get_last_indexed_sha(session, "proj1", branch="develop")
        session.execute.assert_called_once()


class TestRecordIndex:
    async def test_adds_and_commits(self, tracker):
        session = MagicMock()
        session.commit = AsyncMock()

        await tracker.record_index(
            session=session,
            project_id="p1",
            commit_sha="sha123",
            commit_message="initial",
            indexed_files=["a.py", "b.py"],
            branch="main",
        )

        session.add.assert_called_once()
        session.commit.assert_awaited_once()
        entry = session.add.call_args[0][0]
        assert entry.project_id == "p1"
        assert entry.commit_sha == "sha123"


class TestGetLastIndexedRecord:
    async def test_returns_record(self, tracker):
        mock_record = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_record

        session = AsyncMock()
        session.execute.return_value = mock_result

        record = await tracker.get_last_indexed_record(session, "proj1")
        assert record is mock_record

    async def test_returns_none(self, tracker):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        session = AsyncMock()
        session.execute.return_value = mock_result

        record = await tracker.get_last_indexed_record(session, "proj1")
        assert record is None

    async def test_with_branch_filter(self, tracker):
        mock_record = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_record

        session = AsyncMock()
        session.execute.return_value = mock_result

        record = await tracker.get_last_indexed_record(session, "proj1", branch="main")
        assert record is mock_record


class TestCountCommitsAhead:
    async def test_counts_commits(self, tracker):
        mock_repo = MagicMock()
        mock_repo.iter_commits.return_value = [
            MagicMock(),
            MagicMock(),
            MagicMock(),
        ]
        with patch("app.knowledge.git_tracker.Repo", return_value=mock_repo):
            count = await tracker.count_commits_ahead(Path("/repo"), "old_sha")
        assert count == 3

    async def test_returns_negative_one_on_error(self, tracker):
        with patch(
            "app.knowledge.git_tracker.Repo",
            side_effect=Exception("bad repo"),
        ):
            count = await tracker.count_commits_ahead(Path("/repo"), "sha")
        assert count == -1


class TestCleanupOldRecords:
    async def test_deletes_old_records(self, tracker):
        mock_result = MagicMock()
        mock_result.rowcount = 5

        session = AsyncMock()
        session.execute.return_value = mock_result

        deleted = await tracker.cleanup_old_records(session, "proj1", keep=10)
        assert deleted == 5
        session.commit.assert_awaited_once()

    async def test_no_commit_when_nothing_deleted(self, tracker):
        mock_result = MagicMock()
        mock_result.rowcount = 0

        session = AsyncMock()
        session.execute.return_value = mock_result

        deleted = await tracker.cleanup_old_records(session, "proj1", keep=10)
        assert deleted == 0
        session.commit.assert_not_awaited()
