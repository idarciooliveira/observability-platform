# Examples (local demo against `compose.local.yml`)

Four self-contained demo variants, all reporting to the platform gateway via
`http://host.docker.internal:4318` (OTLP/HTTP + instance Bearer token):

| Example | Pattern | Instance | Token | Ports |
|---|---|---|---|---|
| `insurance-direct/` A | Variant B: app -> gateway directly, no local collector | **keve_ubix** (`tenant.id=keve`, `project.id=ubix`) | `KEVE_UBIX_OTEL_TOKEN` | 8083/8082/5433 |
| `insurance-direct/` B (`docker-compose.bci.yml`, `--env-file .env.bci`) | Variant B | **bci_ubix** (`tenant.id=bci`, `project.id=ubix`) | `BCI_UBIX_OTEL_TOKEN` | 8093/8092/5443 |
| `retail-collector/` A | Variant A: app -> local collector -> gateway (buffered) | **keve_digiflow** (`tenant.id=keve`, `project.id=digiflow`) | `KEVE_DIGIFLOW_OTEL_TOKEN` | 8084/5434 |
| `retail-collector/` B (`docker-compose.bci.yml`, `--env-file .env.bci`) | Variant A | **bci_digiflow** (`tenant.id=bci`, `project.id=digiflow`) | `BCI_DIGIFLOW_OTEL_TOKEN` | 8094/5444 |

Variants A/B of each example use distinct containers, networks and
`.env.keve` / `.env.bci` files so they run side by side.

## Quickstart

```bash
# from repo root
./examples/scripts/up.sh
./examples/scripts/load-k6.sh --duration-min 1 --vus 2   # smoke
# Grafana http://localhost:3000 — orgs keve_ubix / bci_ubix = insurance,
# orgs keve_digiflow / bci_digiflow = retail
./examples/scripts/down.sh
```

Windows PowerShell: `.\examples\scripts\up.ps1`, `.\examples\scripts\load-k6.ps1 -DurationMin 1 -Vus 2`, `.\examples\scripts\down.ps1`.

`up` bootstraps missing `.env` files from `.env.example` and exports the
platform `.env` tokens (`KEVE_UBIX_OTEL_TOKEN`, `KEVE_DIGIFLOW_OTEL_TOKEN`,
`BCI_UBIX_OTEL_TOKEN`, `BCI_DIGIFLOW_OTEL_TOKEN`,
`KEYCLOAK_GRAFANA_CLIENT_SECRET`) so gateway and examples cannot drift.

## Load / chaos

```bash
./examples/scripts/load-k6.sh --duration-min 5 --vus 10 --chaos latency
./examples/scripts/load-k6.sh --duration-min 5 --vus 10 --chaos rejects
```

`latency` sets `CHAOS_LATENCY_MS=2500` (trips the 2s risk timeout);
`rejects` sets 30% forced rejections. Both restore to `0/0` afterwards.
Traffic: `examples/load/examples-load.js` (insurance A/B + retail A/B
scenarios; adapted from `poc-observability-infrastructure/load/poc-load.js`
with the banking scenario removed). Chaos applies to all four variants.
