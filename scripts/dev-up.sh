#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m'

info()  { echo -e "${GREEN}[+]${NC} $*"; }
warn()  { echo -e "${YELLOW}[!]${NC} $*"; }
error() { echo -e "${RED}[x]${NC} $*"; }

# ── Preflight checks ────────────────────────────────────────────

if ! command -v docker &>/dev/null; then
    error "docker CLI not found. Install OrbStack (https://orbstack.dev) or Docker Desktop."
    exit 1
fi

if ! docker info &>/dev/null 2>&1; then
    error "Docker daemon is not running. Start OrbStack or Docker Desktop first."
    exit 1
fi

if [ ! -f backend/.env ]; then
    if [ -f backend/.env.example ]; then
        warn "backend/.env not found — copying from backend/.env.example"
        cp backend/.env.example backend/.env
        warn "Edit backend/.env to set MASTER_ENCRYPTION_KEY, JWT_SECRET, and at least one LLM API key."
    else
        error "backend/.env not found and no .env.example available."
        exit 1
    fi
fi

# ── Build & start ────────────────────────────────────────────────

info "Building and starting containers..."
docker compose up --build -d

# ── Wait for backend health ──────────────────────────────────────

BACKEND_URL="http://localhost:8000/api/health"
TIMEOUT=90
ELAPSED=0

info "Waiting for backend to become healthy..."
while [ $ELAPSED -lt $TIMEOUT ]; do
    if curl -sf "$BACKEND_URL" >/dev/null 2>&1; then
        info "Backend is healthy."
        break
    fi
    sleep 2
    ELAPSED=$((ELAPSED + 2))
    printf "."
done
echo

if [ $ELAPSED -ge $TIMEOUT ]; then
    warn "Backend did not become healthy within ${TIMEOUT}s. Check logs: docker compose logs backend"
fi

# ── Wait for frontend health ─────────────────────────────────────

FRONTEND_URL="http://localhost:3000"
ELAPSED=0

info "Waiting for frontend to become healthy..."
while [ $ELAPSED -lt $TIMEOUT ]; do
    if curl -sf "$FRONTEND_URL" >/dev/null 2>&1; then
        info "Frontend is healthy."
        break
    fi
    sleep 2
    ELAPSED=$((ELAPSED + 2))
    printf "."
done
echo

if [ $ELAPSED -ge $TIMEOUT ]; then
    warn "Frontend did not become healthy within ${TIMEOUT}s. Check logs: docker compose logs frontend"
fi

# ── Summary ──────────────────────────────────────────────────────

echo ""
echo -e "${BOLD}──────────────────────────────────${NC}"
echo -e "  Backend:  ${GREEN}http://localhost:8000${NC}"
echo -e "  Frontend: ${GREEN}http://localhost:3000${NC}"
echo -e "${BOLD}──────────────────────────────────${NC}"
echo ""
info "Tail logs with: docker compose logs -f"
info "Stop with:      ./scripts/dev-down.sh  (or make docker-down)"
