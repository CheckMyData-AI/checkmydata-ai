"""The demo's sample database — created, seeded and repaired in one place.

Split out of `app/api/routes/demo.py` because two callers need it and a service must not
import a route: the route seeds when the demo is set up, and `ConnectionService.to_config`
repairs the file when it has gone missing underneath an existing connection.

**It goes missing routinely, and that is the design.** Heroku's filesystem is ephemeral
and per-dyno: a restart takes the file while the `Connection` row survives, and a second
web dyno never had it. Without repair, a demo user's second visit is
`SQLite database file not found` — worse than the empty database this whole change
exists to remove, because it reads as broken rather than as unfinished. The data is
fixed, small and derived from nothing, so rebuilding it is cheaper than any attempt to
keep it.
"""

import logging
import sqlite3
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)

#: Reused rather than re-created, so a second click does not mint a second project.
DEMO_PROJECT_NAME = "Demo Project"

#: Small and legible on purpose. A demo of a query product has to let a person check the
#: agent's answer by eye — five customers and eight orders can be added up in the head,
#: five thousand cannot, and an answer nobody can check demonstrates nothing.
_CUSTOMERS = [
    (1, "Aurora Labs", "DE", "2026-01-14"),
    (2, "Bluefin Studio", "GB", "2026-02-02"),
    (3, "Cedar Freight", "US", "2026-02-19"),
    (4, "Dunlin Analytics", "NL", "2026-03-08"),
    (5, "Everline Retail", "US", "2026-04-21"),
]

_ORDERS = [
    (1, 1, "2026-05-02", "paid", 129900),
    (2, 1, "2026-06-11", "paid", 24900),
    (3, 2, "2026-05-19", "refunded", 8900),
    (4, 3, "2026-06-01", "paid", 459000),
    (5, 3, "2026-06-28", "pending", 12500),
    (6, 4, "2026-07-04", "paid", 76000),
    (7, 5, "2026-07-15", "paid", 31000),
    (8, 5, "2026-07-30", "pending", 5400),
]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    country TEXT NOT NULL,
    signed_up_on TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    placed_on TEXT NOT NULL,
    status TEXT NOT NULL,
    total_cents INTEGER NOT NULL
);
"""


def demo_db_dir() -> Path:
    """The directory holding every user's sample database. Read at call time, so a test
    that repoints ``settings.demo_db_dir`` is honoured by both callers."""
    return Path(settings.demo_db_dir)


def demo_db_path(user_id: str) -> Path:
    """One file per user — two people sharing a demo database is a tenancy leak wearing
    sample data as a costume."""
    return demo_db_dir() / f"demo_{user_id}.db"


def is_demo_db(path: str | None) -> bool:
    """True when *path* names a file this module owns.

    Deliberately a containment check on the configured directory rather than a filename
    pattern: it is the directory the product manages, and a user pointing a connection
    at a database of their own must never be "repaired" by having sample tables written
    into it.
    """
    if not path:
        return False
    try:
        return demo_db_dir().resolve() in Path(path).resolve().parents
    except OSError:
        return False


def seed_demo_db(path: str | Path) -> None:
    """Create the sample schema and rows, idempotently.

    Returns early when the rows are already there, so calling it on every demo setup and
    on every config build costs one `COUNT(*)` against a five-row table.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as db:
        db.executescript(_SCHEMA)
        if db.execute("SELECT COUNT(*) FROM customers").fetchone()[0]:
            return
        db.executemany(
            "INSERT INTO customers (id, name, country, signed_up_on) VALUES (?, ?, ?, ?)",
            _CUSTOMERS,
        )
        db.executemany(
            "INSERT INTO orders (id, customer_id, placed_on, status, total_cents) "
            "VALUES (?, ?, ?, ?, ?)",
            _ORDERS,
        )
    logger.info("Demo sample database ready at %s", path.name)


def repair_demo_db_if_missing(path: str | None) -> None:
    """Rebuild a demo database that the filesystem has taken, and nothing else.

    Called from `ConnectionService.to_config`, which every query, index and health check
    passes through. Best-effort: a failure here must not stop a connection being built,
    because the connector's own error is the honest one to show.
    """
    if not is_demo_db(path) or Path(str(path)).exists():
        return
    try:
        seed_demo_db(str(path))
        logger.info("Demo sample database was missing and has been rebuilt: %s", path)
    except Exception:
        logger.warning("Could not rebuild the demo sample database at %s", path, exc_info=True)
