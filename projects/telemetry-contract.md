# Telemetry contract

Every signal must include:
- service.name
- service.version
- deployment.environment

The platform derives project.id from authenticated project identity. Applications must not choose their tenant.
- trace_id and span_id where applicable

Rules:
- Use normalized routes, never raw URLs.
- Do not log tokens, passwords, payloads, or personal data.
- Keep metric labels low-cardinality.
- Propagate W3C trace context through HTTP and RabbitMQ.
- Use sampling for high-volume traces.
