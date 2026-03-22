from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.backup_manager import BackupManager


@pytest.fixture
def tmp_backup_dir(tmp_path: Path) -> Path:
    return tmp_path / "backups"


@pytest.fixture
def backup_mgr(tmp_backup_dir: Path) -> BackupManager:
    mgr = BackupManager()
    mgr.backup_dir = tmp_backup_dir
    mgr.retention_days = 3
    return mgr


class TestRunBackupCreatesDir:
    async def test_creates_timestamp_directory(self, backup_mgr):
        with (
            patch.object(
                backup_mgr,
                "_backup_database",
                new_callable=AsyncMock,
                return_value=0,
            ),
            patch.object(
                backup_mgr,
                "_backup_chroma",
                new_callable=AsyncMock,
                return_value=0,
            ),
            patch.object(
                backup_mgr,
                "_backup_rules",
                new_callable=AsyncMock,
                return_value=0,
            ),
        ):
            manifest = await backup_mgr.run_backup("manual")

        dirs = [d for d in backup_mgr.backup_dir.iterdir() if d.is_dir()]
        assert len(dirs) == 1
        assert manifest["reason"] == "manual"
        assert manifest["total_size_bytes"] == 0

    async def test_manifest_written_to_disk(self, backup_mgr):
        with (
            patch.object(
                backup_mgr,
                "_backup_database",
                new_callable=AsyncMock,
                return_value=10,
            ),
            patch.object(
                backup_mgr,
                "_backup_chroma",
                new_callable=AsyncMock,
                return_value=20,
            ),
            patch.object(
                backup_mgr,
                "_backup_rules",
                new_callable=AsyncMock,
                return_value=30,
            ),
        ):
            await backup_mgr.run_backup("auto")

        dirs = list(backup_mgr.backup_dir.iterdir())
        manifest_path = dirs[0] / "manifest.json"
        assert manifest_path.exists()
        data = json.loads(manifest_path.read_text())
        assert data["total_size_bytes"] == 60
        assert data["reason"] == "auto"

    async def test_errors_propagated_in_manifest(self, backup_mgr):
        async def fake_db(dest, manifest):
            manifest["errors"].append("DB error")
            return 0

        with (
            patch.object(backup_mgr, "_backup_database", side_effect=fake_db),
            patch.object(
                backup_mgr,
                "_backup_chroma",
                new_callable=AsyncMock,
                return_value=0,
            ),
            patch.object(
                backup_mgr,
                "_backup_rules",
                new_callable=AsyncMock,
                return_value=0,
            ),
        ):
            manifest = await backup_mgr.run_backup("test")

        assert "DB error" in manifest["errors"]


class TestBackupDatabase:
    async def test_unsupported_db_type(self, backup_mgr, tmp_path):
        with patch("app.core.backup_manager.settings") as mock_s:
            mock_s.database_url = "oracle://host/db"
            manifest: dict = {"files": {}, "errors": []}
            dest = tmp_path / "db"
            size = await backup_mgr._backup_database(dest, manifest)

        assert size == 0
        assert any("Unsupported" in e for e in manifest["errors"])

    async def test_sqlite_backup_missing_file(self, backup_mgr, tmp_path):
        with patch("app.core.backup_manager.settings") as mock_s:
            mock_s.database_url = "sqlite:///nonexistent.db"
            manifest: dict = {"files": {}, "errors": []}
            dest = tmp_path / "db"
            dest.mkdir(parents=True)
            size = await backup_mgr._backup_sqlite(dest, manifest)

        assert size == 0
        assert any("not found" in e for e in manifest["errors"])

    async def test_database_exception_handled(self, backup_mgr, tmp_path):
        with patch("app.core.backup_manager.settings") as mock_s:
            mock_s.database_url = "sqlite:///test.db"
            manifest: dict = {"files": {}, "errors": []}
            dest = tmp_path / "db"

            with patch.object(
                backup_mgr,
                "_backup_sqlite",
                side_effect=Exception("boom"),
            ):
                size = await backup_mgr._backup_database(dest, manifest)

        assert size == 0
        assert any("failed" in e.lower() for e in manifest["errors"])


class TestBackupChroma:
    async def test_skips_remote_server(self, backup_mgr, tmp_path):
        with patch("app.core.backup_manager.settings") as mock_s:
            mock_s.chroma_server_url = "http://remote:8000"
            manifest: dict = {"files": {}, "errors": []}
            size = await backup_mgr._backup_chroma(tmp_path / "chroma", manifest)

        assert size == 0
        assert manifest["files"]["chroma"]["skipped"] is True

    async def test_skips_missing_directory(self, backup_mgr, tmp_path):
        with patch("app.core.backup_manager.settings") as mock_s:
            mock_s.chroma_server_url = ""
            mock_s.chroma_persist_dir = str(tmp_path / "nonexistent_chroma")
            manifest: dict = {"files": {}, "errors": []}
            size = await backup_mgr._backup_chroma(tmp_path / "chroma", manifest)

        assert size == 0
        assert manifest["files"]["chroma"]["skipped"] is True

    async def test_copies_chroma_directory(self, backup_mgr, tmp_path):
        src = tmp_path / "chroma_src"
        src.mkdir()
        (src / "data.bin").write_bytes(b"x" * 100)

        with patch("app.core.backup_manager.settings") as mock_s:
            mock_s.chroma_server_url = ""
            mock_s.chroma_persist_dir = str(src)
            manifest: dict = {"files": {}, "errors": []}
            dest = tmp_path / "chroma_dest"
            size = await backup_mgr._backup_chroma(dest, manifest)

        assert size > 0
        assert (dest / "data.bin").exists()


class TestBackupRules:
    async def test_skips_missing_rules_dir(self, backup_mgr, tmp_path):
        with patch("app.core.backup_manager.settings") as mock_s:
            mock_s.custom_rules_dir = str(tmp_path / "no_rules")
            manifest: dict = {"files": {}, "errors": []}
            size = await backup_mgr._backup_rules(tmp_path / "rules_dest", manifest)

        assert size == 0
        assert manifest["files"]["rules"]["skipped"] is True

    async def test_copies_rules_directory(self, backup_mgr, tmp_path):
        src = tmp_path / "rules_src"
        src.mkdir()
        (src / "rule1.yaml").write_text("rule: 1")

        with patch("app.core.backup_manager.settings") as mock_s:
            mock_s.custom_rules_dir = str(src)
            manifest: dict = {"files": {}, "errors": []}
            dest = tmp_path / "rules_dest"
            size = await backup_mgr._backup_rules(dest, manifest)

        assert size > 0
        assert (dest / "rule1.yaml").exists()


class TestPruneOldBackups:
    async def test_keeps_retention_count(self, backup_mgr):
        for i in range(6):
            d = backup_mgr.backup_dir / f"2026010{i}_000000"
            d.mkdir(parents=True)
            (d / "manifest.json").write_text("{}")

        await backup_mgr._prune_old_backups()
        remaining = list(backup_mgr.backup_dir.iterdir())
        assert len(remaining) == 3

    async def test_no_error_when_dir_missing(self, backup_mgr):
        await backup_mgr._prune_old_backups()

    async def test_handles_rmtree_failure(self, backup_mgr):
        for i in range(5):
            d = backup_mgr.backup_dir / f"2026010{i}_000000"
            d.mkdir(parents=True)

        with patch(
            "app.core.backup_manager.shutil.rmtree",
            side_effect=PermissionError("denied"),
        ):
            await backup_mgr._prune_old_backups()

        remaining = list(backup_mgr.backup_dir.iterdir())
        assert len(remaining) == 5


class TestListBackups:
    async def test_empty_when_no_dir(self, backup_mgr):
        result = await backup_mgr.list_backups()
        assert result == []

    async def test_lists_with_valid_manifests(self, backup_mgr):
        d1 = backup_mgr.backup_dir / "20260301_100000"
        d1.mkdir(parents=True)
        (d1 / "manifest.json").write_text(
            json.dumps({"timestamp": "20260301_100000", "reason": "a"})
        )
        d2 = backup_mgr.backup_dir / "20260302_100000"
        d2.mkdir(parents=True)
        (d2 / "manifest.json").write_text(
            json.dumps({"timestamp": "20260302_100000", "reason": "b"})
        )

        result = await backup_mgr.list_backups()
        assert len(result) == 2
        assert result[0]["timestamp"] == "20260302_100000"

    async def test_incomplete_backup_no_manifest(self, backup_mgr):
        d = backup_mgr.backup_dir / "20260305_100000"
        d.mkdir(parents=True)

        result = await backup_mgr.list_backups()
        assert len(result) == 1
        assert result[0]["incomplete"] is True

    async def test_corrupt_manifest(self, backup_mgr):
        d = backup_mgr.backup_dir / "20260306_100000"
        d.mkdir(parents=True)
        (d / "manifest.json").write_text("NOT JSON{{{")

        result = await backup_mgr.list_backups()
        assert len(result) == 1
        assert result[0]["error"] is True

    async def test_skips_files_in_backup_dir(self, backup_mgr):
        backup_mgr.backup_dir.mkdir(parents=True)
        (backup_mgr.backup_dir / "stray_file.txt").write_text("oops")
        d = backup_mgr.backup_dir / "20260307_100000"
        d.mkdir(parents=True)
        (d / "manifest.json").write_text(json.dumps({"timestamp": "20260307_100000"}))

        result = await backup_mgr.list_backups()
        assert len(result) == 1


class TestBackupPostgres:
    async def test_pg_dump_failure(self, backup_mgr, tmp_path):
        with patch("app.core.backup_manager.settings") as mock_s:
            mock_s.database_url = "postgresql+asyncpg://u:p@host/db"
            manifest: dict = {"files": {}, "errors": []}
            dest = tmp_path / "pg_backup"
            dest.mkdir(parents=True)

            mock_result = MagicMock()
            mock_result.returncode = 1
            mock_result.stderr = "pg_dump: connection refused"

            with patch(
                "app.core.backup_manager.subprocess.run",
                return_value=mock_result,
            ):
                size = await backup_mgr._backup_postgres(dest, manifest)

        assert size == 0
        assert any("pg_dump" in e for e in manifest["errors"])
