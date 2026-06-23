# Module 03 — Connections & Connectors — Audit Report

**Round 1** · 2026-06-23 · Scope: `connectors/{base,postgres,mysql,clickhouse,mongodb,registry}.py`,
`core/safety.py`, `services/encryption.py`, `services/connection_service.py`,
`routes/connections.py`.

Documented contract: `vision.md §7` invariants — **read-only by default**, **credentials never
exposed**, graceful degradation. CLAUDE.md: DB credentials Fernet-encrypted at rest with
`MASTER_ENCRYPTION_KEY` (required to boot). This report hunts for read-only-invariant bypasses,
credential-handling defects, injection/SSRF surface, and resource-lifecycle bugs.

**Positive notes (verified):** query params are bound positionally via asyncpg `$N`
(`_dict_to_positional`) — no string interpolation of values; identifier quoting exists per
dialect (`_quote_identifier`); results are capped by both row count (`MAX_RESULT_ROWS=10k`) and
bytes (`MAX_RESULT_BYTES=50MB`); query timeout + poisoned-connection termination on timeout are
handled well (`postgres.py:103-117`); `SafetyLevel.UNRESTRICTED` is **not used anywhere**
(verified) so the always-block dangerous patterns can't be globally disabled; the main agent SQL
path *does* invoke the guard (`core/validation_loop.py:177`).

Severity: 🔴 Critical · 🟠 High · 🟡 Medium · 🟢 Low · ⚪ Info

---

## F-CONN-01 — 🟠 High — Read-only is enforced at scattered higher-layer call sites, not at the connector chokepoint, and not at the DB level

**Type:** Security / vision-invariant (§7 "read-only by default … enforced in code")
**Location:** `connectors/postgres.py:75-159` (`execute_query` — no guard; explicit DDL/DML
branch at `:101-102`); guard call-sites scattered across `core/validation_loop.py:177`,
`main.py:856`, `routes/notes.py:251`, `routes/schedules.py:245`, `mcp_server/tools.py:506`,
`agents/investigation_agent.py:195`. Matches observation **21202** ("No SQL statement-type guard
in execute_query methods across all connectors").

**Description.** The read-only invariant is enforced by calling `SafetyGuard.validate(...)`
*before* `execute_query`, at each of ~6 independent call sites. The connector's `execute_query`
itself performs **no** validation and even has a dedicated branch to run non-row-returning
**DDL/DML** (`return await conn.fetch(numbered_query, *values)`). Crucially, the asyncpg pool is
opened with the connection's **full-privilege credentials** and there is **no DB-level read-only
enforcement**: no read-only role, no `SET TRANSACTION READ ONLY`, no
`default_transaction_read_only`. So the invariant holds only if *every* current and future code
path remembers to call the guard first. Any path that calls `execute_query` (or `sample_data`,
or a new feature) directly bypasses read-only entirely.

**Impact.** A single forgotten guard call — or any of the regex bypasses in F-CONN-02 — results
in writes/DDL hitting a "read-only" connection. This is the load-bearing §7 invariant; enforcing
it at N call sites instead of one chokepoint guarantees eventual drift.

**Proposed fix (defense in depth, both layers):**
1. **DB-level (the real control).** For a read-only connection, open it read-only at the driver:
   asyncpg `create_pool(..., server_settings={"default_transaction_read_only": "on"})` for
   Postgres; a read-only session/role or `SET SESSION TRANSACTION READ ONLY` for MySQL;
   ClickHouse `readonly=1` setting; for Mongo use a read-only DB user. This makes the database
   reject writes regardless of what SQL is generated.
2. **Chokepoint.** Move the `SafetyGuard.validate` call *into* `execute_query` (or a shared
   `BaseConnector.guarded_execute`) keyed on `config.is_read_only`, so no caller can skip it.

---

## F-CONN-02 — 🟠 High — `SafetyGuard` is a regex blocklist with multiple known bypasses

**Type:** Security
**Location:** `core/safety.py:16-70` (`DANGEROUS_PATTERNS_SQL`, `DML_PATTERNS_SQL`,
`validate_sql`).

**Description.** Read-only is enforced by keyword regexes on the raw SQL string. Regex blocklists
on SQL are bypassable; concrete bypasses against these specific patterns:

- **Comment-splitting:** `\s+` matches whitespace, not comments, so `DROP/**/TABLE x`,
  `DELETE/**/FROM x`, `INSERT/**/INTO x` all evade their patterns.
- **`COPY … TO/FROM PROGRAM` (Postgres):** `COPY (SELECT 1) TO PROGRAM 'curl …'` →
  **command execution** if the DB role permits; not in the pattern list at all.
- **`SELECT … INTO newtable` (Postgres):** creates a table without the `CREATE` keyword →
  evades the `CREATE TABLE` pattern.
- **`… INTO OUTFILE/DUMPFILE` and `LOAD DATA INFILE` (MySQL):** file write/read; not matched.
- **`REPLACE INTO …` (MySQL):** a write; not in `DML_PATTERNS_SQL`.
- **`CALL proc()` / `DO $$ … $$` blocks:** stored-procedure / anonymous-block writes; `CALL`
  not matched (and a `DO` block's inner write keyword may or may not match depending on layout).
- **File/admin functions:** `pg_read_file()`, `lo_import()`, `pg_ls_dir()`,
  `pg_terminate_backend()`, and `SELECT pg_sleep(1e9)` (resource-exhaustion DoS) — none blocked.

**Impact.** The "read-only" guarantee can be defeated, ranging from data modification to file
read/write to (with a privileged DB role) command execution.

**Proposed fix.** Treat the regex guard as *advisory UX only* and make DB-level read-only
(F-CONN-01) the authoritative control. If a parse-based guard is desired, use a real SQL parser
(e.g. `sqlglot`) to classify statement type and reject anything that isn't a pure read, rather
than substring matching. At minimum, add `COPY`, `INTO OUTFILE/DUMPFILE`, `LOAD DATA`,
`REPLACE INTO`, `CALL`, and `SELECT … INTO` to the blocklist and strip comments before matching.

---

## F-CONN-03 — 🟡 Medium — MongoDB `$out` / `$merge` aggregation stages bypass the read-only guard

**Type:** Security (read-only bypass)
**Location:** `core/safety.py:72-90` (`validate_mongo` checks only the top-level `operation`);
`connectors/mongodb.py:136-137` (`operation == "aggregate"` runs `collection.aggregate(pipeline)`
with the caller's pipeline verbatim).

**Description.** `validate_mongo` blocks `operation in {"insert","update","delete","drop",…}`,
but an **`aggregate`** operation is treated as read-only. MongoDB aggregation pipelines can end
in a `$out` or `$merge` stage that **writes/overwrites a collection**. So
`{"operation":"aggregate","pipeline":[{"$match":{}},{"$out":"victim"}]}` passes the read-only
guard and writes to `victim`.

**Impact.** Read-only Mongo connections can be made to create/overwrite collections — a direct
read-only-invariant violation, including potential data destruction (`$out` replaces the target).

**Proposed fix.** In `validate_mongo`, when `operation == "aggregate"`, reject pipelines
containing a `$out` or `$merge` stage in read-only mode. Better, per F-CONN-01, use a read-only
Mongo user so the server refuses the write.

---

## F-CONN-04 — 🟡 Medium — Arbitrary `db_host`/`db_port` (+ SSH tunnel) enables internal-network reach (SSRF-class)

**Type:** Security
**Location:** `connectors/postgres.py:55-66` (connects to user-supplied `db_host`/`db_port`);
analogous in mysql/clickhouse/mongodb; SSH tunnel via `ssh_tunnel.shared_tunnel_manager`.

**Description.** An authenticated user can create a connection (and run test-connection / queries)
pointing at any host:port reachable from the backend — including loopback, link-local
(`169.254.169.254`), and RFC-1918 internal services. Even though these speak the DB protocol
(not HTTP), connection success/failure and timing leak internal reachability (port-scan /
service-discovery oracle), and the SSH-tunnel path extends reach into private networks. There is
no egress allowlist or private-range denylist.

**Impact.** Internal network reconnaissance / SSRF-class probing from the server's vantage point;
in multi-tenant SaaS this lets any tenant map the provider's internal network.

**Proposed fix.** Add a configurable host policy: deny loopback/link-local/private ranges by
default (resolve the hostname and check the resolved IP to avoid DNS-rebinding), with an explicit
allowlist for self-hosted deployments. Apply it on connection create and before each connect.

---

## F-CONN-05 — 🟡 Medium — Fernet encryption has no key rotation / versioning

**Type:** Operational / security
**Location:** `services/encryption.py:12-35`.

**Description.** A single global `Fernet(MASTER_ENCRYPTION_KEY)` encrypts/decrypts all secrets.
There is no key-id prefix and no `MultiFernet`, so **rotating** `MASTER_ENCRYPTION_KEY` makes
every stored ciphertext undecryptable (`decrypt` raises), bricking all connections/SSH keys at
once. There is no supported rotation path.

**Impact.** Key rotation — a routine security requirement after suspected exposure — is
effectively impossible without a bespoke migration; raises the blast radius of a leaked key.

**Proposed fix.** Use `cryptography.fernet.MultiFernet([new, old])` so decryption accepts old
keys while new writes use the new key, plus a re-encrypt migration to roll forward. Optionally
prefix ciphertext with a key id for explicit versioning.

---

## F-CONN-06 — 🟢 Low — `_dict_to_positional` regex mis-handles `::type` casts and `:param` in string literals

**Type:** Bug (edge case)
**Location:** `connectors/postgres.py:362` (`_PARAM_RE = r":(?P<name>\w+)\b"`), `:391-413`.

**Description.** The docstring claims the regex avoids replacing inside string literals, but it
matches any `:word`. It only avoids corruption because it leaves names absent from `params`
untouched. Two edge cases still break: (a) a Postgres cast like `x::text` becomes a target if a
param named `text` is supplied (→ `x:$1` corruption); (b) a literal containing `:name` (e.g.
`WHERE note = 'see :id'`) with a same-named param gets rewritten inside the string.

**Impact.** Rare query corruption when param names collide with cast types or literal content.

**Proposed fix.** Skip `::` casts explicitly (`(?<!:):(?P<name>\w+)` plus a guard for the
following char) and ideally tokenize to avoid matching inside string literals; or require callers
to use a non-colliding placeholder style.

---

## F-CONN-07 — 🟢 Low — Persistent pool `min_size=1` per cached connector risks remote connection exhaustion

**Type:** Resource lifecycle (needs follow-up)
**Location:** `connectors/postgres.py:50-66` (`min_size=1, max_size=5`); process-wide caching via
`connector_key` (`base.py:33-68`).

**Description.** Each distinct connection key keeps a pool with `min_size=1`, i.e. at least one
live connection to the remote DB held open indefinitely. With many connections cached
process-wide and no visible idle-TTL/eviction, the backend can pin a growing number of remote DB
connections, exhausting the target's connection limit.

**Impact.** Remote DB connection-slot exhaustion / "too many connections" on customer databases
under many-connection workloads.

**Proposed fix.** Verify the connector registry has idle eviction; if not, add an LRU/TTL eviction
that `disconnect()`s idle pools, and consider `min_size=0` so idle pools hold no remote
connection. (Flag for next-round verification of `connectors/registry.py`.)

---

## Verified-clean / to-confirm

- **Secret exposure (⚪):** connection request models accept `db_password`/`connection_string`
  as input; no obvious decrypted-secret echo found in `routes/connections.py` responses. Confirm
  the `ConnectionResponse` model explicitly excludes secret fields next round.

## Test gaps (⚪ Info)

- No test proving a read-only connection rejects a write at the **DB** level (only guard-level
  regex tests, which don't cover the F-CONN-02 bypasses).
- No test for the Mongo `$out`/`$merge` bypass (F-CONN-03).
- No SSRF/host-policy test (F-CONN-04).
- No key-rotation test (F-CONN-05) — feature absent.

## Summary

| id | sev | one-line |
|----|-----|----------|
| F-CONN-01 | 🟠 | Read-only enforced at scattered call sites, not the connector chokepoint / DB level |
| F-CONN-02 | 🟠 | `SafetyGuard` regex blocklist bypassable (comments, COPY PROGRAM, INTO OUTFILE, …) |
| F-CONN-03 | 🟡 | Mongo `$out`/`$merge` aggregation bypasses read-only guard |
| F-CONN-04 | 🟡 | Arbitrary db_host/port (+SSH) → internal-network/SSRF reach, no host policy |
| F-CONN-05 | 🟡 | Fernet has no key rotation/versioning; rotation bricks all secrets |
| F-CONN-06 | 🟢 | `_dict_to_positional` mishandles `::casts` / `:param` in literals |
| F-CONN-07 | 🟢 | Persistent `min_size=1` pools risk remote connection exhaustion |

**Next-round focus:** `connectors/registry.py` pool eviction/TTL; `ConnectionResponse` secret
exclusion; mysql/clickhouse `execute_query` read-only + injection parity; SSH tunnel module
(Module 04) host-key + pre-command allowlist; connection-string parsing for credential leakage
into logs/errors (`QueryResult.error=str(e)` may echo DSNs with passwords).

---

# Round 2 — additional findings (2026-06-24)

**Several R1 worries resolved positively:**
- **`ConnectionResponse` excludes all secrets** (confirmed + obs 21203): exposes
  id/name/db_host/db_user/ssh_key_id/… but **no `db_password`, no `connection_string`, no
  encrypted fields** — no secret echo in responses (F-CONN "verify" item closed).
- **Value-injection parity confirmed**: MySQL binds via `%s` positional params to aiomysql
  (`_dict_to_positional` → `cur.execute(q, params)`, `mysql.py:83-126`); ClickHouse uses
  `query_row_block_stream(query, parameters=params)` (`clickhouse.py:96`); MongoDB uses a JSON
  spec. No value-level string interpolation in any connector — the only injection surface is the
  query *structure* (the read-only-guard concern, F-CONN-01/02), not bound values.
- **F-CONN-07 (pool leak) largely mitigated**: the registry does **not** cache (fresh adapter per
  `get_connector`, obs 21301); the SQL agent's connector cache is **bounded** (`_MAX_CONNECTORS`)
  and `disconnect()`s the evicted connector (`sql_agent.py:1287-1293`). Residual is below.

## F-CONN-08 — 🟡 Medium — `QueryResult.error=str(e)` is unredacted everywhere → DSN/password can leak to project members and logs

**Type:** Security (credential exposure, §7)
**Location:** `postgres.py:159`, `mysql.py:160`, `clickhouse.py:135`, `mongodb.py:176`
(`return QueryResult(error=str(e), …)`), plus the matching `logger.warning(..., exc)`.

**Description.** Every connector returns the **raw** exception string as `QueryResult.error`, and
that value flows to three unredacted sinks: (1) the API response to the user, (2) **persisted**
storage — note `last_result_json` (Module 16) and trace spans (Module 17), and (3) logs.
Connection-string / authentication errors (e.g. a malformed `connection_string` DSN, or driver
errors that echo connection params) can include the **password**. While the connection owner set
that password, the persisted error is visible to **other project members** (shared notes/traces)
and to operators (logs) — a credential-exposure path beyond the owner. The Sentry pipeline scrubs
(F-LLM-03), but the user-facing response, the stored note/trace, and the app logs do **not**.

**Impact.** DB credentials can leak from error strings to co-tenants (via persisted errors) and to
log readers.

**Proposed fix.** Run connector error strings through a shared redactor (reuse `core/sentry.py`
`scrub_text` / a `redact_secrets()` helper) before assigning `QueryResult.error` and before
logging. Add a test: a DSN-bearing exception → `error` has the password `[redacted]`.

## F-CONN-09 — 🟢 Low — Agent connector cache is FIFO and instance-scoped (verify SQLAgent lifetime)

**Type:** Resource lifecycle (revises F-CONN-07)
**Location:** `sql_agent.py:1278-1297` (`_get_or_create_connector`): `self._connectors` dict,
evicts `next(iter(...))` (oldest-inserted, **FIFO not LRU**) at `_MAX_CONNECTORS`.

**Description.** Eviction is FIFO, so a hot connector inserted early can be evicted while a cold one
lingers (minor churn). More importantly the cache is keyed to the **SQLAgent instance**
(`self._connectors`); if a new `SQLAgent` is constructed per request rather than reused, its cached
pools are only closed on *eviction within that instance* — instance churn would leak pools until
GC (which won't cleanly `await disconnect()`).

**Proposed fix.** Confirm `SQLAgent` is long-lived/singleton; if per-request, add explicit
connector teardown at request end (or move the connector cache to a process-wide manager). Consider
LRU eviction.

## Round 2 summary

| id | sev | one-line |
|----|-----|----------|
| F-CONN-08 | 🟡 | `QueryResult.error=str(e)` unredacted → DSN/password leaks to members (stored) + logs |
| F-CONN-09 | 🟢 | Agent connector cache FIFO + instance-scoped (verify SQLAgent is long-lived) |

**Round 3 focus:** connection `create`/`test` SSRF host-policy (F-CONN-04 fix verification);
mongodb connector `$where`/JS-eval injection surface; clickhouse `readonly=1` session setting as a
DB-level read-only enforcement option (F-CONN-01 fix candidate).
