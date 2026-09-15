# Collector outage

1. Check gateway and collector health.
2. Check queue depth and exporter retry rate.
3. Confirm the backend is reachable.
4. Inspect dropped telemetry counters.
5. Restore capacity or restart the failed replica.
6. Verify ingestion from each affected project.
7. Record data loss, duration, and corrective action.

The platform must fail visibly. Silent telemetry loss is an incident.
