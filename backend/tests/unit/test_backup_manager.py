"""Tests for the backup manager."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

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


class TestRunBackup:
    async def test_creates_manifest(self, backup_mgr: BackupManager):
        with (
            patch.object(backup_mgr, "_backup_database", new_callable=AsyncMock, return_value=100),
            patch.object(backup_mgr, "_backup_chroma", new_callable=AsyncMock, return_value=200),
            patch.object(backup_mgr, "_backup_rules", new_callable=AsyncMock, return_value=50),
        ):
            manifest = await backup_mgr.run_backup("test")

        assert manifest["reason"] == "test"
        assert manifest["total_size_bytes"] == 350
        assert "timestamp" in manifest

        dirs = list(backup_mgr.backup_dir.iterdir())
        assert len(dirs) == 1
        manifest_file = dirs[0] / "manifest.json"
        assert manifest_file.exists()
        data = json.loads(manifest_file.read_text())
        assert data["reason"] == "test"

    async def test_prune_old_backups(self, backup_mgr: BackupManager):
        for i in range(5):
            d = backup_mgr.backup_dir / f"2026010{i}_000000"
            d.mkdir(parents=True)
            (d / "manifest.json").write_text("{}")

        await backup_mgr._prune_old_backups()
        remaining = list(backup_mgr.backup_dir.iterdir())
        assert len(remaining) == 3


class TestListBackups:
    async def test_list_empty(self, backup_mgr: BackupManager):
        result = await backup_mgr.list_backups()
        assert result == []

    async def test_list_with_backups(self, backup_mgr: BackupManager):
        d = backup_mgr.backup_dir / "20260320_120000"
        d.mkdir(parents=True)
        manifest = {"timestamp": "20260320_120000", "reason": "test"}
        (d / "manifest.json").write_text(json.dumps(manifest))

        result = await backup_mgr.list_backups()
        assert len(result) == 1
        assert result[0]["reason"] == "test"


class TestDirSize:
    def test_dir_size(self, tmp_path: Path):
        (tmp_path / "a.txt").write_text("hello")
        (tmp_path / "b.txt").write_text("world!")
        size = BackupManager._dir_size(tmp_path)
        assert size == 11
