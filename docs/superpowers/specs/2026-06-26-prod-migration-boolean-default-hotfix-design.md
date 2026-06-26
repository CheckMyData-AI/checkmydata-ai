# Prod Outage Hotfix — Boolean migration default rejected by Postgres

- **Date:** 2026-06-26
- **Severity:** 🔴 Critical (production outage — web dyno crash-loop, `/api/health` 503)
- **Branch:** `fix/prod-migration-bool-default-2026-06-26` (off `main`)
- **Found via:** Heroku log research after the R5 deploy (release v185).

## Incident

After R5 (`fix(sync)`) merged to `main` and auto-deployed as **release v185**, the web dyno
crash-looped and `/api/health` returned **503**. Heroku app logs:

```
asyncpg.exceptions.DatatypeMismatchError: column "send_sample_data_to_llm" is of type boolean
but default expression is of type integer
...
File "/app/alembic/versions/e909ec65d857_sync_remediation_connection_flag.py", line 20, in upgrade
subprocess.CalledProcessError: Command '['alembic', 'upgrade', 'head']' returned non-zero exit status 1.
uvicorn.error: Application startup failed. Exiting.
```

The `Procfile` web process runs `alembic upgrade head` before uvicorn; the migration failed, so the
dyno never started → 503.

## Root cause

The T14 migration `e909ec65d857` added a **Boolean** column with `server_default=sa.text("1")`:

```python
sa.Column("send_sample_data_to_llm", sa.Boolean(), nullable=False, server_default=sa.text("1"))
```

`sa.text("1")` renders as the **bare integer** `DEFAULT 1`. PostgreSQL rejects a bare integer as a
boolean default (`boolean but ... integer`). SQLite accepts `1` for booleans, so:

- every unit/integration test (SQLite) passed,
- the local `alembic upgrade head` / `downgrade base` check (SQLite) passed,
- the per-task + final whole-branch reviews passed,

…and the bug only surfaced on **production Postgres** at deploy time. **Process gap:** migrations were
validated only against SQLite; the prod dialect (Postgres) was never exercised in CI or locally.

> Note: existing Boolean columns that use a *string* `server_default` (`"0"`/`"1"`) render as the
> **quoted** literal `DEFAULT '0'`, which Postgres *does* accept (string→boolean cast) — those are
> not affected. Only the bare-integer `text("1")` form is invalid.

## Fix (locked)

1. **Migration `e909ec65d857`** — `server_default=sa.text("1")` → **`server_default=sa.true()`**.
   `sa.true()` compiles to `true` on PostgreSQL and `1` on SQLite (verified via the dialect compiler:
   PG → `BOOLEAN DEFAULT true`, SQLite → `BOOLEAN DEFAULT 1`).
2. **Model `app/models/connection.py`** — `server_default="1"` → **`server_default=true()`** (import
   `true` from `sqlalchemy`) for create_all parity and autogenerate correctness.
3. **Regression guard** — `backend/tests/unit/test_boolean_server_defaults_pg.py`: compiles every
   mapped Boolean column's `server_default` for the **postgresql** dialect and fails if any renders a
   **bare integer** default (the exact PG-incompatible form). Quoted-string and `true`/`false`
   defaults pass. Plus a targeted assertion that `connections.send_sample_data_to_llm` renders
   `DEFAULT true` on PG. This catches the class of bug in CI without needing a live Postgres.

## Prod DB state & recovery

`alembic upgrade head` ran under transactional DDL; the failing R5 batch rolled back, so prod remained
at the pre-R5 revision. Redeploying with the corrected migration re-applies the R5 batch
(`2317bf9d9126` → `f37386df158c` no-op → `e909ec65d857` fixed) cleanly — no manual DB surgery needed.
The migration is idempotent w.r.t. the column (fresh add), and alembic resumes from prod's recorded
revision.

## Verification

- SQLAlchemy compiler: `sa.true()` → `true` (PG) / `1` (SQLite); old `text("1")` → `1` (PG, rejected).
- SQLite `alembic upgrade head` + `downgrade base`: clean.
- Regression guard + `test_alembic` + connection tests: green; ruff + mypy clean.
- Docker/local Postgres was unavailable in the fix environment, so PG validation is via the dialect
  compiler (definitive for this DDL) + the deploy itself running the migration on prod Postgres.

## Process follow-up (recommended, separate)

Add a CI job (or a `make` target) that runs `alembic upgrade head` then `downgrade base` against a
**Postgres** service container, so migration-dialect bugs fail in CI rather than at deploy. Tracked as
a follow-up; the regression guard above is the immediate, zero-infra mitigation.

## Deploy plan

Commit fix + guard + spec → push → PR → merge to `main` (squash) → CI + auto-deploy → watch
`heroku ps` / `/api/health` until the web dyno is `up` and health is 200. If the migration still
fails, read logs and iterate (fix-after-deploy, redeploy) until green.
