# Onboarding — Variant A: standard local collector

Default path for projects inside our infrastructure. The project runs a local
OpenTelemetry Collector next to its services; the local collector batches and
queues telemetry and forwards it to the central gateway over OTLP/HTTP with
the instance Bearer token.

Isolation model (Option B): the credential is per INSTANCE
(`<company>_<project>`, 1 credential -> 1 pipeline). Storage isolation is
per company (`storage_tenant` -> `X-Scope-OrgID`); project isolation is soft
(default `project.id` Grafana filter). Never set `tenant.id` / `project.id` /
`X-Scope-OrgID` client-side — the platform derives and overwrites them.

## 1. Platform side (one PR)

Generate the instance wiring with the script (stdlib only, idempotent,
preserves comments):

```bash
python3 scripts/add-instance.py <company> <project> --dry-run   # preview port + org id + files
python3 scripts/add-instance.py <company> <project>             # apply + print token
# If Grafana gives the new org a different id than the script assumed:
python3 scripts/add-instance.py <company> <project> --grafana-org-id <actual-id>
```

What the script edits (example for `<company>=keve <project>=onboarding`,
instance `keve_onboarding`, port `4323`, Grafana org `6`):

| File | Change |
|------|--------|
| `projects/tenants.yml` | tenant entry gains the project; new instance entry (`tenant`, `project`, `grafana_org_id`) |
| `deploy/collector/tenant-routing.yml` | new instance block (`tenant:`, `project:`, `storage_tenant:`, `token_env`, `collector_receiver: otlp/<instance>`, `collector_upstream: http://otel-collector:<port>`) |
| `deploy/collector/collector-config.yml` | new `otlp/<instance>` receiver, `transform/<instance>_identity` processor (sets BOTH `tenant.id` + `project.id`), reuse of shared `otlphttp/{mimir,loki,tempo}_<company>` exporters, `traces|metrics|logs/<instance>` pipelines |
| `compose.prod.yml` + `compose.local.yml` | `GATEWAY_TENANTS` += `<instance>`; `<INSTANCE>_OTEL_TOKEN` (required) + `<INSTANCE>_UPSTREAM` env; `ORG_MAPPING` += `<instance-dashed>-viewers:<org>:Viewer, <instance-dashed>-editors:<org>:Editor` (+ `ROLE_ATTRIBUTE_PATH`) |
| `.env.example` | `<INSTANCE>_OTEL_TOKEN=changeme-<instance>-token` placeholder |
| `grafana/datasources.yml` | new `<instance>-metrics/logs/traces` datasources with `orgId: <org>` and `X-Scope-OrgID: <company>` |

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

The gateway refuses to start if any instance in `tenant-routing.yml` has no
token configured — that is the fail-closed check working.

## 1b. Grafana isolation (manual — orgs cannot be file-provisioned)

The script reserves the next free Grafana org id and writes the files
against it, but the org itself must be created against the running Grafana:

1. Create the org (admin API or Server Admin UI):
   `POST /api/orgs {"name":"<instance>"}` — it **must** return the id
   the script assumed. If it returns another id, re-run the script with
   `--grafana-org-id <actual-id>` to rewrite `datasources.yml` + `ORG_MAPPING`.
2. Keycloak: create groups `<instance-dashed>-viewers` and
   `<instance-dashed>-editors` (plus `<company>-admins` for company admins).
3. Redeploy Grafana, have the instance users log out/in (org membership and
   roles apply at login), then verify: Explore in the new org shows only
   `<instance>-*` sources, and the other instance orgs show nothing of the
   new instance. Viewers get no Explore/create (dashboard-only with a fixed
   `project.id` variable); document project-level as soft, company-level as
   the hard boundary.

One-time prerequisite (already done for this stack, needed once per
environment): Grafana is provisioned from `grafana/datasources.yml` and
authenticates via Keycloak OIDC with group→org mapping
(`ORG_MAPPING`, no anonymous access, no auto-assign to Main Org).
`Main Org.` keeps no datasources; platform admins reach instance orgs via
the org switcher (Profile → Organizations).

Manual follow-ups (not in this repo): Keycloak users, Grafana dashboards
and alerts.

## 2. Project side (their repo)

Copy [`projects/collector-template.yml`](../projects/collector-template.yml)
into the project repo and set:

```bash
PROJECT_OTEL_TOKEN=<instance token from platform team>
SERVICE_NAME=<service-name>
SERVICE_VERSION=<version>              # default: unknown
DEPLOYMENT_ENVIRONMENT=<env>           # default: production
PLATFORM_INGEST_URL=https://ingest.observability.example.com
```

The template uses the `otlphttp` exporter (the gateway serves OTLP/HTTP
only), attaches `Authorization: Bearer ${PROJECT_OTEL_TOKEN}` to every
request, and stamps `service.name` / `service.version` /
`deployment.environment`. The project must **not** set `tenant.id`,
`project.id` or `X-Scope-OrgID` — the platform derives them from the
credential.

## 3. Validate

```bash
# From one service: one metric, one log, one trace must arrive.
# Spoof check: credential of the new instance + project.id/tenant.id of
# another instance must still land under the credential owner's instance.
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:4318/v1/logs \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $NEW_OTEL_TOKEN" \
  -d '{"resourceLogs":[{"resource":{"attributes":[
        {"key":"service.name","value":{"stringValue":"smoke"}},
        {"key":"tenant.id","value":{"stringValue":"keve"}},
        {"key":"project.id","value":{"stringValue":"ubix"}}]},
      "scopeLogs":[{"logRecords":[{"body":{"stringValue":"hi"}}]}]}]}'
# -> 200; gateway log shows tenant=<new-instance> -> http://otel-collector:<port>/v1/logs

# Invalid credential -> 401, never forwarded
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:4318/v1/logs \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer WRONG' -d '{}'
```

Then enable dashboards/alerts and exercise quotas, rotation, PII scrubbing,
and isolation per `README.md` (Project onboarding).
