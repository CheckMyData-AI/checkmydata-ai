# Self-completing embedding reconcile — design spec

**Date:** 2026-07-06
**Branch:** `feat/embedding-self-reconcile`
**Status:** approved (brainstorming) → pending spec review

## Problem

Changing the embedding config (`chroma_embedding_model` / `embedder_max_tokens`)
makes every existing ChromaDB collection dimension-mismatched. Today the fix is a
**manual post-deploy operator step** — running `queue_embedding_reindex(all_project_ids)`
by hand (see `CLAUDE.md` deploy notes). This is easy to forget, easy to run against
the wrong app, and blocks true zero-touch deploys. Until it runs, dense retrieval
silently degrades to BM25-only.

## Goal

Make the deploy **self-completing**: on boot, detect that the embedding config
changed since the last successful reconcile and enqueue a full reindex of all
projects exactly once — idempotently, multi-dyno-safe, and degrading gracefully
without ever blocking startup. The manual step disappears permanently.

**Approach A (approved):** run in the FastAPI `lifespan` startup, guarded by a
Postgres advisory lock. Portable across all three deploy targets (Heroku, Docker,
DigitalOcean); no Procfile change. On the feature's own deploy it also closes the
current stale-embedding backlog (seed marker with the OLD fingerprint on DBs that
already have projects) — so no `!` command is ever needed.

## Non-goals (YAGNI)

- No per-project lazy reindex — full-fleet enqueue on change is enough.
- No new admin endpoint / UI — reconcile is automatic; the existing
  `queue_embedding_reindex` and "Re-index repository" UI action remain for manual use.
- No Heroku `release:` phase — Approach A covers all platforms uniformly.
- No generalization beyond embeddings *now*; `deploy_state` is a generic KV table so
  future deploy-markers can reuse it, but this spec only writes the
  `embedding_fingerprint` key.

## File layout (locked)

| File | Change | Purpose |
|---|---|---|
| `backend/app/models/deploy_state.py` | **new** | `DeployState` ORM model (generic KV) |
| `backend/app/models/__init__.py` | edit | export `DeployState` |
| `backend/app/ops/__init__.py` | **new** (empty) | package marker |
| `backend/app/ops/embedding_reconcile.py` | **new** | fingerprint + reconcile logic |
| `backend/alembic/versions/<rev>_add_deploy_state.py` | **new** | create table + seed marker |
| `backend/app/main.py` | edit | call `reconcile_embeddings()` in `lifespan` startup |
| `backend/tests/unit/ops/test_embedding_reconcile.py` | **new** | unit tests |
| `backend/tests/integration/test_embedding_reconcile_startup.py` | **new** | integration test |
| `CLAUDE.md`, `CHANGELOG.md` | edit | replace manual-step note with auto-reconcile note |

## Data model (locked)

`backend/app/models/deploy_state.py`:

```python
from datetime import datetime
from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base


class DeployState(Base):
    """Generic single-value key/value store for deploy-time reconciliation markers.

    Rows are tiny and few (one per marker kind). Currently only the
    ``embedding_fingerprint`` key is written, by the embedding reconcile flow.
    """

    __tablename__ = "deploy_state"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(255), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
```

## Module contract (locked)

`backend/app/ops/embedding_reconcile.py`:

```python
from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import settings
from app.models.base import async_session_factory
from app.models.deploy_state import DeployState
from app.models.project import Project
from app.services.embedding_reindex import queue_embedding_reindex

logger = logging.getLogger(__name__)

_FINGERPRINT_KEY = "embedding_fingerprint"
# Stable 64-bit key for pg_try_advisory_xact_lock — arbitrary but fixed forever.
_ADVISORY_LOCK_KEY = 8274123001


@dataclass
class ReconcileResult:
    status: str          # "unchanged" | "reindexed" | "skipped_locked" | "seeded" | "error"
    reindexed: int = 0   # number of projects enqueued
    fingerprint: str = ""


def embedding_fingerprint() -> str:
    """Deterministic string identifying the current embedding config."""
    return f"{settings.chroma_embedding_model}|{settings.embedder_max_tokens}"


async def reconcile_embeddings(
    session_factory: async_sessionmaker | None = None,
) -> ReconcileResult:
    """Detect an embedding-config change and enqueue a one-shot full reindex.

    Best-effort: never raises. Marker is advanced ONLY after a successful
    enqueue, so a failure retries on the next boot. Postgres uses a
    transaction-scoped advisory lock to serialize concurrent dynos; other
    dialects (SQLite dev) skip the lock (single process).
    """
```

**Behaviour (locked):**

1. `current = embedding_fingerprint()`.
2. Open a session/transaction from `session_factory or async_session_factory`.
3. **Postgres only** (`session.bind.dialect.name == "postgresql"`): if
   `await session.scalar(text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": _ADVISORY_LOCK_KEY})`
   is falsy → another dyno holds it → return `ReconcileResult("skipped_locked", fingerprint=current)`.
   The lock auto-releases at commit/rollback (no unlock call).
4. Load `stored = await session.get(DeployState, _FINGERPRINT_KEY)`.
5. If `stored is None` (defensive; migration should have seeded it): insert the
   marker with `current`, commit, return `ReconcileResult("seeded", fingerprint=current)`.
   No reindex (unknown prior state ≠ known change).
6. If `stored.value == current`: return `ReconcileResult("unchanged", fingerprint=current)`.
7. Else (changed): fetch all ids
   `ids = list((await session.scalars(select(Project.id))).all())`;
   `jobs = await queue_embedding_reindex(ids)`;
   set `stored.value = current`; commit;
   return `ReconcileResult("reindexed", reindexed=len(ids), fingerprint=current)`.
8. Wrap steps 2–7 in `try/except Exception`: log with `exc_info=True`, do **not**
   commit the marker, return `ReconcileResult("error", fingerprint=current)`.

## Migration (locked)

`backend/alembic/versions/<rev>_add_deploy_state.py`
- `down_revision = "c9b8a7f6e5d4"` (current single head — keeps single-head invariant).
- `upgrade()`:
  1. `op.create_table("deploy_state", ...)` matching the model (key PK `String(64)`,
     value `String(255)` not null, `updated_at` `DateTime(timezone=True)` server_default `now()`).
  2. Data seed — decide fingerprint by whether the DB already has projects:
     ```python
     conn = op.get_bind()
     has_projects = conn.execute(sa.text("SELECT 1 FROM projects LIMIT 1")).first() is not None
     seed = "all-MiniLM-L6-v2|256" if has_projects else "BAAI/bge-base-en-v1.5|512"
     conn.execute(
         sa.text("INSERT INTO deploy_state (key, value, updated_at) "
                 "VALUES ('embedding_fingerprint', :v, now())"),
         {"v": seed},
     )
     ```
     - Existing prod (has projects) → seeds the OLD fingerprint → first reconcile sees
       a diff → reindexes the backlog once.
     - Fresh install (no projects) → seeds the CURRENT fingerprint → no reindex.
     - The seed value only needs to **differ from current** to force the backlog reindex;
       `all-MiniLM-L6-v2|256` is the real prior default.
     - `now()` works on both Postgres and SQLite; guard with a dialect check if needed.
- `downgrade()`: `op.drop_table("deploy_state")`.

## Startup wiring (locked)

In `backend/app/main.py` `lifespan`, after DB init/migrations and alongside the other
best-effort startup tasks, add:

```python
try:
    from app.ops.embedding_reconcile import reconcile_embeddings

    result = await reconcile_embeddings()
    logger.info("Embedding reconcile at startup: %s (reindexed=%d)", result.status, result.reindexed)
except Exception:
    logger.warning("Embedding reconcile failed at startup", exc_info=True)
```

`reconcile_embeddings` is already internally guarded; the outer try/except is belt-and-suspenders
so a broken import can never block boot.

## Error handling / graceful degradation

- Any exception inside reconcile → logged (structured, `exc_info`), marker untouched, boot continues.
- No Redis → `queue_embedding_reindex` → `enqueue` falls back to in-process `asyncio.create_task`
  (non-blocking; boot does not wait on the reindex).
- SQLite dev → advisory lock skipped (single process; no race).
- Multi web-dyno on Postgres → `pg_try_advisory_xact_lock` ensures exactly one dyno reindexes;
  losers return `skipped_locked`.
- Collection-drop failures inside `queue_embedding_reindex` are already best-effort (upsert overwrites).

## Testing (TDD)

**Unit** (`tests/unit/ops/test_embedding_reconcile.py`, SQLite):
1. `embedding_fingerprint()` returns `"<model>|<tokens>"` from settings.
2. `unchanged`: stored == current → no `queue_embedding_reindex` call, status `unchanged`.
3. `reindexed`: stored != current → `queue_embedding_reindex` called with all project ids;
   marker updated to current; status `reindexed`, `reindexed == n`.
4. marker NOT advanced when `queue_embedding_reindex` raises → status `error`, stored value unchanged.
5. `stored is None` → seeds current, no reindex, status `seeded`.
6. no projects + changed fingerprint → `queue_embedding_reindex([])` (no-op), marker still advanced.

**Migration** (`tests/unit/ops/...` or dedicated): seed logic — projects present → `all-MiniLM-L6-v2|256`;
absent → current fingerprint. (Test the helper predicate; full alembic run covered by existing migration smoke.)

**Integration** (`tests/integration/test_embedding_reconcile_startup.py`):
- Seed a `deploy_state` row with the OLD fingerprint + one `Project`; run `reconcile_embeddings()`
  with a monkeypatched `queue_embedding_reindex` spy → asserts it was called with the project id and
  marker advanced.
- Advisory-lock path (Postgres) is asserted via the dialect branch with a mocked `session.scalar`
  returning `False` → `skipped_locked` (SQLite can't take the real lock).

**Definition of Done:** ruff + mypy clean; new tests green; combined coverage ≥72%; single alembic head;
`CLAUDE.md` / `CHANGELOG.md` deploy note updated from "manual step required" to "automatic on deploy".

## Locked contracts summary (for parallel/zero-context implementers)

- `DeployState(key: str[64] PK, value: str[255], updated_at: datetime tz)` — table `deploy_state`.
- `embedding_fingerprint() -> str` == `f"{settings.chroma_embedding_model}|{settings.embedder_max_tokens}"`.
- `reconcile_embeddings(session_factory=None) -> ReconcileResult` — never raises.
- `ReconcileResult(status, reindexed=0, fingerprint="")`; `status ∈ {unchanged, reindexed, skipped_locked, seeded, error}`.
- `_FINGERPRINT_KEY = "embedding_fingerprint"`, `_ADVISORY_LOCK_KEY = 8274123001`.
- migration `down_revision = "c9b8a7f6e5d4"`; seed `all-MiniLM-L6-v2|256` iff projects exist else `BAAI/bge-base-en-v1.5|512`.
- reuse existing `queue_embedding_reindex(project_ids: list[str]) -> list[str|None]` unchanged.
