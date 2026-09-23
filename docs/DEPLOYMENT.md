# Deployment

## Overview
- Project: checkmydata-ai (backend: FastAPI/Python, frontend: Next.js)
- Environments: production
- Deploy branch: `main`
- Deploy trigger: **CI-on-push to `main`** via GitHub Actions (no manual CLI deploy)

## Platforms / targets
| Env | Platform | App / service | URL | Notes |
|-----|----------|---------------|-----|-------|
| production | Heroku (container registry) | `checkmydata-api` (backend) | https://api.checkmydata.ai | `web` + `worker` dynos; Redis addon for ARQ |
| production | Heroku (container registry) | `checkmydata-web` (frontend) | https://checkmydata.ai | App name overridable via repo var `FRONTEND_APP` |

DigitalOcean App Platform config (`.do/app.yaml`) exists but is not the active
path (placeholder repo `<your-github-org>`); Heroku via CI is authoritative.

## Pre-deploy gate
CI (`.github/workflows/ci.yml`) runs on every push/PR to `main` and must pass
before deploy. Mirror it locally:

Backend (`backend/`, Python 3.12):
- Lint: `ruff check app/ tests/`
- Format: `ruff format --check app/ tests/`
- Type check: `mypy app/ --ignore-missing-imports`
- Tests: `pytest tests/unit/ && pytest tests/integration/`
  - Env: `DATABASE_URL=sqlite+aiosqlite:///:memory:`, `MASTER_ENCRYPTION_KEY=<fernet key>`
- Coverage gate: `coverage report --fail-under=80` (combined unit + integration; the per-step runs pass `--cov-fail-under=0`)

Frontend (`frontend/`, Node 20):
- Type check: `npx tsc --noEmit`
- Lint: `npx eslint . --max-warnings=0`
- Tests: `npm test`
- Build: `npm run build`

## Deploy steps
1. Ensure the pre-deploy gate is green locally.
2. Commit all intended changes (never commit secrets).
3. Land the changes on `main` (merge the feature branch / PR into `main`).
4. The push to `main` triggers the `CI` workflow. On CI success, the
   `Deploy to Heroku` workflow (`.github/workflows/deploy.yml`) automatically:
   - Builds `Dockerfile.backend`, `Dockerfile.worker`, `Dockerfile.release` (the backend
     image with `alembic upgrade head` as its CMD) and `Dockerfile.frontend` (linux/amd64).
   - Pushes `registry.heroku.com/<backend>/web`, `/worker`, `/release` and the frontend `/web`.
   - Records the current release version, PATCHes the formation, then waits for a **higher**
     release whose `status` is `succeeded` and for a `worker` dyno `up` on it — a PATCH that
     returns an error fails the job instead of passing it (P0-4).
   - Runs backend + frontend health checks.
   - Deploys **queue** rather than cancel, so backend and frontend never end on different commits.

No local `git push heroku` is needed; deploy is fully CI-driven.

## Environment variables / secrets
- Stored in: GitHub Actions (repo secrets/vars) for the build/release;
  Heroku config vars for runtime.
- GitHub secrets (names only): `HEROKU_API_KEY`, `NEXT_PUBLIC_GOOGLE_CLIENT_ID`.
- GitHub vars (names only, with defaults in deploy.yml): `BACKEND_APP`,
  `FRONTEND_APP`, `BACKEND_API_URL`, `BACKEND_WS_URL`, `FRONTEND_URL`.
- Heroku runtime config (names only): `DATABASE_URL`, `MASTER_ENCRYPTION_KEY`,
  `JWT_SECRET`, `OPENAI_API_KEY`, `CORS_ORIGINS`, `AUTH_COOKIE_DOMAIN`,
  `REDIS_URL`, feature flags (`CODE_GRAPH_ENABLED`, `DAILY_KNOWLEDGE_SYNC_ENABLED`,
  etc.), billing (`BILLING_ENABLED`, `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`,
  `STRIPE_PRICE_PRO`, `STRIPE_PRICE_TEAM`), etc.
- `AUTH_COOKIE_DOMAIN` **must** be set to the shared parent domain
  (`.checkmydata.ai`) because the SPA (`checkmydata.ai`) and API
  (`api.checkmydata.ai`) live on different subdomains. With a host-only cookie
  (empty value) the non-httpOnly CSRF cookie set by the API is unreadable by the
  SPA, so the double-submit check fails on every cookie-authenticated mutation
  (including `POST /auth/refresh` on session restore) and users bounce back to
  `/login`. Set via `heroku config:set AUTH_COOKIE_DOMAIN=.checkmydata.ai -a checkmydata-api`.

## Migrations / release-phase commands
- DB migrations run in the Heroku **release phase**: `Dockerfile.release` runs
  `alembic upgrade head` before the release goes live, and a failed migration aborts the
  deploy. The web image's CMD is plain `uvicorn` (`Dockerfile.backend:80`). As a backstop the
  FastAPI lifespan (`main.py`) and worker start-up (`worker.py`) also call `run_migrations()`
  under a session-level advisory lock. The `Procfile` is not used by the container deploy.
- Worker process: `cd backend && arq app.worker.WorkerSettings`

## Post-deploy verification
- Health checks (also enforced inside deploy.yml):
  - Backend: `GET https://api.checkmydata.ai/api/health` → expect `200`
  - Frontend: `GET https://checkmydata.ai` → expect `200`
- CI/CD status:
  - `gh run list --branch main --limit 5`
  - `gh run watch <run-id>` / `gh run view <run-id> --log-failed`
- Heroku logs (if CLI access): `heroku logs --tail -a checkmydata-api`,
  `heroku ps -a checkmydata-api` (and `checkmydata-web`).

## Rollback
- Heroku: `heroku releases -a <app>` then `heroku rollback <vNNN> -a <app>`
  for each app. Alternatively re-release the previous image digest via the
  Heroku platform API (same call shape as deploy.yml's release step).
- Source: revert the offending commit on `main` and let CI redeploy.

## Contacts / ownership
- Owner: <fill in>
- Escalation: <fill in>
