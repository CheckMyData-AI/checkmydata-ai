# API Reference

> **Coverage note (2026-07-24):** this document is incomplete — 65 implemented endpoints are
> not yet documented here (Billing, Connection Learnings, Runs, and Health Monitor sections
> are missing entirely, plus ~45 individual endpoints). The full audited inventory lives in
> [`docs/qa-audit/full-audit-2026-07-24/02-api-contract.md`](docs/qa-audit/full-audit-2026-07-24/02-api-contract.md).
> For anything not listed below, prefer the OpenAPI docs at `/docs` (see the bottom of this
> page).

The backend exposes a REST API at `http://localhost:8000/api`. All endpoints
require authentication, except the public-by-design set:
`/api/auth/*` (register/login/google/verify-email/resend-verification/forgot-password/reset-password),
`GET /api/health`, `GET /api/plans`, and the two signed webhooks
(`POST /api/webhook` — Stripe signature; `POST /api/repos/{project_id}/webhook` — HMAC).
Note that `GET /api/health/modules` **does** require authentication.
Two mechanisms are supported (`backend/app/api/deps.py::get_current_user`):

- **Browsers** authenticate with an `httpOnly` **session cookie** plus a **CSRF
  double-submit** token (the `X-CSRF-Token` header must equal the CSRF cookie on
  any mutating request, or the call is rejected with `403`). The JWT is not
  exposed to JavaScript and is omitted from login response bodies when
  `auth_cookie_enabled`.
- **Non-browser API clients** continue to pass a JWT in the `Authorization`
  header (CSRF does not apply to bearer auth):

  ```
  Authorization: Bearer <jwt-token>
  ```

## Authentication

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/auth/register` | Create account (email, password, display_name) |
| POST | `/api/auth/login` | Login (email, password) → JWT token |
| POST | `/api/auth/google` | Google OAuth login (credential token) |
| POST | `/api/auth/change-password` | Change password (current + new) |
| POST | `/api/auth/refresh` | Refresh JWT token |
| GET | `/api/auth/me` | Get current user profile |
| POST | `/api/auth/complete-onboarding` | Mark onboarding complete |
| DELETE | `/api/auth/account` | Delete account and all data |
| POST | `/api/auth/mcp-tokens` | Issue a per-user MCP API token (plaintext shown once) |
| GET | `/api/auth/mcp-tokens` | List the caller's MCP tokens (hash + prefix only) |
| DELETE | `/api/auth/mcp-tokens/{token_id}` | Revoke an MCP token (404 if missing/not owned) |
| POST | `/api/auth/verify-email` | Confirm an email address; on success the now-verified address auto-accepts its pending email invites (F-PROJ-01) |
| POST | `/api/auth/resend-verification` | Re-issue and re-send the verification link for the current user |
| POST | `/api/auth/forgot-password` | Request a password-reset link. Public and rate-limited (SCN-013) |
| POST | `/api/auth/reset-password` | Set a new password from a reset link. Public and rate-limited (SCN-013) |

**Rate limits**: Register: 5/min, Login: 10/min, Google: 10/min, MCP token create: 10/min, revoke: 30/min

See [`docs/MCP_SERVER.md`](docs/MCP_SERVER.md) for the full MCP integration guide.

## Projects

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/projects` | Create project |
| GET | `/api/projects` | List user's projects |
| GET | `/api/projects/{id}` | Get project details |
| PATCH | `/api/projects/{id}` | Update project |
| DELETE | `/api/projects/{id}` | Delete project |
| GET | `/api/projects/{id}/readiness` | Check project setup readiness |
| GET | `/api/projects/{id}/pipeline-status` | Unified repo/DB index/code-DB sync running state |
| GET | `/api/projects/{id}/knowledge-health` | Knowledge freshness panel data |
| GET | `/api/projects/{id}/sync-history?limit=N` | Recent scheduled daily-sync runs (viewer). Returns `{"runs": [{id, kind, status, trigger, started_at, finished_at, duration_seconds, error, progress_pct}]}`. `started_at` / `finished_at` are ISO-8601 strings or `null`; `error` is the failure message (or `null`); `duration_seconds` is `null` until the run finishes. `limit` clamped to 1–50, default 20. |
| POST | `/api/projects/access-requests` | Request the privilege to create projects |
| POST | `/api/projects/{project_id}/sync-now` | Trigger a daily-sync run on demand (editor) |
| GET | `/api/projects/{project_id}/sync-schedule` | Effective schedule for a project — its override, else the global setting |
| PUT | `/api/projects/{project_id}/sync-schedule` | Set a per-project daily-sync override (editor) |
| GET | `/api/projects/{project_id}/runs` | Background-run history for a project (viewer) |

## Connections

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/connections` | Create connection (database, MCP, or analytics source) |
| GET | `/api/connections/project/{project_id}` | List connections for a project |
| GET | `/api/connections/{id}` | Get connection |
| PATCH | `/api/connections/{id}` | Update connection |
| DELETE | `/api/connections/{id}` | Delete connection |
| POST | `/api/connections/{id}/test` | Test connectivity (analytics sources are probed with the vendor adapter) |
| POST | `/api/connections/{id}/refresh-schema` | Refresh schema cache |
| POST | `/api/connections/{id}/index-db` | Index database schema |
| POST | `/api/connections/{id}/sync` | Trigger code-DB sync (202) |
| POST | `/api/connections/{connection_id}/reconnect` | Re-run the health probe and reopen the connector. Analytics sources have no database to reach, so they are answered without one (editor) |
| POST | `/api/connections/{connection_id}/test-ssh` | Test SSH reachability on its own, separately from the database behind it |
| GET | `/api/connections/health` | Health of every connection the caller can see |
| GET | `/api/connections/{connection_id}/health` | Health of one connection |
| GET | `/api/connections/{connection_id}/index-db/status` | Schema-index status for a connection |
| GET | `/api/connections/{connection_id}/sync/status` | Code↔DB sync status for a connection |

### Analytics-source fields on create / update

`POST /api/connections` and `PATCH /api/connections/{id}` accept five additional
fields used by analytics sources (Google Analytics 4 today — see
[`docs/ANALYTICS_SOURCES.md`](docs/ANALYTICS_SOURCES.md)):

| Field | Type | Default | Description |
|---|---|---|---|
| `source_type` | string | `"database"` | `"database"`, `"mcp"`, or an analytics vendor: `"ga4"`, `"appstore"`, `"googleplay"` |
| `vendor_credential_id` | string \| null | `null` | Id of an already-stored `VendorCredential`. **Required** when `source_type` is an analytics source; the secret itself is never sent here. |
| `source_config` | object \| null | `null` | Non-secret vendor knobs. For GA4: `{"property_ids": ["294380179"], "backfill_days": 30, "event_names": [...], "currency_code": "USD"}` |
| `collection_enabled` | boolean | `true` | Whether the hourly wave dispatches this connection |
| `collection_hour` | integer (0–23) | `3` | Hour the connection collects in, local to `DAILY_KNOWLEDGE_SYNC_TIMEZONE` |

`source_config` is returned on `ConnectionResponse` as a decoded object (a corrupt
blob degrades to `null` rather than failing the listing). `db_type`, `db_port` and
`db_name` are **nullable** in the response since an analytics source has no engine,
port or database — they are cleared on create rather than persisted as defaults.

Behaviour notes:

- Creating or updating an analytics connection without `vendor_credential_id` → **422**.
- A `vendor_credential_id` the caller does not own → **404** (the lookup is owner-strict,
  so "someone else's" and "does not exist" are answered identically). A credential whose
  `provider` does not match `source_type` → **422**.
- `PATCH` asserts credential ownership on the **merged** row, so a connection can never
  end a PATCH holding a credential the requester does not own.
- `source_type` `appstore` / `googleplay` → **422** in this release (no collector yet).
- `index-db`, `refresh-schema` and `sync` refuse an analytics connection with **400**
  and point at `POST /api/connections/{id}/collect`.

### Analytics collection

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/connections/{id}/collect` | Enqueue a collection run now (**202**). Editor role. Rate limit 10/min. |
| GET | `/api/connections/{id}/collection-status` | Per-report collection state. Viewer role. |

Both return **400** for a non-analytics connection and **404** when the connection
does not exist.

`POST /api/connections/{id}/collect` enqueues exactly the job the hourly cron
enqueues — same task name, same day-scoped task id — so "collect now" and the
schedule cannot race into two concurrent runs for one connection on one day. It
deliberately ignores `collection_enabled` (that flag pauses the *schedule*; pulling
on demand is how a credential fix is verified). Response:

```json
{"status": "queued", "connection_id": "…", "task_id": "analytics_collect:<connection_id>:<YYYY-MM-DD>"}
```

`GET /api/connections/{id}/collection-status` returns:

```json
{
  "connection_id": "…",
  "source_type": "ga4",
  "collection_enabled": true,
  "collection_hour": 3,
  "next_scheduled_hour": 3,
  "timezone": "Europe/Berlin",
  "backfill_days": 30,
  "status": "partial",
  "last_run_at": "2026-08-01T03:04:11+00:00",
  "last_error": null,
  "caveat": "GA4 returned a truncated page for this period",
  "pending_periods": 2,
  "reports": [
    {
      "report": "overview",
      "grain": "daily",
      "latest_ok_period": "2026-07-31",
      "latest_collected_period": "2026-07-31",
      "ok_periods": 28,
      "empty_periods": 0,
      "failed_periods": 1,
      "rows_written": 28,
      "pending_periods": 2,
      "pending_sample": ["2026-07-14", "2026-07-15"],
      "last_run_at": "2026-08-01T03:04:11+00:00",
      "last_error": null,
      "caveat": "GA4 returned a truncated page for this period"
    }
  ]
}
```

**`status`** is one of:

| Value | Meaning |
|---|---|
| `never_collected` | The journal holds no row for this connection — nothing has run yet. |
| `ok` | Every period the backfill window expects has been collected. |
| `partial` | Some periods landed; some are still owed (failed, or not yet fetched). |
| `failed` | Rows exist but nothing succeeded — every period failed. |

Zero rows is only a failure when something actually failed: a window that came back
genuinely `empty` everywhere collected fine and reports `ok`.

**`caveat` is not an error.** `last_error` carries the newest journal row whose
*status* is `failed`; `caveat` carries the newest non-failed row that still has a
note attached — most often "the vendor truncated this page", i.e. the data is real
but a lower bound. An `ok` period can carry a caveat. Both fields exist per report
and at connection level; clients must not render a caveat as a failure.

**Pending vs empty.** `pending_periods` counts expected periods the journal has not
completed. A period recorded `empty` is complete (the vendor genuinely had no data)
and is not pending; a period recorded `failed` stays owed until it succeeds and is
refilled on the next run. The tail-refetch window (the most recent
`ANALYTICS_REFETCH_TAIL_PERIODS` periods, always re-fetched) is deliberately not
counted as pending. `pending_sample` is capped at 10 periods.

`next_scheduled_hour` is `null` when `collection_enabled` is `false`. A run that
failed before it could reach any report is journalled under the reserved report
name `_connect`, which currently appears as an entry in `reports[]` with
`grain: null`.

## Chat

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/chat/ask` | Send message (returns full response) |
| POST | `/api/chat/ask/stream` | Send message (SSE streaming) |
| GET | `/api/chat/sessions/{project_id}` | List chat sessions for a project |
| GET | `/api/chat/sessions/{id}/messages` | Get session messages |
| DELETE | `/api/chat/sessions/{id}` | Delete session |
| GET | `/api/chat/estimate` | Estimate token cost |
| GET | `/api/chat/suggestions` | Get query suggestions |
| WS | `/api/chat/ws/{project_id}/{connection_id}` | WebSocket chat (single-use ticket via `Sec-WebSocket-Protocol`; mint with `POST /api/chat/ws-ticket`) |
| POST | `/api/chat/feedback` | Rate a message (body: `{message_id, rating}`) |
| GET | `/api/chat/search?project_id=&q=&limit=` | Full-text search across the project's chat messages (viewer) |
| POST | `/api/chat/explain-sql` | Plain-language explanation of a SQL statement, with a computed complexity score; cached by statement hash (viewer) |
| POST | `/api/chat/summarize` | Summarise one chat message (viewer) |
| POST | `/api/chat/sessions/ensure-welcome` | Idempotently create the project's welcome session; returns whether it was created (viewer) |
| POST | `/api/chat/sessions/{session_id}/generate-title` | Derive a session title from its first user message |
| GET | `/api/chat/analytics/feedback/{project_id}` | Aggregated message-feedback statistics for a project |
| POST | `/api/chat/sessions` | Create a chat session |

**Chat concurrency & limits**: `/api/chat/ask` and `/api/chat/ask/stream` first check the user's token budget (`429` when exhausted), then acquire an `agent_limiter` concurrency slot (`429` when the per-user/global slot cap is hit) and hold a per-session lock (`409` if a request for the same session is already running). The agent run is bounded by a wall-clock timeout (`stream_timeout_seconds`, default 360s): the non-streaming `/ask` returns **`504`** on timeout; `/ask/stream` reports the timeout in-band as an SSE `error` event (`error_type: "timeout"`) since the HTTP status is already committed.

**Chat response types** (`response_type` field in the answer body):
- `text` — plain conversational or knowledge answer (no SQL executed).
- `sql_result` — at least one SQL query ran and produced rows.
- `clarification_request` — agent needs more information before proceeding.
- `step_limit_reached` — the orchestrator (single-loop or pipeline path) exhausted `max_orchestrator_iterations` or the wall-clock budget before completing normally; a partial/best-effort answer is still returned. Clients should surface this as a soft warning (not an error). As of W3 (ORCH-A02), pipeline answers can also return this type when the pipeline budget is exhausted.
- `error` — an unrecoverable failure; `answer` contains a user-friendly message.

## Notes

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/notes` | Save a query as note |
| GET | `/api/notes?project_id=` | List notes |
| PATCH | `/api/notes/{id}` | Update note |
| DELETE | `/api/notes/{id}` | Delete note |
| POST | `/api/notes/{note_id}/execute` | Run a saved note's query. Routed through `SafetyGuard` like every other raw-SQL entry point |

## Batch Queries

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/batch/execute` | Create and run batch |
| GET | `/api/batch?project_id=` | List batches |
| GET | `/api/batch/{id}` | Get batch results |
| DELETE | `/api/batch/{id}` | Delete batch |
| POST | `/api/batch/{id}/export` | Export batch results |

## Connection Learnings

Per-connection agent memory. Learnings are **not** shared across connections by default —
`cross_connection_learnings_enabled` is off, and `vision.md` §7 treats that as an invariant.

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/connections/{connection_id}/learnings` | List active learnings for a connection |
| DELETE | `/api/connections/{connection_id}/learnings` | Clear every learning for a connection |
| PATCH | `/api/connections/{connection_id}/learnings/{learning_id}` | Edit one learning (a user override outranks a derived lesson) |
| DELETE | `/api/connections/{connection_id}/learnings/{learning_id}` | Remove one learning |
| POST | `/api/connections/{connection_id}/learnings/{learning_id}/contradict` | Downvote a learning: lowers confidence and may deactivate it |
| POST | `/api/connections/{connection_id}/learnings/recompile` | Force the learnings prompt to be rebuilt |
| POST | `/api/connections/{connection_id}/learnings/validate-schema` | Cross-check learnings against the connection's current schema |
| GET | `/api/connections/{connection_id}/learnings/status` | Learning count and last-compiled time |
| GET | `/api/connections/{connection_id}/learnings/summary` | The compiled learnings prompt as the agent receives it |
| POST | `/api/connections/{connection_id}/learnings/{learning_id}/confirm` | Upvote a learning: raises confidence and `times_confirmed`. Deduplicated per user — a second identical vote is a no-op |

## Repositories

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/repos/{project_id}/repositories` | Add repository |
| GET | `/api/repos/{project_id}/repositories` | List repositories |
| PATCH | `/api/repos/repositories/{id}` | Update repository |
| DELETE | `/api/repos/repositories/{id}` | Delete repository |
| POST | `/api/repos/{project_id}/index` | Index repository |
| GET | `/api/repos/{project_id}/docs` | List indexed documents |
| POST | `/api/repos/check-access` | Verify SSH/HTTPS reachability of a repository and list its branches |
| POST | `/api/repos/{project_id}/check-updates` | Fetch the remote and compare HEAD against the last indexed SHA |
| GET | `/api/repos/{project_id}/docs/{doc_id}` | Full content of one indexed document |
| GET | `/api/repos/{project_id}/status` | Index state of the project's repository |

## Rules

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/rules` | Create custom rule |
| GET | `/api/rules?project_id=` | List rules |
| PATCH | `/api/rules/{id}` | Update rule |
| DELETE | `/api/rules/{id}` | Delete rule |

## Dashboards

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/dashboards` | Create dashboard |
| GET | `/api/dashboards?project_id=` | List dashboards |
| GET | `/api/dashboards/{id}` | Get dashboard |
| PATCH | `/api/dashboards/{id}` | Update dashboard |
| DELETE | `/api/dashboards/{id}` | Delete dashboard |

## Request Logs (Owner-only)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/logs/{project_id}/users` | List users with request counts |
| GET | `/api/logs/{project_id}/requests` | Paginated request traces |
| GET | `/api/logs/{project_id}/requests/{trace_id}` | Full trace detail with spans |
| GET | `/api/logs/{project_id}/summary` | Aggregated summary (totals, success rate, cost) |
| PATCH | `/api/logs/{project_id}/errors/{error_id}` | Move an error through open → acknowledged → resolved |
| GET | `/api/logs/{project_id}/query-failures` | Paginated list of captured query failures |
| GET | `/api/logs/{project_id}/query-failures/{failure_id}` | One query failure in full, including its parsed attempt history |
| GET | `/api/logs/{project_id}/errors` | Filterable, deduplicated error catalog. A run killed by the stale-run reaper is catalogued here, its message naming the step that died |
| GET | `/api/logs/{project_id}/runs` | Background-run history for the observability screen |

All logs endpoints require **owner** role. Query parameters: `days`, `user_id`, `status`, `date_from`, `date_to`, `page`, `page_size`.

## SSH Keys

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/ssh-keys` | Create SSH key for current user |
| GET | `/api/ssh-keys` | List current user's SSH keys |
| GET | `/api/ssh-keys/{key_id}` | Get SSH key by id |
| DELETE | `/api/ssh-keys/{key_id}` | Delete SSH key (409 if in use by a connection) |

## Vendor Credentials

Owner-scoped, reusable secrets for external analytics vendors (Google Analytics 4
service-account JSON today; App Store Connect and Google Play secrets are accepted
and stored but have no collector yet). Modelled on SSH keys: strictly owner-scoped
lookups, Fernet-encrypted at rest, **write-only over HTTP**.

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/vendor-credentials` | Store a credential (10/min) |
| GET | `/api/vendor-credentials` | List the caller's credentials |
| DELETE | `/api/vendor-credentials/{credential_id}` | Delete (10/min); **409** if a connection still references it |

**Create body:**

```json
{"name": "analytics-sa", "provider": "ga4", "secret": "{\"type\":\"service_account\", …}"}
```

`provider` is one of `ga4`, `appstore`, `googleplay`. `secret` is capped at 32,000
characters and is stored verbatim (no stripping — a `.p8` PEM's trailing newline is
part of the key material).

**Response — the secret is never in it, on any route:**

```json
{
  "id": "…",
  "name": "analytics-sa",
  "provider": "ga4",
  "fingerprint": "3f2a1c9e7b4d5061",
  "meta": {"client_email": "sa@project.iam.gserviceaccount.com", "project_id": "…"},
  "created_at": "2026-08-01T10:00:00+00:00",
  "updated_at": "2026-08-01T10:00:00+00:00"
}
```

`VendorCredentialResponse` has no field for the plaintext or its ciphertext.
`fingerprint` is the first 16 hex characters of `sha256(plaintext)` — enough to
answer "is this the same key?" without handing anything back. `meta` carries only
non-secret fields lifted out of the credential (for GA4: `client_email` and
`project_id`, so the UI can show which service account to share a property with);
it is `null` for providers whose secret is an opaque blob. The plaintext leaves the
store only through the collection job's service-level lookup — never over HTTP.

Status codes:

- **422** — unsupported `provider`, empty secret, or (for `ga4`) a secret that is
  not valid JSON, is not a JSON object, or is missing `client_email` / `private_key`.
  Nothing is persisted on a rejected create.
- **404** — the credential is not visible to the caller. The lookup never unions
  NULL-owner rows, so another tenant's credential and a non-existent id are answered
  identically and neither confirms the id.
- **409** — `DELETE` while a connection still references the credential
  (`connections.vendor_credential_id` is `ON DELETE RESTRICT`, so the refusal comes
  from the database rather than a pre-check a concurrent create could slip past):
  *"Cannot delete: this credential is in use by a connection. Delete or re-point the
  connection first."*

## Invites & Members

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/invites/{project_id}/invites` | Create invite (owner); sends email |
| GET | `/api/invites/{project_id}/invites` | List project invites (owner) |
| DELETE | `/api/invites/{project_id}/invites/{invite_id}` | Revoke invite (owner) |
| POST | `/api/invites/{project_id}/invites/{invite_id}/resend` | Resend pending invite email (owner) |
| POST | `/api/invites/accept/{invite_id}` | Accept invite for current user |
| GET | `/api/invites/pending` | List pending invites for current user |
| GET | `/api/invites/{project_id}/members` | List project members |
| DELETE | `/api/invites/{project_id}/members/{member_user_id}` | Remove member (owner) |
| POST | `/api/invites/{project_id}/transfer-ownership` | **Transfer ownership** (F-PROJ-10). Body `{new_owner_user_id}`. `204` on success, no body. The target must already be a member (else `400`); the previous owner is demoted to **editor**, not removed; `Project.owner_id` and the member row move together. The **receiving** owner's plan project-quota is enforced before any write. Authorization is the current owner **or** an admin (`ADMIN_EMAILS`) — deliberately not `require_role(…, "owner")`, because `owner_id` is `ondelete="SET NULL"` and an orphaned project has no owner, so that check would `403` everyone on exactly the project this exists to rescue. A non-admin member claiming an orphaned project gets `403`. Rate limit `5/minute`. Note `PATCH …/members/{id}` accepts only `editor`/`viewer` — ownership has one way in, so the quota check cannot be bypassed. |
| DELETE | `/api/invites/{project_id}/members/me` | **Leave the project** (F-PROJ-12). Removes the caller's own membership; `204` on success, `404` when not a member. An **owner is refused with 400** — leaving would strand the workspace, which is what F-PROJ-10 exists to prevent — and the message names the transfer route. Ownership is read from the member row *or* `Project.owner_id`, so an owner whose row disagrees with the column is still refused. Path is `/me`, not `/{id}`: the request cannot express acting on anyone else. Rate limit `10/minute`. |
| GET | `/api/invites/{project_id}/members` | List members, **bounded** (F-PROJ-13): default 500, hard maximum 1000. `X-Total-Count` carries the real total and `X-Result-Capped` is `true` when the body is a partial page — a capped page with no marker reads as complete. Headers rather than a wrapper object so the response shape is unchanged for existing clients. |
| POST | `/api/invites/decline/{invite_id}` | Decline an invitation addressed to the caller |

## Schedules

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/schedules` | Create SQL schedule (cron expression, alert conditions) |
| GET | `/api/schedules?project_id=` | List schedules |
| GET | `/api/schedules/{id}` | Get schedule |
| PATCH | `/api/schedules/{id}` | Update schedule |
| DELETE | `/api/schedules/{id}` | Delete schedule |
| POST | `/api/schedules/{id}/run-now` | Execute schedule SQL immediately; evaluate alerts |
| GET | `/api/schedules/{id}/history` | Get run history |

## Notifications

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/notifications` | List notifications (query: `unread_only`, `limit`) |
| GET | `/api/notifications/count` | Unread notification count |
| PATCH | `/api/notifications/{id}/read` | Mark notification as read |
| POST | `/api/notifications/read-all` | Mark all notifications as read |

## Visualizations & Export

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/visualizations/render` | Render visualization from columns/rows and config |
| POST | `/api/visualizations/export` | Export query result as CSV, JSON, or XLSX |

## Runs

The `IndexingRun` projection behind every background job — repo index, DB index, code↔DB
sync. A run reaped as stale carries `error='stale run reaped'`; `RunCoordinator`
reconciles it if the pipeline turns out to still be alive.

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/runs/{run_id}` | One run: status, current step, progress, failure kind |
| GET | `/api/runs/{run_id}/events` | The run's step journal |
| POST | `/api/runs/{run_id}/cancel` | Request cooperative cancellation (editor) |
| POST | `/api/runs/{run_id}/retry` | Start a fresh run from the same trigger (editor) |

## Workflows

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/workflows/events` | SSE stream of workflow step events (query: `workflow_id`) |

## Data Validation

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/data-validation/validate-data` | Record validation verdict and run feedback pipeline |
| GET | `/api/data-validation/validation-stats/{connection_id}` | Accuracy stats for connection |
| GET | `/api/data-validation/benchmarks/{connection_id}` | Benchmarks for connection |
| GET | `/api/data-validation/analytics/{project_id}` | Project-wide feedback analytics (owner) |
| GET | `/api/data-validation/summary/{project_id}` | Lightweight analytics summary (owner) |
| POST | `/api/data-validation/investigate` | Start async data investigation |
| GET | `/api/data-validation/investigate/{investigation_id}` | Get investigation detail |
| POST | `/api/data-validation/investigate/{investigation_id}/confirm-fix` | Accept or reject proposed fix |
| POST | `/api/data-validation/anomaly-analysis` | Run anomaly intelligence on posted rows/columns |
| POST | `/api/data-validation/anomaly-scan/{connection_id}` | Probe tables for anomalies |

## LLM Models

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/models` | List available LLM models (query: `provider`) |

## Tasks

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/tasks/active` | List currently running background workflows |

## Usage

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/usage/stats` | Token usage comparison and daily breakdown (query: `days`, `project_id`) |

## Metrics (Admin-only)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/metrics` | App metrics: active workflows, per-path request stats, uptime |
| GET | `/api/metrics/prometheus` | Prometheus text-format exposition of the same metrics |

Both metrics endpoints require an **admin** user (`ADMIN_EMAILS`).

### Prometheus counters (W1 intelligence-remediation)

The following counters are registered by `MetricsCollector` and exposed via `/api/metrics/prometheus`:

| Counter | Labels | Description |
|---------|--------|-------------|
| `datagate_block_total` | `stage_id`, `check` | Incremented each time DataGate hard-fails a pipeline stage result (impossible value, impossible count). Useful for alerting on persistent data quality issues. |
| `filter_guard_degrade_total` | `project_id` | Incremented when the required-filter guard degrades (satisfiable filter present but cannot be applied — query is answered with a warning rather than blocked). |
| `retrieval_degraded_total` | `project_id` | Incremented when `KnowledgeFreshnessService` flags a retrieval result as degraded (stale index, missing BM25 snapshot, etc). |

## Backup

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/backup/trigger` | Run manual backup |
| GET | `/api/backup/list` | List backup files on disk |
| GET | `/api/backup/history` | Recent backup records from DB |

## Billing

Present only when `billing_enabled` is on; every route below returns **404** when it is off.

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/billing/plans` | Public plan catalogue for the pricing page |
| GET | `/api/billing/subscription` | The caller's plan, subscription state, and usage against its limits |
| POST | `/api/billing/checkout` | Start a Stripe Checkout session for a plan |
| POST | `/api/billing/portal` | Open the Stripe Customer Portal — invoices, cancellation, card update |
| POST | `/api/billing/webhook` | Stripe webhook receiver. Signature-verified and idempotent (T-BILL-5) |

## Demo

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/demo/setup` | Create demo project with sample in-memory database |

## Data Graph

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/data-graph/{project_id}/summary` | Graph summary (metric and relationship counts) |
| GET | `/api/data-graph/{project_id}/metrics` | List metrics (query: `connection_id`, `category`) |
| POST | `/api/data-graph/{project_id}/metrics` | Upsert metric definition |
| GET | `/api/data-graph/{project_id}/relationships` | List relationships (query: `metric_id`) |
| POST | `/api/data-graph/{project_id}/relationships` | Add metric relationship |
| POST | `/api/data-graph/{project_id}/discover/{connection_id}` | Auto-discover metrics from DB index |
| DELETE | `/api/data-graph/{project_id}/metrics/{metric_id}` | Delete metric |

## Insights

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/insights/{project_id}` | List insights (filters: connection, type, severity, status, confidence) |
| GET | `/api/insights/{project_id}/summary` | Counts by type and severity |
| POST | `/api/insights/{project_id}` | Create insight (owner) |
| PATCH | `/api/insights/{project_id}/{insight_id}/confirm` | Confirm insight |
| PATCH | `/api/insights/{project_id}/{insight_id}/dismiss` | Dismiss insight |
| PATCH | `/api/insights/{project_id}/{insight_id}/resolve` | Resolve insight |
| GET | `/api/insights/{project_id}/actions` | Prioritized actions from active insights |

## Feed (Autonomous Scans)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/feed/{project_id}/scan/{connection_id}` | Run autonomous insight scan for one connection |
| POST | `/api/feed/{project_id}/scan` | Scan all connections in project |
| POST | `/api/feed/{project_id}/opportunities/{connection_id}` | Scan for growth opportunities |
| POST | `/api/feed/{project_id}/losses/{connection_id}` | Scan for revenue/conversion losses |

## Reconciliation

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/reconciliation/{project_id}/row-counts` | Compare row counts between two connections |
| POST | `/api/reconciliation/{project_id}/values` | Compare aggregate values |
| POST | `/api/reconciliation/{project_id}/schemas` | Compare table/column schemas |
| POST | `/api/reconciliation/{project_id}/full` | Full reconciliation with insight storage |

## Semantic Layer

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/semantic-layer/{project_id}/build/{connection_id}` | Build semantic catalog from DB index |
| POST | `/api/semantic-layer/{project_id}/normalize` | Normalize metrics across connections |
| GET | `/api/semantic-layer/{project_id}/catalog` | Browse metric catalog (query: `connection_id`, `category`) |

## Exploration

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/explore/{project_id}` | Query-less investigation report (query: `connection_id`) |

## Temporal Intelligence

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/temporal/{project_id}/analyze` | Time-series analysis (trend, seasonality, anomalies) |
| POST | `/api/temporal/{project_id}/lag` | Lag/lead detection between two series |

## Health

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/health` | Basic health check (public) |
| GET | `/api/health/modules` | Detailed module health (authentication required — 401 without a token) |

## Error Responses

All errors follow this format:

```json
{
  "detail": "Human-readable error message"
}
```

Common status codes:
- `400` — Bad request (invalid input)
- `401` — Unauthorized (missing/invalid token)
- `403` — Forbidden (insufficient permissions)
- `404` — Not found
- `409` — Conflict (duplicate resource)
- `422` — Validation error (Pydantic)
- `429` — Rate limit exceeded
- `500` — Internal server error

## Rate Limiting

Most mutating endpoints are rate-limited per IP (112 of 120 mutations; the 8
unthrottled exceptions include `POST /api/checkout`, `POST /api/portal`,
`PATCH /api/schedules/{id}`, `POST /api/chat/ws-ticket`,
`POST /api/data-validation/investigate/{id}/confirm-fix`, `POST /api/auth/logout`,
`POST /api/auth/complete-onboarding`, and the Stripe `POST /api/webhook` — see
[`docs/qa-audit/full-audit-2026-07-24/02-api-contract.md`](docs/qa-audit/full-audit-2026-07-24/02-api-contract.md)
§3 N-1). Limits vary by endpoint sensitivity. The `X-RateLimit-*` headers
indicate current usage.

## OpenAPI Documentation

When running locally, interactive API docs are available at:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`
