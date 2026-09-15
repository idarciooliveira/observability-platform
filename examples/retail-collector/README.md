# Example: retail-collector (Variant A — local collector)

`retail-api` -> local `retail-collector` (OTLP/gRPC plaintext, no auth) ->
platform `compose.local.yml` gateway via `http://host.docker.internal:4318`
(OTLP/HTTP + Bearer). Tenant: **digiflow** (`project.id=digiflow` derived from
the `DIGIFLOW_OTEL_TOKEN` credential).

Copied from `poc-observability-infrastructure/custumers/retail-orders-services`
with these adjustments:

- App leg unchanged: `http://retail-collector:4317`, `grpc` (customer-internal)
- Collector platform leg: `otlphttp/platform` ->
  `http://host.docker.internal:4318` (was `otlp/platform` ->
  `https://retail-otlp.localhost:443` via Traefik/SNI + `ca.crt`)
- Removed `tls.ca_file` + `ca.crt` volume (plaintext to host gateway)
- `bearertokenauth/platform` token: `${env:DIGIFLOW_OTEL_TOKEN}` (was `RETAIL_TOKEN`)
- Dropped `tenant.id` from app `OTEL_RESOURCE_ATTRIBUTES` (platform overwrites
  `project.id` server-side)
- Removed `otel-ingress` network; isolated `retail-example` network +
  `extra_hosts: host-gateway` on the collector for Linux
- Self-contained layout (`./retail-api`, `./collector`) instead of
  `../../observability/...` cert paths

## Run (preferred: shared scripts from repo root)

```bash
./examples/scripts/up.sh                        # platform + both examples
./examples/scripts/load-k6.sh --duration-min 1 --vus 2   # smoke traffic
./examples/scripts/down.sh                      # stop everything
```

## Run (manual, this example only)

```bash
# 1. Platform first (from repo root):
cp .env.example .env   # set real UBIX_OTEL_TOKEN / DIGIFLOW_OTEL_TOKEN
docker compose -f compose.local.yml up -d --build
curl http://localhost:4318/healthz

# 2. This example:
cd examples/retail-collector
cp .env.example .env   # set DIGIFLOW_OTEL_TOKEN to the same value as platform .env
docker compose up -d --build
curl http://localhost:8084/actuator/health
```

Validate in Grafana (`http://localhost:3000`, org `digiflow`): metrics/logs/traces
for `service.name=retail-api` under `project.id=digiflow`. Kill the platform
gateway briefly to see the collector file queue buffer (Variant A) vs the
direct example (Variant B) erroring fast.
