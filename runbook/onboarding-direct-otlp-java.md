# Onboarding — Variant B: external Java app, direct OTLP (no local collector)

Worked example: a simple Java application called `onboarding` running on its
**own VPS outside our infrastructure**, sending telemetry **directly** to the
central gateway (`https://ingest.observability.example.com`, OTLP/HTTP +
Bearer token) with **no local collector** in between.

Platform side is identical to Variant A — only the project side differs.
The credential is per INSTANCE (`<company>_<project>`); the example below
onboards `bci_onboarding` (company `bci`, project `onboarding`).

## 1. Platform side (one PR)

```bash
python3 scripts/add-instance.py bci onboarding --dry-run
# instance=bci_onboarding company=bci project=onboarding port=4323 grafana_org_id=6 token_env=BCI_ONBOARDING_OTEL_TOKEN
# would change: projects/tenants.yml,
#   deploy/collector/tenant-routing.yml,
#   deploy/collector/collector-config.yml, compose.prod.yml, compose.local.yml,
#   .env.example, grafana/datasources.yml

python3 scripts/add-instance.py bci onboarding
# prints: BCI_ONBOARDING_OTEL_TOKEN=<hex> -> secret manager, never git
```

Resulting PR touches 7 files (port `4323` = next free after
`4319=keve_ubix`, `4320=keve_digiflow`, `4321=bci_ubix`, `4322=bci_digiflow`;
Grafana org `6` = next free after `1=Main Org.`, `2=keve_ubix`,
`3=keve_digiflow`, `4=bci_ubix`, `5=bci_digiflow`):

- `projects/tenants.yml` — tenant `bci` gains project `onboarding`; new
  instance `bci_onboarding` (`grafana_org: bci_onboarding`)
- `deploy/collector/tenant-routing.yml` — `tenant: bci_onboarding`,
  `project: onboarding`, `storage_tenant: bci`,
  `token_env: BCI_ONBOARDING_OTEL_TOKEN`,
  `collector_upstream: http://otel-collector:4323`
- `deploy/collector/collector-config.yml` — `otlp/bci_onboarding` receiver
  (`0.0.0.0:4323`), `transform/bci_onboarding_identity` (sets BOTH
  `tenant.id=bci` + `project.id=onboarding`), reuse of shared
  `otlphttp/{mimir,loki,tempo}_bci` exporters (`X-Scope-OrgID: bci`),
  3 pipelines
- `compose.prod.yml` + `compose.local.yml` — `GATEWAY_TENANTS` +=
  `bci_onboarding` + `BCI_ONBOARDING_OTEL_TOKEN` / `BCI_ONBOARDING_UPSTREAM`
  + `ORG_MAPPING` entries
  (`bci-onboarding-viewers:4:Viewer, bci-onboarding-editors:4:Editor`)
- `.env.example` — `BCI_ONBOARDING_OTEL_TOKEN=changeme-bci_onboarding-token`
- `grafana/datasources.yml` — unchanged (`bci` company org 3 already owns
  `bci-metrics/logs/traces` with header `bci`)

Then the manual Grafana step: no new org needed (`bci` org 4 is reused) —
create the Keycloak `bci-onboarding-viewers` / `bci-onboarding-editors`
groups, add an `onboarding` folder with the `project.id` filter in the
`bci` org, redeploy, and have users log out/in. (A brand-new company
would need its org created against the running Grafana — it must get the
script's `--grafana-org-id`, else re-run with the actual id.)
Full checklist: Variant A §1b.

Deploy and test:

```bash
python3 -m pytest gateway/tests/ tests/ -v
BCI_ONBOARDING_OTEL_TOKEN=<token> docker compose -f compose.prod.yml up -d --build
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
export OTEL_EXPORTER_OTLP_HEADERS="Authorization=Bearer ${BCI_ONBOARDING_OTEL_TOKEN}"

java -javaagent:opentelemetry-javaagent.jar -jar onboarding.jar
```

Notes:

- The gateway serves **OTLP/HTTP only** — the agent must use
  `http/protobuf`, never gRPC.
- Every request must carry `Authorization: Bearer <token>`; missing/unknown
  credentials get `401` and are never forwarded.
- Do **not** set `tenant.id`, `project.id` or `X-Scope-OrgID` in the app:
  the gateway strips tenant headers and the
  `transform/bci_onboarding_identity` processor overwrites
  `tenant.id=bci` + `project.id=onboarding` as defense in depth.
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
  -H "Authorization: Bearer $BCI_ONBOARDING_OTEL_TOKEN" \
  -d '{"resourceLogs":[{"resource":{"attributes":[
        {"key":"service.name","value":{"stringValue":"onboarding"}}]},
      "scopeLogs":[{"logRecords":[{"body":{"stringValue":"hi"}}]}]}]}'

# Isolation: bci_onboarding credential + tenant.id=keve/project.id=ubix must
# still land on bci_onboarding (check Grafana org=bci_onboarding: Explore
# shows only bci_onboarding-*; nothing may appear under the keve orgs)
# Gateway log: tenant=bci_onboarding ... -> http://otel-collector:4323/v1/logs
```

Then confirm one metric, one log, and one trace for
`service.name=onboarding` in the `bci_onboarding` Grafana org, and enable
dashboards/alerts.
