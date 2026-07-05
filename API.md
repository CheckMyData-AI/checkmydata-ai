# API Reference

The backend exposes a REST API at `http://localhost:8000/api`. All endpoints
except `/api/auth/*` and `/api/health` require authentication via one of two
mechanisms (`backend/app/api/deps.py::get_current_user`):

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

## Connections

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/connections` | Create database connection |
| GET | `/api/connections/project/{project_id}` | List connections for a project |
| GET | `/api/connections/{id}` | Get connection |
| PATCH | `/api/connections/{id}` | Update connection |
| DELETE | `/api/connections/{id}` | Delete connection |
| POST | `/api/connections/{id}/test` | Test connectivity |
| POST | `/api/connections/{id}/refresh-schema` | Refresh schema cache |
| POST | `/api/connections/{id}/index-db` | Index database schema |
| POST | `/api/connections/{id}/sync` | Trigger code-DB sync (202) |

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

**Chat concurrency & limits**: `/api/chat/ask` and `/api/chat/ask/stream` first check the user's token budget (`429` when exhausted), then acquire an `agent_limiter` concurrency slot (`429` when the per-user/global slot cap is hit) and hold a per-session lock (`409` if a request for the same session is already running). The agent run is bounded by a wall-clock timeout (`stream_timeout_seconds`, default 360s): the non-streaming `/ask` returns **`504`** on timeout; `/ask/stream` reports the timeout in-band as an SSE `error` event (`error_type: "timeout"`) since the HTTP status is already committed.

## Notes

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/notes` | Save a query as note |
| GET | `/api/notes?project_id=` | List notes |
| PATCH | `/api/notes/{id}` | Update note |
| DELETE | `/api/notes/{id}` | Delete note |

## Batch Queries

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/batch` | Create and run batch |
| GET | `/api/batch?project_id=` | List batches |
| GET | `/api/batch/{id}` | Get batch results |
| DELETE | `/api/batch/{id}` | Delete batch |
| GET | `/api/batch/{id}/export` | Export batch results |

## Repositories

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/repos/{project_id}/repositories` | Add repository |
| GET | `/api/repos/{project_id}/repositories` | List repositories |
| PATCH | `/api/repos/repositories/{id}` | Update repository |
| DELETE | `/api/repos/repositories/{id}` | Delete repository |
| POST | `/api/repos/{project_id}/index` | Index repository |
| GET | `/api/repos/{project_id}/docs` | List indexed documents |

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

All logs endpoints require **owner** role. Query parameters: `days`, `user_id`, `status`, `date_from`, `date_to`, `page`, `page_size`.

## SSH Keys

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/ssh-keys` | Create SSH key for current user |
| GET | `/api/ssh-keys` | List current user's SSH keys |
| GET | `/api/ssh-keys/{key_id}` | Get SSH key by id |
| DELETE | `/api/ssh-keys/{key_id}` | Delete SSH key (409 if in use by a connection) |

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
| GET | `/api/health` | Basic health check |
| GET | `/api/health/modules` | Detailed module health |

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

Mutating endpoints are rate-limited per IP. Limits vary by endpoint
sensitivity. The `X-RateLimit-*` headers indicate current usage.

## OpenAPI Documentation

When running locally, interactive API docs are available at:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`
