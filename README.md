# Observability Platform

Central, multi-tenant observability for internal projects (metrics, logs,
traces) on a Phase 1 Docker Compose deployment: one OTLP gateway, one
OpenTelemetry Collector, Mimir, Loki, Tempo, Grafana and Keycloak.

```text
Project application
        │
        └── Local OTel Collector (otlphttp + Bearer token)
                    │
                    ▼
        https://ingest.observability.example.com
                    │
                    ▼
            Central OTel Gateway (otel-gateway:4318)
                    │  authenticate project, resolve trusted identity,
                    │  ignore client project.id, route by credential
          ┌─────────┼─────────┐
          ▼         ▼         ▼
        Mimir      Loki      Tempo
```

Tenant identity comes from the authenticated machine credential, never from
client-supplied telemetry attributes. A client sending `project.id=digiflow`
with the `ubix` credential is still stored under `ubix`.

## Quickstart

```bash
cp .env.example .env   # then set real UBIX_OTEL_TOKEN / DIGIFLOW_OTEL_TOKEN
docker compose -f compose.prod.yml up -d --build
curl http://localhost:4318/healthz
python3 -m pytest gateway/tests/ tests/ -v
```

## Tenant isolation

### Request path

```text
OTLP/HTTP request
  -> otel-gateway:4318 ........... authentication + credential lookup
  -> project identity ............. trusted, from the Bearer credential
  -> otel-collector:4319|4320 ..... tenant-private pipeline
  -> transform overwrites ......... project.id = <authenticated tenant>
  -> exporter attaches ............ X-Scope-OrgID: <tenant>
  -> Mimir / Loki / Tempo ......... backend tenant
```

### Machine authentication

Each project owns one Bearer token (Phase 1 model):

```text
Authorization: Bearer <project-token>
```

Tokens are configured via environment variables and never committed:

| Project  | Env var              | Gateway upstream             |
|----------|----------------------|------------------------------|
| ubix     | `UBIX_OTEL_TOKEN`    | `http://otel-collector:4319` |
| digiflow | `DIGIFLOW_OTEL_TOKEN`| `http://otel-collector:4320` |

The gateway refuses to start if any configured tenant has no token, and
rejects unknown/missing credentials with `401` without forwarding anything
to any backend. Token comparison uses constant-time equality.

### Credential -> project mapping

The mapping lives in `deploy/collector/tenant-routing.yml` (no secrets in
that file) and is enforced at runtime by the gateway environment:

```text
token-ubix     -> ubix     -> otel-collector:4319 -> X-Scope-OrgID: ubix
token-digiflow -> digiflow -> otel-collector:4320 -> X-Scope-OrgID: digiflow
```

### project.id is not trusted

A client may send `project.id=digiflow` while authenticating with the ubix
credential. This cannot cross tenants, for two independent reasons:

1. **Routing precedes inspection.** The gateway forwards the opaque request
   body to the credential owner's private pipeline (`otel-collector:4319`
   for ubix). There is no code path from the ubix credential to the digiflow
   pipeline.
2. **The pipeline overwrites the attribute.** Each per-tenant pipeline runs
   `transform/<tenant>_identity`, i.e. `set(attributes["project.id"],
   "<tenant>")` on traces, metrics and logs. `set` replaces a spoofed value
   and creates the attribute when absent, so both values never coexist.

The gateway additionally strips any client-supplied `X-Scope-OrgID` /
`X-Tenant` headers; the only tenant header the internal collector sees is
the one the gateway sets from the authenticated credential.

### Backend propagation

Mimir, Loki and Tempo all use `X-Scope-OrgID` for multitenancy (requires
`multitenancy_enabled: true` server-side). Each per-tenant exporter carries
a static header because the value is fixed per pipeline:

- `otlphttp/mimir_<tenant>` -> `http://mimir:9009/otlp` (Mimir OTLP ingest)
- `otlphttp/loki_<tenant>` -> `http://loki:3100/otlp` (Loki OTLP ingest, >= 2.9)
- `otlphttp/tempo_<tenant>` -> `http://tempo:4318` (Tempo OTLP/HTTP)

Note: contrib 0.135.0 ships no Loki exporter, and the `bearertokenauth`
extension accepts tokens without mapping them to identities, so dynamic
per-request tenant headers are not expressible in pure Collector config.
The gateway sidecar is the smallest component that closes this gap
(stdlib-only Python, no new infrastructure).

### Reproducing the spoofing test

With the stack running (`compose.prod.yml`, tokens exported):

```bash
# UBIX credential, spoofed project.id=digiflow -> still lands on ubix
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:4318/v1/logs \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $UBIX_OTEL_TOKEN" \
  -d '{"resourceLogs":[{"resource":{"attributes":[
        {"key":"service.name","value":{"stringValue":"spoof-demo"}},
        {"key":"project.id","value":{"stringValue":"digiflow"}}]},
      "scopeLogs":[{"logRecords":[{"body":{"stringValue":"hi"}}]}]}]}'

# Gateway log shows: tenant=ubix ... -> http://otel-collector:4319/v1/logs
docker compose -f compose.prod.yml logs otel-gateway | grep tenant=

# Invalid credential -> 401, never forwarded
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:4318/v1/logs \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer WRONG' -d '{}'
```

Automated coverage: `python3 -m pytest gateway/tests/ tests/ -v`
(10 live gateway isolation tests + 8 collector/registry consistency tests).

## Telemetry contract

Every signal must include:

- service.name
- service.version
- deployment.environment
- trace_id and span_id where applicable

Authentication: every OTLP/HTTP request to the central gateway must carry
`Authorization: Bearer <project-token>` (see
`projects/collector-template.yml`).

Tenant identity: the platform derives project identity from the
authenticated credential (`credential -> project_id`). `project.id` supplied
by the client is NOT trusted and is overwritten by the gateway pipeline.
Applications must not choose their tenant.

Rules:

- Use normalized routes, never raw URLs.
- Do not log tokens, passwords, payloads, or personal data.
- Keep metric labels low-cardinality.
- Propagate W3C trace context through HTTP and RabbitMQ.
- Use sampling for high-volume traces.

## Project onboarding

Automated with [`scripts/add-tenant.py`](scripts/add-tenant.py) (stdlib only,
idempotent, preserves comments). Full guides in [`runbook/`](runbook/):

- [Variant A: standard local collector](runbook/onboarding-standard-collector.md)
  (default — project runs a collector next to its services)
- [Variant B: external app, direct OTLP](runbook/onboarding-direct-otlp-java.md)
  (e.g. simple Java app on its own VPS, no local collector)

1. Generate the tenant wiring: `python3 scripts/add-tenant.py <tenant-id> --dry-run`,
   then `python3 scripts/add-tenant.py <tenant-id>`. This edits `projects/tenants.yml`,
   `deploy/collector/tenant-routing.yml`, `deploy/collector/collector-config.yml`
   (receiver on the next `43xx` port, `transform/<id>_identity`, three exporters,
   three pipelines), `compose.prod.yml` (`GATEWAY_TENANTS`, `<ID>_OTEL_TOKEN`,
   `<ID>_UPSTREAM`, Grafana `ORG_MAPPING`), `grafana/datasources.yml` (three
   datasources scoped to the tenant org id), and `.env.example`. Review the diff, run
   `python3 -m pytest gateway/tests/ tests/ -v`, redeploy.
   Then create the Grafana org against the running Grafana (manual — orgs cannot
   be file-provisioned): its id must match the script's `--grafana-org-id`,
   else re-run with the actual id. Full checklist: Variant A §1b.
2. Register ownership and environments in `projects/tenants.yml` (done by the script).
   Create Keycloak groups and Grafana organization (manual, not in this repo).
3. Create the project machine credential and store it in the secret manager:
   - the script prints a fresh token (`secrets.token_hex(32)`, equivalent to
     `openssl rand -hex 32`); or generate with `openssl rand -hex 32`
   - export as `<PROJECT>_OTEL_TOKEN` (e.g. `UBIX_OTEL_TOKEN`)
   - hand the token to the project team over a secure channel, never in git
   - the gateway refuses to start if any tenant in
     `deploy/collector/tenant-routing.yml` has no token configured
4. Issue telemetry configuration (pick one runbook variant):
   1. Variant A: copy `projects/collector-template.yml` to the project repo,
      set `PROJECT_OTEL_TOKEN` + `service.name` (plus version/environment),
      point at `ingest.observability.example.com` (OTLP/HTTP), start.
   2. Variant B: configure the app/SDK to send OTLP/HTTP directly to
      `ingest.observability.example.com` with
      `Authorization: Bearer <project-token>` on every request.
5. Validate metrics, logs, and traces from one service.
6. Test RabbitMQ, Camunda, and Angular traces.
7. Test quotas, rotation, PII scrubbing, and isolation:
   - send with the project credential but `project.id` of another project;
     telemetry must still land under the credential owner's tenant
     (see [Reproducing the spoofing test](#reproducing-the-spoofing-test)).
8. Enable dashboards and alerts.

## Collector outage

1. Check gateway and collector health.
2. Check queue depth and exporter retry rate.
3. Confirm the backend is reachable.
4. Inspect dropped telemetry counters.
5. Restore capacity or restart the failed replica.
6. Verify ingestion from each affected project.
7. Record data loss, duration, and corrective action.

The platform must fail visibly. Silent telemetry loss is an incident.

## Reference files

| File | Purpose |
|------|---------|
| [`scripts/add-tenant.py`](scripts/add-tenant.py) | Automate tenant onboarding (edits the 7 registry/config files + prints token; Grafana org creation stays manual) |
| [`runbook/`](runbook/) | Onboarding runbooks: Variant A (local collector), Variant B (direct OTLP, external Java) |
| [`projects/collector-template.yml`](projects/collector-template.yml) | Copy-paste local collector config for projects |
| [`projects/tenants.yml`](projects/tenants.yml) | Tenant registry (source of truth for onboarding) |
| [`deploy/collector/tenant-routing.yml`](deploy/collector/tenant-routing.yml) | Credential → project routing registry (no secrets) |
| [`deploy/collector/collector-config.yml`](deploy/collector/collector-config.yml) | Internal collector: per-tenant pipelines |
| [`compose.prod.yml`](compose.prod.yml) | Production Compose topology |
| [`.env.example`](.env.example) | Required environment / secrets (placeholders only) |
