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
                    │  authenticate instance, resolve trusted identity,
                    │  ignore client tenant.id/project.id, route by credential
          ┌─────────┼─────────┐
          ▼         ▼         ▼
        Mimir      Loki      Tempo   (X-Scope-OrgID = company)
```

Isolation model (Option B, soft project isolation, proxy-ready):

```text
tenant (company, HARD storage isolation, X-Scope-OrgID): keve, bci
project (soft query isolation, project.id + tenant.id attrs): ubix, digiflow
instance (ingest identity, 1 credential -> 1 pipeline): keve_ubix,
  keve_digiflow, bci_ubix, bci_digiflow
```

Ingestion: 4 receivers/transforms. Storage: 2 OrgIDs. Query: 2 company
Grafana orgs (Main:2, keve:3, bci:4 on fresh Grafana 12 — org 1 is the
bootstrap admin's personal org and is unused) with one folder per project
and a default `project.id` filter (soft). A future read-proxy can enforce
the filter without re-ingestion because both IDs are already stored.

Tenant identity comes from the authenticated machine credential, never from
client-supplied telemetry attributes. A client sending `project.id=digiflow`
with the `keve_ubix` credential is still stored under
(`tenant.id=keve`, `project.id=ubix`).

## Quickstart

```bash
cp .env.example .env   # then set the 4 real *_OTEL_TOKEN values (see below)
docker compose -f compose.prod.yml up -d --build
curl http://localhost:4318/healthz
python3 -m pytest gateway/tests/ tests/ -v
```

> Rollout note: the per-instance Grafana orgs (`keve_ubix`, `keve_digiflow`,
> `bci_ubix`, `bci_digiflow`) and old per-project OrgIDs (`ubix`/`digiflow`)
> are retired — history stays, no backfill. Grafana cannot renumber orgs,
> so existing environments must reset its state: backup volumes, stop the
> stack, land the new config, `docker volume rm
> <project>_grafana-data`, `compose.local.yml up -d --build`, seed the
> company orgs (`keve` -> id 3, `bci` -> id 4; Main is 2 on fresh Grafana
> 12), restart Grafana to provision company datasources, have users
> re-login, then retire `UBIX_`/`DIGIFLOW_` after the examples migrate.
> Telemetry history in Mimir/Loki/Tempo is untouched (separate volumes).

## Tenant isolation

### Request path

```text
OTLP/HTTP request
  -> otel-gateway:4318 ........... authentication + credential lookup
  -> instance identity ............ trusted, from the Bearer credential
  -> otel-collector:4319|4320|4321|4322 .. instance-private pipeline
  -> transform overwrites ......... tenant.id = <company>, project.id = <project>
  -> shared company exporter ...... X-Scope-OrgID: <company> (keve|bci)
  -> Mimir / Loki / Tempo ......... backend company tenant
```

### Machine authentication

Each instance owns one Bearer token (1 credential -> 1 pipeline):

```text
Authorization: Bearer <instance-token>
```

Tokens are configured via environment variables and never committed:

| Instance     | Company | Project  | Env var                  | Gateway upstream             |
|--------------|---------|----------|--------------------------|------------------------------|
| keve_ubix     | keve     | ubix     | `KEVE_UBIX_OTEL_TOKEN`    | `http://otel-collector:4319` |
| keve_digiflow | keve     | digiflow | `KEVE_DIGIFLOW_OTEL_TOKEN`| `http://otel-collector:4320` |
| bci_ubix     | bci     | ubix     | `BCI_UBIX_OTEL_TOKEN`    | `http://otel-collector:4321` |
| bci_digiflow | bci     | digiflow | `BCI_DIGIFLOW_OTEL_TOKEN`| `http://otel-collector:4322` |

The gateway refuses to start if any configured instance has no token, and
rejects unknown/missing credentials with `401` without forwarding anything
to any backend. Token comparison uses constant-time equality.

### Credential -> instance mapping

The mapping lives in `deploy/collector/tenant-routing.yml` (no secrets in
that file) and is enforced at runtime by the gateway environment:

```text
token-keve_ubix     -> keve_ubix     -> otel-collector:4319 -> X-Scope-OrgID: keve
token-keve_digiflow -> keve_digiflow -> otel-collector:4320 -> X-Scope-OrgID: keve
token-bci_ubix     -> bci_ubix     -> otel-collector:4321 -> X-Scope-OrgID: bci
token-bci_digiflow -> bci_digiflow -> otel-collector:4322 -> X-Scope-OrgID: bci
```

Instances sharing a company share the storage OrgID but use DIFFERENT
pipelines (same-OrgID / different-pipeline).

### tenant.id / project.id are not trusted

A client may send `project.id=digiflow, tenant.id=bci` while authenticating
with the keve_ubix credential. This cannot cross instances, for two
independent reasons:

1. **Routing precedes inspection.** The gateway forwards the opaque request
   body to the credential owner's private pipeline (`otel-collector:4319`
   for keve_ubix). There is no code path from the keve_ubix credential to any
   other pipeline.
2. **The pipeline overwrites both attributes.** Each per-instance pipeline
   runs `transform/<instance>_identity`, i.e.
   `set(attributes["tenant.id"], "<company>")` +
   `set(attributes["project.id"], "<project>")` on traces, metrics and logs.
   `set` replaces spoofed values and creates the attributes when absent, so
   both values never coexist.

The gateway additionally strips any client-supplied `X-Scope-OrgID` /
`X-Tenant` headers; the only tenant header the internal collector sees is
the one the gateway sets from the authenticated credential.

### Backend propagation

Mimir, Loki and Tempo all use `X-Scope-OrgID` for multitenancy (requires
`multitenancy_enabled: true` server-side). Each SHARED company exporter
carries a static header because the value is fixed per company:

- `otlphttp/mimir_{keve,bci}` -> `http://mimir:9009/otlp` (Mimir OTLP ingest)
- `otlphttp/loki_{keve,bci}` -> `http://loki:3100/otlp` (Loki OTLP ingest, >= 2.9)
- `otlphttp/tempo_{keve,bci}` -> `http://tempo:4318` (Tempo OTLP/HTTP)

Note: contrib 0.135.0 ships no Loki exporter, and the `bearertokenauth`
extension accepts tokens without mapping them to identities, so dynamic
per-request tenant headers are not expressible in pure Collector config.
The gateway sidecar is the smallest component that closes this gap
(stdlib-only Python, no new infrastructure).

### Query layer (soft project isolation)

Grafana orgs: Main:2, keve:3, bci:4. Each company org owns 3 datasources
(`<company>-metrics/logs/traces`) pointing at its COMPANY header.
Projects live inside their company org as folders/teams; project
isolation inside a company is SOFT: dashboards carry a fixed `project.id`
variable, viewers get no Explore/create. Document project-level as soft;
company-level as the hard security boundary.

RBAC (flat Keycloak groups + `GF_AUTH_GENERIC_OAUTH_ORG_MAPPING`):

- `obs-platform-admins` -> Admin 2,3,4 (Platform Team)
- `keve-admins` -> Admin 3 ; `bci-admins` -> Admin 4 (company-admin)
- 8 project groups (`keve-ubix-viewers/editors`, ...) -> Viewer/Editor in
  their company org only
- cross-company lead, e.g. Domingos: member of `keve-digiflow-editors` +
  `bci-digiflow-editors` -> Editor 3+4 only

Phase 2 hook (not now): read-proxy (`query-gateway`: Keycloak JWT ->
allowed `(tenant,project)` -> inject PromQL/LogQL/TraceQL filter + audit
log) or migrate to hard per-project OrgIDs. No ingest redesign needed since
both IDs are stored from day one.

### Reproducing the spoofing test

With the stack running (`compose.prod.yml`, tokens exported):

```bash
# KEVE_UBIX credential, spoofed project.id=digiflow + tenant.id=bci
# -> still lands on keve_ubix (tenant.id=keve, project.id=ubix)
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:4318/v1/logs \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $KEVE_UBIX_OTEL_TOKEN" \
  -d '{"resourceLogs":[{"resource":{"attributes":[
        {"key":"service.name","value":{"stringValue":"spoof-demo"}},
        {"key":"tenant.id","value":{"stringValue":"bci"}},
        {"key":"project.id","value":{"stringValue":"digiflow"}}]},
      "scopeLogs":[{"logRecords":[{"body":{"stringValue":"hi"}}]}]}]}'

# Gateway log shows: tenant=keve_ubix ... -> http://otel-collector:4319/v1/logs
docker compose -f compose.prod.yml logs otel-gateway | grep tenant=

# Invalid credential -> 401, never forwarded
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:4318/v1/logs \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer WRONG' -d '{}'
```

Automated coverage: `python3 -m pytest gateway/tests/ tests/ -v`
(11 live gateway isolation tests + 9 collector/registry consistency tests).

## Telemetry contract

Every signal must include:

- service.name
- service.version
- deployment.environment
- trace_id and span_id where applicable

Authentication: every OTLP/HTTP request to the central gateway must carry
`Authorization: Bearer <instance-token>` (see
`projects/collector-template.yml`).

Tenant identity: the platform derives instance identity from the
authenticated credential (`credential -> instance_id`, i.e.
company + project). `tenant.id` / `project.id` supplied by the client are
NOT trusted and are overwritten by the gateway pipeline. `X-Scope-OrgID`
supplied by the client is stripped. Applications must not choose their
tenant.

Rules:

- Never set `tenant.id` / `project.id` / `X-Scope-OrgID` client-side.
- Use normalized routes, never raw URLs.
- Do not log tokens, passwords, payloads, or personal data.
- Keep metric labels low-cardinality.
- Propagate W3C trace context through HTTP and RabbitMQ.
- Use sampling for high-volume traces.

## Project onboarding

Automated with [`scripts/add-instance.py`](scripts/add-instance.py) (stdlib
only, idempotent, preserves comments). Full guides in [`runbook/`](runbook/):

- [Variant A: standard local collector](runbook/onboarding-standard-collector.md)
  (default — project runs a collector next to its services)
- [Variant B: external app, direct OTLP](runbook/onboarding-direct-otlp-java.md)
  (e.g. simple Java app on its own VPS, no local collector)

1. Generate the instance wiring: `python3 scripts/add-instance.py <company> <project> --dry-run`,
   then `python3 scripts/add-instance.py <company> <project>`. This edits
   `projects/tenants.yml` (tenant + instance entries),
   `deploy/collector/tenant-routing.yml` (instance block with `tenant:`,
   `project:`, `storage_tenant:`), `deploy/collector/collector-config.yml`
   (receiver on the next `43xx` port, `transform/<instance>_identity` setting
   BOTH ids, reuse of the shared company exporters, three pipelines),
    `compose.prod.yml` + `compose.local.yml` (`GATEWAY_TENANTS`,
    `<INSTANCE>_OTEL_TOKEN`, `<INSTANCE>_UPSTREAM`, Grafana `ORG_MAPPING` +
    `ROLE_ATTRIBUTE_PATH`), `grafana/datasources.yml` (three
    `<company>-metrics/logs/traces` datasources scoped to the company org
    id with the COMPANY header; new companies only), and `.env.example`.
    Review the diff, run `python3 -m pytest gateway/tests/ tests/ -v`,
    redeploy. A new company also needs its Grafana org created against the
    running Grafana (manual — orgs cannot be file-provisioned): its id must
    match the script's `--grafana-org-id`, else re-run with the actual id.
    Instances in an existing company reuse its org (no manual step).
    Full checklist: Variant A §1b.
2. Register ownership and environments in `projects/tenants.yml` (done by the script).
    Create Keycloak groups and (new companies only) the Grafana organization
    (manual, not in this repo): `<instance-dashed>-viewers` / `-editors`
    plus `<company>-admins` for company admins.
3. Create the instance machine credential and store it in the secret manager:
    - the script prints a fresh token (`secrets.token_hex(32)`, equivalent to
      `openssl rand -hex 32`); or generate with `openssl rand -hex 32`
    - export as `<COMPANY>_<PROJECT>_OTEL_TOKEN` (e.g. `KEVE_UBIX_OTEL_TOKEN`)
    - hand the token to the project team over a secure channel, never in git
    - the gateway refuses to start if any instance in
      `deploy/collector/tenant-routing.yml` has no token configured
4. Issue telemetry configuration (pick one runbook variant):
    1. Variant A: copy `projects/collector-template.yml` to the project repo,
       set `PROJECT_OTEL_TOKEN` + `service.name` (plus version/environment),
       point at `ingest.observability.example.com` (OTLP/HTTP), start.
    2. Variant B: configure the app/SDK to send OTLP/HTTP directly to
       `ingest.observability.example.com` with
       `Authorization: Bearer <instance-token>` on every request.
5. Validate metrics, logs, and traces from one service.
6. Test RabbitMQ, Camunda, and Angular traces.
7. Test quotas, rotation, PII scrubbing, and isolation:
    - send with the instance credential but `project.id`/`tenant.id` of
      another instance; telemetry must still land under the credential
      owner's instance (see [Reproducing the spoofing test](#reproducing-the-spoofing-test)).
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
| [`scripts/add-instance.py`](scripts/add-instance.py) | Automate instance onboarding (edits the 7 registry/config files + prints token; Grafana org creation stays manual) |
| [`runbook/`](runbook/) | Onboarding runbooks: Variant A (local collector), Variant B (direct OTLP, external Java) |
| [`projects/collector-template.yml`](projects/collector-template.yml) | Copy-paste local collector config for projects (never set tenant.id/project.id/X-Scope-OrgID) |
| [`projects/tenants.yml`](projects/tenants.yml) | Tenant registry: companies + instances (source of truth for onboarding) |
| [`deploy/collector/tenant-routing.yml`](deploy/collector/tenant-routing.yml) | Credential → instance routing registry (no secrets) |
| [`deploy/collector/collector-config.yml`](deploy/collector/collector-config.yml) | Internal collector: per-instance pipelines -> shared company exporters |
| [`compose.prod.yml`](compose.prod.yml) | Production Compose topology |
| [`.env.example`](.env.example) | Required environment / secrets (placeholders only) |
