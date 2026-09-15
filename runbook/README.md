# Runbooks

Operational guides for the observability platform.

| Guide | When to use it |
|-------|----------------|
| [`onboarding-standard-collector.md`](onboarding-standard-collector.md) — Variant A | Default path: project runs a **local collector** next to its services (batching, offline queue, `service.name` defaults). |
| [`onboarding-direct-otlp-java.md`](onboarding-direct-otlp-java.md) — Variant B | Project runs **outside our infrastructure** (own VPS) and sends **direct OTLP/HTTP** to the central gateway with no local collector. Worked example: simple Java app as tenant `onboarding`. |

Both variants share the same platform-side steps, automated by
[`scripts/add-tenant.py`](../scripts/add-tenant.py):

```bash
python3 scripts/add-tenant.py <tenant-id> --dry-run   # preview
python3 scripts/add-tenant.py <tenant-id>             # edit 5 files + print token
python3 -m pytest gateway/tests/ tests/ -v
```

Trust model (applies to both variants): tenant identity comes **only** from
the authenticated Bearer credential. Client-supplied `project.id` is routed
to the credential owner's pipeline and overwritten there, and
client-supplied `X-Scope-OrgID` / `X-Tenant` headers are stripped by the
gateway. See `README.md` (Tenant isolation).
