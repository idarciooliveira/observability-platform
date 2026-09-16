#!/bin/sh
# Stop the local demo (reverse order of up.sh).
# Usage: ./examples/scripts/down.sh [--volumes|-v]   # -v also removes named volumes
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
PLATFORM="$ROOT/compose.local.yml"
INS_DIR="$ROOT/examples/insurance-direct"
RETAIL_DIR="$ROOT/examples/retail-collector"

DOWN_FLAGS=""
for arg in "$@"; do
  case "$arg" in
    -v|--volumes) DOWN_FLAGS="-v" ;;
    -h|--help)
      echo "Usage: ./examples/scripts/down.sh [--volumes|-v]"
      exit 0 ;;
    *) echo "Unknown flag: $arg (try --help)" >&2; exit 1 ;;
  esac
done

# down only needs interpolation to succeed, not real secrets:
# export platform tokens if present, else placeholder so :? fail-closed vars resolve.
get_env_value() {
  key="$2"
  val="$(grep -E "^[[:space:]]*(export[[:space:]]+)?$key=" "$1" 2>/dev/null | sed -n '$p' | sed -E "s/^[[:space:]]*(export[[:space:]]+)?$key=//" | tr -d '\r' | sed -E "s/^[\"']//; s/[\"'][[:space:]]*(#.*)?$//; s/[[:space:]]*(#.*)?$//")"
  printf '%s' "$val"
}
KEVE_UBIX_OTEL_TOKEN="$(get_env_value "$ROOT/.env" KEVE_UBIX_OTEL_TOKEN)"
KEVE_DIGIFLOW_OTEL_TOKEN="$(get_env_value "$ROOT/.env" KEVE_DIGIFLOW_OTEL_TOKEN)"
BCI_UBIX_OTEL_TOKEN="$(get_env_value "$ROOT/.env" BCI_UBIX_OTEL_TOKEN)"
BCI_DIGIFLOW_OTEL_TOKEN="$(get_env_value "$ROOT/.env" BCI_DIGIFLOW_OTEL_TOKEN)"
KEYCLOAK_GRAFANA_CLIENT_SECRET="$(get_env_value "$ROOT/.env" KEYCLOAK_GRAFANA_CLIENT_SECRET)"
[ -z "${KEVE_UBIX_OTEL_TOKEN:-}" ] && KEVE_UBIX_OTEL_TOKEN="placeholder-for-down"
[ -z "${KEVE_DIGIFLOW_OTEL_TOKEN:-}" ] && KEVE_DIGIFLOW_OTEL_TOKEN="placeholder-for-down"
[ -z "${BCI_UBIX_OTEL_TOKEN:-}" ] && BCI_UBIX_OTEL_TOKEN="placeholder-for-down"
[ -z "${BCI_DIGIFLOW_OTEL_TOKEN:-}" ] && BCI_DIGIFLOW_OTEL_TOKEN="placeholder-for-down"
[ -z "${KEYCLOAK_GRAFANA_CLIENT_SECRET:-}" ] && KEYCLOAK_GRAFANA_CLIENT_SECRET="placeholder-for-down"
export KEVE_UBIX_OTEL_TOKEN KEVE_DIGIFLOW_OTEL_TOKEN BCI_UBIX_OTEL_TOKEN BCI_DIGIFLOW_OTEL_TOKEN KEYCLOAK_GRAFANA_CLIENT_SECRET

# shellcheck disable=SC2086
docker compose -f "$RETAIL_DIR/docker-compose.bci.yml" --env-file "$RETAIL_DIR/.env.bci" down $DOWN_FLAGS
# shellcheck disable=SC2086
docker compose -f "$RETAIL_DIR/docker-compose.yml" down $DOWN_FLAGS
# shellcheck disable=SC2086
docker compose -f "$INS_DIR/docker-compose.bci.yml" --env-file "$INS_DIR/.env.bci" down $DOWN_FLAGS
# shellcheck disable=SC2086
docker compose -f "$INS_DIR/docker-compose.yml" down $DOWN_FLAGS
# shellcheck disable=SC2086
docker compose -f "$PLATFORM" down $DOWN_FLAGS

echo "All stacks stopped."
