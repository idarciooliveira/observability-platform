"""Instance-isolation tests for the otel-gateway trust boundary (Option B).

Proves, against a live gateway backed by fake per-instance upstreams:
  credential -> instance mapping (4 instances, 2 companies x 2 projects)
  instances sharing one company share the storage OrgID but use
      DIFFERENT pipelines (same-OrgID / different-pipeline)
  client project.id / tenant.id cannot override the instance (request lands
      on the credential owner's pipeline; the collector overwrites both)
  client tenant headers are stripped; only the gateway's trusted header
      (instance id) reaches the collector
  invalid credentials are rejected and never forwarded

Run:  python3 -m pytest gateway/tests/ -v
Requires: pytest only (stdlib HTTP servers/clients otherwise).
"""

import importlib.util
import json
import threading
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

GATEWAY_PATH = __file__.rsplit("/tests/", 1)[0] + "/gateway.py"

INSTANCES = ("keve_ubix", "keve_digiflow", "bci_ubix", "bci_digiflow")

TEST_TOKENS = {
    "KEVE_UBIX_OTEL_TOKEN": "test-token-keve-ubix",
    "KEVE_DIGIFLOW_OTEL_TOKEN": "test-token-keve-digiflow",
    "BCI_UBIX_OTEL_TOKEN": "test-token-bci-ubix",
    "BCI_DIGIFLOW_OTEL_TOKEN": "test-token-bci-digiflow",
    "GATEWAY_TENANTS": "keve_ubix,keve_digiflow,bci_ubix,bci_digiflow",
}

# Instance -> storage company (mirrors tenant-routing.yml storage_tenant).
STORAGE = {
    "keve_ubix": "keve",
    "keve_digiflow": "keve",
    "bci_ubix": "bci",
    "bci_digiflow": "bci",
}


def load_gateway(monkeypatch, upstreams):
    for env, token in TEST_TOKENS.items():
        monkeypatch.setenv(env, token)
    for instance, url in upstreams.items():
        prefix = instance.upper()
        monkeypatch.setenv(f"{prefix}_UPSTREAM", url)
    spec = importlib.util.spec_from_file_location("otel_gateway", GATEWAY_PATH)
    gw = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gw)
    routing, _ = gw.load_config()
    gw.ROUTING = routing
    return gw


class Recorder:
    """Fake internal-collector endpoint for one instance."""

    def __init__(self):
        self.hits = []
        self.server = None

    def start(self):
        recorder = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                recorder.hits.append(
                    {
                        "path": self.path,
                        "headers": {k.lower(): v for k, v in self.headers.items()},
                        "body": self.rfile.read(length) if length else b"",
                    }
                )
                data = b"{}"
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        port = self.server.server_address[1]
        return f"http://127.0.0.1:{port}"


@pytest.fixture()
def backends(monkeypatch):
    recorders = {i: Recorder() for i in INSTANCES}
    upstreams = {i: r.start() for i, r in recorders.items()}
    gw = load_gateway(monkeypatch, upstreams)
    server = ThreadingHTTPServer(("127.0.0.1", 0), gw.Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    yield {"gw": gw, "recorders": recorders, "base": base}
    server.shutdown()


def otlp_logs_body(project_id, tenant_id="keve"):
    return json.dumps(
        {
            "resourceLogs": [
                {
                    "resource": {
                        "attributes": [
                            {"key": "service.name", "value": {"stringValue": "test-svc"}},
                            {"key": "project.id", "value": {"stringValue": project_id}},
                            {"key": "tenant.id", "value": {"stringValue": tenant_id}},
                        ]
                    },
                    "scopeLogs": [
                        {
                            "logRecords": [
                                {"body": {"stringValue": "hello"}, "severityNumber": 9}
                            ]
                        }
                    ],
                }
            ]
        }
    ).encode()


def post(base, path, token=None, body=b"{}", headers=None, content_type="application/json"):
    req = urllib.request.Request(base + path, data=body, method="POST")
    req.add_header("Content-Type", content_type)
    if token is not None:
        req.add_header("Authorization", f"Bearer {token}")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def hits(backends, instance):
    return backends["recorders"][instance].hits


def test_all_four_credentials_route_to_own_pipeline(backends):
    for instance in INSTANCES:
        token = TEST_TOKENS[f"{instance.upper()}_OTEL_TOKEN"]
        status, _ = post(backends["base"], "/v1/logs", token,
                         otlp_logs_body("ubix", "keve"))
        assert status == 200
    for instance in INSTANCES:
        assert len(hits(backends, instance)) == 1, f"{instance} got no hit"
        hit = hits(backends, instance)[0]
        # Gateway stamps the trusted instance header (collector maps the
        # instance pipeline to the shared COMPANY exporter downstream).
        assert hit["headers"].get("x-scope-orgid") == instance
        assert hit["path"] == "/v1/logs"


def test_same_company_shares_storage_but_not_pipeline(backends):
    # keve_ubix and keve_digiflow share storage_tenant=keve but must use
    # different pipelines: a request on one credential never hits the other.
    status, _ = post(backends["base"], "/v1/logs",
                     TEST_TOKENS["KEVE_UBIX_OTEL_TOKEN"],
                     otlp_logs_body("digiflow", "keve"))
    assert status == 200
    assert len(hits(backends, "keve_ubix")) == 1
    assert hits(backends, "keve_digiflow") == []
    assert STORAGE["keve_ubix"] == STORAGE["keve_digiflow"] == "keve"


def test_spoofed_project_id_is_routed_to_credential_owner(backends):
    # KEVE_UBIX credential + project.id=digiflow must still land on keve_ubix.
    status, _ = post(backends["base"], "/v1/logs",
                     TEST_TOKENS["KEVE_UBIX_OTEL_TOKEN"],
                     otlp_logs_body("digiflow", "keve"))
    assert status == 200
    assert len(hits(backends, "keve_ubix")) == 1
    assert hits(backends, "keve_digiflow") == []
    assert hits(backends, "keve_ubix")[0]["headers"].get("x-scope-orgid") == "keve_ubix"


def test_spoofed_tenant_id_is_routed_to_credential_owner(backends):
    # KEVE_UBIX credential + tenant.id=bci must still land on keve_ubix
    # (collector overwrites tenant.id=keve as defense in depth).
    status, _ = post(backends["base"], "/v1/logs",
                     TEST_TOKENS["KEVE_UBIX_OTEL_TOKEN"],
                     otlp_logs_body("ubix", "bci"))
    assert status == 200
    assert len(hits(backends, "keve_ubix")) == 1
    assert hits(backends, "bci_ubix") == []
    assert hits(backends, "bci_digiflow") == []
    assert hits(backends, "keve_ubix")[0]["headers"].get("x-scope-orgid") == "keve_ubix"


def test_client_tenant_header_is_stripped(backends):
    status, _ = post(
        backends["base"], "/v1/traces", TEST_TOKENS["KEVE_UBIX_OTEL_TOKEN"],
        otlp_logs_body("digiflow", "bci"),
        headers={"X-Scope-OrgID": "bci", "X-Tenant": "bci"},
        content_type="application/x-protobuf",
    )
    assert status == 200
    for other in ("keve_digiflow", "bci_ubix", "bci_digiflow"):
        assert hits(backends, other) == []
    hit = hits(backends, "keve_ubix")[0]
    assert hit["headers"].get("x-scope-orgid") == "keve_ubix"
    assert "x-tenant" not in hit["headers"]
    assert "authorization" not in hit["headers"]


def test_cross_company_spoofing_stays_on_owner(backends):
    # BCI_DIGIFLOW credential claiming ubix/keve must still land on bci_digiflow.
    status, _ = post(backends["base"], "/v1/logs",
                     TEST_TOKENS["BCI_DIGIFLOW_OTEL_TOKEN"],
                     otlp_logs_body("ubix", "keve"))
    assert status == 200
    assert len(hits(backends, "bci_digiflow")) == 1
    for other in ("keve_ubix", "keve_digiflow", "bci_ubix"):
        assert hits(backends, other) == []
    assert hits(backends, "bci_digiflow")[0]["headers"].get("x-scope-orgid") == "bci_digiflow"


def test_other_instance_token_never_produces_foreign_header(backends):
    for path in ("/v1/traces", "/v1/metrics", "/v1/logs"):
        post(backends["base"], path, TEST_TOKENS["BCI_UBIX_OTEL_TOKEN"], b"{}")
    for other in ("keve_ubix", "keve_digiflow", "bci_digiflow"):
        assert hits(backends, other) == []
    for hit in hits(backends, "bci_ubix"):
        assert hit["headers"].get("x-scope-orgid") == "bci_ubix"


def test_invalid_credential_rejected_and_never_forwarded(backends):
    status, _ = post(backends["base"], "/v1/logs", "INVALID_TOKEN", otlp_logs_body("ubix"))
    assert status == 401
    for instance in INSTANCES:
        assert hits(backends, instance) == []


def test_missing_credential_rejected(backends):
    status, _ = post(backends["base"], "/v1/logs", None, otlp_logs_body("ubix"))
    assert status == 401
    for instance in INSTANCES:
        assert hits(backends, instance) == []


def test_unknown_path_rejected(backends):
    status, _ = post(backends["base"], "/v1/spoof", TEST_TOKENS["KEVE_UBIX_OTEL_TOKEN"], b"{}")
    assert status == 404
    for instance in INSTANCES:
        assert hits(backends, instance) == []


def test_gateway_refuses_to_start_without_tokens(monkeypatch, tmp_path):
    for env in ("KEVE_UBIX_OTEL_TOKEN", "KEVE_DIGIFLOW_OTEL_TOKEN",
                "BCI_UBIX_OTEL_TOKEN", "BCI_DIGIFLOW_OTEL_TOKEN"):
        monkeypatch.delenv(env, raising=False)
    monkeypatch.setenv("GATEWAY_TENANTS", "keve_ubix,keve_digiflow,bci_ubix,bci_digiflow")
    spec = importlib.util.spec_from_file_location("otel_gateway_nocreds", GATEWAY_PATH)
    gw = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gw)
    with pytest.raises(SystemExit):
        gw.load_config()
