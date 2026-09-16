# Example: retail-collector (Variant A — local collector)

`retail-api` -> local `retail-collector` (OTLP/gRPC plaintext, no auth) ->
platform `compose.local.yml` gateway via `http://host.docker.internal:4318`
(OTLP/HTTP + Bearer). Project: **digiflow**; two instances run side by side:

| Variant | Instance | tenant.id | project.id | Token | Ports (api/pg) |
|---|---|---|---|---|---|
| A (`docker-compose.yml`) | **keve_digiflow** | keve | digiflow | `KEVE_DIGIFLOW_OTEL_TOKEN` | 8084/5434 |
| B (`docker-compose.bci.yml` + `--env-file .env.bci`) | **bci_digiflow** | bci | digiflow | `BCI_DIGIFLOW_OTEL_TOKEN` | 8094/5444 |

The collector injects the instance token from `INSTANCE_OTEL_TOKEN`
(mapped from the variant token in compose). Identity is derived from the
credential. Distinct containers (`*-keve` / `*-bci`), networks
(`retail-example-keve` / `-bci`) and env files (`.env.keve` / `.env.bci`).

Copied from `poc-observability-infrastructure/custumers/retail-orders-services`
with these adjustments:

- App leg unchanged: `http://retail-collector:4317`, `grpc` (customer-internal)
- Collector platform leg: `otlphttp/platform` ->
  `http://host.docker.internal:4318` (was `otlp/platform` ->
  `https://retail-otlp.localhost:443` via Traefik/SNI + `ca.crt`)
- Removed `tls.ca_file` + `ca.crt` volume (plaintext to host gateway)
- `bearertokenauth/platform` token: `${env:INSTANCE_OTEL_TOKEN}`
  (mapped from `KEVE_DIGIFLOW_OTEL_TOKEN` / `BCI_DIGIFLOW_OTEL_TOKEN`;
  was `RETAIL_TOKEN`)
- Dropped `tenant.id` from app `OTEL_RESOURCE_ATTRIBUTES` (platform overwrites
  `tenant.id` + `project.id` server-side)
- Removed `otel-ingress` network; isolated per-variant networks +
  `extra_hosts: host-gateway` on the collector for Linux
- Self-contained layout (`./retail-api`, `./collector`) instead of
  `../../observability/...` cert paths

## Run (preferred: shared scripts from repo root)

```bash
./examples/scripts/up.sh                        # platform + all four example variants
./examples/scripts/load-k6.sh --duration-min 1 --vus 2   # smoke traffic
./examples/scripts/down.sh                      # stop everything
```

## Run (manual, this example only)

```bash
# 1. Platform first (from repo root):
cp .env.example .env   # set the 4 real *_OTEL_TOKEN values
docker compose -f compose.local.yml up -d --build
curl http://localhost:4318/healthz

# 2. This example, variant A:
cd examples/retail-collector
cp .env.example .env   # set KEVE_DIGIFLOW_OTEL_TOKEN to the same value as platform .env
docker compose up -d --build
curl http://localhost:8084/actuator/health

# 3. Variant B (side by side):
cp .env.example .env.bci  # set BCI_DIGIFLOW_OTEL_TOKEN + ports 8094/5444
docker compose -f docker-compose.bci.yml --env-file .env.bci up -d --build
curl http://localhost:8094/actuator/health
```

Validate in Grafana (`http://localhost:3000`, org `keve_digiflow` /
`bci_digiflow`): metrics/logs/traces for `service.name=retail-api` under
`tenant.id=keve|bci` + `project.id=digiflow`. Kill the platform
gateway briefly to see the collector file queue buffer (Variant A) vs the
direct example (Variant B) erroring fast.
