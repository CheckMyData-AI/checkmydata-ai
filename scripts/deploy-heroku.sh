#!/usr/bin/env bash
set -euo pipefail

# ── Configuration ──────────────────────────────────────────────────
BACKEND_APP="checkmydata-api"
FRONTEND_APP="checkmydata-web"
BACKEND_API_URL="https://api.checkmydata.ai/api"
BACKEND_WS_URL="wss://api.checkmydata.ai/api/chat/ws"
FRONTEND_URL="https://checkmydata.ai"
GOOGLE_CLIENT_ID="687379670843-rlce3csi6d8hbmd8iks863b7cmolid9o.apps.googleusercontent.com"

DEPLOY_BACKEND=true
DEPLOY_FRONTEND=true

usage() {
  echo "Usage: $0 [--backend-only | --frontend-only | --all]"
  echo ""
  echo "  --backend-only   Deploy only the backend"
  echo "  --frontend-only  Deploy only the frontend"
  echo "  --all            Deploy both (default)"
  exit 0
}

for arg in "$@"; do
  case "$arg" in
    --backend-only)  DEPLOY_FRONTEND=false ;;
    --frontend-only) DEPLOY_BACKEND=false ;;
    --all)           ;;
    --help|-h)       usage ;;
    *) echo "Unknown option: $arg"; usage ;;
  esac
done

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

# ── Preflight checks ──────────────────────────────────────────────
echo "══════════════════════════════════════════════════════════"
echo "  CheckMyData.ai — Manual Heroku Deploy"
echo "══════════════════════════════════════════════════════════"

command -v docker >/dev/null 2>&1 || { echo "✗ docker not found"; exit 1; }
command -v heroku >/dev/null 2>&1 || { echo "✗ heroku CLI not found"; exit 1; }
command -v curl   >/dev/null 2>&1 || { echo "✗ curl not found"; exit 1; }

echo "  Backend app:  $BACKEND_APP (deploy=$DEPLOY_BACKEND)"
echo "  Frontend app: $FRONTEND_APP (deploy=$DEPLOY_FRONTEND)"
echo "  Commit:       $(git rev-parse --short HEAD) — $(git log -1 --format='%s')"
echo "══════════════════════════════════════════════════════════"

# Resolve Heroku API key: env var → heroku CLI token
if [ -z "${HEROKU_API_KEY:-}" ]; then
  HEROKU_API_KEY="$(heroku auth:token 2>/dev/null | grep -v '›')"
fi

if [ -z "$HEROKU_API_KEY" ]; then
  echo "✗ No HEROKU_API_KEY and 'heroku auth:token' failed. Run 'heroku login' first."
  exit 1
fi
export HEROKU_API_KEY

# ── Docker login ──────────────────────────────────────────────────
echo ""
echo "→ Logging in to Heroku Container Registry …"
echo "$HEROKU_API_KEY" | docker login -u _ --password-stdin registry.heroku.com
echo ""

heroku_release() {
  local app="$1"
  local image_tag="registry.heroku.com/${app}/web"

  local image_id
  image_id="$(docker inspect --format='{{.Id}}' "$image_tag")"

  echo "→ Releasing $app (image ${image_id:0:19})…"
  curl -sf -X PATCH "https://api.heroku.com/apps/${app}/formation" \
    -H "Content-Type: application/json" \
    -H "Accept: application/vnd.heroku+json; version=3.docker-releases" \
    -H "Authorization: Bearer ${HEROKU_API_KEY}" \
    -d "{\"updates\":[{\"type\":\"web\",\"docker_image\":\"${image_id}\"}]}" \
    | python3 -m json.tool 2>/dev/null || true
  echo ""
}

health_check() {
  local label="$1"
  local url="$2"
  local max_attempts="${3:-5}"
  local sleep_sec="${4:-30}"

  echo "→ Health-checking $label at $url …"
  for i in $(seq 1 "$max_attempts"); do
    sleep "$sleep_sec"
    local status
    status="$(curl -s -o /dev/null -w '%{http_code}' "$url")" || true
    if [ "$status" = "200" ]; then
      echo "  ✓ $label is healthy (HTTP 200) on attempt $i"
      return 0
    fi
    echo "  attempt $i/$max_attempts: HTTP $status"
  done
  echo "  ✗ $label health check failed after $max_attempts attempts"
  return 1
}

# ── Backend ───────────────────────────────────────────────────────
if [ "$DEPLOY_BACKEND" = true ]; then
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "  BACKEND"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "→ Building backend image …"
  docker build \
    --platform linux/amd64 \
    -t "registry.heroku.com/${BACKEND_APP}/web" \
    -f Dockerfile.backend .

  echo "→ Pushing backend image …"
  docker push "registry.heroku.com/${BACKEND_APP}/web"

  heroku_release "$BACKEND_APP"
fi

# ── Frontend ──────────────────────────────────────────────────────
if [ "$DEPLOY_FRONTEND" = true ]; then
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "  FRONTEND"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "→ Building frontend image …"
  docker build \
    --platform linux/amd64 \
    --build-arg "NEXT_PUBLIC_API_URL=${BACKEND_API_URL}" \
    --build-arg "NEXT_PUBLIC_WS_URL=${BACKEND_WS_URL}" \
    --build-arg "NEXT_PUBLIC_GOOGLE_CLIENT_ID=${GOOGLE_CLIENT_ID}" \
    -t "registry.heroku.com/${FRONTEND_APP}/web" \
    -f Dockerfile.frontend .

  echo "→ Pushing frontend image …"
  docker push "registry.heroku.com/${FRONTEND_APP}/web"

  heroku_release "$FRONTEND_APP"
fi

# ── Health checks ─────────────────────────────────────────────────
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  HEALTH CHECKS"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

FAILED=0

if [ "$DEPLOY_BACKEND" = true ]; then
  health_check "Backend" "${BACKEND_API_URL}/health" 5 30 || FAILED=1
fi

if [ "$DEPLOY_FRONTEND" = true ]; then
  health_check "Frontend" "$FRONTEND_URL" 3 15 || FAILED=1
fi

echo ""
if [ "$FAILED" -eq 0 ]; then
  echo "══════════════════════════════════════════════════════════"
  echo "  ✓ Deploy complete — all services healthy"
  echo "══════════════════════════════════════════════════════════"
else
  echo "══════════════════════════════════════════════════════════"
  echo "  ⚠ Deploy finished but some health checks failed"
  echo "══════════════════════════════════════════════════════════"
  exit 1
fi
