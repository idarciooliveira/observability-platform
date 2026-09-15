"""Static consistency tests: gateway, collector, registry and compose agree.

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

# Tenants explicitly covered by name below (gateway upstreams, token envs).
# The full expected set is derived from the routing registry so that
# scripts/add-tenant.py can add tenants without editing this file.
BASE_TENANTS = {"ubix", "digiflow"}


def expected_tenants():
    return set(yaml.safe_load(ROUTING.read_text())["tenants"])


@pytest.fixture(scope="module")
def collector():
    return yaml.safe_load(COLLECTOR_CFG.read_text())


@pytest.fixture(scope="module")
def routing():
    return yaml.safe_load(ROUTING.read_text())


def test_tenant_sets_match_everywhere(routing):
    expected = expected_tenants()
    assert set(routing["tenants"]) == expected
    assert expected >= BASE_TENANTS
    registry = yaml.safe_load(TENANTS.read_text())
    assert {p["id"] for p in registry["projects"]} >= expected


def test_per_tenant_receivers_match_gateway_upstreams(collector, routing):
    receivers = collector["receivers"]
    for tenant, info in routing["tenants"].items():
        name = info["collector_receiver"]
        assert name == f"otlp/{tenant}"
        assert name in receivers
        endpoint = receivers[name]["protocols"]["http"]["endpoint"]
        port = endpoint.rsplit(":", 1)[1]
        upstream_port = str(urllib.parse.urlparse(info["collector_upstream"]).port)
        assert port == upstream_port, f"{tenant}: receiver port != gateway upstream port"


def test_identity_processors_overwrite_project_id(collector, routing):
    processors = collector["processors"]
    for tenant in routing["tenants"]:
        name = f"transform/{tenant}_identity"
        assert name in processors
        cfg = processors[name]
        expected = f'set(attributes["project.id"], "{tenant}")'
        for section in ("trace_statements", "metric_statements", "log_statements"):
            assert section in cfg, f"{name} missing {section}"
            joined = " ".join(
                str(s.get("statements", "")) for s in cfg[section]
            )
            assert expected in joined, f"{name}/{section} does not set project.id={tenant}"


def test_per_tenant_exporters_use_tenant_header(collector, routing):
    exporters = collector["exporters"]
    for tenant, info in routing["tenants"].items():
        for backend in ("mimir", "loki", "tempo"):
            name = f"otlphttp/{backend}_{tenant}"
            assert name in exporters, f"missing exporter {name}"
            headers = exporters[name].get("headers", {})
            assert headers.get("X-Scope-OrgID") == info["storage_tenant"] == tenant


def test_pipelines_wire_receiver_identity_exporters(collector, routing):
    pipelines = collector["service"]["pipelines"]
    for tenant, info in routing["tenants"].items():
        receiver = info["collector_receiver"]
        identity = f"transform/{tenant}_identity"
        for signal, backend in (("traces", "tempo"), ("metrics", "mimir"), ("logs", "loki")):
            pipe = pipelines[f"{signal}/{tenant}"]
            assert receiver in pipe["receivers"]
            assert identity in pipe["processors"]
            assert f"otlphttp/{backend}_{tenant}" in pipe["exporters"]


def test_no_static_cross_tenant_header(collector):
    expected = expected_tenants()
    text = COLLECTOR_CFG.read_text()
    for tenant in expected:
        for other in expected - {tenant}:
            # A <tenant> pipeline must never carry another tenant's header.
            for line_no, line in enumerate(text.splitlines(), 1):
                if f"_{tenant}:" in line or f"/{tenant}" in line:
                    context = "\n".join(text.splitlines()[max(0, line_no - 1):line_no + 6])
                    assert f"X-Scope-OrgID: {other}" not in context


def test_env_example_has_placeholders_not_secrets():
    text = ENV_EXAMPLE.read_text()
    routing = yaml.safe_load(ROUTING.read_text())
    prefixes = {info["token_env"].rsplit("_OTEL_TOKEN", 1)[0] for info in routing["tenants"].values()}
    assert prefixes >= {"UBIX", "DIGIFLOW"}
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
    assert services["otel-collector"].get("ports") is None
    env = gw["environment"]
    routing = yaml.safe_load(ROUTING.read_text())
    tenants = list(routing["tenants"])
    assert tenants[:2] == ["ubix", "digiflow"]
    assert env["GATEWAY_TENANTS"] == ",".join(tenants)
    for tenant, info in routing["tenants"].items():
        token_env = info["token_env"]
        prefix = token_env.rsplit("_OTEL_TOKEN", 1)[0]
        assert token_env in env
        assert f"{token_env}:?{token_env} is not set" in str(env[token_env])
        assert env[f"{prefix}_UPSTREAM"] == info["collector_upstream"]
    assert env["UBIX_UPSTREAM"] == "http://otel-collector:4319"
    assert env["DIGIFLOW_UPSTREAM"] == "http://otel-collector:4320"


def _datasources_by_name():
    docs = yaml.safe_load(DATASOURCES.read_text())
    return {d["name"]: d for d in docs.get("datasources", [])}


def test_per_tenant_grafana_datasources_isolated(routing):
    by_name = _datasources_by_name()
    org_ids = {}
    for tenant in routing["tenants"]:
        orgs = set()
        for sig, dtype in (("metrics", "prometheus"), ("logs", "loki"), ("traces", "tempo")):
            name = f"{tenant}-{sig}"
            assert name in by_name, f"missing Grafana datasource {name}"
            ds = by_name[name]
            assert ds["type"] == dtype, f"{name} has wrong type"
            assert ds.get("orgId", 1) != 1, f"{name} must not live in Main Org"
            assert ds["secureJsonData"]["httpHeaderValue1"] == tenant
            orgs.add(ds["orgId"])
        assert len(orgs) == 1, f"{tenant} datasources span multiple orgs: {orgs}"
        org_ids[tenant] = orgs.pop()
    assert len(set(org_ids.values())) == len(org_ids), f"tenants share a Grafana org: {org_ids}"


def test_org_mapping_covers_tenants(routing):
    text = COMPOSE.read_text()
    m = re.search(r'GF_AUTH_GENERIC_OAUTH_ORG_MAPPING:\s*"([^"]*)"', text)
    if not m:
        pytest.skip("prod Grafana OIDC not wired yet (no ORG_MAPPING in compose.prod.yml)")
    mapping = m.group(1)
    by_name = _datasources_by_name()
    for tenant in routing["tenants"]:
        org_id = by_name[f"{tenant}-metrics"]["orgId"]
        assert f"{tenant}-viewers:{org_id}:Viewer" in mapping, f"{tenant} viewers missing from ORG_MAPPING"
        assert f"{tenant}-editors:{org_id}:Editor" in mapping, f"{tenant} editors missing from ORG_MAPPING"
