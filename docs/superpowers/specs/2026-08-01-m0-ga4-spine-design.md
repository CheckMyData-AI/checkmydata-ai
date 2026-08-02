# Spec — m0-ga4-spine

Module 1 of 3. Brief: `2026-08-01-analytics-sources-brief.md` · Design:
`…-design.md` · Map: `…-modules.md` · Docs study: `…-docs-study.md`.
**REQs: 001–015.** Alembic head at authoring time: `eff7aad70326`.

Goal: a project owner connects a GA4 property, it collects on schedule, and chat
answers questions about it with honest caveats and a chart. Everything the later two
modules reuse is built here and proven by one real vendor.

---

## 1. Data model

### 1.1 `vendor_credentials` (new) — REQ-002

Owner-scoped, reusable across connections. Mirrors `SshKey` deliberately.

| Column | Type | Notes |
|---|---|---|
| `id` | `String(36)` PK | uuid4 |
| `user_id` | `String(36)` FK `users.id` ON DELETE CASCADE, **nullable**, indexed | owner |
| `name` | `String(255)` not null | user label |
| `provider` | `String(50)` not null | `ga4` \| `appstore` \| `googleplay` |
| `secret_encrypted` | `Text` not null | Fernet ciphertext (SA JSON / .p8 PEM) |
| `fingerprint` | `String(64)` not null | sha256 of the plaintext, first 16 hex — for "same key?" display, never the key |
| `meta_json` | `Text` nullable | non-secret extras (e.g. SA `client_email`) shown in the UI |
| `created_at` / `updated_at` | `DateTime(tz)` | server defaults |

**Owner-strict rule (copied from `ssh_key_service` F-SSH-06, verbatim intent):**
`list_all`/`get` accept `user_id: str | None`; when it is a string, filter
`VendorCredential.user_id == user_id` and **never** union `user_id.is_(None)`.
`user_id=None` means a trusted internal call and returns unfiltered.

`secret_encrypted` and `fingerprint`-source plaintext appear in **no** response model.

### 1.2 `Connection` changes — REQ-001

- `source_type` gains `ga4` (+ `appstore`, `googleplay` reserved for m1/m2).
- New: `vendor_credential_id` `String(36)` FK `vendor_credentials.id` ON DELETE
  RESTRICT, nullable (RESTRICT: deleting a credential still in use must fail loudly,
  not orphan a connection).
- New: `source_config_json` `Text` nullable — non-secret knobs.
- New: `collection_enabled` `Boolean` not null server_default `true` (D6).
- New: `collection_hour` `Integer` not null server_default `3` — 0–23, local to
  `settings.daily_knowledge_sync_timezone`.
- **Made nullable:** `db_type`, `db_port`, `db_name`. A GA4 connection has no host,
  port or database; today all three are `nullable=False`.

> **Migration risk (A1).** `db_port`/`db_name`/`db_type` are `NOT NULL` today with
> existing rows. `ALTER COLUMN … DROP NOT NULL` is safe on Postgres and is emulated by
> batch-mode on SQLite. The migration MUST use `op.batch_alter_table` so the dev
> SQLite path works. Existing rows are untouched.

`source_config_json` for GA4:
```json
{"property_ids": ["294380179"], "backfill_days": 30,
 "event_names": ["pin_show_promo"], "currency_code": "USD"}
```

### 1.3 `analytics_imports` (new) — the journal, REQ-005

| Column | Type |
|---|---|
| `id` | `String(36)` PK |
| `connection_id` | FK `connections.id` **ON DELETE CASCADE**, indexed |
| `report` | `String(64)` — `overview` \| `geo` \| `platform` \| `trend` \| `events` |
| `period` | `String(16)` — `YYYY-MM-DD` (daily) or `YYYY-MM` (monthly) |
| `status` | `String(16)` — `ok` \| `empty` \| `failed` |
| `rows_written` | `Integer` default 0 |
| `error` | `Text` nullable |
| `fetched_at` | `DateTime(tz)` server default now |

**UNIQUE `(connection_id, report, period)`** → upsert.

### 1.4 GA4 fact tables — REQ-006

All five carry `connection_id` FK **CASCADE** + `property_id` + `date`, and all
metrics are `BigInteger`/`Numeric`, never float for counts.

| Table | Natural key (UNIQUE) | Payload |
|---|---|---|
| `ga4_overview_daily` | `(connection_id, property_id, date)` | `sessions`, `active_users`, `new_users`, `screen_page_views`, `event_count`, `total_revenue Numeric(18,4)` |
| `ga4_geo_daily` | `(connection_id, property_id, date, country)` | `sessions`, `active_users` |
| `ga4_platform_daily` | `(connection_id, property_id, date, platform, device_category)` | `sessions`, `active_users` |
| `ga4_trend_daily` | `(connection_id, property_id, date, channel_group)` | `sessions`, `active_users`, `key_events` |
| `ga4_event_daily` | `(connection_id, property_id, date, event_name)` | `event_count`, `active_users` |

Upsert: `INSERT … ON CONFLICT (natural key) DO UPDATE SET <metrics>, fetched_at=now()`.
Dialect-portable via `sqlalchemy.dialects.{postgresql,sqlite}.insert` chosen at runtime.

---

## 2. Contracts

### 2.1 `app/analytics/errors.py`

```python
class AnalyticsError(Exception): ...
class AnalyticsAuthError(AnalyticsError): ...        # 401 — bad/expired credential
class AnalyticsPermissionError(AnalyticsError): ...  # 403 — credential lacks access
class AnalyticsEmpty(AnalyticsError): ...            # 404 / no data for the period
class QuotaExhaustedError(AnalyticsError): ...       # vendor quota
class AnalyticsTransientError(AnalyticsError): ...   # 429 / 5xx / network
```
**Retry only `AnalyticsTransientError` and `QuotaExhaustedError`.** Auth and permission
are configuration errors — retrying burns quota and never succeeds (REQ-003).

### 2.2 `app/analytics/http.py`

```python
Resp = namedtuple("Resp", "status headers body")
HttpFn = Callable[..., Awaitable[Resp]]        # (method, url, headers, body=None)

async def request_with_retry(
    http: HttpFn, method: str, url: str, *, headers: dict, body: bytes | None = None,
    attempts: int = 3, base_delay: float = 1.0, sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> Resp
```
`http` and `sleep` are **injected** — production passes an aiohttp/urllib adapter,
tests pass fakes. **No test in this module touches the network.** `Retry-After` is
honored when present; backoff is `base_delay * 2**attempt` otherwise.

### 2.3 `app/analytics/base.py`

```python
@dataclass(frozen=True)
class ReportSpec:
    name: str; grain: Literal["daily", "monthly"]; description: str

@dataclass
class AnalyticsReport:
    columns: list[str]
    rows: list[list[Any]]
    truncated: bool = False          # set when a vendor cap was still hit after paging
    degraded: str | None = None      # human-readable partial-data reason

class AnalyticsSourceAdapter(DataSourceAdapter):
    @property
    def source_type(self) -> str: ...
    async def connect(self, config: ConnectionConfig) -> None: ...
    async def disconnect(self) -> None: ...
    async def test_connection(self) -> bool: ...
    def available_reports(self) -> list[ReportSpec]: ...
    async def fetch(self, report: str, period: str) -> AnalyticsReport: ...
    async def list_entities(self) -> list[str]:   # DataSourceAdapter contract
        return [r.name for r in self.available_reports()]
    async def query(self, query: str, params=None) -> QueryResult:
        raise NotImplementedError("analytics sources are not queried with a query language")
```

### 2.4 `app/analytics/outcome.py` — REQ-008

```python
@dataclass
class CollectOutcome:
    rows_written: int = 0
    periods_ok: int = 0
    periods_empty: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def status(self) -> Literal["ok", "partial", "failed"]:
        if not self.errors:            return "ok"
        if self.rows_written > 0:      return "partial"
        return "failed"

    @property
    def exit_code(self) -> int:  # 0 / 1 / 2
```
**"No errors and zero rows" is `ok`** — nothing was due. **"Errors and zero rows" is
`failed`.** The two must never collapse into one status; that is the whole point.

### 2.5 `app/analytics/journal.py` — REQ-005

```python
async def pending_periods(session, *, connection_id, report,
                          expected: list[str], tail: int) -> list[str]
async def record(session, *, connection_id, report, period, status, rows_written=0, error=None)
async def prune(session, *, older_than_days: int = 400) -> int      # REQ-015
```
`pending_periods` = `sorted(set(expected) - {p for p in done if status in ("ok","empty")})`
**∪ the last `tail` entries of `expected`** (always refetched — vendors revise).
Never `max(period)`: a hole below the high-water mark must refill. A `failed` period
stays pending.

### 2.6 Orchestrator tool — REQ-009

`app/agents/tools/analytics_tools.py`:
```python
QUERY_ANALYTICS_SOURCE_TOOL = Tool(
    name="query_analytics_source",
    description="Query a connected analytics/app-store source (Google Analytics, "
                "App Store Connect, Google Play) for traffic, revenue, installs or "
                "subscription data that has been collected into this project.",
    parameters=[question(str, required), connection_id(str, optional),
                report(str, optional), date_from(str, optional), date_to(str, optional)],
)
```
Gated in `get_orchestrator_tools(..., has_analytics_sources: bool = False)`, mirroring
`has_mcp_sources`. `ContextLoader.has_analytics_sources(project_id)` returns
`any(c.source_type in ANALYTICS_SOURCE_TYPES for c in connections)`.

**C7:** `QUERY_MCP_SOURCE_TOOL`'s description drops "Google Analytics" and gains
"…for sources not natively supported; Google Analytics, App Store Connect and Google
Play have first-class connectors — prefer `query_analytics_source` for those."

---

## 3. Behavior

### 3.1 Collection (`AnalyticsCollectService`) — REQ-007, 008

```
for report in adapter.available_reports():
    expected = period_range(report.grain, backfill_days, today_minus_lag)
    for period in journal.pending_periods(..., expected, tail=REFETCH_TAIL):
        try:    rep = await adapter.fetch(report.name, period)
        except AnalyticsEmpty:            journal.record(..., "empty");  outcome.periods_empty += 1;  continue
        except (AnalyticsAuth|Permission): journal.record(..., "failed", error);  outcome.errors.append(...);  break-report
        except (Transient|Quota) as e:     journal.record(..., "failed", error);  outcome.errors.append(...);  continue
        n = upsert(rep.rows);  journal.record(..., "ok", n);  outcome.rows_written += n
return outcome
```
`REFETCH_TAIL = 2` periods for GA4 (data settles within ~48 h). GA4 is queried only
up to **yesterday** — today is always partial (blueprint rule, kept).

**Per-period isolation:** one failing period never aborts the run, but it is always
recorded and always surfaces in the outcome. An auth/permission error *does* stop that
report — the credential is wrong; continuing wastes quota.

### 3.2 Scheduling — REQ-007

`app/main.py` gains `_analytics_collect_cron_loop()`, a near-copy of
`_daily_knowledge_sync_cron_loop`:
- returns immediately unless `settings.analytics_collect_enabled`;
- wakes at the top of each hour, wall-clock aligned;
- `redis_lock(f"cron:analytics_collect:{run_date}:{hour}", ttl_seconds=3600)`;
- selects connections where `source_type ∈ ANALYTICS_SOURCE_TYPES`,
  `is_active`, `collection_enabled`, `collection_hour == current_hour`;
- `task_queue.enqueue("run_analytics_collect", coro_factory=…,
  task_id=f"analytics_collect:{conn.id}:{run_date}", connection_id=…)`.

`worker.py` gains `run_analytics_collect(ctx, *, connection_id)` and registers it in
`WorkerSettings.functions`. **The `coro_factory` keeps the no-Redis path working.**

### 3.3 The agent — REQ-009, 010, 011

`AnalyticsAgent` follows `MCPSourceAgent`'s loop shape (bounded iterations, tool
results truncated, `no_result` on budget exhaustion — never a fabricated answer) but
its tools read the **local fact tables**, not the vendor:

| Tool | Does |
|---|---|
| `list_reports` | what this connection has, and each report's collected coverage |
| `query_report(report, date_from, date_to, group_by?, limit?)` | parameterised read of one fact table — **no free-form SQL**, no user string reaches a query |
| `coverage(report)` | journal state: latest `ok` period, pending periods, last error |

Then, before returning (REQ-010):
1. **DataGate** hard checks on the rows (impossible percentages, future dates,
   negative counts/revenue) → block per `data_gate_hard_checks_enabled`.
2. **Truncation / partial caveat** — if any requested period is pending or `failed`,
   or `AnalyticsReport.truncated`, the answer states exactly which.
3. **Freshness** — the answer states the vendor lag and the latest collected period.
4. **AnswerQualityGate** on the final text.
5. `VizAgent` renders as for any tabular result.

> Because the answer is composed from local rows, "we have no data for July" and
> "July collected as zero" are different sentences and the agent must produce the right
> one. `coverage()` exists precisely so it can tell them apart.

### 3.4 Retention — REQ-015

- Raw vendor payloads are **never written to disk**: `fetch()` returns parsed rows and
  the response body goes out of scope. (Also required by Heroku's ephemeral FS.)
- `journal.prune(older_than_days=400)` runs in the existing 24 h maintenance cron.
- `connections.id` CASCADE covers journal + all five fact tables; deleting a project
  cascades through its connections.

---

## 4. Config / env — REQ-027 partial

| Setting | Default | Env |
|---|---|---|
| `analytics_collect_enabled` | `False` | `ANALYTICS_COLLECT_ENABLED` |
| `analytics_backfill_days` | `30` | `ANALYTICS_BACKFILL_DAYS` |
| `analytics_refetch_tail_periods` | `2` | `ANALYTICS_REFETCH_TAIL_PERIODS` |
| `analytics_collect_job_timeout_seconds` | `1800` | `ANALYTICS_COLLECT_JOB_TIMEOUT_SECONDS` |
| `analytics_http_attempts` | `3` | `ANALYTICS_HTTP_ATTEMPTS` |
| `analytics_journal_retention_days` | `400` | `ANALYTICS_JOURNAL_RETENTION_DAYS` |

New dependency: `google-analytics-data>=0.18`. `google-auth` arrives transitively.

## 5. API — REQ-002, 012

| Route | Purpose |
|---|---|
| `GET/POST /api/vendor-credentials` | list (owner-scoped) / create. **Response never includes the secret** — only `id`, `name`, `provider`, `fingerprint`, `meta`, timestamps |
| `DELETE /api/vendor-credentials/{id}` | owner-strict; 409 when a connection still references it (FK RESTRICT) |
| `POST /api/projects/{pid}/connections` | accepts `source_type`, `vendor_credential_id`, `source_config`, `collection_enabled`, `collection_hour` |
| `POST /api/connections/{id}/collect` | manual "collect now" → enqueues the same job |
| `GET /api/connections/{id}/collection-status` | journal summary: per report, latest ok period, pending count, last error |

## 6. UI — REQ-012, 013

- **`ConnectionSelector`** — source-type select gains *Google Analytics 4*; choosing it
  hides DB/SSH fields, shows a credential picker (mirroring the SSH-key select, with a
  "＋ new credential" affordance) and a property-ID field, backfill-days, collection
  hour and an enable toggle.
- **`VendorCredentialsPanel`** (new, in settings) — list / add / delete, mirroring the
  SSH-keys panel. Paste area for the SA JSON; the value is write-only.
- **`ConnectionHealth`** — a collection row: last run, outcome badge
  (`ok`/`partial`/`failed`), pending periods, next scheduled hour, "Collect now".

Scenarios appended to `docs/ux/scenarios.md` in format v1. **IDs corrected during the
build: SCN-105…108 were already taken (the file runs to SCN-112), so the block is
SCN-113…116.** A spec that names scenario IDs is a proposal, not a reservation — IDs
are allocated from the end of the file at write time and never reused.
`SCN-113` add a GA4 connection · `SCN-114` add/delete a vendor credential ·
`SCN-115` collection status incl. **partial** and pending periods ·
`SCN-116` credential delete blocked while in use.

A `Coverage:` entry may be prefixed `planned:` when the component it names is created by
a later task; such an entry is exempt from the existence check **only while the scenario
is `draft`** (enforced by its own test).

## 7. Failure & edge cases (each gets a test)

| Case | Behavior |
|---|---|
| SA JSON malformed | create fails 422 with a specific message; nothing stored |
| Credential valid, property not shared with the SA | `test_connection` false; 403 → `AnalyticsPermissionError`; UI shows "grant Viewer on this property" |
| GA4 returns > 250 000 rows | paginate on `offset`; if still capped, `truncated=True` → caveat (Δ1) |
| A trend day has no events | `keep_empty_rows=True` so it is a zero, not a gap (Δ2) |
| Quota exhausted mid-run | that period `failed`, run continues, outcome `partial`, answer says so |
| Redis absent | `task_queue` in-process fallback runs the same coroutine |
| Two dynos, same hour | hour-scoped Redis lock; exactly one wave dispatches |
| Same day twice | day-scoped `task_id` dedupes; and the upsert is idempotent anyway |
| Period previously `failed` | stays pending; refilled on the next run (hole below the watermark) |
| Connection deleted mid-collect | job resolves the connection first and exits cleanly if gone |
| Credential deleted while referenced | FK RESTRICT → 409, never an orphaned connection |

## 8. Test plan (REQ-028: coverage must not drop below 72 %)

`backend/tests/unit/analytics/` — `test_http_retry.py` (one test per status code +
`Retry-After` + no-retry-on-auth), `test_outcome.py` (all three statuses incl. the
zero-rows/zero-errors case), `test_journal.py` (**hole below the watermark refills**,
tail refetch, prune), `test_ga4_adapter.py` (fake HTTP: paging, truncation,
`keep_empty_rows`, quota), `test_collect_service.py` (per-period isolation, auth
aborts the report, idempotent rerun), `test_analytics_agent.py` (gating, `no_result`,
DataGate block, freshness caveat, empty-vs-zero).
`backend/tests/unit/models/test_connection_analytics.py`,
`backend/tests/unit/services/test_vendor_credential_service.py` (owner-strict,
never-serialised), `backend/tests/unit/docs/test_ux_scenarios.py` (C11).
`backend/tests/integration/test_analytics_collect_e2e.py` (fake vendor → tables → agent).
Frontend vitest for each changed/new component.

**Every test asserts on behavior, not on having been called.** Each new gate is probed
both ways: a planted defect must make it fail before it counts as green.
