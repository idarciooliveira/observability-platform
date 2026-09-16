#!/usr/bin/env python3
"""Add a new instance (company x project) to the observability platform.

Decision (company orgs, soft project isolation, proxy-ready):
  tenant (company, hard storage isolation): keve, bci
  project (soft query isolation): ubix, digiflow
  instance (ingest identity, 1 credential -> 1 pipeline): <company>_<project>

Grafana orgs are per COMPANY (Main:2, keve:3, bci:4 on fresh Grafana 12 —
org 1 is the bootstrap admin's personal org and is unused); projects live
inside their company org as folders/teams with a fixed project.id filter.
Adding an instance to an existing company reuses that company's org and
datasources. A brand-new company gets the next free org id plus 3 fresh
datasources.

Idempotently edits (text-preserving, no YAML round-trip so comments survive):

  - projects/tenants.yml (tenant entry + instance entry)
  - deploy/collector/tenant-routing.yml
  - deploy/collector/collector-config.yml (receiver, transform setting BOTH
    tenant.id + project.id, shared company exporters, 3 pipelines)
  - compose.prod.yml + compose.local.yml (gateway wiring; ORG_MAPPING in
    compose.local.yml)
  - .env.example
  - grafana/datasources.yml (3 per-company datasources scoped to the
    company org, header = company; new companies only)

It never writes real secrets to the repo. It generates a token with
``secrets.token_hex(32)`` (equivalent to ``openssl rand -hex 32``), prints the
``export`` line for the secret manager, and writes only a
``changeme-<instance>-token`` placeholder to ``.env.example``.

Grafana org creation is NOT automated: orgs can only be created against a
running Grafana (API/UI). New companies need a company org whose id must
match the script's --grafana-org-id; instances in an existing company
reuse that company's org and need no manual Grafana step.

Usage:
  python3 scripts/add-instance.py keve ubix
  python3 scripts/add-instance.py bci onboarding --dry-run
  python3 scripts/add-instance.py keve ubix --port 4323 --no-token
  python3 scripts/add-instance.py keve ubix --grafana-org-id 6

After running:
  python3 -m pytest gateway/tests/ tests/ -v
  docker compose -f compose.local.yml up -d --build
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
COMPOSE_PROD = ROOT / "compose.prod.yml"
COMPOSE_LOCAL = ROOT / "compose.local.yml"
ENV_EXAMPLE = ROOT / ".env.example"
DATASOURCES = ROOT / "grafana/datasources.yml"

ID_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")


def fail(msg):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def next_free_port(texts, default=4319):
    ports = []
    for text in texts:
        ports += [int(p) for p in re.findall(r"otel-collector:(\d+)", text)]
        ports += [int(p) for p in re.findall(r"0\.0\.0\.0:(\d+)", text)]
    ports = [p for p in ports if 4300 <= p < 4500]
    return max(ports) + 1 if ports else default


def next_free_org_id(text, default=2):
    ids = [int(i) for i in re.findall(r"orgId:\s*(\d+)", text)]
    return max(ids) + 1 if ids else default


def company_org_id(datasources_text, company):
    """Return the Grafana org id for a company, allocating a new one only
    for companies without datasources yet."""
    m = re.search(
        rf"^  - name: {re.escape(company)}-metrics\s*\n(?:.*\n)*?\s*orgId:\s*(\d+)",
        datasources_text,
        re.M,
    )
    if m:
        return int(m.group(1))
    return next_free_org_id(datasources_text)


def ensure_tenants_yml(text, company, project, instance, org_id, grafana_org):
    changed = False
    # 1. Tenant entry: `- id: <company>` with `projects: [...]` containing project.
    m = re.search(rf"^  - id: {re.escape(company)}\s*$\n((?:^    .*\n)*)", text, re.M)
    if not m:
        entry = (
            f"  - id: {company}\n"
            f"    display_name: {company.upper()}\n"
            f"    projects: [{project}]\n"
        )
        anchor = "tenants:\n"
        if anchor in text:
            text = text.replace(anchor, anchor + entry, 1)
        else:
            text = text.rstrip("\n") + "\n" + entry
        changed = True
    else:
        block = m.group(0)
        pm = re.search(r"projects:\s*\[([^\]]*)\]", block)
        if pm:
            projects = [p.strip() for p in pm.group(1).split(",") if p.strip()]
            if project not in projects:
                new_block = block.replace(
                    pm.group(0), f"projects: [{', '.join(projects + [project])}]", 1
                )
                text = text.replace(block, new_block, 1)
                changed = True
        else:
            new_block = block.rstrip("\n") + f"\n    projects: [{project}]\n"
            text = text.replace(block, new_block, 1)
            changed = True
    # 2. Instance entry under `instances:`.
    if not re.search(rf"^  - id: {re.escape(instance)}\s*$", text, re.M):
        entry = (
            f"  - id: {instance}\n"
            f"    tenant: {company}\n"
            f"    project: {project}\n"
            f"    grafana_org_id: {org_id}\n"
            f"    grafana_org: {grafana_org}\n"
        )
        if "instances:\n" in text:
            # Append at end of instances list (before trailing anchor comment).
            anchor = "# Keep this registry as the source of truth for onboarding."
            if anchor in text:
                # Insert before the anchor, keeping list order.
                lines = text.splitlines(keepends=True)
                idx = next(i for i, l in enumerate(lines) if anchor in l)
                # Find last instance entry end: insert right before anchor block.
                text = "".join(lines[:idx]) + entry + "".join(lines[idx:])
            else:
                text = text.rstrip("\n") + "\n" + entry
        else:
            text = text.rstrip("\n") + f"\ninstances:\n{entry}"
        changed = True
    return text, changed


def ensure_routing_yml(text, instance, company, project, port):
    prefix = instance.upper()
    if re.search(rf"^  {re.escape(instance)}:\s*$", text, re.M):
        return text, False
    block = (
        f"  {instance}:\n"
        f"    tenant: {instance}\n"
        f"    project: {project}\n"
        f"    storage_tenant: {company} # sent as X-Scope-OrgID to Mimir, Loki and Tempo\n"
        f"    token_env: {prefix}_OTEL_TOKEN\n"
        f"    collector_receiver: otlp/{instance}\n"
        f"    collector_upstream: http://otel-collector:{port}\n"
        f"    max_series: 250000\n"
        f"    log_rate_mb: 20\n"
    )
    text = text.rstrip("\n") + "\n" + block
    # Extend gateway tenants comment list (cosmetic, best-effort).
    text, _ = re.subn(
        r'tenants_env: GATEWAY_TENANTS\s+# "([^"]+)"',
        lambda m: f'tenants_env: GATEWAY_TENANTS  # "{m.group(1)},{instance}"'
        if instance not in m.group(1).split(",")
        else m.group(0),
        text,
        count=1,
    )
    return text, True


def ensure_collector_cfg(text, instance, company, project, port, template="keve_ubix"):
    changed = False
    if f"otlp/{instance}:" in text or f"transform/{instance}_identity:" in text:
        # Receiver/processor exist; still ensure company exporters + pipelines.
        pass
    else:
        for marker in (f"otlp/{template}:", f"transform/{template}_identity:"):
            if marker not in text:
                fail(f"template block {marker} not found in collector-config.yml")
        lines = text.splitlines(keepends=True)

        def find_line(start, needle):
            for i in range(start, len(lines)):
                if needle in lines[i]:
                    return i
            return -1

        recv_start = find_line(0, f"  otlp/{template}:")
        recv_end = find_line(recv_start, "include_metadata: true")
        new_recv = (
            f"  otlp/{instance}:\n"
            f"    protocols:\n"
            f"      http:\n"
            f"        endpoint: 0.0.0.0:{port}\n"
            f"        include_metadata: true\n"
        )
        lines.insert(recv_end + 1, new_recv)
        text = "".join(lines)
        lines = text.splitlines(keepends=True)

        proc_start = find_line(0, f"  transform/{template}_identity:")
        needle = f'set(attributes["project.id"]'
        proc_end = -1
        for i in range(proc_start, len(lines)):
            if needle in lines[i]:
                proc_end = i
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
            f"  transform/{instance}_identity:\n"
            f"    error_mode: ignore\n"
            f"    trace_statements:\n"
            f"      - context: resource\n"
            f"        statements:\n"
            f'          - set(attributes["tenant.id"], "{company}")\n'
            f'          - set(attributes["project.id"], "{project}")\n'
            f"    metric_statements:\n"
            f"      - context: resource\n"
            f"        statements:\n"
            f'          - set(attributes["tenant.id"], "{company}")\n'
            f'          - set(attributes["project.id"], "{project}")\n'
            f"    log_statements:\n"
            f"      - context: resource\n"
            f"        statements:\n"
            f'          - set(attributes["tenant.id"], "{company}")\n'
            f'          - set(attributes["project.id"], "{project}")\n'
        )
        lines.insert(proc_end + 1, new_proc)
        text = "".join(lines)
        lines = text.splitlines(keepends=True)
        changed = True

    # Ensure shared company exporters exist.
    for backend, endpoint in (
        ("mimir", "http://mimir:9009/otlp"),
        ("loki", "http://loki:3100/otlp"),
        ("tempo", "http://tempo:4318"),
    ):
        if f"otlphttp/{backend}_{company}:" not in text:
            # Insert after the template company's block if present, else append
            # before `service:`.
            anchor = None
            for cand in (template.split("_")[0], "keve", "bci"):
                idx = text.find(f"  otlphttp/{backend}_{cand}:")
                if idx != -1:
                    # End of that block = its sending_queue line.
                    m = re.search(
                        rf"  otlphttp/{backend}_{re.escape(cand)}:.*?"
                        r"sending_queue: \{[^\n]*\}\n",
                        text,
                        re.S,
                    )
                    if m:
                        anchor = m.group(0)
                        break
            new_exp = (
                f"  otlphttp/{backend}_{company}:\n"
                f"    endpoint: {endpoint}\n"
                f"    headers:\n"
                f"      X-Scope-OrgID: {company}\n"
                f"    retry_on_failure: {{ enabled: true }}\n"
                f"    sending_queue: {{ enabled: true, queue_size: 10000 }}\n"
            )
            if anchor:
                text = text.replace(anchor, anchor + new_exp, 1)
            else:
                text = text.replace("service:\n", new_exp + "\nservice:\n", 1)
            changed = True

    # Ensure 3 pipelines for the instance.
    lines = text.splitlines(keepends=True)

    def find_line2(start, needle):
        for i in range(start, len(lines)):
            if needle in lines[i]:
                return i
        return -1

    new_pipes = ""
    for signal, backend in (("traces", "tempo"), ("metrics", "mimir"), ("logs", "loki")):
        if f"    {signal}/{instance}:" not in text:
            new_pipes += (
                f"    {signal}/{instance}:\n"
                f"      receivers: [otlp/{instance}]\n"
                f"      processors: [memory_limiter, transform/{instance}_identity, transform/redact_pii, batch]\n"
                f"      exporters: [otlphttp/{backend}_{company}, debug]\n"
            )
    if new_pipes:
        # Append after the last pipeline block (end of file).
        text = text.rstrip("\n") + "\n" + new_pipes
        changed = True
    return text, changed


def ensure_compose_gateway(text, instance, port):
    prefix = instance.upper()
    changed = False
    m = re.search(r"GATEWAY_TENANTS:\s*(\S+)", text)
    if not m:
        fail("GATEWAY_TENANTS not found in compose file")
    tenants = [t.strip() for t in m.group(1).split(",")]
    if instance not in tenants:
        text = text.replace(
            f"GATEWAY_TENANTS: {m.group(1)}",
            f"GATEWAY_TENANTS: {','.join(tenants + [instance])}",
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
            fail("no existing _OTEL_TOKEN line to anchor on in compose file")
        text = text.replace(anchor, anchor + "\n" + token_line, 1)
        changed = True
    upstream_line = f"      {prefix}_UPSTREAM: http://otel-collector:{port}"
    if prefix + "_UPSTREAM" not in text:
        upstreams = [l for l in text.splitlines() if "_UPSTREAM:" in l]
        text = text.replace(upstreams[-1], upstreams[-1] + "\n" + upstream_line, 1)
        changed = True
    return text, changed


def ensure_org_mapping(text, instance, company_org_id):
    group_base = instance.replace("_", "-")
    if f"{group_base}-viewers:" in text:
        return text, False
    m = re.search(r'GF_AUTH_GENERIC_OAUTH_ORG_MAPPING:\s*"([^"]*)"', text)
    if not m:
        return text, False  # prod compose has no OIDC block: nothing to do
    entries = f"{group_base}-viewers:{company_org_id}:Viewer, {group_base}-editors:{company_org_id}:Editor"
    inner = m.group(1).rstrip()
    sep = ", " if inner else ""
    return text.replace(
        m.group(0),
        f'GF_AUTH_GENERIC_OAUTH_ORG_MAPPING: "{inner}{sep}{entries}"',
        1,
    ), True


def ensure_role_path(text, instance):
    group_base = instance.replace("_", "-")
    m = re.search(r'GF_AUTH_GENERIC_OAUTH_ROLE_ATTRIBUTE_PATH:\s*"([^"]*)"', text)
    if not m or f"{group_base}-editors" in m.group(1):
        return text, False
    inner = m.group(1)
    marker = " || 'Viewer'"
    addition = f" || contains(groups[*], '{group_base}-editors') && 'Editor'"
    if marker in inner:
        inner = inner.replace(marker, addition + marker, 1)
    else:
        inner = inner + addition
    return text.replace(m.group(0), f'GF_AUTH_GENERIC_OAUTH_ROLE_ATTRIBUTE_PATH: "{inner}"', 1), True


def ensure_env_example(text, instance):
    prefix = instance.upper()
    if re.search(rf"^{re.escape(prefix)}_OTEL_TOKEN=", text, re.M):
        return text, False
    if not text.endswith("\n"):
        text += "\n"
    return text + f"{prefix}_OTEL_TOKEN=changeme-{instance}-token\n", True


def ensure_datasources(text, instance, company, org_id, template="keve"):
    """Ensure the 3 per-company datasources exist. Instances in an existing
    company reuse them (no change); a new company is cloned from the
    template company's blocks with name/header/orgId swapped."""
    sec = re.search(r"^datasources:\s*$\n?", text, re.M)
    if not sec:
        fail("datasources: section not found in grafana/datasources.yml")
    if re.search(rf"^  - name: {re.escape(company)}-metrics\s*$", text, re.M):
        return text, False
    head, body = text[: sec.end()], text[sec.end():]
    changed = False
    for sig in ("metrics", "logs", "traces"):
        m = re.search(
            rf"(^  - name: {re.escape(template)}-{sig}\s*\n(?:.*\n)*?)"
            r"(?=^  - name: |\Z|^# Repeat)",
            body,
            re.M,
        )
        if not m:
            fail(f"template datasource {template}-{sig} not found")
        new = m.group(1).replace(f"name: {template}-{sig}", f"name: {company}-{sig}")
        new = re.sub(r"orgId:\s*\d+", f"orgId: {org_id}", new)
        # Template header is a company (keve/bci): swap to the new company.
        new = re.sub(r"httpHeaderValue1: \S+", f"httpHeaderValue1: {company}", new)
        body = body.replace(m.group(1), m.group(1) + new, 1)
        changed = True
    return head + body, changed


def main():
    ap = argparse.ArgumentParser(description="Add a company x project instance.")
    ap.add_argument("company", help="company id, e.g. keve")
    ap.add_argument("project", help="project id, e.g. ubix")
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--grafana-org-id", type=int, default=None)
    ap.add_argument("--template", default="keve")
    ap.add_argument("--no-token", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    company = args.company.strip().lower()
    project = args.project.strip().lower()
    for label, val in (("company", company), ("project", project)):
        if not ID_RE.match(val):
            fail(f"{label} id must match [a-z0-9]([a-z0-9-]*[a-z0-9])?")
    instance = f"{company}_{project}"
    prefix = instance.upper()
    grafana_org = company

    routing_text = ROUTING.read_text()
    collector_text = COLLECTOR_CFG.read_text()
    existing = re.search(
        rf"^  {re.escape(instance)}:[\s\S]*?collector_upstream: http://otel-collector:(\d+)",
        routing_text,
        re.M,
    )
    port = args.port or (int(existing.group(1)) if existing else next_free_port([routing_text, collector_text]))
    if not (4300 <= port < 4500):
        fail(f"--port {port} looks wrong; expected 43xx-44xx")

    datasources_text = DATASOURCES.read_text()
    # Company orgs are shared: reuse the company's org id when its
    # datasources exist, else take the next free id (new company).
    if args.grafana_org_id is not None:
        org_id = args.grafana_org_id
    else:
        org_id = company_org_id(datasources_text, company)
    if org_id < 3:
        fail(f"--grafana-org-id {org_id} looks wrong; orgs 1-2 are reserved (personal + Main Org)")

    token = None if args.no_token else secrets.token_hex(32)

    edits = {}
    edits[str(TENANTS)] = ensure_tenants_yml(
        TENANTS.read_text(), company, project, instance, org_id, grafana_org
    )
    edits[str(ROUTING)] = ensure_routing_yml(routing_text, instance, company, project, port)
    edits[str(COLLECTOR_CFG)] = ensure_collector_cfg(
        collector_text, instance, company, project, port, args.template
    )
    prod_text, prod_changed = ensure_compose_gateway(COMPOSE_PROD.read_text(), instance, port)
    edits[str(COMPOSE_PROD)] = (prod_text, prod_changed)
    local_text, local_changed = ensure_compose_gateway(COMPOSE_LOCAL.read_text(), instance, port)
    local_text2, map_changed = ensure_org_mapping(local_text, instance, org_id)
    local_text3, role_changed = ensure_role_path(local_text2, instance)
    edits[str(COMPOSE_LOCAL)] = (local_text3, local_changed or map_changed or role_changed)
    edits[str(ENV_EXAMPLE)] = ensure_env_example(ENV_EXAMPLE.read_text(), instance)
    edits[str(DATASOURCES)] = ensure_datasources(
        datasources_text, instance, company, org_id, args.template
    )

    changed_files = [f for f, (_, c) in edits.items() if c]
    if args.dry_run:
        print(f"instance={instance} company={company} project={project} port={port} grafana_org_id={org_id} token_env={prefix}_OTEL_TOKEN")
        print(f"would change: {', '.join(changed_files) or '(nothing - already present)'}")
        if token:
            print(f"generated token (store in secret manager, NOT in git):\n  {prefix}_OTEL_TOKEN={token}")
        return

    for path, (new_text, _) in edits.items():
        Path(path).write_text(new_text)

    print(f"added instance '{instance}' (company={company} project={project}) on port {port} (company org '{company}' id {org_id})")
    for f in changed_files:
        print(f"  updated {Path(f).relative_to(ROOT)}")
    if not changed_files:
        print("  (nothing to change - instance already present)")
    if token:
        print(f"\nStore this in the secret manager and hand it to the project team:")
        print(f"  {prefix}_OTEL_TOKEN={token}")
        print(f"Deploy with: {prefix}_OTEL_TOKEN=<token> docker compose -f compose.prod.yml up -d --build")
    print(
        f"\nManual - only for a NEW company (orgs cannot be file-provisioned):\n"
        f"  1. Create the Grafana org named '{company}' (API or admin UI).\n"
        f"     It MUST get id {org_id}; if it gets another id, re-run with\n"
        f"     --grafana-org-id <actual-id> to rewrite the files.\n"
        f"     Instances in an existing company reuse its org: skip this.\n"
        f"  2. Keycloak: create groups '{instance.replace('_', '-')}-viewers' and\n"
        f"     '{instance.replace('_', '-')}-editors' (plus '{company}-admins' for\n"
        f"     company admins).\n"
        f"  3. In org '{company}', add a folder per project and set each\n"
        f"     dashboard's project.id filter; restrict the folders with Teams.\n"
        f"  4. Redeploy Grafana, have users log out/in, then verify Explore in\n"
        f"     org '{company}' shows only {company}-* sources."
    )
    print("\nNext: python3 -m pytest gateway/tests/ tests/ -v")


if __name__ == "__main__":
    main()
