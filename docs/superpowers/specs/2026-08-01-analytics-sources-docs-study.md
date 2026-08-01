# Stage 1 — docs study: vendor contracts grounded on fetched docs

Every contract below was fetched at 2026-08-01 (context7 + a live probe), **not
recalled**. The pasted personal-OS blueprint is ~a year old; six things have moved,
three of which are correctness bugs if the blueprint is copied verbatim.

Sources: context7 `/websites/developers_google_analytics_devguides_reporting_data_v1`,
`/googleapis/google-auth-library-python`, `/websites/developer_apple_appstoreconnectapi`,
`/websites/developers_google_play_developer_reporting`; live probe of frankfurter.

---

## GA4 — Data API v1beta (`google-analytics-data`)

**Confirmed.** `BetaAnalyticsDataClient.run_report(RunReportRequest(...))`;
`property=f"properties/{id}"`; `dimensions=[Dimension(name=…)]`,
`metrics=[Metric(name=…)]`, `date_ranges=[DateRange(start_date=…, end_date=…)]`.
Response: `response.rows[].dimension_values[].value` / `.metric_values[].value`,
with `response.dimension_headers[]` / `.metric_headers[]` giving names and
`metric_headers[].type_` the `MetricType`. `response.row_count` is the total.

**Credentials.** `service_account.Credentials.from_service_account_info(json.loads(...))`
then `.with_scopes([...])`; `credentials.refresh(google.auth.transport.requests.Request())`
and `credentials.apply(headers)` for raw HTTP. Confirmed current.

### Δ1 — pagination is mandatory (blueprint does not paginate) ⚠️ correctness

> `limit`: "If unspecified, **10,000 rows** are returned. The API returns a maximum of
> **250,000 rows** per request, no matter how many you ask for."

A property with >10 000 rows for a dimension combination silently truncates at 10 000.
The blueprint issues a single un-paginated `runReport`. **Contract:** loop on `offset`
until `len(rows) < limit` or `offset >= row_count`; when a cap is nonetheless hit,
set `truncated=True` so REQ-010's truncation caveat fires. This is exactly the
"silent truncation reads as complete" failure the W0 honesty program exists to prevent.

### Δ2 — `keepEmptyRows` defaults to false

Rows where every metric is 0 are omitted. For a daily trend this yields **gaps, not
zeros** — a chart would interpolate over a genuinely dead day. **Contract:** request
`keep_empty_rows=True` for time-series reports, or zero-fill the date spine on write.

### Δ3 — `returnPropertyQuota` is available

Setting it returns `PropertyQuota` in the response. **Contract:** request it and log
remaining tokens; on exhaustion raise the typed `QuotaExhaustedError` (REQ-003) rather
than inferring quota state from a 429 alone.

---

## App Store Connect API

**JWT confirmed.** Header `{"alg":"ES256","typ":"JWT"}` + `kid`; payload
`{"iss":…, "iat":…, "exp":…, "aud":"appstoreconnect-v1"}`. (Apple's marketplace-key
docs add a `pid` claim — not applicable to team API keys.) TTL ≤ 20 min stands.

**`GET /v1/salesReports` filters confirmed:** `filter[frequency]`,
`filter[reportType]`, `filter[reportSubType]`, `filter[version]`,
`filter[vendorNumber]`, `filter[reportDate]` (`YYYY-MM-DD` for all frequencies
except `DAILY`).

### Δ4 — the report-type enum has grown

Now: `SALES · PRE_ORDER · NEWSSTAND · SUBSCRIPTION · SUBSCRIPTION_EVENT · SUBSCRIBER ·
SUBSCRIPTION_OFFER_CODE_REDEMPTION · INSTALLS · FIRST_ANNUAL · WIN_BACK_ELIGIBILITY`.
Sub-types now include `SUMMARY_INSTALL_TYPE · SUMMARY_TERRITORY · SUMMARY_CHANNEL`.

> "The allowed values for `reportType`, `reportSubType`, `frequency` and `version` are
> **specific to each sales report type**. Using invalid combinations will result in an error."

**Contract:** the (type, subType, frequency, version) quadruple is validated as a unit
against a table of known-good combinations, not assembled from four independent config
knobs. D7 keeps us at blueprint parity (`SALES`/`SUBSCRIPTION`/`SUBSCRIPTION_EVENT`);
`INSTALLS` and `FIRST_ANNUAL` are newly available and go to the carry-over ledger.

### Δ5 — a newer Analytics Reports API exists

`/v1/analyticsReportRequests/{id}/reports` with `filter[category]` (App Usage,
Commerce…), `filter[name]`, `limit` ≤ 200 — a request/poll/download flow distinct from
`salesReports`. Out of scope under D7 (blueprint parity); recorded as carry-over.

---

## Google Play

**Reporting API confirmed:** `POST https://playdeveloperreporting.googleapis.com/v1beta1/apps/{app}/{metricSet}:query`,
scope `https://www.googleapis.com/auth/playdeveloperreporting`, paginated by
`pageSize`/`pageToken` → `nextPageToken`. Storage side keeps the
`devstorage.read_only` scope — two scopes, one service account, as the blueprint says.

### Δ6 — `timelineSpec` takes structured dates, not ISO strings ⚠️ correctness

```json
"timeline_spec": {
  "aggregation_period": "DAILY",
  "start_time": {"year":"2021","month":"7","day":"1","time_zone":"America/Los_Angeles"},
  "end_time":   {"year":"2021","month":"7","day":"3","time_zone":"America/Los_Angeles"}
}
```

The blueprint documents `"startTime": …, "endTime": …` as scalars. **Contract:** build
structured `{year, month, day, time_zone}` objects; the time zone is part of the key,
not a detail.

### Δ7 — the row shape differs between metric sets ⚠️ correctness

Google's own reference shows **two** response shapes:
`rows[].dimensions[].int64_value` + `rows[].metrics[].decimal_value` (metricset-queries
guide) versus `rows[].dimensionValues[].value` + `rows[].metricValues[].value`
(`vitals.errors.counts`). **Contract:** the parser accepts both and is tested against
both fixtures; an unrecognised shape raises rather than silently yielding zero rows.

---

## FX — frankfurter

### Δ8 — host and provenance

Live probe `GET https://api.frankfurter.dev/v1/2026-07-01?base=EUR&symbols=USD` →
`{"amount":1.0,"base":"EUR","date":"2026-07-01","rates":{"USD":1.1383}}`.
Keyless, historical, no auth — **A3 validated with evidence.**

The host is **`api.frankfurter.dev/v1`**, not the `api.frankfurter.app` named in the
blueprint and in decision D8. Corrected here.

**Provenance rule:** ECB does not publish on weekends or holidays, so the response
`date` may be **earlier than the date requested**. Store the **returned** `date` as the
rate's provenance, never the requested one — otherwise `fx_rates` claims a rate for a
day the ECB never published, and every downstream conversion inherits a false date.

---

## Contract impact on the REQ spine

| Δ | REQ affected | Change |
|---|---|---|
| Δ1 | REQ-003, REQ-010 | GA4 adapter paginates on `offset`; residual cap ⇒ `truncated=True` |
| Δ2 | REQ-006 | time-series reports request `keep_empty_rows=True` / zero-fill on write |
| Δ3 | REQ-003 | `returnPropertyQuota` → typed `QuotaExhaustedError` |
| Δ4 | REQ-017 | (type, subType, frequency, version) validated as a quadruple |
| Δ6 | REQ-022 | structured `timelineSpec` dates incl. time zone |
| Δ7 | REQ-022 | dual-shape row parser, both fixtures tested |
| Δ8 | REQ-020, D8 | host `api.frankfurter.dev/v1`; provenance = **returned** date |

No Δ contradicts a locked decision, so no D12 stop-and-ask is triggered. D8's URL is
corrected in place.
