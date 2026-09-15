# Project onboarding

1. Register ownership and environments in `projects/tenants.yml`.
2. Create Keycloak groups and Grafana organization.
3. Create the project machine credential and store it in the secret manager:
   - generate with `openssl rand -hex 32`
   - export as `<PROJECT>_OTEL_TOKEN` (e.g. `UBIX_OTEL_TOKEN`)
   - hand the token to the project team over a secure channel, never in git
   - the gateway refuses to start if any tenant in
     `deploy/collector/tenant-routing.yml` has no token configured
4. Issue collector configuration from `projects/collector-template.yml`:
   1. Choose runtime collector template
   2. Set project credential (`PROJECT_OTEL_TOKEN`)
   3. Set `service.name` (plus version/environment)
   4. Point collector to `ingest.observability.example.com` (OTLP/HTTP)
   5. Start application
5. Validate metrics, logs, and traces from one service.
6. Test RabbitMQ, Camunda, and Angular traces.
7. Test quotas, rotation, PII scrubbing, and isolation:
   - send with the project credential but `project.id` of another project;
     telemetry must still land under the credential owner's tenant
     (see `docs/tenant-isolation.md` for the exact spoofing test).
8. Enable dashboards and alerts.
