# API Reference

The backend exposes a REST API at `http://localhost:8000/api`. All endpoints
except authentication and health require a JWT token in the `Authorization`
header:

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

**Rate limits**: Register: 5/min, Login: 10/min, Google: 10/min

## Projects

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/projects` | Create project |
| GET | `/api/projects` | List user's projects |
| GET | `/api/projects/{id}` | Get project details |
| PATCH | `/api/projects/{id}` | Update project |
| DELETE | `/api/projects/{id}` | Delete project |
| GET | `/api/projects/{id}/readiness` | Check project setup readiness |

## Connections

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/connections` | Create database connection |
| GET | `/api/connections?project_id=` | List connections |
| GET | `/api/connections/{id}` | Get connection |
| PATCH | `/api/connections/{id}` | Update connection |
| DELETE | `/api/connections/{id}` | Delete connection |
| POST | `/api/connections/{id}/test` | Test connectivity |
| POST | `/api/connections/{id}/refresh-schema` | Refresh schema cache |
| POST | `/api/connections/{id}/index-db` | Index database schema |
| POST | `/api/connections/{id}/trigger-sync` | Trigger code-DB sync |

## Chat

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/chat/ask` | Send message (returns full response) |
| POST | `/api/chat/ask/stream` | Send message (SSE streaming) |
| GET | `/api/chat/sessions?project_id=` | List chat sessions |
| GET | `/api/chat/sessions/{id}/messages` | Get session messages |
| DELETE | `/api/chat/sessions/{id}` | Delete session |
| GET | `/api/chat/estimate` | Estimate token cost |
| GET | `/api/chat/suggestions` | Get query suggestions |
| POST | `/api/chat/messages/{id}/rate` | Rate a message |

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
| PATCH | `/api/repos/{project_id}/repositories/{id}` | Update repository |
| DELETE | `/api/repos/{project_id}/repositories/{id}` | Delete repository |
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
