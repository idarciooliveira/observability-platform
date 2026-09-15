"""Tenant-isolation tests for the otel-gateway trust boundary.

Proves, against a live gateway backed by fake per-tenant upstreams:
  credential -> tenant mapping
  client project.id cannot override the tenant (request lands on the
      credential owner's pipeline; the collector overwrites project.id)
  invalid credentials are rejected and never forwarded
  the tenant header is generated from the credential, never from the client
  ubix telemetry cannot reach the digiflow pipeline and vice versa

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

TEST_TOKENS = {
    "UBIX_OTEL_TOKEN": "test-token-ubix",
    "DIGIFLOW_OTEL_TOKEN": "test-token-digiflow",
    "GATEWAY_TENANTS": "ubix,digiflow",
}


def load_gateway(monkeypatch, upstream_ubix, upstream_digiflow):
    monkeypatch.setenv("UBIX_OTEL_TOKEN", TEST_TOKENS["UBIX_OTEL_TOKEN"])
    monkeypatch.setenv("DIGIFLOW_OTEL_TOKEN", TEST_TOKENS["DIGIFLOW_OTEL_TOKEN"])
    monkeypatch.setenv("GATEWAY_TENANTS", "ubix,digiflow")
    monkeypatch.setenv("UBIX_UPSTREAM", upstream_ubix)
    monkeypatch.setenv("DIGIFLOW_UPSTREAM", upstream_digiflow)
    spec = importlib.util.spec_from_file_location("otel_gateway", GATEWAY_PATH)
    gw = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gw)
    routing, _ = gw.load_config()
    gw.ROUTING = routing
    return gw


class Recorder:
    """Fake internal-collector endpoint for one tenant."""

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
    ubix = Recorder()
    digiflow = Recorder()
    url_ubix = ubix.start()
    url_digiflow = digiflow.start()
    gw = load_gateway(monkeypatch, url_ubix, url_digiflow)
    server = ThreadingHTTPServer(("127.0.0.1", 0), gw.Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    yield {"gw": gw, "ubix": ubix, "digiflow": digiflow, "base": base}
    server.shutdown()


def otlp_logs_body(project_id):
    return json.dumps(
        {
            "resourceLogs": [
                {
                    "resource": {
                        "attributes": [
                            {"key": "service.name", "value": {"stringValue": "test-svc"}},
                            {"key": "project.id", "value": {"stringValue": project_id}},
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


def test_valid_ubix_request(backends):
    status, _ = post(backends["base"], "/v1/logs", TEST_TOKENS["UBIX_OTEL_TOKEN"],
                     otlp_logs_body("ubix"))
    assert status == 200
    assert len(backends["ubix"].hits) == 1
    assert len(backends["digiflow"].hits) == 0
    hit = backends["ubix"].hits[0]
    assert hit["headers"].get("x-scope-orgid") == "ubix"
    assert hit["path"] == "/v1/logs"


def test_spoofed_project_id_is_routed_to_credential_owner(backends):
    # UBIX credential + project.id=digiflow must still land on ubix pipeline.
    status, _ = post(backends["base"], "/v1/logs", TEST_TOKENS["UBIX_OTEL_TOKEN"],
                     otlp_logs_body("digiflow"))
    assert status == 200
    assert len(backends["ubix"].hits) == 1
    assert len(backends["digiflow"].hits) == 0
    assert backends["ubix"].hits[0]["headers"].get("x-scope-orgid") == "ubix"


def test_client_tenant_header_is_stripped(backends):
    status, _ = post(
        backends["base"], "/v1/traces", TEST_TOKENS["UBIX_OTEL_TOKEN"],
        otlp_logs_body("digiflow"),
        headers={"X-Scope-OrgID": "digiflow", "X-Tenant": "digiflow"},
        content_type="application/x-protobuf",
    )
    assert status == 200
    assert len(backends["digiflow"].hits) == 0
    hit = backends["ubix"].hits[0]
    assert hit["headers"].get("x-scope-orgid") == "ubix"
    assert "x-tenant" not in hit["headers"]
    assert "authorization" not in hit["headers"]


def test_valid_digiflow_request(backends):
    status, _ = post(backends["base"], "/v1/metrics", TEST_TOKENS["DIGIFLOW_OTEL_TOKEN"],
                     otlp_logs_body("digiflow"))
    assert status == 200
    assert len(backends["digiflow"].hits) == 1
    assert len(backends["ubix"].hits) == 0
    assert backends["digiflow"].hits[0]["headers"].get("x-scope-orgid") == "digiflow"


def test_cross_tenant_spoofing_digiflow_claiming_ubix(backends):
    status, _ = post(backends["base"], "/v1/logs", TEST_TOKENS["DIGIFLOW_OTEL_TOKEN"],
                     otlp_logs_body("ubix"))
    assert status == 200
    assert len(backends["digiflow"].hits) == 1
    assert len(backends["ubix"].hits) == 0
    assert backends["digiflow"].hits[0]["headers"].get("x-scope-orgid") == "digiflow"


def test_invalid_credential_rejected_and_never_forwarded(backends):
    status, _ = post(backends["base"], "/v1/logs", "INVALID_TOKEN", otlp_logs_body("ubix"))
    assert status == 401
    assert backends["ubix"].hits == []
    assert backends["digiflow"].hits == []


def test_missing_credential_rejected(backends):
    status, _ = post(backends["base"], "/v1/logs", None, otlp_logs_body("ubix"))
    assert status == 401
    assert backends["ubix"].hits == []
    assert backends["digiflow"].hits == []


def test_other_tenants_token_not_accepted_as_ubix(backends):
    # Digiflow token must never produce a ubix tenant header anywhere.
    for path in ("/v1/traces", "/v1/metrics", "/v1/logs"):
        post(backends["base"], path, TEST_TOKENS["DIGIFLOW_OTEL_TOKEN"], b"{}")
    assert backends["ubix"].hits == []
    for hit in backends["digiflow"].hits:
        assert hit["headers"].get("x-scope-orgid") == "digiflow"


def test_unknown_path_rejected(backends):
    status, _ = post(backends["base"], "/v1/spoof", TEST_TOKENS["UBIX_OTEL_TOKEN"], b"{}")
    assert status == 404
    assert backends["ubix"].hits == []


def test_gateway_refuses_to_start_without_tokens(monkeypatch, tmp_path):
    import os
    monkeypatch.delenv("UBIX_OTEL_TOKEN", raising=False)
    monkeypatch.delenv("DIGIFLOW_OTEL_TOKEN", raising=False)
    monkeypatch.setenv("GATEWAY_TENANTS", "ubix,digiflow")
    spec = importlib.util.spec_from_file_location("otel_gateway_nocreds", GATEWAY_PATH)
    gw = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gw)
    with pytest.raises(SystemExit):
        gw.load_config()
