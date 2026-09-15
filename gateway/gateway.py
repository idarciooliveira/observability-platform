#!/usr/bin/env python3
"""Central OTLP tenant gateway (trust boundary).

Public entrypoint for project telemetry::

    project collector (OTLP/HTTP + Bearer token)
        -> otel-gateway:4318            (this service: authenticate + route)
        -> otel-collector:<tenant-port> (per-tenant pipeline: overwrite
                                          project.id, export with tenant header)
        -> Mimir / Loki / Tempo

Responsibilities:
  1. Authenticate machine telemetry via ``Authorization: Bearer <token>``.
     Tokens come from the environment (``<TENANT>_OTEL_TOKEN``); the process
     refuses to start if any configured tenant has no token.
  2. Map the authenticated credential to a project identity
     (``credential -> project_id``). The client-supplied ``project.id``
     resource attribute is NEVER trusted; the body is forwarded opaquely to
     the tenant's private pipeline, whose ``transform`` processor overwrites
     ``project.id`` with the authenticated value.
  3. Strip any client-supplied tenant-selection headers (``X-Scope-OrgID``,
     ``X-Tenant``, ...) and set the trusted ``X-Scope-OrgID: <tenant>``
     header on the upstream request.
  4. Reject unknown/missing credentials with 401 without forwarding anything.

Phase 1 scope: OTLP/HTTP only (``POST /v1/traces|metrics|logs``). Project
collectors must use the ``otlphttp`` exporter. No request bodies are parsed,
so JSON and protobuf encodings are both forwarded safely.

Only the Python standard library is used (no third-party dependencies).
"""

import hmac
import logging
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

LOG = logging.getLogger("otel-gateway")

# OTLP/HTTP signal paths accepted by the gateway.
SIGNALS = ("/v1/traces", "/v1/metrics", "/v1/logs")

# Forwarded as-is: W3C trace context and content encoding only. Everything
# else from the client (Authorization, X-Scope-OrgID, X-Tenant, cookies,
# ...) is dropped by construction: the upstream request carries only the
# trusted tenant header set below.

MAX_BODY_BYTES = 32 * 1024 * 1024
UPSTREAM_TIMEOUT_S = 30

TENANT_HEADER = "X-Scope-OrgID"


class Metrics:
    """Small Prometheus exposition implementation with no dependencies."""

    HISTOGRAM_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10)

    def __init__(self):
        self._lock = threading.Lock()
        self.requests = {}
        self.durations = {}
        self.body_bytes = {}
        self.auth_failures = {}
        self.upstream_requests = {}
        self.upstream_errors = {}

    @staticmethod
    def _inc(mapping, key, value=1):
        mapping[key] = mapping.get(key, 0) + value

    def request(self, method, path, status, duration, body_size=0):
        key = (method, path, str(status))
        with self._lock:
            self._inc(self.requests, key)
            self._inc(self.body_bytes, (path,), body_size)
            buckets, total, count = self.durations.setdefault(
                (method, path), ([0] * len(self.HISTOGRAM_BUCKETS), 0.0, 0)
            )
            for index, boundary in enumerate(self.HISTOGRAM_BUCKETS):
                if duration <= boundary:
                    buckets[index] += 1
            self.durations[(method, path)] = (buckets, total + duration, count + 1)

    def auth_failure(self, path):
        with self._lock:
            self._inc(self.auth_failures, (path,))

    def upstream_request(self, tenant, status):
        with self._lock:
            self._inc(self.upstream_requests, (tenant, str(status)))

    def upstream_error(self, tenant):
        with self._lock:
            self._inc(self.upstream_errors, (tenant,))

    @staticmethod
    def _labels(**labels):
        return "{" + ",".join(f'{key}="{str(value).replace(chr(92), chr(92) * 2).replace(chr(34), chr(92) + chr(34))}"' for key, value in labels.items()) + "}"

    def render(self):
        lines = [
            "# HELP gateway_http_requests_total HTTP requests handled by the gateway.",
            "# TYPE gateway_http_requests_total counter",
            "# HELP gateway_request_duration_seconds Gateway request duration.",
            "# TYPE gateway_request_duration_seconds histogram",
            "# HELP gateway_request_body_bytes_total Bytes received by the gateway.",
            "# TYPE gateway_request_body_bytes_total counter",
            "# HELP gateway_auth_failures_total Requests rejected for invalid credentials.",
            "# TYPE gateway_auth_failures_total counter",
            "# HELP gateway_upstream_requests_total Requests sent to tenant collectors.",
            "# TYPE gateway_upstream_requests_total counter",
            "# HELP gateway_upstream_errors_total Requests that could not reach a tenant collector.",
            "# TYPE gateway_upstream_errors_total counter",
        ]
        with self._lock:
            for (method, path, status), value in sorted(self.requests.items()):
                lines.append(f"gateway_http_requests_total{self._labels(method=method, path=path, status=status)} {value}")
            for (method, path), (buckets, total, count) in sorted(self.durations.items()):
                running = 0
                for index, boundary in enumerate(self.HISTOGRAM_BUCKETS):
                    lines.append(f"gateway_request_duration_seconds_bucket{self._labels(method=method, path=path, le=boundary)} {buckets[index]}")
                lines.append(f"gateway_request_duration_seconds_bucket{self._labels(method=method, path=path, le='+Inf')} {count}")
                lines.append(f"gateway_request_duration_seconds_sum{self._labels(method=method, path=path)} {total}")
                lines.append(f"gateway_request_duration_seconds_count{self._labels(method=method, path=path)} {count}")
            for (path,), value in sorted(self.body_bytes.items()):
                lines.append(f"gateway_request_body_bytes_total{self._labels(path=path)} {value}")
            for (path,), value in sorted(self.auth_failures.items()):
                lines.append(f"gateway_auth_failures_total{self._labels(path=path)} {value}")
            for (tenant, status), value in sorted(self.upstream_requests.items()):
                lines.append(f"gateway_upstream_requests_total{self._labels(tenant=tenant, status=status)} {value}")
            for (tenant,), value in sorted(self.upstream_errors.items()):
                lines.append(f"gateway_upstream_errors_total{self._labels(tenant=tenant)} {value}")
        return ("\n".join(lines) + "\n").encode()


def load_config():
    """Build tenant routing table from the environment.

    GATEWAY_TENANTS: comma-separated tenant ids, e.g. ``ubix,digiflow``.
    Per tenant ``<name>`` (upper-cased, dashes -> underscores):
      ``<NAME>_OTEL_TOKEN``  - Bearer credential (required, never logged).
      ``<NAME>_UPSTREAM``    - internal collector URL, defaults to
                               ``http://otel-collector:<port>`` where ports
                               are assigned sequentially from 4319.
    """
    tenants_raw = os.environ.get("GATEWAY_TENANTS", "ubix,digiflow")
    tenants = [t.strip().lower() for t in tenants_raw.split(",") if t.strip()]
    if not tenants:
        raise SystemExit("GATEWAY_TENANTS is empty; refusing to start.")

    routing = {}
    for i, tenant in enumerate(tenants):
        prefix = tenant.upper().replace("-", "_")
        token = os.environ.get(f"{prefix}_OTEL_TOKEN", "")
        if not token:
            raise SystemExit(
                f"{prefix}_OTEL_TOKEN is not set; refusing to start "
                f"without a credential for tenant '{tenant}'."
            )
        upstream = os.environ.get(
            f"{prefix}_UPSTREAM", f"http://otel-collector:{4319 + i}"
        ).rstrip("/")
        routing[token] = {"tenant": tenant, "upstream": upstream}
    # Same token for two tenants is a configuration error: it would make the
    # credential -> project mapping ambiguous.
    if len(routing) != len(tenants):
        raise SystemExit("Duplicate project tokens detected; refusing to start.")
    port = int(os.environ.get("GATEWAY_LISTEN_PORT", "4318"))
    return routing, port


ROUTING, LISTEN_PORT, METRICS_PORT = None, None, None  # set in main(); read by handlers
METRICS = Metrics()


def authenticate(authorization):
    """Return the routing entry for a valid ``Bearer`` header, else None."""
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    token = token.strip()
    for candidate, entry in ROUTING.items():
        if hmac.compare_digest(candidate, token):
            return entry
    return None


class Handler(BaseHTTPRequestHandler):
    server_version = "otel-gateway/1"

    def send_response(self, code, message=None):
        self._metric_status = code
        super().send_response(code, message)

    def log_message(self, fmt, *args):  # route through logging, never log tokens
        LOG.info("%s %s", self.address_string(), fmt % args)

    def _send(self, status, body=b"", content_type="text/plain"):
        data = body if isinstance(body, bytes) else body.encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def do_GET(self):
        if self.path in ("/healthz", "/readyz", "/health", "/"):
            self._send(200, '{"status":"ok"}', "application/json")
        else:
            self._send(404, "not found\n")

    def do_POST(self):
        started = time.monotonic()
        self._metric_status = 500
        self._metric_body_size = 0
        try:
            self._do_POST()
        finally:
            METRICS.request(
                "POST", self.path, self._metric_status,
                time.monotonic() - started, self._metric_body_size,
            )

    def _do_POST(self):
        if self.path not in SIGNALS:
            self._send(404, "unknown OTLP path; use /v1/traces, /v1/metrics or /v1/logs\n")
            return

        entry = authenticate(self.headers.get("Authorization"))
        if entry is None:
            # Never forward unauthenticated payloads to any backend.
            self.send_response(401)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", "0")
            self.end_headers()
            METRICS.auth_failure(self.path)
            LOG.warning("rejected unauthenticated %s from %s", self.path, self.address_string())
            return

        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self._send(400, "invalid Content-Length\n")
            return
        if length > MAX_BODY_BYTES:
            self._send(413, "payload too large\n")
            return
        body = self.rfile.read(length) if length else b""
        self._metric_body_size = len(body)

        tenant = entry["tenant"]
        url = entry["upstream"] + self.path
        content_type = self.headers.get("Content-Type", "application/x-protobuf")
        upstream = Request(url, data=body, method="POST")
        upstream.add_header("Content-Type", content_type)
        upstream.add_header(TENANT_HEADER, tenant)
        # Propagate W3C trace context; drop everything tenant-related.
        passthrough = ("traceparent", "tracestate", "content-encoding", "content-type")
        for key, value in self.headers.items():
            low = key.lower()
            if low in passthrough and low not in ("content-type",):
                upstream.add_header(key, value)

        try:
            with urlopen(upstream, timeout=UPSTREAM_TIMEOUT_S) as resp:
                resp_body = resp.read()
                METRICS.upstream_request(tenant, resp.status)
                self.send_response(resp.status)
                self.send_header("Content-Type", resp.headers.get("Content-Type", "application/json"))
                self.send_header("Content-Length", str(len(resp_body)))
                self.end_headers()
                self.wfile.write(resp_body)
            LOG.info("tenant=%s %s %d bytes -> %s", tenant, self.path, len(body), url)
        except HTTPError as exc:
            err_body = exc.read()
            METRICS.upstream_request(tenant, exc.code)
            self.send_response(exc.code)
            self.send_header("Content-Type", exc.headers.get("Content-Type", "text/plain"))
            self.send_header("Content-Length", str(len(err_body)))
            self.end_headers()
            self.wfile.write(err_body)
            LOG.warning("tenant=%s %s upstream=%s", tenant, self.path, exc.code)
        except (URLError, OSError) as exc:
            METRICS.upstream_error(tenant)
            LOG.error("tenant=%s %s upstream unreachable: %s", tenant, self.path, exc)
            self._send(502, "upstream collector unavailable\n")

    # Explicitly reject anything else; the gateway only speaks OTLP/HTTP.
    def do_PUT(self):
        self._send(405, "method not allowed\n")

    def do_DELETE(self):
        self._send(405, "method not allowed\n")

    def do_PATCH(self):
        self._send(405, "method not allowed\n")


class MetricsHandler(BaseHTTPRequestHandler):
    server_version = "otel-gateway-metrics/1"

    def do_GET(self):
        if self.path != "/metrics":
            self.send_error(404)
            return
        body = METRICS.render()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        return


def main():
    global ROUTING, LISTEN_PORT, METRICS_PORT
    logging.basicConfig(
        level=os.environ.get("GATEWAY_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,
    )
    ROUTING, LISTEN_PORT = load_config()
    METRICS_PORT = int(os.environ.get("GATEWAY_METRICS_PORT", "9464"))
    tenants = sorted(e["tenant"] for e in ROUTING.values())
    LOG.info("starting: port=%d tenants=%s", LISTEN_PORT, ",".join(tenants))
    server = ThreadingHTTPServer(("0.0.0.0", LISTEN_PORT), Handler)
    metrics_server = ThreadingHTTPServer(("0.0.0.0", METRICS_PORT), MetricsHandler)
    metrics_thread = threading.Thread(target=metrics_server.serve_forever, daemon=True)
    metrics_thread.start()
    LOG.info("metrics: private port=%d", METRICS_PORT)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        metrics_server.shutdown()


if __name__ == "__main__":
    main()
