# Examples (local demo against `compose.local.yml`)

Two self-contained demos, both reporting to the platform gateway via
`http://host.docker.internal:4318` (OTLP/HTTP + tenant Bearer token):

| Example | Pattern | Tenant | Path |
|---|---|---|---|
| `insurance-direct/` | Variant B: app -> gateway directly, no local collector | **ubix** (`UBIX_OTEL_TOKEN`) | `insurance-api` + `risk-service` + `postgres` |
| `retail-collector/` | Variant A: app -> local collector -> gateway (buffered) | **digiflow** (`DIGIFLOW_OTEL_TOKEN`) | `retail-api` + `retail-collector` + `postgres` |

## Quickstart

```bash
# from repo root
./examples/scripts/up.sh
./examples/scripts/load-k6.sh --duration-min 1 --vus 2   # smoke
# Grafana http://localhost:3000 — org ubix = insurance, org digiflow = retail
./examples/scripts/down.sh
```

Windows PowerShell: `.\examples\scripts\up.ps1`, `.\examples\scripts\load-k6.ps1 -DurationMin 1 -Vus 2`, `.\examples\scripts\down.ps1`.

`up` bootstraps missing `.env` files from `.env.example` and exports the
platform `.env` tokens (`UBIX_OTEL_TOKEN`, `DIGIFLOW_OTEL_TOKEN`,
`KEYCLOAK_GRAFANA_CLIENT_SECRET`) so gateway and examples cannot drift.

## Load / chaos

```bash
./examples/scripts/load-k6.sh --duration-min 5 --vus 10 --chaos latency
./examples/scripts/load-k6.sh --duration-min 5 --vus 10 --chaos rejects
```

`latency` sets `CHAOS_LATENCY_MS=2500` (trips the 2s risk timeout);
`rejects` sets 30% forced rejections. Both restore to `0/0` afterwards.
Traffic: `examples/load/examples-load.js` (insurance + retail scenarios only;
adapted from `poc-observability-infrastructure/load/poc-load.js` with the
banking scenario removed).
