# Analytics Sources — operator runbook

How to connect Google Analytics 4 as a first-class data source, collect it on a
schedule, read its collection status, and diagnose it when it stops.

Written for someone who has never seen this code. Everything below is the
behaviour of the shipped release — where a step is "the one people get wrong",
it is called out.

| | |
|---|---|
| **Supported today** | Google Analytics 4 (`ga4`) |
| **Reserved, not usable yet** | App Store Connect (`appstore`), Google Play (`googleplay`) — see [§8 Not yet supported](#8-not-yet-supported) |
| **Global switch** | `ANALYTICS_COLLECT_ENABLED` (default **off**) |
| **Per-connection switch** | `collection_enabled` (default **on**) |
| **API contracts** | [`API.md` → Vendor Credentials / Analytics collection](../API.md) |
| **Design decision** | [`docs/adr/0001-external-report-cache.md`](adr/0001-external-report-cache.md) |

---

## 1. What this is, and why it exists

CheckMyData normally answers questions by reading the user's own systems live —
that is the rule in `vision.md` §8 ("not a data warehouse or ETL pipeline").
Analytics vendors break that rule's assumptions: GA4 is quota-limited, its data
lags and keeps settling for roughly 48 hours, and it has no query language — only
a fixed set of canned reports. Proxying every chat question to the vendor would
burn the property's quota on repetition and could still never answer "compare
this month with last".

So the product **caches the vendor's already-aggregated reports per connection,
with provenance and a refetch policy** — a cache, deliberately not a warehouse.
`vision.md` §8 carries this carve-out explicitly and points at
[ADR-0001](adr/0001-external-report-cache.md), which records the decision, the
alternatives rejected (live proxy, MCP-only), and the retention rules. The
carve-out applies **only** to external report APIs reached with a vendor
credential the user supplied for that purpose. Data in a user's production
database is still only ever read in place, on demand — never copied, transformed
or moved.

Concretely, per GA4 connection the system stores:

- five typed fact tables — `ga4_overview_daily`, `ga4_geo_daily`,
  `ga4_platform_daily`, `ga4_trend_daily`, `ga4_event_daily` — each keyed on
  `(connection_id, property_id, date, …dimensions)` and written with an upsert,
  so re-collecting a period overwrites rather than duplicates;
- an import journal (`analytics_imports`), one row per
  `(connection_id, report, period)` recording `ok` / `empty` / `failed`,
  `rows_written`, `error` and `fetched_at`.

The journal is what lets an answer say *"July was collected and it was zero"*
rather than *"we have no July"*. Raw vendor response bodies are **never** written
to disk or to a blob column.

---

## 2. Human setup in Google (do this first)

These five steps happen in Google's consoles, not in CheckMyData. Step 2 and
step 3 are the two that are usually missed, and both fail *later*, at collection
time, not at paste time.

### 2.1 Create a service account

Google Cloud Console → **IAM & Admin → Service Accounts → Create service
account**. A plain service account with **no** project roles is enough — GA4
access is granted inside Analytics (step 3), not through GCP IAM.

### 2.2 Enable the Google Analytics Data API ⚠️

Google Cloud Console → **APIs & Services → Library → "Google Analytics Data
API"** → **Enable**, in the *same* GCP project as the service account.

Without this the credential is valid, the paste succeeds, and every collection
fails with a permission error from Google that mentions the API not being
enabled. This is the most common "the key is fine but nothing collects" cause
after step 3.

### 2.3 Grant the service account **Viewer** on each GA4 property ⚠️ (most commonly missed)

GA4 → **Admin → Property Access Management → +  → Add users** → paste the
service account's **`client_email`** (it looks like
`something@your-project.iam.gserviceaccount.com`) → role **Viewer** → Add.

Do this for **every** property the connection will collect. A service account
that exists, is enabled, and has a valid key still gets **403** on any property
it has not been added to. CheckMyData shows the `client_email` next to the
stored credential precisely so you can copy it into this screen.

### 2.4 Download the JSON key

Service Accounts → your account → **Keys → Add key → Create new key → JSON**.
The downloaded file is the secret you will paste. Treat it as a password: it is
stored Fernet-encrypted and never shown again.

The file must contain `client_email` and `private_key`, or the paste is rejected
with a 422 naming the missing field.

### 2.5 Find the Property ID — a number, **not** `G-XXXXXXX` ⚠️

GA4 → **Admin → Property → Property details** (older UI: *Property Settings*).
The **PROPERTY ID** is a bare number such as `294380179`.

It is **not** the Measurement ID (`G-XXXXXXX`), which is the web-stream tag and
will never work here. Both `294380179` and `properties/294380179` are accepted
and normalised to the bare number.

---

## 3. Add the credential and the connection in the app

### 3.1 Store the credential

Sidebar → **Setup → Vendor Credentials** → **Add**. The panel is owner-scoped
and visible without an active project; credentials are reusable across
connections.

In the **Add Vendor Credential** dialog:

| Field | What to enter |
|---|---|
| *Credential name (e.g. analytics-sa)* | A label you will recognise later |
| *Credential provider* | **Google Analytics 4** |
| *Service account JSON* | The **entire** downloaded JSON file, pasted unmodified |

The dialog states the storage contract: *"Stored encrypted and never shown again
— only its fingerprint and the service-account address come back."* After
saving, the row shows the provider chip (`GA4`), a short fingerprint, and the
service-account email — copy that email into GA4 property access (§2.3) if you
have not already.

A malformed paste is refused before anything is stored, with a message naming
the problem (not valid JSON / not a JSON object / missing `client_email`,
`private_key`).

### 3.2 Create the connection

Project → Connections → **New Connection**, and pick **Google Analytics 4** in
the source-type select. The database/SSH fields disappear and the GA4 form
appears:

| Field | Default | Notes |
|---|---|---|
| *GA4 vendor credential* | — | Only `ga4` credentials are listed. **New credential** adds one inline without leaving the form. |
| *GA4 property ID* | — | The number from §2.5 |
| *Backfill days* | `30` | How far back a fresh connection collects. Clamped to 1–3650. |
| *Collection hour* | `03:00` | Local to the scheduler timezone (`DAILY_KNOWLEDGE_SYNC_TIMEZONE`, default `Europe/Berlin`) |
| *Collect automatically* | on | Per-connection pause switch for the schedule |

The form ends with the honest bit: *"GA4 is collected up to yesterday — today is
always partial. Grant the service account Viewer on the property first."*

Three things worth knowing:

- **The source type is fixed at creation.** Editing a GA4 connection shows the
  source type read-only; to change source, create a new connection.
- **Test connectivity** (`POST /api/connections/{id}/test`) probes the vendor
  with the real credential. A wrong key and an unshared property both come back
  as a failure with the vendor's own message, never as a silent success. The
  fallback message is exactly the fix: *"The vendor rejected this credential or
  the configured property is not shared with it. Grant the service account
  Viewer access on the property and try again."*
- A GA4 connection has **no schema to index**. `index-db`, `refresh-schema` and
  code↔DB `sync` refuse it with a 400 pointing at
  `POST /api/connections/{id}/collect` instead. It also has no health dot in the
  connection list — the collection row (§5) is its status signal.

---

## 4. Turn collection on, and what the schedule does

Collection is **off by default**, in line with the house rule that ingestion
automation ships off. Enable it and restart the API process:

```bash
ANALYTICS_COLLECT_ENABLED=true
```

The hourly wave lives in the **web** process (`app/main.py` lifespan) and reads
the flag **once at start-up** — a config change without a restart leaves the loop
dormant. The worker does not gate on the flag; it only executes the jobs the wave
(or a manual **Collect now**) enqueues.

`backend/app/config.py` / `backend/.env.example` carry the full knob set:

| Env var | Default | What it does |
|---|---|---|
| `ANALYTICS_COLLECT_ENABLED` | `false` | Master switch for the hourly wave |
| `ANALYTICS_BACKFILL_DAYS` | `30` | Default window width; per-connection `source_config.backfill_days` overrides it |
| `ANALYTICS_REFETCH_TAIL_PERIODS` | `2` | Recent periods always refetched (GA4 settles within ~48 h) |
| `ANALYTICS_COLLECT_JOB_TIMEOUT_SECONDS` | `1800` | Wall-clock budget for one connection's run |
| `ANALYTICS_HTTP_ATTEMPTS` | `3` | Attempts per vendor call; only transient/quota failures are retried |
| `ANALYTICS_JOURNAL_RETENTION_DAYS` | `400` | Journal prune horizon |

**What the wave does.** `_analytics_collect_cron_loop` (in `backend/app/main.py`,
alongside the daily-knowledge-sync loop) wakes at the top of every hour, aligned
to wall-clock time, and dispatches every connection that is an analytics source,
active, `collection_enabled`, and whose `collection_hour` equals the current hour
in `DAILY_KNOWLEDGE_SYNC_TIMEZONE`. It takes an hour-scoped Redis lock
(`cron:analytics_collect:<date>:<hour>`) so exactly one web dyno dispatches, and
enqueues `run_analytics_collect` with a day-scoped task id
(`analytics_collect:<connection_id>:<date>`) so a connection cannot be collected
twice in one calendar day. With no `REDIS_URL`, `task_queue` runs the same
coroutine in-process — the schedule still works, single-dyno.

**What one run does.** For each of the five reports, it computes the expected
periods (backfill window ending **yesterday**), asks the journal which of them
are still pending, and fetches those. Per-period isolation: one failing period
never aborts the run, but it is always journalled and always reported. An
auth/permission failure *does* stop that report — the credential is wrong, and
continuing would only burn quota.

**Collect now.** `POST /api/connections/{id}/collect` (or the **Collect now**
button on the collection row) enqueues exactly the same job with the same
day-scoped id. It deliberately ignores `collection_enabled`: that flag pauses the
*schedule*, and pulling on demand is the normal way to verify a credential fix.

---

## 5. Reading collection status

`GET /api/connections/{id}/collection-status`, rendered in the UI as the
**Collection** row under an analytics connection.

### Connection-level `status`

| Value | Badge | Means |
|---|---|---|
| `never_collected` | *not collected* | The journal has no row at all for this connection. Nothing has run yet. |
| `ok` | *ok* | Every period the backfill window expects has been collected. |
| `partial` | *partial* | Some periods landed, some are still owed (failed or not yet fetched). |
| `failed` | *failed* | Rows exist but **nothing** succeeded — every period failed. |

The rule mirrors the collector's own exit contract: **zero rows is only a failure
when something actually failed.** A window that came back genuinely `empty`
everywhere collected fine — the vendor simply had no data — and is `ok`.

### `caveat` is not an error

Two separate fields, and they must never be collapsed:

- **`last_error`** — the newest journal row whose *status* is `failed`. A real
  failure. Rendered red, with `role="alert"`.
- **`caveat`** — the newest journal row that is **not** failed but still carries
  a note. The most common case: the vendor truncated the page, so the data that
  arrived is real but is a **lower bound**. An `ok` period can carry a caveat.
  Rendered amber, prefixed `Caveat:`.

If you render a caveat as an error, a successful collection looks broken.

### Pending vs empty

`pending_periods` counts periods the window expects that the journal has not
completed. A period recorded `empty` **is** complete — the vendor genuinely had
no data — so it is not pending. A period recorded `failed` stays owed forever
until it succeeds; the hole below the high-water mark refills on the next run.

Note that the tail-refetch (the last 2 periods, always re-fetched) is *not*
counted as pending — otherwise a fully collected connection would report work
outstanding forever.

### Per-report entries

`reports[]` carries one entry per report — `overview`, `geo`, `platform`,
`trend`, `events` — with `latest_ok_period`, `latest_collected_period`,
`ok_periods` / `empty_periods` / `failed_periods`, `rows_written`,
`pending_periods`, a `pending_sample` (first 10), `last_run_at`, `last_error` and
`caveat`.

**One entry is not a report.** A connection-level failure — a bad credential, an
unreachable vendor, a source type with no collector — never reaches a report, so
it is journalled under the reserved name **`_connect`** (`grain: null`). Without
it, the single most likely failure for a fresh GA4 connection would be
indistinguishable from nothing having happened yet. Treat a `_connect` entry as
"the run never got past connecting" and read its `last_error`. A successful
connect deletes any stale `_connect` row, so a fixed credential stops showing
yesterday's banner.

> The sentinel's stated contract is that the reader "surfaces the error and
> excludes `_connect` from the per-report list", but `collection_status` builds
> `reports[]` from every report name in the journal, so the entry is currently
> **included**. Read it as a run-level verdict, not as a sixth GA4 report.

---

## 6. Troubleshooting

### 403 from Google — "the property is not shared with the service account"

By far the most common failure, and it is almost always §2.3. The credential is
valid; the property has simply never had the service account added to it.

Fix: GA4 → **Admin → Property Access Management** → add the credential's
`client_email` (shown next to the stored credential) with role **Viewer** on
**each** property listed in the connection. Then **Collect now** — a 403 is
classified as a *permission* error and is **never retried automatically**,
because retrying a configuration error only burns quota.

If access looks correct, re-check §2.2: an unenabled Google Analytics Data API
also surfaces as a permission failure.

### 401 — bad or expired credential

Same class of problem, same handling (no retry). Re-download the JSON key, add a
new credential, re-point the connection at it, and delete the old credential.

### Quota exhaustion

GA4's per-property/per-project token buckets are read from every response. When a
bucket reports zero remaining, that period is journalled `failed`, the run
**continues** with the next period, and the outcome is `partial` — not success.
Transient failures (429, 5xx, network) and quota errors are retried up to
`ANALYTICS_HTTP_ATTEMPTS` times with exponential backoff that honours the
vendor's `Retry-After`, bounded at 60 s per wait so a hostile header cannot park
the job.

If you see repeated quota failures, lower `ANALYTICS_BACKFILL_DAYS` (or the
connection's `source_config.backfill_days`), stagger `collection_hour` across
connections that share one GCP project, and restrict the `events` report to the
event names you actually care about — an unrestricted `events` report on a busy
property is the row-hungriest of the five.

### A period is stuck `failed`

Nothing to clean up. A `failed` period is **not** treated as done: it stays in
the pending set and is refetched on the next run — including when it sits below
the newest collected period. Fix the underlying cause (access, quota) and either
wait for the next scheduled hour or press **Collect now**.

### "Today's numbers are missing"

By design. The collection window always ends **yesterday**, in the scheduler's
timezone. GA4 does not finalise the current day, and a half-collected today looks
exactly like a crash in traffic. GA4 also keeps revising the previous ~48 h,
which is why the last 2 periods are refetched on every run.

### The chat answer says it has no data

The agent answers from the local fact tables only, and refuses to invent. If no
tool read anything, it returns a refusal rather than prose. If the window it was
asked about contains periods that were never collected or failed, the answer
carries a `PARTIAL DATA:` caveat naming them, and every answer states which
period the report is collected through. That is intended behaviour, not a bug —
check the collection status before treating it as one.

### Status says `never_collected` but a run was expected

`never_collected` means the journal holds **no row at all** — not even a
`_connect` failure. So the run was never dispatched, or it never reached the
journal. Check, in order:

1. `ANALYTICS_COLLECT_ENABLED` on the running API process, and whether it has
   been restarted since the change — the flag is read once at start-up.
2. The connection's `collection_enabled` (the status payload reports it, and
   `next_scheduled_hour` is `null` when it is off) and its `collection_hour`
   against the current hour in `DAILY_KNOWLEDGE_SYNC_TIMEZONE`.
3. Whether the connection is `is_active` — the wave selects on it.
4. Press **Collect now**, which bypasses both the schedule and
   `collection_enabled`, and re-read the status: a failure will now be durable
   under `_connect` instead of invisible.

---

## 7. Retention and deletion

| What | Policy |
|---|---|
| **Fact rows** (`ga4_*_daily`) | **Kept** for the life of the connection. They are the answerable surface; expiring them would silently turn answered history into "not collected". |
| **Raw vendor payloads** | **Never written to disk** — `fetch()` returns parsed rows and the response body goes out of scope. There is nothing to retain, and nothing to leak. |
| **Journal** (`analytics_imports`) | **Pruned at 400 days** (`ANALYTICS_JOURNAL_RETENTION_DAYS`) by the existing 24 h maintenance cron. Best-effort: a failed prune never fails the maintenance pass. |
| **Delete a connection** | `analytics_imports` and all five `ga4_*` fact tables cascade on `connections.id` — every cached row for that connection goes with it. |
| **Delete a project** | Cascades through its connections, so the same applies. |
| **Delete a credential** | `connections.vendor_credential_id` is `ON DELETE RESTRICT`: deleting a credential a connection still references fails loudly with **409**, never orphaning the connection. Re-point or delete the connection first. |
| **Delete an account** | Connections that reference the departing user's credentials are detached and have `collection_enabled` set to `false` before the credentials are destroyed, so an orphaned source stops being dispatched nightly. |

---

## 8. Not yet supported

`appstore` (App Store Connect) and `googleplay` (Google Play) are reserved source
types. The vendor-credential store accepts and encrypts their secrets, but **no
connection can be created against them in this release** — creation and update
both refuse with **422**:

> App Store Connect and Google Play sources are not available yet, so a
> … connection cannot be created. Analytics source types this release can
> collect: ga4.

The refusal is derived from the table of registered fact tables, so it lifts
itself automatically when those modules ship — there is no second list to
maintain. The connection form does not offer either option today.

---

## 9. Reference — where things live

| Concern | File |
|---|---|
| Vendor credential store (owner-strict, Fernet) | `backend/app/services/vendor_credential_service.py` |
| Credential API | `backend/app/api/routes/vendor_credentials.py` |
| Source-type family (`ga4`, `appstore`, `googleplay`) | `backend/app/analytics/source_types.py` |
| GA4 adapter (paging, quota, error taxonomy) | `backend/app/analytics/ga4/adapter.py` |
| GA4 knobs vs secret | `backend/app/analytics/ga4/config.py` |
| The five report definitions | `backend/app/analytics/ga4/reports.py` |
| Import journal + `prune` | `backend/app/analytics/journal.py` |
| Retry policy (`retry_async`, `Retry-After`) | `backend/app/analytics/http.py` |
| Collection service + `period_range` | `backend/app/services/analytics_collect_service.py` |
| Hourly wave | `backend/app/main.py` (`_analytics_collect_cron_loop`) |
| ARQ job | `backend/app/worker.py` (`run_analytics_collect`) |
| Collection-status payload | `backend/app/services/connection_service.py` (`collection_status`) |
| Chat sub-agent + honesty gates | `backend/app/agents/analytics_agent.py` |
| Pipeline plugin | `backend/app/pipelines/analytics_pipeline.py` |
| Migration | `backend/alembic/versions/a7b8c9d0e1f2_add_analytics_sources.py` |
