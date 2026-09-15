#!/bin/sh
# Start the local demo: platform (compose.local.yml) + insurance-direct + retail-collector.
# Fresh-clone safe: bootstraps missing .env files from .env.example and
# exports the platform tokens so both examples always agree with the gateway.
# Usage: ./examples/scripts/up.sh [--build] [--no-build]
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
PLATFORM="$ROOT/compose.local.yml"
INS_DIR="$ROOT/examples/insurance-direct"
RETAIL_DIR="$ROOT/examples/retail-collector"

BUILD="--build"
for arg in "$@"; do
  case "$arg" in
    --no-build) BUILD="" ;;
    --build) BUILD="--build" ;;
    -h|--help)
      echo "Usage: ./examples/scripts/up.sh [--build|--no-build]"
      exit 0 ;;
    *) echo "Unknown flag: $arg (try --help)" >&2; exit 1 ;;
  esac
done

copy_if_missing() {
  if [ ! -f "$2" ]; then
    if [ -f "$1" ]; then
      cp "$1" "$2"
      echo "created $2 from example (edit it for real secrets)"
    else
      echo "WARNING: neither $2 nor $1 exists, continuing with compose defaults" >&2
    fi
  fi
}

# 1. Bootstrap .env files (all gitignored, only *.example is committed).
copy_if_missing "$ROOT/.env.example" "$ROOT/.env"
copy_if_missing "$INS_DIR/.env.example" "$INS_DIR/.env"
copy_if_missing "$RETAIL_DIR/.env.example" "$RETAIL_DIR/.env"

# 2. Single source of truth: tokens come from the PLATFORM .env.
#    Exported shell vars win over each example's own .env during
#    `docker compose` interpolation, so gateway and clients cannot drift.
get_env_value() {
  key="$2"
  val="$(grep -E "^[[:space:]]*(export[[:space:]]+)?$key=" "$1" 2>/dev/null | sed -n '$p' | sed -E "s/^[[:space:]]*(export[[:space:]]+)?$key=//" | tr -d '\r' | sed -E "s/^[\"']//; s/[\"'][[:space:]]*(#.*)?$//; s/[[:space:]]*(#.*)?$//")"
  printf '%s' "$val"
}
UBIX_OTEL_TOKEN="$(get_env_value "$ROOT/.env" UBIX_OTEL_TOKEN)"
DIGIFLOW_OTEL_TOKEN="$(get_env_value "$ROOT/.env" DIGIFLOW_OTEL_TOKEN)"
if [ -z "${UBIX_OTEL_TOKEN:-}" ] || [ -z "${DIGIFLOW_OTEL_TOKEN:-}" ]; then
  echo "ERROR: UBIX_OTEL_TOKEN / DIGIFLOW_OTEL_TOKEN missing in $ROOT/.env" >&2
  echo "Copy .env.example to .env and set both tokens." >&2
  exit 1
fi
export UBIX_OTEL_TOKEN DIGIFLOW_OTEL_TOKEN
# compose.local.yml also needs the Grafana/Keycloak secret (fail closed).
KEYCLOAK_GRAFANA_CLIENT_SECRET="$(get_env_value "$ROOT/.env" KEYCLOAK_GRAFANA_CLIENT_SECRET)"
if [ -z "${KEYCLOAK_GRAFANA_CLIENT_SECRET:-}" ]; then
  echo "ERROR: KEYCLOAK_GRAFANA_CLIENT_SECRET missing in $ROOT/.env" >&2
  exit 1
fi
export KEYCLOAK_GRAFANA_CLIENT_SECRET

if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: docker not found in PATH." >&2
  exit 1
fi

# 3. Start in dependency order: platform first, examples second.
echo "== platform (compose.local.yml) =="
docker compose -f "$PLATFORM" up -d $BUILD
echo "== insurance-direct (ubix, direct OTLP) =="
docker compose -f "$INS_DIR/docker-compose.yml" up -d $BUILD
echo "== retail-collector (digiflow, local collector) =="
docker compose -f "$RETAIL_DIR/docker-compose.yml" up -d $BUILD

# 4. Wait for the public surface (gateway has no healthcheck probe,
#    so poll TCP from the host instead).
wait_tcp() {
  host="$1"; port="$2"; tries="${3:-30}"
  i=1
  while [ "$i" -le "$tries" ]; do
    if python3 -c "import socket; s=socket.create_connection(('$host', $port), timeout=2); s.close()" 2>/dev/null; then
      return 0
    fi
    sleep 2
    i=$((i + 1))
  done
  return 1
}
if command -v python3 >/dev/null 2>&1; then
  for p in 4318 3000 8083 8082 8084; do
    if wait_tcp 127.0.0.1 "$p" 30; then
      echo "ok 127.0.0.1:$p"
    else
      echo "WARNING: 127.0.0.1:$p not reachable yet (see docker compose ps/logs)" >&2
    fi
  done
else
  echo "(python3 not found: skipping TCP wait, giving services 15s to settle)"
  sleep 15
fi

cat <<'EOF'

All stacks started:
  Gateway       http://localhost:4318/healthz (OTLP/HTTP + Bearer)
  Grafana       http://localhost:3000 (admin/admin local demo)
  Insurance API http://localhost:8083  (container :8080, direct -> ubix)
  Risk svc      http://localhost:8082
  Retail API    http://localhost:8084  (container :8080, via retail-collector -> digiflow)

Useful:
  ./examples/scripts/down.sh                 # stop everything
  ./examples/scripts/load-k6.sh --duration-min 1 --vus 2   # smoke traffic
  docker compose -f compose.local.yml logs -f otel-gateway
EOF
