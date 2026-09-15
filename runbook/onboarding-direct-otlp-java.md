# Onboarding — Variant B: external Java app, direct OTLP (no local collector)

Worked example: a simple Java application called `onboarding` running on its
**own VPS outside our infrastructure**, sending telemetry **directly** to the
central gateway (`https://ingest.observability.example.com`, OTLP/HTTP +
Bearer token) with **no local collector** in between.

Platform side is identical to Variant A — only the project side differs.

## 1. Platform side (one PR)

```bash
python3 scripts/add-tenant.py onboarding --dry-run
# tenant=onboarding port=4321 token_env=ONBOARDING_OTEL_TOKEN
# would change: projects/tenants.yml,
#   deploy/collector/tenant-routing.yml,
#   deploy/collector/collector-config.yml, compose.prod.yml, .env.example

python3 scripts/add-tenant.py onboarding
# prints: ONBOARDING_OTEL_TOKEN=<hex> -> secret manager, never git
```

Resulting PR touches exactly 5 files (port `4321` = next free after
`4319=ubix`, `4320=digiflow`):

- `projects/tenants.yml` — `id: onboarding`, `owner_group: onboarding-editors`, `grafana_org: onboarding`
- `deploy/collector/tenant-routing.yml` — `token_env: ONBOARDING_OTEL_TOKEN`, `collector_upstream: http://otel-collector:4321`
- `deploy/collector/collector-config.yml` — `otlp/onboarding` receiver (`0.0.0.0:4321`), `transform/onboarding_identity`, 3 exporters (`X-Scope-OrgID: onboarding`), 3 pipelines
- `compose.prod.yml` — `GATEWAY_TENANTS: ubix,digiflow,onboarding` + `ONBOARDING_OTEL_TOKEN` / `ONBOARDING_UPSTREAM`
- `.env.example` — `ONBOARDING_OTEL_TOKEN=changeme-onboarding-token`

Deploy and test:

```bash
python3 -m pytest gateway/tests/ tests/ -v
ONBOARDING_OTEL_TOKEN=<token> docker compose -f compose.prod.yml up -d --build
```

## 2. VPS side (their machine)

Prerequisites on the VPS: egress `443` to
`ingest.observability.example.com`, synced clock, Java 17+, the
OpenTelemetry Java agent jar next to the app. No collector to install.

```bash
export OTEL_SERVICE_NAME=onboarding
export OTEL_SERVICE_VERSION=0.1.0
export OTEL_DEPLOYMENT_ENVIRONMENT=production
export OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
export OTEL_EXPORTER_OTLP_ENDPOINT=https://ingest.observability.example.com
export OTEL_EXPORTER_OTLP_HEADERS="Authorization=Bearer ${ONBOARDING_OTEL_TOKEN}"

java -javaagent:opentelemetry-javaagent.jar -jar onboarding.jar
```

Notes:

- The gateway serves **OTLP/HTTP only** — the agent must use
  `http/protobuf`, never gRPC.
- Every request must carry `Authorization: Bearer <token>`; missing/unknown
  credentials get `401` and are never forwarded.
- Do **not** set `project.id` or `X-Scope-OrgID` in the app: the gateway
  strips tenant headers and the `transform/onboarding_identity` processor
  overwrites `project.id=onboarding` as defense in depth.
- Keep the telemetry contract: `service.name`, `service.version`,
  `deployment.environment` on every signal; normalized routes (never raw
  URLs); low-cardinality metric labels; no tokens, passwords, payloads, or
  personal data in logs; W3C trace propagation; sampling for high-volume
  traces.
- Tradeoff of skipping the local collector: no local batch queue — a gateway
  outage surfaces as export errors in the app logs instead of being buffered.
  Acceptable for this simple app; switch to Variant A if buffering is needed.

## 3. Validate end to end

```bash
# Smoke: direct OTLP/HTTP log with the onboarding credential -> 200
curl -s -o /dev/null -w '%{http_code}\n' \
  https://ingest.observability.example.com/v1/logs \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $ONBOARDING_OTEL_TOKEN" \
  -d '{"resourceLogs":[{"resource":{"attributes":[
        {"key":"service.name","value":{"stringValue":"onboarding"}}]},
      "scopeLogs":[{"logRecords":[{"body":{"stringValue":"hi"}}]}]}]}'

# Isolation: onboarding credential + project.id=ubix must still land on onboarding
# (check Grafana org=onboarding; nothing may appear under ubix)
# Gateway log: tenant=onboarding ... -> http://otel-collector:4321/v1/logs
```

Then confirm one metric, one log, and one trace for
`service.name=onboarding` in the `onboarding` Grafana org, and enable
dashboards/alerts.
