# Module map — analytics data sources (GA4 · App Store Connect · Google Play)

Build order top to bottom. Status: `planned` → `in progress` → `done` | `deferred`.
**This map's status column is the program's resume point** after a lost context.

| # | Module | Delivers | Owns (entities) | Depends on | Contracts exposed | UI? | REQs | Status |
|---|---|---|---|---|---|---|---|---|
| 1 | **m0-ga4-spine** | Connect a GA4 property, collect it on schedule, ask about it in chat, see a chart — end to end | `VendorCredential`, `AnalyticsImport`, `Ga4Overview/Geo/Platform/Trend/Event` | — | `AnalyticsSourceAdapter` ABC · `AnalyticsPipeline` · `CollectOutcome` · journal API · `query_analytics_source` tool · `/api/vendor-credentials` | yes | REQ-001…015 | **done** — `1.16.0`, prod v199, 2026-08-02 |
| 2 | **m1-appstore** | App Store revenue, subscriptions and authoritative finance, normalised to USD | `AscSalesDaily`, `AscSubscriptionEventDaily`, `AscSubscriptionDaily`, `AscFinanceMonthly`, `AscProduct`, `FxRate` | m0-ga4-spine | `FxRate` table + `fx.rate_for(currency, month)` | yes | REQ-016…021 | planned |
| 3 | **m2-googleplay** | Google Play earnings, sales, installs, subscriptions and vitals | `GpEarningsMonthly`, `GpSalesMonthly`, `GpInstallsDaily`, `GpSubscriptionsDaily`, `GpVitalsDaily` | m0-ga4-spine, m1-appstore (`FxRate` only) | — (terminal consumer) | yes | REQ-022…026 | planned |
| — | *program-level* | Docs/runbook/wiki currency and the coverage floor | — | all | — | no | REQ-027, REQ-028 | planned |

## Brick criteria — check

| Criterion | m0 | m1 | m2 |
|---|---|---|---|
| Independently specifiable | ✅ | ✅ | ✅ |
| Independently buildable/testable | ✅ | ✅ — stubs `FxRate` if built alone | ✅ — `FxRate` exists after m1 |
| Owns its data | ✅ | ✅ | ✅ — no table written by two modules |
| Talks through declared contracts only | ✅ | ✅ consumes m0's ABC + journal | ✅ consumes m0's ABC + m1's `FxRate` |
| Deliverable on its own | ✅ GA4 fully usable | ✅ adds a source | ✅ adds a source |

Graph is acyclic: `m0 → m1 → m2`, with m2's dependency on m1 limited to the `FxRate`
table. **m0 is a genuine walking skeleton** — the thinnest slice that proves every
layer (credential → adapter → journal → upsert → schedule → agent → gates → chart →
UI) against one real vendor, chosen as the cheapest to validate (official SDK, one
API, no archive parsing, no fiscal calendar).

### Written exception — REQ-027 / REQ-028 are program-level

Doctrine wants each REQ in exactly one module. These two are genuinely cross-cutting
and splitting them three ways would produce bookkeeping, not verification:

- **REQ-027 (docs/wiki current):** each module updates the docs it touches in its own
  stage 9; the requirement is *closed* only at final platform acceptance, when the
  runbook covers all three sources and the ledger's stale rows are all fixed.
- **REQ-028 (coverage ≥ 72 %):** checked as a **gate** at every module's stage 6, and
  closed once at the end. It is a standing floor, not a deliverable.

Both are carried in the map's program-level row so neither can vanish between modules.

## Cut rationale

Cut **by vendor capability**, not by layer. A layer cut ("models, then adapters, then
agent, then UI") would mean nothing works until the last brick lands and every
integration risk — credential flow, journal semantics, agent gating, quota handling —
surfaces at the worst moment. The vendor cut means GA4 is answering real questions in
production while Apple's fiscal calendar is still being written.

The shared spine is **not** its own module. A "foundations" brick would be
unshippable by criterion 5 and untestable end-to-end by criterion 2 — precisely the
anti-pattern the walking-skeleton rule exists to prevent. It is therefore built
*inside* m0, proven by GA4, and consumed unchanged by m1/m2.

`FxRate` sits in **m1**, not m0: GA4 reports no money, so putting FX in the skeleton
would add an external dependency the skeleton cannot exercise. m2 consumes it.

## Cross-module contracts

**1. `AnalyticsSourceAdapter` (owner: m0 · consumers: m1, m2)**
```python
class AnalyticsSourceAdapter(DataSourceAdapter):
    source_type: str
    async def connect(self, config: ConnectionConfig) -> None
    async def test_connection(self) -> bool
    def available_reports(self) -> list[ReportSpec]
    async def fetch(self, report: str, period: str) -> AnalyticsReport   # rows + truncated
```
Failure behavior: raises the typed errors in `analytics/errors.py`; the collect
service maps auth/permission to a non-retryable connection failure, `AnalyticsEmpty`
to a journalled `empty`, transient/quota to retry-with-backoff.

**2. Import journal (owner: m0 · consumers: m1, m2)**
```python
async def pending_periods(conn_id, report, expected: list[str], tail: int) -> list[str]
async def record(conn_id, report, period, status: Literal["ok","empty","failed"], rows: int)
```
Watermark is `expected − done`, never `max(period)`. Failure behavior: a journal write
failure fails the period, never silently marks it done.

**3. `FxRate` (owner: m1 · consumer: m2)**
```python
async def rate_for(currency: str, month: str) -> tuple[Decimal | None, date | None]
```
Returns `(None, None)` when no rate exists. Failure behavior: the caller keeps the
native amount and sets `amount_usd = NULL`; **it never substitutes 1.0 or skips the row.**
Provenance is the ECB-**returned** date (docs-study Δ8).

**4. `query_analytics_source` tool (owner: m0 · consumers: none — m1/m2 extend its
report enum only)** — gated on `has_analytics_sources`, mirroring `has_mcp_sources`.

## Deferred to later modules / the ledger

| Item | Home |
|---|---|
| ASC `INSTALLS`, `FIRST_ANNUAL`, `WIN_BACK_ELIGIBILITY`, offer-code redemptions | carry-over C8 → `BACKLOG.md` |
| Apple Analytics Reports API (request/poll/download) | carry-over C9 → `BACKLOG.md` |
| OAuth sign-in for Google sources | carry-over C1 |
| GA4 realtime | carry-over C2 |
| SQL access over the cache | carry-over C3 |

## Deploy cadence

Per module, per brief D10: all eight gates green → merge to `main` → CI → production →
stage-8 verification → mark the row `done` in the same commit as that module's
acceptance.
