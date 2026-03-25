web: cd backend && alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
worker: cd backend && arq app.worker.WorkerSettings
