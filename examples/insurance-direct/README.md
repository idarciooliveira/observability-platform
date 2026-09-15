# Example: insurance-direct (Variant B — direct OTLP, no local collector)

`insurance-api` + `risk-service` sending OTLP/HTTP **directly** to the platform
`compose.local.yml` gateway. Tenant: **ubix** (`project.id=ubix` derived from
the `UBIX_OTEL_TOKEN` credential, never from client attributes).

Copied from `poc-observability-infrastructure/custumers/insurance-services`
(+ `custumers/risk-service`) with these adjustments:

- `OTEL_EXPORTER_OTLP_ENDPOINT=http://host.docker.internal:4318` (was
  `https://insurance-otlp.localhost` via Traefik/SNI)
- `OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf` (was `grpc`; gateway is HTTP-only)
- Removed `OTEL_EXPORTER_OTLP_CERTIFICATE` + `ca.crt` volume (plaintext to host gateway)
- `OTEL_EXPORTER_OTLP_HEADERS=Authorization=Bearer ${UBIX_OTEL_TOKEN}` (was `INSURANCE_TOKEN`)
- Dropped `tenant.id` from `OTEL_RESOURCE_ATTRIBUTES` (platform overwrites
  `project.id` server-side; client must not claim a tenant)
- Removed `otel-ingress` network (no Traefik leg); isolated `insurance-direct`
  network + `extra_hosts: host-gateway` for Linux
- Self-contained build contexts (`./insurance-api`, `./risk-service`) instead
  of `../risk-service`

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
cd examples/insurance-direct
cp .env.example .env   # set UBIX_OTEL_TOKEN to the same value as platform .env
docker compose up -d --build
curl http://localhost:8083/actuator/health
```

Validate in Grafana (`http://localhost:3000`, org `ubix`): one metric, log,
trace for `service.name=insurance-api` / `risk-service` under `project.id=ubix`.
