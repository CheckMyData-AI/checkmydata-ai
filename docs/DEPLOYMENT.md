# Deployment

## Overview
- Project: checkmydata-ai (backend: FastAPI/Python, frontend: Next.js)
- Environments: production
- Deploy branch: `main`
- Deploy trigger: **CI-on-push to `main`** via GitHub Actions (no manual CLI deploy)

## Platforms / targets
| Env | Platform | App / service | URL | Notes |
|-----|----------|---------------|-----|-------|
| production | Heroku (container registry) | `checkmydata-api` (backend) | https://api.checkmydata.ai | App name overridable via repo var `BACKEND_APP` |
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
- Coverage gate: `coverage report --fail-under=72` (combined unit + integration)

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
   - Builds `Dockerfile.backend` and `Dockerfile.frontend` (linux/amd64).
   - Pushes images to `registry.heroku.com/<app>/web`.
   - Releases both Heroku apps via the platform API.
   - Runs backend + frontend health checks.

No local `git push heroku` is needed; deploy is fully CI-driven.

## Environment variables / secrets
- Stored in: GitHub Actions (repo secrets/vars) for the build/release;
  Heroku config vars for runtime.
- GitHub secrets (names only): `HEROKU_API_KEY`, `NEXT_PUBLIC_GOOGLE_CLIENT_ID`.
- GitHub vars (names only, with defaults in deploy.yml): `BACKEND_APP`,
  `FRONTEND_APP`, `BACKEND_API_URL`, `BACKEND_WS_URL`, `FRONTEND_URL`.
- Heroku runtime config (names only): `DATABASE_URL`, `MASTER_ENCRYPTION_KEY`,
  `JWT_SECRET`, `OPENAI_API_KEY`, `CORS_ORIGINS`, `AUTH_COOKIE_DOMAIN`, etc.
- `AUTH_COOKIE_DOMAIN` **must** be set to the shared parent domain
  (`.checkmydata.ai`) because the SPA (`checkmydata.ai`) and API
  (`api.checkmydata.ai`) live on different subdomains. With a host-only cookie
  (empty value) the non-httpOnly CSRF cookie set by the API is unreadable by the
  SPA, so the double-submit check fails on every cookie-authenticated mutation
  (including `POST /auth/refresh` on session restore) and users bounce back to
  `/login`. Set via `heroku config:set AUTH_COOKIE_DOMAIN=.checkmydata.ai -a checkmydata-api`.

## Migrations / release-phase commands
- DB migrations run on backend boot via the `Procfile` web command:
  `cd backend && alembic upgrade head && uvicorn app.main:app ...`
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
