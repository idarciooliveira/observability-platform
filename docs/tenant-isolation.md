# Tenant isolation

## Request path

```text
OTLP/HTTP request
  -> otel-gateway:4318 ........... authentication + credential lookup
  -> project identity ............. trusted, from the Bearer credential
  -> otel-collector:4319|4320 ..... tenant-private pipeline
  -> transform overwrites ......... project.id = <authenticated tenant>
  -> exporter attaches ............ X-Scope-OrgID: <tenant>
  -> Mimir / Loki / Tempo ......... backend tenant
```

## Machine authentication

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

## Credential -> project mapping

The mapping lives in `deploy/collector/tenant-routing.yml` (no secrets in
that file) and is enforced at runtime by the gateway environment:

```text
token-ubix     -> ubix     -> otel-collector:4319 -> X-Scope-OrgID: ubix
token-digiflow -> digiflow -> otel-collector:4320 -> X-Scope-OrgID: digiflow
```

## project.id is not trusted

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

## Backend propagation

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

## Reproducing the spoofing test

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
