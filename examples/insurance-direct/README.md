# Example: insurance-direct (Variant B — direct OTLP, no local collector)

`insurance-api` + `risk-service` sending OTLP/HTTP **directly** to the platform
`compose.local.yml` gateway. Project: **ubix**; two instances run side by side:

| Variant | Instance | tenant.id | project.id | Token | Ports (api/risk/pg) |
|---|---|---|---|---|---|
| A (`docker-compose.yml`) | **keve_ubix** | keve | ubix | `KEVE_UBIX_OTEL_TOKEN` | 8083/8082/5433 |
| B (`docker-compose.bci.yml` + `--env-file .env.bci`) | **bci_ubix** | bci | ubix | `BCI_UBIX_OTEL_TOKEN` | 8093/8092/5443 |

Identity (`tenant.id` + `project.id`) is derived from the credential, never
from client attributes. Distinct containers (`*-keve` / `*-bci`), networks
(`insurance-direct-keve` / `-bci`) and env files (`.env.keve` / `.env.bci`).

Copied from `poc-observability-infrastructure/custumers/insurance-services`
(+ `custumers/risk-service`) with these adjustments:

- `OTEL_EXPORTER_OTLP_ENDPOINT=http://host.docker.internal:4318` (was
  `https://insurance-otlp.localhost` via Traefik/SNI)
- `OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf` (was `grpc`; gateway is HTTP-only)
- Removed `OTEL_EXPORTER_OTLP_CERTIFICATE` + `ca.crt` volume (plaintext to host gateway)
- `OTEL_EXPORTER_OTLP_HEADERS=Authorization=Bearer ${KEVE_UBIX_OTEL_TOKEN}`
  (variant B: `${BCI_UBIX_OTEL_TOKEN}`; was `INSURANCE_TOKEN`)
- Dropped `tenant.id` from `OTEL_RESOURCE_ATTRIBUTES` (platform overwrites
  `tenant.id` + `project.id` server-side; client must not claim a tenant)
- Removed `otel-ingress` network (no Traefik leg); isolated per-variant
  networks + `extra_hosts: host-gateway` for Linux
- Self-contained build contexts (`./insurance-api`, `./risk-service`) instead
  of `../risk-service`

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
cd examples/insurance-direct
cp .env.example .env   # set KEVE_UBIX_OTEL_TOKEN to the same value as platform .env
docker compose up -d --build
curl http://localhost:8083/actuator/health

# 3. Variant B (side by side):
cp .env.example .env.bci  # set BCI_UBIX_OTEL_TOKEN + ports 8093/8092/5443
docker compose -f docker-compose.bci.yml --env-file .env.bci up -d --build
curl http://localhost:8093/actuator/health
```

Validate in Grafana (`http://localhost:3000`, org `keve_ubix` / `bci_ubix`):
one metric, log, trace for `service.name=insurance-api` / `risk-service`
under `tenant.id=keve|bci` + `project.id=ubix`.
