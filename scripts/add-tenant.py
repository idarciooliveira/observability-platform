#!/usr/bin/env python3
"""Add a new tenant/project to the observability platform.

Idempotently edits (text-preserving, no YAML round-trip so comments survive):

  - projects/tenants.yml
  - deploy/collector/tenant-routing.yml
  - deploy/collector/collector-config.yml
  - compose.prod.yml (gateway wiring + Grafana org mapping)
  - .env.example
  - grafana/datasources.yml (3 per-tenant datasources scoped to the tenant org)

It never writes real secrets to the repo. It generates a token with
``secrets.token_hex(32)`` (equivalent to ``openssl rand -hex 32``), prints the
``export`` line for the secret manager, and writes only a
``changeme-<tenant>-token`` placeholder to ``.env.example``.

Grafana org creation is NOT automated: orgs can only be created against a
running Grafana (API/UI), so the script reserves the next free org id,
writes the files against it, and prints the manual org-creation step.
If the created org gets a different id, re-run with --grafana-org-id.

Usage:
  python3 scripts/add-tenant.py onboarding
  python3 scripts/add-tenant.py onboarding --display-name Onboarding --dry-run
  python3 scripts/add-tenant.py onboarding --port 4321 --no-token
  python3 scripts/add-tenant.py onboarding --grafana-org-id 4

After running:
  python3 -m pytest gateway/tests/ tests/ -v
  docker compose -f compose.prod.yml up -d --build
"""

import argparse
import re
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TENANTS = ROOT / "projects/tenants.yml"
ROUTING = ROOT / "deploy/collector/tenant-routing.yml"
COLLECTOR_CFG = ROOT / "deploy/collector/collector-config.yml"
COMPOSE = ROOT / "compose.prod.yml"
ENV_EXAMPLE = ROOT / ".env.example"
DATASOURCES = ROOT / "grafana/datasources.yml"

TENANT_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")


def fail(msg):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def next_free_port(texts, default=4319):
    ports = []
    for text in texts:
        ports += [int(p) for p in re.findall(r"otel-collector:(\d+)", text)]
        ports += [int(p) for p in re.findall(r"0\.0\.0\.0:(\d+)", text)]
    ports = [p for p in ports if 4300 <= p < 4400]
    return max(ports) + 1 if ports else default


def add_tenants_yml(text, tenant, display, owner_group, grafana_org, envs):
    if re.search(rf"^  - id: {re.escape(tenant)}\s*$", text, re.M):
        return text, False
    env_list = "[" + ", ".join(envs) + "]"
    entry = (
        f"  - id: {tenant}\n"
        f"    display_name: {display}\n"
        f"    owner_group: {owner_group}\n"
        f"    grafana_org: {grafana_org}\n"
        f"    environments: {env_list}\n"
    )
    anchor = "# Keep this registry as the source of truth for onboarding."
    if anchor in text:
        return text.replace(anchor, entry + "\n" + anchor), True
    return text.rstrip("\n") + "\n" + entry, True


def add_routing_yml(text, tenant, port):
    prefix = tenant.upper().replace("-", "_")
    changed = False
    if re.search(rf"^  {re.escape(tenant)}:\s*$", text, re.M):
        return text, False
    block = (
        f"  {tenant}:\n"
        f"    token_env: {prefix}_OTEL_TOKEN\n"
        f"    collector_receiver: otlp/{tenant}\n"
        f"    collector_upstream: http://otel-collector:{port}\n"
        f"    storage_tenant: {tenant} # sent as X-Scope-OrgID to Mimir, Loki and Tempo\n"
        f"    max_series: 250000\n"
        f"    log_rate_mb: 20\n"
    )
    text = text.rstrip("\n") + "\n" + block
    changed = True
    # Keep header comments accurate (cosmetic, best-effort): append the new
    # token env var to the list instead of replacing it.
    def _extend_token_list(m):
        names = [n.strip().rstrip(".") for n in m.group(1).split(",")]
        names = [n for n in names if n]
        if prefix in names:
            return m.group(0)
        return f"#   {', '.join(names + [prefix + '_OTEL_TOKEN'])} (see .env.example)."

    text, n1 = re.subn(
        r"^#\s+(UBIX_OTEL_TOKEN.*)\(see \.env\.example\)\.\s*$",
        _extend_token_list,
        text,
        count=1,
        flags=re.M,
    )
    text, n3 = re.subn(
        r'tenants_env: GATEWAY_TENANTS\s+# "([^"]+)"',
        lambda m: f'tenants_env: GATEWAY_TENANTS  # "{m.group(1)},{tenant}"'
        if tenant not in m.group(1).split(",")
        else m.group(0),
        text,
        count=1,
    )
    return text, changed or bool(n1 or n3)


def add_collector_cfg(text, tenant, port, template="digiflow"):
    if f"otlp/{tenant}:" in text or f"transform/{tenant}_identity:" in text:
        return text, False
    for marker in (
        f"otlp/{template}:",
        f"transform/{template}_identity:",
        f"otlphttp/mimir_{template}:",
        f"otlphttp/loki_{template}:",
        f"otlphttp/tempo_{template}:",
        f"traces/{template}:",
        f"metrics/{template}:",
        f"logs/{template}:",
    ):
        if marker not in text:
            fail(f"template block {marker} not found in collector-config.yml")
    lines = text.splitlines(keepends=True)

    def find_line(start, needle):
        for i in range(start, len(lines)):
            if needle in lines[i]:
                return i
        return -1

    # 1. Receiver: insert after the template receiver's include_metadata line.
    recv_start = find_line(0, f"  otlp/{template}:")
    recv_end = find_line(recv_start, "include_metadata: true")
    new_recv = (
        f"  otlp/{tenant}:\n"
        f"    protocols:\n"
        f"      http:\n"
        f"        endpoint: 0.0.0.0:{port}\n"
        f"        include_metadata: true\n"
    )
    lines.insert(recv_end + 1, new_recv)
    text = "".join(lines)
    lines = text.splitlines(keepends=True)

    # 2. Identity processor: insert after the template block's last project.id line.
    proc_start = find_line(0, f"  transform/{template}_identity:")
    # Block ends at the last set(project.id, "<template>") line after proc_start.
    proc_end = -1
    needle = f'set(attributes["project.id"], "{template}")'
    for i in range(proc_start, len(lines)):
        if needle in lines[i]:
            proc_end = i
        # Stop at the next sibling processor/exporter section header.
        if i > proc_start and (
            lines[i].startswith("  transform/")
            or lines[i].startswith("  # Minimal")
            or lines[i].startswith("exporters:")
        ):
            break
    if proc_end == -1:
        fail(f"template processor transform/{template}_identity body not found")
    new_proc = (
        f"\n"
        f"  transform/{tenant}_identity:\n"
        f"    error_mode: ignore\n"
        f"    trace_statements:\n"
        f"      - context: resource\n"
        f"        statements:\n"
        f'          - set(attributes["project.id"], "{tenant}")\n'
        f"    metric_statements:\n"
        f"      - context: resource\n"
        f"        statements:\n"
        f'          - set(attributes["project.id"], "{tenant}")\n'
        f"    log_statements:\n"
        f"      - context: resource\n"
        f"        statements:\n"
        f'          - set(attributes["project.id"], "{tenant}")\n'
    )
    lines.insert(proc_end + 1, new_proc)
    text = "".join(lines)
    lines = text.splitlines(keepends=True)

    # 3. Exporters: insert each new backend block after the template one.
    for backend, endpoint in (
        ("mimir", "http://mimir:9009/otlp"),
        ("loki", "http://loki:3100/otlp"),
        ("tempo", "http://tempo:4318"),
    ):
        idx = find_line(0, f"  otlphttp/{backend}_{template}:")
        # Template block ends at its sending_queue line.
        end = find_line(idx, "sending_queue:")
        new_exp = (
            f"  otlphttp/{backend}_{tenant}:\n"
            f"    endpoint: {endpoint}\n"
            f"    headers:\n"
            f"      X-Scope-OrgID: {tenant}\n"
            f"    retry_on_failure: {{ enabled: true }}\n"
            f"    sending_queue: {{ enabled: true, queue_size: 10000 }}\n"
        )
        lines.insert(end + 1, new_exp)
        text = "".join(lines)
        lines = text.splitlines(keepends=True)

    # 4. Pipelines: append the three new pipelines after logs/<template>.
    idx = find_line(0, f"    logs/{template}:")
    end = find_line(idx, f"otlphttp/loki_{template}")
    new_pipes = "".join(
        f"    {signal}/{tenant}:\n"
        f"      receivers: [otlp/{tenant}]\n"
        f"      processors: [memory_limiter, transform/{tenant}_identity, transform/redact_pii, batch]\n"
        f"      exporters: [otlphttp/{backend}_{tenant}, debug]\n"
        for signal, backend in (("traces", "tempo"), ("metrics", "mimir"), ("logs", "loki"))
    )
    # Insert traces+metrics+logs as one block to keep them together.
    lines.insert(end + 1, new_pipes)
    text = "".join(lines)

    return text, True


def add_compose(text, tenant, port):
    prefix = tenant.upper().replace("-", "_")
    changed = False
    m = re.search(r"GATEWAY_TENANTS:\s*(\S+)", text)
    if not m:
        fail("GATEWAY_TENANTS not found in compose.prod.yml")
    tenants = [t.strip() for t in m.group(1).split(",")]
    if tenant not in tenants:
        text = text.replace(
            f"GATEWAY_TENANTS: {m.group(1)}",
            f"GATEWAY_TENANTS: {','.join(tenants + [tenant])}",
            1,
        )
        changed = True
    token_line = f"      {prefix}_OTEL_TOKEN: ${{{prefix}_OTEL_TOKEN:?{prefix}_OTEL_TOKEN is not set}}"
    if prefix + "_OTEL_TOKEN" not in text:
        anchor = None
        for line in text.splitlines():
            if "_OTEL_TOKEN:" in line:
                anchor = line
        if anchor is None:
            fail("no existing _OTEL_TOKEN line to anchor on in compose.prod.yml")
        text = text.replace(anchor, anchor + "\n" + token_line, 1)
        changed = True
    upstream_line = f"      {prefix}_UPSTREAM: http://otel-collector:{port}"
    if prefix + "_UPSTREAM" not in text:
        # Anchor on the last existing _UPSTREAM line.
        upstreams = [l for l in text.splitlines() if "_UPSTREAM:" in l]
        text = text.replace(upstreams[-1], upstreams[-1] + "\n" + upstream_line, 1)
        changed = True
    return text, changed


def add_env_example(text, tenant):
    prefix = tenant.upper().replace("-", "_")
    if re.search(rf"^{re.escape(prefix)}_OTEL_TOKEN=", text, re.M):
        return text, False
    if not text.endswith("\n"):
        text += "\n"
    return text + f"{prefix}_OTEL_TOKEN=changeme-{tenant}-token\n", True


def next_free_org_id(text, default=2):
    ids = [int(i) for i in re.findall(r"orgId:\s*(\d+)", text)]
    return max(ids) + 1 if ids else default


def add_datasources(text, tenant, org_id, template="digiflow"):
    # Only the datasources: section carries full blocks; the
    # deleteDatasources: section above it has same-indented 2-line
    # entries that must never be used as copy templates.
    sec = re.search(r"^datasources:\s*$\n?", text, re.M)
    if not sec:
        fail("datasources: section not found in grafana/datasources.yml")
    head, body = text[: sec.end()], text[sec.end():]
    changed = False
    for sig in ("metrics", "logs", "traces"):
        if re.search(rf"^  - name: {re.escape(tenant)}-{sig}\s*$", body, re.M):
            continue  # already present: idempotent
        m = re.search(
            rf"(^  - name: {re.escape(template)}-{sig}\s*\n(?:.*\n)*?)"
            r"(?=^  - name: |\Z|^# Repeat)",
            body,
            re.M,
        )
        if not m:
            fail(f"template datasource {template}-{sig} not found in grafana/datasources.yml")
        new = m.group(1).replace(f"name: {template}-{sig}", f"name: {tenant}-{sig}")
        new = re.sub(r"orgId:\s*\d+", f"orgId: {org_id}", new)
        new = new.replace(f"httpHeaderValue1: {template}", f"httpHeaderValue1: {tenant}")
        body = body.replace(m.group(1), m.group(1) + new, 1)
        changed = True
    return head + body, changed


def add_org_mapping(text, tenant, org_id):
    if f"{tenant}-viewers:" in text:
        return text, False  # already present: idempotent
    m = re.search(r'GF_AUTH_GENERIC_OAUTH_ORG_MAPPING:\s*"([^"]*)"', text)
    if not m:
        fail(
            "GF_AUTH_GENERIC_OAUTH_ORG_MAPPING not found in compose.prod.yml - "
            "wire prod Grafana OIDC first (one-time step, see runbook)."
        )
    entries = f"{tenant}-viewers:{org_id}:Viewer, {tenant}-editors:{org_id}:Editor"
    inner = m.group(1).rstrip()
    sep = ", " if inner else ""
    return text.replace(
        m.group(0),
        f'GF_AUTH_GENERIC_OAUTH_ORG_MAPPING: "{inner}{sep}{entries}"',
        1,
    ), True


def main():
    ap = argparse.ArgumentParser(description="Add a new tenant to the platform.")
    ap.add_argument("tenant", help="lowercase id, e.g. onboarding")
    ap.add_argument("--display-name", default=None)
    ap.add_argument("--owner-group", default=None)
    ap.add_argument("--grafana-org", default=None)
    ap.add_argument("--environments", default="dev,staging,production")
    ap.add_argument("--port", type=int, default=None, help="internal collector port (default: max+1)")
    ap.add_argument("--grafana-org-id", type=int, default=None, help="Grafana org id (default: max+1 in grafana/datasources.yml)")
    ap.add_argument("--template", default="digiflow", help="tenant to copy blocks from")
    ap.add_argument("--no-token", action="store_true", help="do not generate a token")
    ap.add_argument("--dry-run", action="store_true", help="print what would change, write nothing")
    args = ap.parse_args()

    tenant = args.tenant.strip().lower()
    if not TENANT_RE.match(tenant):
        fail("tenant id must match [a-z0-9]([a-z0-9-]*[a-z0-9])?")
    prefix = tenant.upper().replace("-", "_")
    display = args.display_name or tenant.capitalize()
    owner_group = args.owner_group or f"{tenant}-editors"
    grafana_org = args.grafana_org or tenant
    envs = [e.strip() for e in args.environments.split(",") if e.strip()] or ["production"]

    routing_text = ROUTING.read_text()
    collector_text = COLLECTOR_CFG.read_text()
    # If the tenant already exists, reuse its port so re-runs are stable.
    existing = re.search(
        rf"^  {re.escape(tenant)}:[\s\S]*?collector_upstream: http://otel-collector:(\d+)",
        routing_text,
        re.M,
    )
    port = args.port or (int(existing.group(1)) if existing else next_free_port([routing_text, collector_text]))
    if not (4300 <= port < 4500):
        fail(f"--port {port} looks wrong; expected 43xx-44xx")

    datasources_text = DATASOURCES.read_text()
    already_onboarded = re.search(rf"^  - name: {re.escape(tenant)}-metrics\s*$", datasources_text, re.M)
    org_id = args.grafana_org_id or next_free_org_id(datasources_text)
    if org_id < 2:
        fail(f"--grafana-org-id {org_id} looks wrong; org 1 is Main Org, tenants start at 2")

    token = None if args.no_token else secrets.token_hex(32)

    edits = {}
    edits[str(TENANTS)] = add_tenants_yml(
        TENANTS.read_text(), tenant, display, owner_group, grafana_org, envs
    )
    edits[str(ROUTING)] = add_routing_yml(routing_text, tenant, port)
    edits[str(COLLECTOR_CFG)] = add_collector_cfg(collector_text, tenant, port, args.template)
    edits[str(COMPOSE)] = add_compose(COMPOSE.read_text(), tenant, port)
    edits[str(ENV_EXAMPLE)] = add_env_example(ENV_EXAMPLE.read_text(), tenant)
    edits[str(DATASOURCES)] = add_datasources(datasources_text, tenant, org_id, args.template)
    compose_text, compose_changed = edits[str(COMPOSE)]
    mapped_text, mapped_changed = add_org_mapping(compose_text, tenant, org_id)
    edits[str(COMPOSE)] = (mapped_text, compose_changed or mapped_changed)

    changed_files = [f for f, (_, c) in edits.items() if c]
    if already_onboarded and not args.grafana_org_id:
        print(f"note: tenant '{tenant}' already has datasources; pass --grafana-org-id to move them")
    if args.dry_run:
        print(f"tenant={tenant} port={port} grafana_org_id={org_id} token_env={prefix}_OTEL_TOKEN")
        print(f"would change: {', '.join(changed_files) or '(nothing - already present)'}")
        if token:
            print(f"generated token (store in secret manager, NOT in git):\n  {prefix}_OTEL_TOKEN={token}")
        return

    for path, (new_text, _) in edits.items():
        Path(path).write_text(new_text)

    print(f"added tenant '{tenant}' on internal port {port} (grafana org id {org_id})")
    for f in changed_files:
        print(f"  updated {Path(f).relative_to(ROOT)}")
    if not changed_files:
        print("  (nothing to change - tenant already present)")
    if token:
        print(f"\nStore this in the secret manager and hand it to the project team:")
        print(f"  {prefix}_OTEL_TOKEN={token}")
        print(f"Deploy with: {prefix}_OTEL_TOKEN=<token> docker compose -f compose.prod.yml up -d --build")
    print(
        f"\nManual - needs the running stack (orgs cannot be file-provisioned):\n"
        f"  1. Create the Grafana org named '{grafana_org}' (API or admin UI).\n"
        f"     It MUST get id {org_id}; if it gets another id, re-run with\n"
        f"     --grafana-org-id <actual-id> to rewrite the files.\n"
        f"  2. Keycloak: create groups '{tenant}-viewers' and '{tenant}-editors'.\n"
        f"  3. Redeploy Grafana, have users log out/in (org membership applies at login),\n"
        f"     then verify Explore in org '{grafana_org}' shows only {tenant}-* sources."
    )
    print("\nNext: python3 -m pytest gateway/tests/ tests/ -v")


if __name__ == "__main__":
    main()
