# Installation

## Prerequisites

| Tool | Version | Check |
|------|---------|-------|
| Python | 3.12+ | `python3 --version` |
| Node.js | 20+ | `node --version` |
| npm | 10+ | `npm --version` |
| Git | 2.30+ | `git --version` |

## Quick Setup

```bash
# Clone the repository
git clone https://github.com/CheckMyData-AI/checkmydata-ai.git
cd checkmydata-ai

# Install everything (Python venv, Node deps, .env, migrations)
make setup

# Start development servers
make dev
```

This gives you:
- Backend API at `http://localhost:8000`
- Frontend at `http://localhost:3100`

## Step-by-Step Setup

### 1. Backend

```bash
cd backend

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate    # macOS/Linux
# .venv\Scripts\activate     # Windows

# Install dependencies (including dev tools)
pip install -e ".[dev]"
```

### 2. Frontend

```bash
cd frontend
npm install
```

### 3. Environment Configuration

```bash
# Copy example env file
cp backend/.env.example backend/.env
```

Edit `backend/.env` and set required values:

```env
# Required: encryption key for stored credentials
# Generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
MASTER_ENCRYPTION_KEY=<your-key>

# Required: at least one LLM provider API key
OPENAI_API_KEY=sk-...
# Or: ANTHROPIC_API_KEY=sk-ant-...
# Or: OPENROUTER_API_KEY=sk-or-...

# Optional: Google OAuth for "Sign in with Google"
GOOGLE_CLIENT_ID=<your-client-id>.apps.googleusercontent.com

# Optional: change JWT secret for production
JWT_SECRET=<random-secret>
```

### 4. Database Migrations

```bash
cd backend
PYTHONPATH=. alembic upgrade head
```

Or use the Makefile:

```bash
make migrate
```

### 5. Start Development Servers

```bash
make dev
```

Or start individually:

```bash
# Backend
cd backend && uvicorn app.main:app --reload --port 8000

# Frontend (separate terminal)
cd frontend && npm run dev -- --port 3100
```

## Docker Setup

```bash
# Start with Docker Compose
docker compose up -d

# Or use the helper script
make docker-up
```

The `docker-compose.yml` runs both backend and frontend containers.

## Full Environment Variable Reference

Copy `backend/.env.example` to `backend/.env`. All available variables:

| Variable | Required | Description |
|----------|----------|-------------|
| `MASTER_ENCRYPTION_KEY` | **Yes** | Fernet key for encrypting stored credentials. Generate: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `JWT_SECRET` | **Yes (prod)** | Secret for signing JWT tokens. Generate: `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `DATABASE_URL` | No | Default: `sqlite+aiosqlite:///./data/agent.db`. For production: `postgresql+asyncpg://...` |
| `OPENAI_API_KEY` | One of three | OpenAI API key (for GPT-4o, etc.) |
| `ANTHROPIC_API_KEY` | One of three | Anthropic API key (for Claude) |
| `OPENROUTER_API_KEY` | One of three | OpenRouter API key (multi-model proxy) |
| `GOOGLE_CLIENT_ID` | No | Google OAuth Client ID from [Google Cloud Console](https://console.cloud.google.com/apis/credentials). Enables "Sign in with Google". |
| `NEXT_PUBLIC_GOOGLE_CLIENT_ID` | No | Same value as above, set in `frontend/.env.local` for the GIS JavaScript SDK. |
| `RESEND_API_KEY` | No | [Resend](https://resend.com) API key for transactional emails (welcome, invite, acceptance). If empty, emails are silently skipped. |
| `RESEND_FROM_EMAIL` | No | Sender address for emails (default: `CheckMyData <noreply@checkmydata.ai>`). Must match a verified domain in Resend. |
| `APP_URL` | No | Frontend URL for email links (default: `http://localhost:3000`). Set to production URL in prod. |
| `CORS_ORIGINS` | No | JSON array of allowed origins |
| `ENVIRONMENT` | No | Set to `production` for strict secret validation |
| `REDIS_URL` | No | Enables shared cache + ARQ task queue. Empty = in-process fallback. |
| `JWT_EXPIRE_MINUTES` | No | Token expiry (default: 1440 = 24h) |
| `CHROMA_SERVER_URL` | No | Remote ChromaDB server URL. If empty, uses embedded PersistentClient. |
| `MAX_HISTORY_TOKENS` | No | Token budget for chat history before summarization (default: 4000) |
| `MAX_CONTEXT_TOKENS` | No | Total context window budget (default: 16000) |
| `LOG_FORMAT` | No | `text` (default) or `json` (for production log aggregation) |
| `LOG_LEVEL` | No | `DEBUG`, `INFO` (default), `WARNING`, `ERROR` |

See `backend/.env.example` for the complete list of optional/advanced settings (ChromaDB, session rotation, orchestrator limits, DB index, pipeline, streaming, backup, token budgets, connection pool).

## Production Deployment

### Heroku (Primary)

The production environment runs on Heroku as two Docker container apps with Heroku Postgres.

**Auto-deploy (CI/CD):** Every push to `main` triggers deployment via GitHub Actions (`.github/workflows/deploy.yml`): CI runs → builds Docker images → pushes to Heroku Container Registry → releases → health checks.

**Manual deploy:** Use `./scripts/deploy-heroku.sh` when CI/CD is unavailable. The script requires `HEROKU_API_KEY` and `GOOGLE_CLIENT_ID` environment variables.

```bash
./scripts/deploy-heroku.sh              # Deploy both
./scripts/deploy-heroku.sh --backend-only
./scripts/deploy-heroku.sh --frontend-only
```

**Setting up a new Heroku deployment:**

```bash
heroku create <your-api-app> --stack container
heroku create <your-web-app> --stack container
heroku addons:create heroku-postgresql:essential-0 --app <your-api-app>

heroku config:set \
  MASTER_ENCRYPTION_KEY="$(python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')" \
  JWT_SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')" \
  DEFAULT_LLM_PROVIDER=openai \
  OPENAI_API_KEY=sk-... \
  CORS_ORIGINS='["https://your-domain.com"]' \
  --app <your-api-app>
```

**Heroku notes:**
- Heroku provides `DATABASE_URL` automatically via the Postgres addon; `config.py` converts `postgres://` to `postgresql+asyncpg://`
- Alembic migrations run automatically on every container startup
- Frontend `NEXT_PUBLIC_*` vars must be passed as `--build-arg` since Next.js bakes them at build time

### Local Docker

```bash
docker compose up --build
```

Both services are containerized with health checks. The backend runs Alembic migrations before starting.

### DigitalOcean App Platform

App spec at `.do/app.yaml`. Set secrets (`MASTER_ENCRYPTION_KEY`, `JWT_SECRET`, API keys) in the DigitalOcean dashboard.

### CI/CD

Two GitHub Actions workflows in `.github/workflows/`:

| Workflow | Trigger | What it does |
|----------|---------|-------------|
| `ci.yml` | Every push/PR to `main` | Backend lint, unit + integration tests, frontend type check + build |
| `deploy.yml` | After CI passes on `main` | Builds Docker images, pushes to Heroku, releases, health check |

## Backup and Restore

The system includes automated daily backups (configurable via `BACKUP_ENABLED`, `BACKUP_HOUR`, `BACKUP_RETENTION_DAYS`, `BACKUP_DIR`). Backup APIs: `POST /api/backup/trigger`, `GET /api/backup/list`, `GET /api/backup/history`.

**Manual backup:**

```bash
# SQLite (development)
cp backend/data/agent.db backend/data/agent.db.bak

# PostgreSQL (production)
pg_dump -Fc "$DATABASE_URL" > backup_$(date +%Y%m%d_%H%M%S).dump
```

**Restore:**

```bash
# SQLite
cp backend/data/agent.db.bak backend/data/agent.db

# PostgreSQL
pg_restore --clean --if-exists -d "$DATABASE_URL" backup.dump
```

**Alembic migrations:**

```bash
cd backend && alembic upgrade head      # Apply all pending
cd backend && alembic current           # Check current state
cd backend && alembic downgrade -1      # Rollback last
```

**ChromaDB:** Data stored in `backend/data/chroma/`. To reset: `rm -rf backend/data/chroma/` and restart.

## Troubleshooting

See [FAQ.md](FAQ.md) for common setup issues and solutions.
