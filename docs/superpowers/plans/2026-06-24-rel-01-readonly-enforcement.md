# Plan — Release R1: DB-level read-only enforcement

Implements [`2026-06-24-rel-01-readonly-enforcement-design.md`](../specs/2026-06-24-rel-01-readonly-enforcement-design.md).
Contracts C1–C7 are locked in the spec. TDD per task (failing test → impl → green). All commands from
`backend/`. Subagent file ownership is non-overlapping → tasks T1–T6 run in parallel; T7 is the
sequential glue.

## Parallel tasks (one subagent each)

- **T1 — Postgres (C1)** · owns `app/connectors/postgres.py` + `tests/unit/test_postgres_*` ·
  read-only `server_settings`; test asserts kwarg passed iff `is_read_only`.
- **T2 — MySQL (C2)** · owns `app/connectors/mysql.py` + `tests/unit/test_mysql_*` ·
  `init_command="SET SESSION TRANSACTION READ ONLY"` iff read-only.
- **T3 — ClickHouse (C3)** · owns `app/connectors/clickhouse.py` + `tests/unit/test_clickhouse_*` ·
  `settings={"readonly": 1}` iff read-only. *(Confirmed via Context7: `get_client(settings=...)`.)*
- **T4 — MongoDB (C4)** · owns `app/connectors/mongodb.py` + `tests/unit/test_mongodb_*` ·
  `_assert_mongo_read_safe` blocks write ops, `$out`/`$merge`, `$where`/`$function`/`$accumulator`.
- **T5 — SafetyGuard allow-list (C5)** · owns `app/core/safety.py` + `tests/unit/test_safety*` ·
  statement-initial read allow-list + single-statement check in READ_ONLY; keep existing denylist.
- **T6 — Call sites (C6/C7)** · owns `app/api/routes/batch.py` + `app/api/routes/notes.py` + their
  tests · route raw SQL through `SafetyGuard` (level per connection `is_read_only`).

Each subagent: confirm its driver's read-only kwarg via Context7; write the failing test first;
implement minimal; run `.venv/bin/pytest <its tests> -q -p no:cov`, `.venv/bin/ruff check <files>`,
`.venv/bin/ruff format <files>`, `.venv/bin/mypy <files> --ignore-missing-imports`; do **not** commit.

## T7 — Integration (sequential, me)
1. Confirm no cross-file conflicts (ownership is disjoint).
2. DOC updates: `CLAUDE.md` connectors/read-only note; operator note in `docs/DEPLOYMENT.md` /
   `.env.example` (read-only DB user; Mongo `--noscripting`).
3. Full gate: `make check` (ruff format+check, mypy, full unit+integration, coverage ≥72%).
4. Commit per task group; push branch (updates PR). Prod merge = gated human step.
5. Post-deploy (after merge): `/api/health` + Heroku logs; then mark R1 bugs closed in `issues.md`.

## DoD
C1–C7 implemented + tested; `make check` green; DOC updated; branch pushed. F-SQL-08, F-SQL-04,
F-CONN-01/02/03/10, F-SCHED-02, F-NOTE-01 closed once deployed + verified.
