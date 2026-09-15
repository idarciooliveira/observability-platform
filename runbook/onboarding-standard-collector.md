# Onboarding — Variant A: standard local collector

Default path for projects inside our infrastructure. The project runs a local
OpenTelemetry Collector next to its services; the local collector batches and
queues telemetry and forwards it to the central gateway over OTLP/HTTP with
the project Bearer token.

## 1. Platform side (one PR)

Generate the tenant wiring with the script (stdlib only, idempotent,
preserves comments):

```bash
python3 scripts/add-tenant.py <tenant-id> --dry-run   # preview port + files
python3 scripts/add-tenant.py <tenant-id>             # apply + print token
```

What the script edits (example for `<tenant-id>=onboarding`, port `4321`):

| File | Change |
|------|--------|
| `projects/tenants.yml` | new entry (`id`, `display_name`, `owner_group`, `grafana_org`, `environments`) |
| `deploy/collector/tenant-routing.yml` | new tenant block (`token_env`, `collector_receiver: otlp/<id>`, `collector_upstream: http://otel-collector:<port>`, `storage_tenant`) |
| `deploy/collector/collector-config.yml` | new `otlp/<id>` receiver, `transform/<id>_identity` processor, `otlphttp/{mimir,loki,tempo}_<id>` exporters, `traces|metrics|logs/<id>` pipelines |
| `compose.prod.yml` | `GATEWAY_TENANTS` += `<id>`; `<ID>_OTEL_TOKEN` (required) + `<ID>_UPSTREAM` env |
| `.env.example` | `<ID>_OTEL_TOKEN=changeme-<id>-token` placeholder |

The script prints a fresh token (`secrets.token_hex(32)`, equivalent to
`openssl rand -hex 32`). Store it in the secret manager and hand it to the
project team over a secure channel — **never commit it**. No code change in
`gateway/gateway.py` is needed; it builds routing from the environment.

Then:

```bash
python3 -m pytest gateway/tests/ tests/ -v
docker compose -f compose.prod.yml up -d --build
curl http://localhost:4318/healthz
```

The gateway refuses to start if any tenant in `tenant-routing.yml` has no
token configured — that is the fail-closed check working.

Manual follow-ups (not in this repo): Keycloak `<id>-editors` group, Grafana
`<id>` org, dashboards and alerts.

## 2. Project side (their repo)

Copy [`projects/collector-template.yml`](../projects/collector-template.yml)
into the project repo and set:

```bash
PROJECT_OTEL_TOKEN=<token from platform team>
SERVICE_NAME=<service-name>
SERVICE_VERSION=<version>              # default: unknown
DEPLOYMENT_ENVIRONMENT=<env>           # default: production
PLATFORM_INGEST_URL=https://ingest.observability.example.com
```

The template uses the `otlphttp` exporter (the gateway serves OTLP/HTTP
only), attaches `Authorization: Bearer ${PROJECT_OTEL_TOKEN}` to every
request, and stamps `service.name` / `service.version` /
`deployment.environment`. The project must **not** set `project.id` or
`X-Scope-OrgID` — the platform derives both from the credential.

## 3. Validate

```bash
# From one service: one metric, one log, one trace must arrive.
# Spoof check: credential of the new tenant + project.id of another tenant
# must still land under the credential owner's tenant.
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:4318/v1/logs \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $NEW_OTEL_TOKEN" \
  -d '{"resourceLogs":[{"resource":{"attributes":[
        {"key":"service.name","value":{"stringValue":"smoke"}},
        {"key":"project.id","value":{"stringValue":"ubix"}}]},
      "scopeLogs":[{"logRecords":[{"body":{"stringValue":"hi"}}]}]}]}'
# -> 200; gateway log shows tenant=<new-id> -> http://otel-collector:<port>/v1/logs

# Invalid credential -> 401, never forwarded
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:4318/v1/logs \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer WRONG' -d '{}'
```

Then enable dashboards/alerts and exercise quotas, rotation, PII scrubbing,
and isolation per `README.md` (Project onboarding).
