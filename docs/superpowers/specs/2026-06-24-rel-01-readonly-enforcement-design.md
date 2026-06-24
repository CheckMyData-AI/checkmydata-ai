# Spec — Release R1: DB-level read-only enforcement

**Date:** 2026-06-24 · **Source:** `docs/qa-audit/issues.md` §8 R1
**Bugs:** F-SQL-08, F-SQL-04, F-CONN-01, F-CONN-02, F-CONN-03, F-CONN-10, F-SCHED-02, F-NOTE-01
**Branch:** `fix/security-audit-2026-06-24`

## Problem

The read-only invariant (`vision.md` §7 #1) rests on a single **app-layer regex** (`core/safety.py`)
that is evadable (`CREATE OR REPLACE VIEW`, `SELECT … INTO`, `ALTER ROLE`, comment tricks, etc.), and
**no connector opens a read-only DB session** — `is_read_only` is never used in any `execute_query`.
MySQL even forces `autocommit=True`. So on a connection whose DB user has write rights, a crafted /
prompt-injected / batch / note query can write. Defense is needed at **two layers**: the DB session
(authoritative backstop) and the app guard (clean rejection + the writable-connection case).

## Design — two layers

1. **Connector DB-session read-only** (authoritative): when `config.is_read_only`, every connection
   the connector opens runs in a read-only mode the *database* enforces. Closes F-CONN-01 and the
   read-only leg of F-SQL-08/04/SCHED-02/NOTE-01 for read-only connections.
2. **App-layer statement-initial allow-list** in `SafetyGuard` (defense-in-depth + writable
   connections): a read-only query must *start* with an allowed read keyword and be single-statement.
   Closes the F-SQL-08/F-CONN-02 regex-evasion class.
3. **Call-site guards**: batch `/execute` and note-exec must route through `SafetyGuard` (F-SCHED-02,
   F-NOTE-01). Mongo write-stages / server-side JS rejected in code (F-CONN-03, F-CONN-10).

## Locked contracts

### C1 — Postgres read-only session (`connectors/postgres.py`)
In `connect()`, add `server_settings={"default_transaction_read_only": "on"}` to **both**
`asyncpg.create_pool(...)` calls when `config.is_read_only`:
```python
server_settings = {"default_transaction_read_only": "on"} if config.is_read_only else None
# pass server_settings=server_settings to create_pool (asyncpg ignores None)
```
PG then raises `cannot execute INSERT in a read-only transaction` for any write/DDL. (asyncpg applies
`server_settings` as `SET` on each pooled connection — confirm via Context7.)

### C2 — MySQL read-only session (`connectors/mysql.py`)
`autocommit=True` defeats `SET TRANSACTION READ ONLY` (next-txn only). Use a per-connection
**session default** via `init_command` on **both** `aiomysql.create_pool(...)` calls when read-only:
```python
init_command = "SET SESSION TRANSACTION READ ONLY" if config.is_read_only else None
# pass init_command=init_command (keep autocommit=True)
```
`SET SESSION TRANSACTION READ ONLY` sets the access mode for all subsequent transactions in the
session; autocommit statements are transactions, so writes raise `ER_TRANSACTION_READ_ONLY`. Confirm
`init_command` kwarg via Context7. (If `init_command` proves unreliable across aiomysql versions,
fall back to issuing the `SET SESSION` statement on each acquired connection before the user query.)

### C3 — ClickHouse read-only session (`connectors/clickhouse.py`)
In `connect()`, pass `settings={"readonly": 1}` to `clickhouse_connect.get_client(...)` when
`config.is_read_only` (readonly=1 blocks writes and setting changes). Confirm the `settings` kwarg
name/shape via Context7.

### C4 — MongoDB write-stage & server-side-JS guard (`connectors/mongodb.py`)
Add a module helper applied in `execute_query` **before** running, when `self._config.is_read_only`:
```python
_MONGO_WRITE_OPS = {"insert","update","delete","drop","rename","create_index","drop_index","replace"}
_MONGO_JS_OPERATORS = ("$where", "$function", "$accumulator")  # server-side JS
_MONGO_WRITE_STAGES = ("$out", "$merge")                       # aggregation writes
def _assert_mongo_read_safe(spec: dict) -> None:  # raises ValueError if unsafe
    op = spec.get("operation", "find")
    if op in _MONGO_WRITE_OPS: raise ValueError(f"Write operation '{op}' not allowed (read-only)")
    blob = json.dumps(spec)
    for js in _MONGO_JS_OPERATORS:
        if js in blob: raise ValueError(f"Server-side JS operator '{js}' not allowed")
    if op == "aggregate":
        for stage in spec.get("pipeline", []):
            for w in _MONGO_WRITE_STAGES:
                if w in stage: raise ValueError(f"Aggregation write stage '{w}' not allowed")
```
On `ValueError`, return `QueryResult(error=...)`. (Deploy hardening — read-only Mongo user +
`--noscripting` — documented in DOC, not code.)

### C5 — SafetyGuard statement-initial allow-list (`core/safety.py`)
Extend `validate_sql` so that in `SafetyLevel.READ_ONLY` the query must (after `_strip_sql_comments`):
- be **single-statement**: no `;` followed by further non-whitespace (reject stacked statements);
- **start with an allowed read token** (case-insensitive, first word):
```python
_READ_ONLY_LEADING = frozenset({"SELECT","WITH","SHOW","EXPLAIN","DESCRIBE","DESC","TABLE","VALUES","EXISTS"})
```
Keep the existing `DANGEROUS_PATTERNS_SQL` (always) and `DML_PATTERNS_SQL` (read-only) as
defense-in-depth. Return a clear `SafetyResult(is_safe=False, reason=...)` on violation. `ALLOW_DML`
and `UNRESTRICTED` levels are unchanged. This is the keystone for F-SQL-08/F-CONN-02.

### C6 — Batch `/execute` routes through SafetyGuard (`routes/batch.py`)
The batch execute path runs stored raw SQL with no `SafetyGuard`. Before executing each query, run
`SafetyGuard(SafetyLevel.READ_ONLY if conn.is_read_only else SafetyLevel.ALLOW_DML).validate(sql, db_type)`
and skip/fail the item with the safety reason when unsafe (mirror the agent path in
`core/validation_loop.py`). Exact insertion point confirmed at implementation time.

### C7 — Note exec routes through SafetyGuard (`routes/notes.py`)
`execute_note` must validate via the shared `SafetyGuard` (same level selection as C6) instead of any
ad-hoc call-site regex, then execute through the connector (which now has the C1–C3 backstop).

## Test plan (TDD)

- `tests/unit/test_safety.py` (or existing) — C5: `SELECT 1` ok; `WITH x AS (...) SELECT` ok;
  `CREATE OR REPLACE VIEW v AS SELECT 1` rejected (didn't start with read token); `SELECT 1; DROP TABLE t`
  rejected (multi-statement); `EXPLAIN SELECT` ok; `ALTER ROLE` rejected. `ALLOW_DML` still allows INSERT.
- `tests/unit/test_postgres_connector*.py` — C1: mock `asyncpg.create_pool`; assert
  `server_settings={"default_transaction_read_only":"on"}` passed when `is_read_only`, absent otherwise.
- `tests/unit/test_mysql_connector*.py` — C2: mock `aiomysql.create_pool`; assert
  `init_command="SET SESSION TRANSACTION READ ONLY"` when read-only, `None` otherwise.
- `tests/unit/test_clickhouse_connector*.py` — C3: mock `get_client`; assert `settings={"readonly":1}`
  when read-only.
- `tests/unit/test_mongodb_connector*.py` — C4: `$out`/`$merge`/`$where`/`$function` and write ops
  rejected under read-only; `find`/`aggregate`(read) allowed.
- `tests/integration/test_batch*.py` / `test_notes*.py` — C6/C7: a write/DDL query is rejected by the
  guard.

## DOC updates (Definition of Done)
- `CLAUDE.md` "Multi-tenancy & access control" / connectors note: read-only is now enforced at the DB
  session per dialect + statement-initial allow-list (not just regex).
- `vision.md` §7 #1 cross-ref (read-only by default) — note the DB-level backstop.
- Operator note (`docs/DEPLOYMENT.md` or `.env.example`): for full assurance use a read-only DB user;
  for Mongo add `--noscripting`.

## Verification & deploy
`make check` green (ruff/mypy/full tests, coverage ≥72%). Branch → PR; prod merge is the gated human
step. Post-deploy: `/api/health` + Heroku logs; then close R1 bugs in `issues.md`.

## Parallelization (file ownership — no two tasks touch the same file)
- T1 `connectors/postgres.py` (+test) · T2 `connectors/mysql.py` (+test) ·
  T3 `connectors/clickhouse.py` (+test) · T4 `connectors/mongodb.py` (+test) ·
  T5 `core/safety.py` (+test) · T6 `routes/batch.py` + `routes/notes.py` (+tests).
All six are independent → run as parallel subagents; integration + `make check` is the sequential glue.
