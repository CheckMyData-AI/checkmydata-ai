.PHONY: setup setup-backend setup-frontend setup-env migrate \
       dev dev-backend dev-frontend stop logs \
       test test-integration test-all test-frontend lint check \
       docker-up docker-down docker-clean docker-logs \
       clean

BACKEND_DIR  = backend
FRONTEND_DIR = frontend
LOGS_DIR     = logs
PIDS_DIR     = .pids
VENV         = $(BACKEND_DIR)/.venv/bin

# ── Setup ────────────────────────────────────────────────────────

setup: setup-backend setup-frontend setup-env migrate
	@echo "Setup complete. Run 'make dev' to start."

setup-backend:
	@echo "Setting up backend..."
	cd $(BACKEND_DIR) && python3 -m venv .venv
	$(VENV)/pip install --upgrade pip
	$(VENV)/pip install -e ".[dev]"

setup-frontend:
	@echo "Setting up frontend..."
	cd $(FRONTEND_DIR) && npm install

setup-env:
	@if [ ! -f $(BACKEND_DIR)/.env ]; then \
		cp $(BACKEND_DIR)/.env.example $(BACKEND_DIR)/.env; \
		echo "Created $(BACKEND_DIR)/.env from .env.example"; \
	fi
	@if grep -q "^MASTER_ENCRYPTION_KEY=$$" $(BACKEND_DIR)/.env 2>/dev/null; then \
		KEY=$$($(VENV)/python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"); \
		sed -i '' "s/^MASTER_ENCRYPTION_KEY=$$/MASTER_ENCRYPTION_KEY=$$KEY/" $(BACKEND_DIR)/.env; \
		echo "Generated MASTER_ENCRYPTION_KEY"; \
	fi

migrate:
	@echo "Running Alembic migrations..."
	cd $(BACKEND_DIR) && PYTHONPATH=. $(VENV)/alembic upgrade head

# ── Local Development ────────────────────────────────────────────

dev: stop
	@mkdir -p $(LOGS_DIR) $(PIDS_DIR)
	@echo "Starting backend on http://localhost:8000 ..."
	@cd $(BACKEND_DIR) && $(VENV)/uvicorn app.main:app --reload --port 8000 \
		> ../$(LOGS_DIR)/backend.log 2>&1 & echo $$! > ../$(PIDS_DIR)/backend.pid
	@echo "Starting frontend on http://localhost:3100 ..."
	@cd $(FRONTEND_DIR) && npm run dev -- --port 3100 \
		> ../$(LOGS_DIR)/frontend.log 2>&1 & echo $$! > ../$(PIDS_DIR)/frontend.pid
	@sleep 1
	@echo "──────────────────────────────────"
	@echo "  Backend:  http://localhost:8000"
	@echo "  Frontend: http://localhost:3100"
	@echo "──────────────────────────────────"
	@echo "Run 'make logs' to tail output, 'make stop' to shut down."

dev-backend: stop
	@mkdir -p $(LOGS_DIR) $(PIDS_DIR)
	@echo "Starting backend on http://localhost:8000 ..."
	@cd $(BACKEND_DIR) && $(VENV)/uvicorn app.main:app --reload --port 8000 \
		> ../$(LOGS_DIR)/backend.log 2>&1 & echo $$! > ../$(PIDS_DIR)/backend.pid
	@echo "Run 'make logs' to tail output, 'make stop' to shut down."

dev-frontend: stop
	@mkdir -p $(LOGS_DIR) $(PIDS_DIR)
	@echo "Starting frontend on http://localhost:3100 ..."
	@cd $(FRONTEND_DIR) && npm run dev -- --port 3100 \
		> ../$(LOGS_DIR)/frontend.log 2>&1 & echo $$! > ../$(PIDS_DIR)/frontend.pid
	@echo "Run 'make logs' to tail output, 'make stop' to shut down."

stop:
	@if [ -f $(PIDS_DIR)/backend.pid ]; then \
		kill $$(cat $(PIDS_DIR)/backend.pid) 2>/dev/null || true; \
		rm -f $(PIDS_DIR)/backend.pid; \
		echo "Backend stopped."; \
	fi
	@if [ -f $(PIDS_DIR)/frontend.pid ]; then \
		kill $$(cat $(PIDS_DIR)/frontend.pid) 2>/dev/null || true; \
		rm -f $(PIDS_DIR)/frontend.pid; \
		echo "Frontend stopped."; \
	fi

logs:
	@tail -f $(LOGS_DIR)/*.log

# ── Testing & Quality ────────────────────────────────────────────

test:
	cd $(BACKEND_DIR) && $(VENV)/python -m pytest tests/unit/ -v

test-integration:
	cd $(BACKEND_DIR) && $(VENV)/python -m pytest tests/integration/ -v

test-all:
	cd $(BACKEND_DIR) && $(VENV)/python -m pytest tests/ -v

test-frontend:
	cd $(FRONTEND_DIR) && npm test

lint:
	cd $(BACKEND_DIR) && $(VENV)/ruff check app/ tests/

check: lint test-all

# ── M1-M6 rollout helpers (see docs/ROLLOUT_M1_M6.md) ────────────
# Reads ADMIN_TOKEN + HEROKU_APP from env (or defaults to production).
# Use `make rollout-check` after flipping any flag to verify the dyno
# is healthy and the new code path is firing.

HEROKU_APP    ?= checkmydata-api
PROD_BASE_URL ?= https://checkmydata-api-990b0bcf28ab.herokuapp.com

rollout-check:
	@echo "=== Heroku flag state ($(HEROKU_APP)) ==="
	@heroku config -a $(HEROKU_APP) | \
		grep -E "CODE_GRAPH_ENABLED|HYBRID_RETRIEVAL_ENABLED|SCHEMA_RETRIEVAL_ENABLED|LINEAGE_ENABLED|CLUSTERING_ENABLED|CLUSTER_LLM_LABEL_ENABLED" \
		|| echo "(no M1-M6 flags set; all default to false)"
	@echo
	@echo "=== Dyno state ==="
	@heroku ps -a $(HEROKU_APP)
	@echo
	@echo "=== Health endpoint ==="
	@curl -fsS $(PROD_BASE_URL)/api/health || echo "FAILED"
	@echo
	@if [ -n "$$ADMIN_TOKEN" ]; then \
		echo "=== Code-graph counters (admin JSON metrics) ==="; \
		curl -fsSH "Authorization: Bearer $$ADMIN_TOKEN" $(PROD_BASE_URL)/api/metrics \
			| python -c "import json,sys; d=json.load(sys.stdin); print(json.dumps(d.get('code_graph',{}), indent=2))" \
			|| echo "metrics fetch failed (token expired?)"; \
	else \
		echo "(set ADMIN_TOKEN=... to fetch live code_graph metrics)"; \
	fi

# ── Docker (OrbStack / Docker Desktop) ────────────────────────────

docker-up:
	@bash scripts/dev-up.sh

docker-down:
	@bash scripts/dev-down.sh

docker-clean:
	@bash scripts/dev-down.sh --volumes

docker-logs:
	docker compose logs -f

# ── Cleanup ──────────────────────────────────────────────────────

clean: stop
	rm -rf $(LOGS_DIR) $(PIDS_DIR)
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf $(FRONTEND_DIR)/.next
	@echo "Cleaned."
