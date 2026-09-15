#!/bin/sh
# Generate sustained realistic traffic with k6 (grafana/k6 in Docker, no local install).
# Targets the examples only: insurance-direct (:8083 -> ubix) + retail-collector (:8084 -> digiflow).
# Usage: ./examples/scripts/load-k6.sh [--duration-min 5] [--vus 10] [--chaos off|latency|rejects]
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
PLATFORM_COMPOSE="$ROOT/compose.local.yml"
INS_COMPOSE="$ROOT/examples/insurance-direct/docker-compose.yml"
RETAIL_COMPOSE="$ROOT/examples/retail-collector/docker-compose.yml"
LOAD_DIR="$ROOT/examples/load"

DURATION_MIN=5
VUS=10
CHAOS="off"

for arg in "$@"; do
  case "$arg" in
    -h|--help)
      cat <<'EOF'
Usage: ./examples/scripts/load-k6.sh [--duration-min 5] [--vus 10] [--chaos off|latency|rejects]

  --duration-min  steady-load minutes (default 5; ramp adds +2m, or +1m when <= 2)
  --vus           virtual users per scenario (default 10; insurance + retail run together)
  --chaos         off | latency | rejects (default off)
                  latency: CHAOS_LATENCY_MS=2500 on risk-service (trips 2s timeout)
                           + CHAOS_LATENCY_MS=2500 on retail-api (processing delay)
                  rejects: CHAOS_REJECT_RATE=0.3 on risk-service (reject storm)
                           + CHAOS_FAIL_RATE=0.3 on retail-api (500 storm)

Examples:
  ./examples/scripts/load-k6.sh --duration-min 1 --vus 2
  ./examples/scripts/load-k6.sh --duration-min 5 --vus 10 --chaos latency

Notes:
  k6 runs in Docker (grafana/k6) on the default bridge network via
  http://host.docker.internal:8083|:8084 (Docker Desktop resolves it;
  native-Linux Engine may need extra_hosts).
  Start everything first: ./examples/scripts/up.sh
EOF
      exit 0 ;;
  esac
done

while [ "$#" -gt 0 ]; do
  case "$1" in
    --duration-min) DURATION_MIN="${2:?missing value}"; shift 2 ;;
    --vus) VUS="${2:?missing value}"; shift 2 ;;
    --chaos) CHAOS="${2:?missing value}"; shift 2 ;;
    *) echo "Unknown flag: $1 (try --help)" >&2; exit 1 ;;
  esac
done

case "$CHAOS" in
  off|latency|rejects) ;;
  *) echo "ERROR: --chaos must be off|latency|rejects (got '$CHAOS')" >&2; exit 1 ;;
esac
if [ "$DURATION_MIN" -lt 1 ]; then echo "ERROR: --duration-min must be >= 1" >&2; exit 1; fi
if [ "$VUS" -lt 1 ]; then echo "ERROR: --vus must be >= 1" >&2; exit 1; fi

# Ramp scales down for short runs so `--duration-min 1` stays a quick smoke test.
RAMP_MIN=2
if [ "$DURATION_MIN" -le 2 ]; then RAMP_MIN=1; fi

if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: docker not found in PATH." >&2
  exit 1
fi
if [ ! -f "$LOAD_DIR/examples-load.js" ]; then
  echo "ERROR: examples/load/examples-load.js not found. Run from the repo root." >&2
  exit 1
fi

# Single source of truth (mirrors up.sh): chaos `compose up -d` recreates
# risk-service and retail-api, so the platform tokens must be exported or
# compose falls back to dir-.env placeholders and the gateway rejects telemetry.
get_env_value() {
  key="$2"
  val="$(grep -E "^[[:space:]]*(export[[:space:]]+)?$key=" "$1" 2>/dev/null | sed -n '$p' | sed -E "s/^[[:space:]]*(export[[:space:]]+)?$key=//" | tr -d '\r' | sed -E "s/^[\"']//; s/[\"'][[:space:]]*(#.*)?$//; s/[[:space:]]*(#.*)?$//")"
  printf '%s' "$val"
}
UBIX_OTEL_TOKEN="$(get_env_value "$ROOT/.env" UBIX_OTEL_TOKEN)"
DIGIFLOW_OTEL_TOKEN="$(get_env_value "$ROOT/.env" DIGIFLOW_OTEL_TOKEN)"
if [ -z "${UBIX_OTEL_TOKEN:-}" ] || [ -z "${DIGIFLOW_OTEL_TOKEN:-}" ]; then
  echo "ERROR: UBIX_OTEL_TOKEN / DIGIFLOW_OTEL_TOKEN missing in $ROOT/.env" >&2
  exit 1
fi
export UBIX_OTEL_TOKEN DIGIFLOW_OTEL_TOKEN

wait_tcp() {
  host="$1"; port="$2"; tries="${3:-5}"
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

set_chaos() {
  # $1 = latency ms, $2 = reject rate. No rebuild needed: risk-service reads
  # CHAOS_LATENCY_MS / CHAOS_REJECT_RATE on restart; retail-api reads
  # CHAOS_LATENCY_MS / CHAOS_FAIL_RATE (different reject var name — mapped here).
  echo "== chaos CHAOS_LATENCY_MS=$1 CHAOS_REJECT/FAIL_RATE=$2 =="
  CHAOS_LATENCY_MS="$1" CHAOS_REJECT_RATE="$2" docker compose -f "$INS_COMPOSE" up -d risk-service
  CHAOS_LATENCY_MS="$1" CHAOS_FAIL_RATE="$2" docker compose -f "$RETAIL_COMPOSE" up -d retail-api
}

echo "== insurance (direct -> ubix) =="
if wait_tcp 127.0.0.1 8083 5; then
  echo "ok 127.0.0.1:8083 (insurance-api)"
else
  echo "WARNING: 127.0.0.1:8083 not reachable — start the stack first: ./examples/scripts/up.sh" >&2
fi
echo "== retail (collector -> digiflow) =="
if wait_tcp 127.0.0.1 8084 5; then
  echo "ok 127.0.0.1:8084 (retail-api)"
else
  echo "WARNING: 127.0.0.1:8084 not reachable — start the stack first: ./examples/scripts/up.sh" >&2
fi
echo "== pipeline =="
if docker compose -f "$PLATFORM_COMPOSE" ps --status running otel-gateway otel-collector >/dev/null 2>&1; then
  echo "ok platform gateway + collector are running (OTLP/HTTP :4318)"
else
  echo "WARNING: platform services are not all running (see docker compose logs)" >&2
fi

# Chaos set-up (restored to 0/0 below, even when k6 fails).
if [ "$CHAOS" = "latency" ]; then set_chaos "2500" "0"; fi
if [ "$CHAOS" = "rejects" ]; then set_chaos "0" "0.3"; fi

echo "== k6 (insurance + retail, vus=$VUS steady=${DURATION_MIN}m ramp=${RAMP_MIN}m chaos=$CHAOS) =="
if docker run --rm -i \
  --network bridge \
  -e "INSURANCE_URL=http://host.docker.internal:8083" \
  -e "RETAIL_URL=http://host.docker.internal:8084" \
  -e "VUS=$VUS" \
  -e "RAMP_MIN=$RAMP_MIN" \
  -e "STEADY_MIN=$DURATION_MIN" \
  -e "CHAOS_MODE=$CHAOS" \
  -v "$LOAD_DIR:/scripts:ro" \
  grafana/k6 run /scripts/examples-load.js; then
  K6_EXIT=0
else
  K6_EXIT=$?
fi

if [ "$CHAOS" != "off" ]; then
  echo "== chaos restore (0/0) =="
  set_chaos "0" "0"
fi

echo ""
echo "Endpoints: Insurance API http://localhost:8083, Retail API http://localhost:8084,"
echo "  Gateway http://localhost:4318/healthz, Grafana http://localhost:3000."
exit "$K6_EXIT"
