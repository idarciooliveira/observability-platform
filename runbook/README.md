# Runbooks

Operational guides for the observability platform.

| Guide | When to use it |
|-------|----------------|
| [`onboarding-standard-collector.md`](onboarding-standard-collector.md) — Variant A | Default path: project runs a **local collector** next to its services (batching, offline queue, `service.name` defaults). |
| [`onboarding-direct-otlp-java.md`](onboarding-direct-otlp-java.md) — Variant B | Project runs **outside our infrastructure** (own VPS) and sends **direct OTLP/HTTP** to the central gateway with no local collector. Worked example: simple Java app as instance `bci_onboarding`. |

Both variants share the same platform-side steps, automated by
[`scripts/add-instance.py`](../scripts/add-instance.py):

```bash
python3 scripts/add-instance.py <company> <project> --dry-run   # preview
python3 scripts/add-instance.py <company> <project>             # edit files + print token
python3 -m pytest gateway/tests/ tests/ -v
```

Plus one manual step the script cannot do (orgs only exist at runtime):
create the Grafana org against the running Grafana and confirm its id
matches `--grafana-org-id` (re-run with the actual id if not). Details:
Variant A §1b.

Trust model (applies to both variants): instance identity comes **only**
from the authenticated Bearer credential. Client-supplied `tenant.id` /
`project.id` are routed to the credential owner's pipeline and overwritten
there, and client-supplied `X-Scope-OrgID` / `X-Tenant` headers are stripped
by the gateway. Storage isolation is per company (hard); project isolation
is soft. See `README.md` (Tenant isolation).
