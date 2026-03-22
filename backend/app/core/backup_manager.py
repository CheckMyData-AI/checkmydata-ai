"""Automated backup manager for project data (DB, ChromaDB, rules)."""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)


class BackupManager:
    """Creates point-in-time backups of all project data."""

    def __init__(self) -> None:
        self.backup_dir = Path(settings.backup_dir)
        self.retention_days = settings.backup_retention_days

    async def run_backup(self, reason: str = "scheduled") -> dict:
        """Main entry point. Returns manifest dict on success, raises on failure."""
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        dest = self.backup_dir / timestamp
        dest.mkdir(parents=True, exist_ok=True)

        manifest: dict = {
            "timestamp": timestamp,
            "reason": reason,
            "created_at": datetime.now(UTC).isoformat(),
            "files": {},
            "errors": [],
        }

        db_size = await self._backup_database(dest / "db", manifest)
        chroma_size = await self._backup_chroma(dest / "chroma", manifest)
        rules_size = await self._backup_rules(dest / "rules", manifest)

        manifest["total_size_bytes"] = db_size + chroma_size + rules_size

        manifest_path = dest / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, default=str))

        await self._prune_old_backups()

        logger.info(
            "Backup complete: reason=%s, size=%d bytes, path=%s",
            reason,
            manifest["total_size_bytes"],
            dest,
        )
        return manifest

    async def _backup_database(self, dest: Path, manifest: dict) -> int:
        dest.mkdir(parents=True, exist_ok=True)
        db_url = settings.database_url

        try:
            if "sqlite" in db_url:
                return await self._backup_sqlite(dest, manifest)
            elif "postgresql" in db_url or "postgres" in db_url:
                return await self._backup_postgres(dest, manifest)
            else:
                manifest["errors"].append(f"Unsupported DB type: {db_url.split(':')[0]}")
                return 0
        except Exception as e:
            manifest["errors"].append(f"Database backup failed: {e}")
            logger.exception("Database backup failed")
            return 0

    async def _backup_sqlite(self, dest: Path, manifest: dict) -> int:
        db_url = settings.database_url
        db_path_str = db_url.split("///")[-1] if "///" in db_url else "./data/agent.db"
        db_path = Path(db_path_str)

        if not db_path.exists():
            manifest["errors"].append(f"SQLite file not found: {db_path}")
            return 0

        backup_file = dest / "agent.db"
        result = await asyncio.to_thread(
            subprocess.run,
            ["sqlite3", str(db_path), f".backup '{backup_file}'"],
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode != 0:
            shutil.copy2(db_path, backup_file)

        size = backup_file.stat().st_size if backup_file.exists() else 0
        manifest["files"]["database"] = {
            "path": str(backup_file),
            "size_bytes": size,
            "type": "sqlite",
        }
        manifest["db_type"] = "sqlite"
        return size

    async def _backup_postgres(self, dest: Path, manifest: dict) -> int:
        backup_file = dest / "dump.sql.gz"

        raw_url = settings.database_url
        for prefix in ("postgresql+asyncpg://", "postgres+asyncpg://"):
            if raw_url.startswith(prefix):
                raw_url = "postgresql://" + raw_url[len(prefix) :]
                break

        def _run_pg_dump() -> subprocess.CompletedProcess[bytes]:
            pg = subprocess.Popen(
                ["pg_dump", raw_url],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            gz = subprocess.Popen(
                ["gzip"],
                stdin=pg.stdout,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            if pg.stdout:
                pg.stdout.close()
            gz_out, gz_err = gz.communicate(timeout=300)
            pg.wait(timeout=10)
            backup_file.write_bytes(gz_out)
            return subprocess.CompletedProcess(
                args=["pg_dump"],
                returncode=pg.returncode or gz.returncode,
                stderr=(pg.stderr.read() if pg.stderr else b"") + (gz_err or b""),
            )

        result = await asyncio.to_thread(_run_pg_dump)

        if result.returncode != 0:
            stderr = result.stderr
            err_msg = stderr if isinstance(stderr, str) else stderr.decode(errors="replace")
            manifest["errors"].append(f"pg_dump failed: {err_msg[:500]}")
            return 0

        size = backup_file.stat().st_size if backup_file.exists() else 0
        manifest["files"]["database"] = {
            "path": str(backup_file),
            "size_bytes": size,
            "type": "postgres",
        }
        manifest["db_type"] = "postgres"
        return size

    async def _backup_chroma(self, dest: Path, manifest: dict) -> int:
        if settings.chroma_server_url:
            manifest["files"]["chroma"] = {"skipped": True, "reason": "remote server"}
            return 0

        src = Path(settings.chroma_persist_dir)
        if not src.exists():
            manifest["files"]["chroma"] = {"skipped": True, "reason": "directory not found"}
            return 0

        try:
            await asyncio.to_thread(shutil.copytree, src, dest, dirs_exist_ok=True)
            size = await asyncio.to_thread(self._dir_size, dest)
            manifest["files"]["chroma"] = {"path": str(dest), "size_bytes": size}
            return size
        except Exception as e:
            manifest["errors"].append(f"ChromaDB backup failed: {e}")
            return 0

    async def _backup_rules(self, dest: Path, manifest: dict) -> int:
        src = Path(settings.custom_rules_dir)
        if not src.exists():
            manifest["files"]["rules"] = {"skipped": True, "reason": "directory not found"}
            return 0

        try:
            await asyncio.to_thread(shutil.copytree, src, dest, dirs_exist_ok=True)
            size = await asyncio.to_thread(self._dir_size, dest)
            manifest["files"]["rules"] = {"path": str(dest), "size_bytes": size}
            return size
        except Exception as e:
            manifest["errors"].append(f"Rules backup failed: {e}")
            return 0

    async def _prune_old_backups(self) -> None:
        if not self.backup_dir.exists():
            return

        backups = sorted(
            [d for d in self.backup_dir.iterdir() if d.is_dir()],
            key=lambda d: d.name,
            reverse=True,
        )

        to_remove = backups[self.retention_days :]
        for old_dir in to_remove:
            try:
                await asyncio.to_thread(shutil.rmtree, old_dir)
                logger.info("Pruned old backup: %s", old_dir.name)
            except Exception:
                logger.warning("Failed to prune backup: %s", old_dir.name)

    async def list_backups(self) -> list[dict]:
        if not self.backup_dir.exists():
            return []

        result = []
        for d in sorted(self.backup_dir.iterdir(), reverse=True):
            if not d.is_dir():
                continue
            manifest_path = d / "manifest.json"
            if manifest_path.exists():
                try:
                    data = json.loads(manifest_path.read_text())
                    data["backup_path"] = str(d)
                    result.append(data)
                except Exception:
                    result.append({"timestamp": d.name, "backup_path": str(d), "error": True})
            else:
                result.append({"timestamp": d.name, "backup_path": str(d), "incomplete": True})
        return result

    @staticmethod
    def _dir_size(path: Path) -> int:
        return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
