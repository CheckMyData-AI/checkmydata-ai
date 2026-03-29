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

## Production Deployment

### Environment Variables (Production)

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | Yes | PostgreSQL connection string |
| `MASTER_ENCRYPTION_KEY` | Yes | Fernet encryption key |
| `JWT_SECRET` | Yes | Secure random string |
| `OPENAI_API_KEY` | Conditional | Required if using OpenAI |
| `ANTHROPIC_API_KEY` | Conditional | Required if using Anthropic |
| `OPENROUTER_API_KEY` | Conditional | Required if using OpenRouter |
| `GOOGLE_CLIENT_ID` | No | For Google OAuth |
| `CORS_ORIGINS` | No | Comma-separated allowed origins |
| `ENVIRONMENT` | No | Set to `production` for strict validation |

### Heroku

The project includes `Procfile`, `heroku.yml`, and Dockerfiles for Heroku
Container Registry deployment. CI automatically deploys to Heroku when the
`main` branch passes all checks.

## Troubleshooting

See [FAQ.md](FAQ.md) for common setup issues and solutions.
