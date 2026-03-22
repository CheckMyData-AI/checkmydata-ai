# Frequently Asked Questions

## Setup Issues

### `make setup` fails with "python3: command not found"

Ensure Python 3.12+ is installed and available as `python3`. On some systems
you may need to install it via your package manager:

```bash
# macOS
brew install python@3.12

# Ubuntu/Debian
sudo apt install python3.12 python3.12-venv
```

### `MASTER_ENCRYPTION_KEY` is empty

Generate one manually:

```bash
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Add the output to `backend/.env` as `MASTER_ENCRYPTION_KEY=<value>`.

### Frontend shows "Failed to fetch" errors

The backend must be running. Check:

1. Is the backend running? (`make dev` or `cd backend && uvicorn app.main:app --port 8000`)
2. Is the frontend pointing to the right API URL? Check `NEXT_PUBLIC_API_URL`
   in `frontend/.env.local` (default: `http://localhost:8000/api`)

### Database migration errors

```bash
cd backend
PYTHONPATH=. alembic upgrade head
```

If migrations are corrupt, for development you can reset:

```bash
rm -f data/agent.db
PYTHONPATH=. alembic upgrade head
```

### Google Sign-In not working

1. Set `GOOGLE_CLIENT_ID` in `backend/.env`
2. Set `NEXT_PUBLIC_GOOGLE_CLIENT_ID` in `frontend/.env.local`
3. Add `http://localhost:3100` to authorized JavaScript origins in
   [Google Cloud Console](https://console.cloud.google.com/apis/credentials)

## Usage Questions

### Which databases are supported?

- PostgreSQL
- MySQL
- ClickHouse
- MongoDB (limited SQL — uses aggregation pipelines)

### Can I use SSH tunnels?

Yes. When creating a connection, enable "Use SSH Tunnel" and provide:
- SSH host, port, username
- SSH key (upload via SSH Key Manager in settings)

### How do I change the LLM provider?

Set in `backend/.env`:

```env
DEFAULT_LLM_PROVIDER=openai     # or: anthropic, openrouter
OPENAI_API_KEY=sk-...
# ANTHROPIC_API_KEY=sk-ant-...
# OPENROUTER_API_KEY=sk-or-...
```

Per-project LLM overrides are available in project settings.

### Are my database credentials safe?

Yes. All database credentials are encrypted at rest using Fernet symmetric
encryption (`MASTER_ENCRYPTION_KEY`). The key is never stored in the database.

### How do I export query results?

Click the export button on any query result. Supported formats:
- CSV
- JSON

Batch queries can also be exported as a combined file.

## Contributing Questions

### How do I run tests?

```bash
make test           # Backend unit tests
make test-frontend  # Frontend tests
make test-all       # All backend tests
make check          # Lint + all tests
```

### How do I add a new API endpoint?

1. Create or edit a route file in `backend/app/api/routes/`
2. Register it in `backend/app/api/routes/__init__.py`
3. Add rate limiting with `@limiter.limit()`
4. Add input validation with Pydantic models
5. Add tests in `backend/tests/unit/`
6. Update `API.md` if it's a public endpoint

### How do I add a new frontend component?

1. Create the component in the appropriate `frontend/src/components/` directory
2. Use `"use client"` directive if it has interactivity
3. Follow the existing patterns for state management (Zustand) and styling (Tailwind)
4. Add a test file alongside the component (e.g., `MyComponent.test.tsx`)

### CI is failing on my PR — what do I check?

1. **Backend lint**: `cd backend && ruff check app/ tests/`
2. **Backend format**: `cd backend && ruff format --check app/ tests/`
3. **Backend types**: `cd backend && mypy app/ --ignore-missing-imports`
4. **Backend tests**: `cd backend && pytest tests/ -x`
5. **Frontend types**: `cd frontend && npx tsc --noEmit`
6. **Frontend lint**: `cd frontend && npx eslint . --max-warnings=0`
7. **Frontend tests**: `cd frontend && npm test`
8. **Frontend build**: `cd frontend && npm run build`
