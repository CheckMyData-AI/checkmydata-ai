#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info() { echo -e "${GREEN}[+]${NC} $*"; }
warn() { echo -e "${YELLOW}[!]${NC} $*"; }

EXTRA_ARGS=()

for arg in "$@"; do
    case "$arg" in
        --volumes|-v)
            EXTRA_ARGS+=("--volumes")
            warn "Will remove volumes (backend-data: SQLite DB, repos, ChromaDB)."
            ;;
        *)
            EXTRA_ARGS+=("$arg")
            ;;
    esac
done

info "Stopping containers..."
docker compose down "${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"}"
info "Done."
