# Telemetry contract

Every signal must include:
- service.name
- service.version
- deployment.environment

Authentication: every OTLP/HTTP request to the central gateway must carry
`Authorization: Bearer <project-token>` (see `projects/collector-template.yml`).

Tenant identity: the platform derives project identity from the
authenticated credential (`credential -> project_id`). `project.id` supplied
by the client is NOT trusted and is overwritten by the gateway pipeline.
Applications must not choose their tenant.
- trace_id and span_id where applicable

Rules:
- Use normalized routes, never raw URLs.
- Do not log tokens, passwords, payloads, or personal data.
- Keep metric labels low-cardinality.
- Propagate W3C trace context through HTTP and RabbitMQ.
- Use sampling for high-volume traces.
