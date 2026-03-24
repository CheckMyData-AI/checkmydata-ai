"""Two-tier GeoIP cache — in-memory LRU + SQLite persistent storage.

L1 (hot):  OrderedDict with LRU eviction, bounded by ``memory_max_size``.
L2 (warm): SQLite ``WITHOUT ROWID`` table, WAL mode, handles millions of rows.

All operations are protected by a threading.Lock for safe concurrent access.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
from collections import OrderedDict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.geoip_service import GeoIPResult

logger = logging.getLogger(__name__)

_CREATE_TABLE = """\
CREATE TABLE IF NOT EXISTS geoip_cache (
    ip TEXT PRIMARY KEY,
    country_code TEXT NOT NULL,
    country_name TEXT NOT NULL,
    is_private INTEGER NOT NULL DEFAULT 0
) WITHOUT ROWID
"""


class GeoIPCache:
    """Two-tier IP geolocation cache (memory LRU + SQLite)."""

    def __init__(self, db_path: str, memory_max_size: int = 100_000) -> None:
        self._memory_max_size = memory_max_size
        self._mem: OrderedDict[str, GeoIPResult] = OrderedDict()
        self._lock = threading.Lock()

        db_dir = os.path.dirname(db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute(_CREATE_TABLE)
        self._conn.commit()

        row = self._conn.execute("SELECT COUNT(*) FROM geoip_cache").fetchone()
        logger.info("GeoIP cache opened: %s (%d persistent entries)", db_path, row[0])

    # ------------------------------------------------------------------
    # single-key operations
    # ------------------------------------------------------------------

    def get(self, ip: str) -> GeoIPResult | None:
        """Return cached result or ``None`` on miss."""
        with self._lock:
            hit = self._mem.get(ip)
            if hit is not None:
                self._mem.move_to_end(ip)
                return hit

            row = self._conn.execute(
                "SELECT country_code, country_name, is_private FROM geoip_cache WHERE ip = ?",
                (ip,),
            ).fetchone()

        if row is None:
            return None

        from app.services.geoip_service import GeoIPResult

        result = GeoIPResult(country_code=row[0], country_name=row[1], is_private=bool(row[2]))
        with self._lock:
            self._mem_put(ip, result)
        return result

    def put(self, ip: str, result: GeoIPResult) -> None:
        """Store a result in both tiers."""
        with self._lock:
            self._mem_put(ip, result)
            self._conn.execute(
                "INSERT OR REPLACE INTO geoip_cache (ip, country_code, country_name, is_private) "
                "VALUES (?, ?, ?, ?)",
                (ip, result.country_code, result.country_name, int(result.is_private)),
            )
            self._conn.commit()

    # ------------------------------------------------------------------
    # batch operations
    # ------------------------------------------------------------------

    def get_many(self, ips: list[str]) -> dict[str, GeoIPResult]:
        """Return a dict of cached results for the given IPs (misses omitted)."""
        from app.services.geoip_service import GeoIPResult

        found: dict[str, GeoIPResult] = {}
        remaining: list[str] = []

        with self._lock:
            for ip in ips:
                hit = self._mem.get(ip)
                if hit is not None:
                    self._mem.move_to_end(ip)
                    found[ip] = hit
                else:
                    remaining.append(ip)

            if remaining:
                for batch_start in range(0, len(remaining), 500):
                    batch = remaining[batch_start : batch_start + 500]
                    placeholders = ",".join("?" * len(batch))
                    rows = self._conn.execute(
                        f"SELECT ip, country_code, country_name, is_private "  # noqa: S608
                        f"FROM geoip_cache WHERE ip IN ({placeholders})",
                        batch,
                    ).fetchall()
                    for row in rows:
                        r = GeoIPResult(
                            country_code=row[1],
                            country_name=row[2],
                            is_private=bool(row[3]),
                        )
                        found[row[0]] = r
                        self._mem_put(row[0], r)

        return found

    def put_many(self, items: list[tuple[str, GeoIPResult]]) -> None:
        """Batch-insert results into both tiers."""
        if not items:
            return
        with self._lock:
            for ip, result in items:
                self._mem_put(ip, result)
            self._conn.executemany(
                "INSERT OR REPLACE INTO geoip_cache (ip, country_code, country_name, is_private) "
                "VALUES (?, ?, ?, ?)",
                [(ip, r.country_code, r.country_name, int(r.is_private)) for ip, r in items],
            )
            self._conn.commit()

    # ------------------------------------------------------------------
    # housekeeping
    # ------------------------------------------------------------------

    def stats(self) -> dict[str, int]:
        """Return cache size statistics."""
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) FROM geoip_cache").fetchone()
            mem_size = len(self._mem)
        return {"memory_entries": mem_size, "sqlite_entries": row[0]}

    def clear(self) -> None:
        """Wipe both tiers."""
        with self._lock:
            self._mem.clear()
            self._conn.execute("DELETE FROM geoip_cache")
            self._conn.commit()
        logger.info("GeoIP cache cleared")

    def close(self) -> None:
        """Close the SQLite connection."""
        try:
            self._conn.close()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # internal
    # ------------------------------------------------------------------

    def _mem_put(self, ip: str, result: GeoIPResult) -> None:
        """Insert into memory LRU (caller must hold ``_lock``)."""
        if ip in self._mem:
            self._mem.move_to_end(ip)
        self._mem[ip] = result
        while len(self._mem) > self._memory_max_size:
            self._mem.popitem(last=False)
