"""Static consistency tests: gateway, collector, registry and compose agree (Option B).

Model:
  tenant (company, HARD storage isolation): keve, bci -> X-Scope-OrgID.
  project (soft query isolation): ubix, digiflow -> project.id attribute.
  instance (ingest identity): keve_ubix, keve_digiflow, bci_ubix, bci_digiflow.

Run:  python3 -m pytest tests/ -v
Requires: pytest, pyyaml.
"""

import re
import urllib.parse
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
COLLECTOR_CFG = ROOT / "deploy/collector/collector-config.yml"
ROUTING = ROOT / "deploy/collector/tenant-routing.yml"
TENANTS = ROOT / "projects/tenants.yml"
ENV_EXAMPLE = ROOT / ".env.example"
COMPOSE = ROOT / "compose.prod.yml"
DATASOURCES = ROOT / "grafana/datasources.yml"

# Instances explicitly covered by name below (gateway upstreams, token envs).
# The full expected set is derived from the routing registry so that
# scripts/add-instance.py can add instances without editing this file.
BASE_INSTANCES = {"keve_ubix", "keve_digiflow", "bci_ubix", "bci_digiflow"}
BASE_COMPANIES = {"keve", "bci"}


def expected_instances():
    return set(yaml.safe_load(ROUTING.read_text())["tenants"])


@pytest.fixture(scope="module")
def collector():
    return yaml.safe_load(COLLECTOR_CFG.read_text())


@pytest.fixture(scope="module")
def routing():
    return yaml.safe_load(ROUTING.read_text())


def test_instance_sets_match_everywhere(routing):
    expected = expected_instances()
    assert set(routing["tenants"]) == expected
    assert expected >= BASE_INSTANCES
    registry = yaml.safe_load(TENANTS.read_text())
    tenants = {t["id"]: t for t in registry["tenants"]}
    assert set(tenants) >= BASE_COMPANIES
    instances = {i["id"]: i for i in registry.get("instances", [])}
    assert set(instances) >= BASE_INSTANCES
    for instance, info in routing["tenants"].items():
        assert info["tenant"] == instance
        assert info["project"] == instances[instance]["project"]
        assert info["storage_tenant"] == instances[instance]["tenant"]
        assert info["storage_tenant"] == tenants[info["storage_tenant"]]["id"]
        assert instances[instance]["project"] in tenants[info["storage_tenant"]]["projects"]


def test_per_instance_receivers_match_gateway_upstreams(collector, routing):
    receivers = collector["receivers"]
    for instance, info in routing["tenants"].items():
        name = info["collector_receiver"]
        assert name == f"otlp/{instance}"
        assert name in receivers
        endpoint = receivers[name]["protocols"]["http"]["endpoint"]
        port = endpoint.rsplit(":", 1)[1]
        upstream_port = str(urllib.parse.urlparse(info["collector_upstream"]).port)
        assert port == upstream_port, f"{instance}: receiver port != gateway upstream port"


def test_identity_processors_overwrite_both_ids(collector, routing):
    processors = collector["processors"]
    for instance, info in routing["tenants"].items():
        name = f"transform/{instance}_identity"
        assert name in processors
        cfg = processors[name]
        expected_tenant = f'set(attributes["tenant.id"], "{info["storage_tenant"]}")'
        expected_project = f'set(attributes["project.id"], "{info["project"]}")'
        for section in ("trace_statements", "metric_statements", "log_statements"):
            assert section in cfg, f"{name} missing {section}"
            joined = " ".join(
                str(s.get("statements", "")) for s in cfg[section]
            )
            assert expected_tenant in joined, f"{name}/{section} does not set tenant.id"
            assert expected_project in joined, f"{name}/{section} does not set project.id"


def test_company_exporters_use_company_header(collector, routing):
    exporters = collector["exporters"]
    companies = {info["storage_tenant"] for info in routing["tenants"].values()}
    assert companies >= BASE_COMPANIES
    for company in companies:
        for backend in ("mimir", "loki", "tempo"):
            name = f"otlphttp/{backend}_{company}"
            assert name in exporters, f"missing shared exporter {name}"
            headers = exporters[name].get("headers", {})
            assert headers.get("X-Scope-OrgID") == company
    # Exactly 6 shared exporters (2 companies x 3 backends), no per-instance ones.
    for instance in routing["tenants"]:
        for backend in ("mimir", "loki", "tempo"):
            assert f"otlphttp/{backend}_{instance}" not in exporters


def test_pipelines_wire_receiver_identity_to_company_exporter(collector, routing):
    pipelines = collector["service"]["pipelines"]
    assert len(pipelines) == 3 * len(routing["tenants"])
    for instance, info in routing["tenants"].items():
        receiver = info["collector_receiver"]
        identity = f"transform/{instance}_identity"
        company = info["storage_tenant"]
        for signal, backend in (("traces", "tempo"), ("metrics", "mimir"), ("logs", "loki")):
            pipe = pipelines[f"{signal}/{instance}"]
            assert receiver in pipe["receivers"]
            assert identity in pipe["processors"]
            assert f"otlphttp/{backend}_{company}" in pipe["exporters"]


def test_no_static_cross_company_header(collector, routing):
    companies = {info["storage_tenant"] for info in routing["tenants"].values()}
    text = COLLECTOR_CFG.read_text()
    for company in companies:
        for other in companies - {company}:
            # A <company> exporter block must never carry another company's header.
            for line_no, line in enumerate(text.splitlines(), 1):
                if f"_{company}:" in line:
                    context = "\n".join(text.splitlines()[max(0, line_no - 1):line_no + 6])
                    assert f"X-Scope-OrgID: {other}" not in context


def test_env_example_has_placeholders_not_secrets():
    text = ENV_EXAMPLE.read_text()
    routing = yaml.safe_load(ROUTING.read_text())
    prefixes = {info["token_env"].rsplit("_OTEL_TOKEN", 1)[0] for info in routing["tenants"].values()}
    assert prefixes >= {"KEVE_UBIX", "KEVE_DIGIFLOW", "BCI_UBIX", "BCI_DIGIFLOW"}
    for prefix in prefixes:
        match = re.search(rf"^{re.escape(prefix)}_OTEL_TOKEN=(.+)$", text, re.M)
        assert match, f"{prefix}_OTEL_TOKEN missing from .env.example"
        assert "changeme" in match.group(1), "expected a placeholder, not a real secret"


def test_compose_wiring():
    compose = yaml.safe_load(COMPOSE.read_text())
    services = compose["services"]
    gw = services["otel-gateway"]
    # Gateway is the only publisher of the ingestion port.
    assert "4318:4318" in gw["ports"]
    for name, svc in services.items():
        if name == "otel-gateway":
            continue
        assert svc.get("ports") is None, f"{name} must not publish ports to host"
        assert svc.get("network_mode") != "host", f"{name} must not use host network"
    env = gw["environment"]
    routing = yaml.safe_load(ROUTING.read_text())
    instances = list(routing["tenants"])
    assert instances[:4] == ["keve_ubix", "keve_digiflow", "bci_ubix", "bci_digiflow"]
    assert env["GATEWAY_TENANTS"] == ",".join(instances)
    for instance, info in routing["tenants"].items():
        token_env = info["token_env"]
        prefix = token_env.rsplit("_OTEL_TOKEN", 1)[0]
        assert token_env in env
        assert f"{token_env}:?{token_env} is not set" in str(env[token_env])
        assert env[f"{prefix}_UPSTREAM"] == info["collector_upstream"]
    assert env["KEVE_UBIX_UPSTREAM"] == "http://otel-collector:4319"
    assert env["KEVE_DIGIFLOW_UPSTREAM"] == "http://otel-collector:4320"
    assert env["BCI_UBIX_UPSTREAM"] == "http://otel-collector:4321"
    assert env["BCI_DIGIFLOW_UPSTREAM"] == "http://otel-collector:4322"


def _datasources_by_name():
    docs = yaml.safe_load(DATASOURCES.read_text())
    return {d["name"]: d for d in docs.get("datasources", [])}


def test_per_instance_grafana_datasources_isolated(routing):
    by_name = _datasources_by_name()
    org_ids = {}
    for instance, info in routing["tenants"].items():
        orgs = set()
        for sig, dtype in (("metrics", "prometheus"), ("logs", "loki"), ("traces", "tempo")):
            name = f"{instance}-{sig}"
            assert name in by_name, f"missing Grafana datasource {name}"
            ds = by_name[name]
            assert ds["type"] == dtype, f"{name} has wrong type"
            assert ds.get("orgId", 1) != 1, f"{name} must not live in Main Org"
            # Datasource header is the COMPANY (hard boundary); the project
            # filter is soft (dashboard variable / future read-proxy).
            assert ds["secureJsonData"]["httpHeaderValue1"] == info["storage_tenant"]
            orgs.add(ds["orgId"])
        assert len(orgs) == 1, f"{instance} datasources span multiple orgs: {orgs}"
        org_ids[instance] = orgs.pop()
    assert len(set(org_ids.values())) == len(org_ids), f"instances share a Grafana org: {org_ids}"
    assert set(org_ids.values()) >= {2, 3, 4, 5}


def test_org_mapping_covers_instances(routing):
    text = COMPOSE.read_text()
    # compose.prod.yml has no Grafana OIDC block; the mapping lives in
    # compose.local.yml. Check whichever file wires it.
    for path in (ROOT / "compose.local.yml", COMPOSE):
        m = re.search(r'GF_AUTH_GENERIC_OAUTH_ORG_MAPPING:\s*"([^"]*)"', path.read_text())
        if m:
            break
    assert m, "ORG_MAPPING not found in compose.local.yml nor compose.prod.yml"
    mapping = m.group(1)
    by_name = _datasources_by_name()
    for required in (
        "obs-platform-admins:1:Admin", "obs-platform-admins:2:Admin",
        "obs-platform-admins:3:Admin", "obs-platform-admins:4:Admin",
        "obs-platform-admins:5:Admin",
        "keve-admins:2:Admin", "keve-admins:3:Admin",
        "bci-admins:4:Admin", "bci-admins:5:Admin",
    ):
        assert required in mapping, f"{required} missing from ORG_MAPPING"
    for instance in routing["tenants"]:
        org_id = by_name[f"{instance}-metrics"]["orgId"]
        group_base = instance.replace("_", "-")
        assert f"{group_base}-viewers:{org_id}:Viewer" in mapping
        assert f"{group_base}-editors:{org_id}:Editor" in mapping
