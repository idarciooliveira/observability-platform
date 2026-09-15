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


ROUTING, LISTEN_PORT = None, None  # set in main(); read by the handler


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
                self.send_response(resp.status)
                self.send_header("Content-Type", resp.headers.get("Content-Type", "application/json"))
                self.send_header("Content-Length", str(len(resp_body)))
                self.end_headers()
                self.wfile.write(resp_body)
            LOG.info("tenant=%s %s %d bytes -> %s", tenant, self.path, len(body), url)
        except HTTPError as exc:
            err_body = exc.read()
            self.send_response(exc.code)
            self.send_header("Content-Type", exc.headers.get("Content-Type", "text/plain"))
            self.send_header("Content-Length", str(len(err_body)))
            self.end_headers()
            self.wfile.write(err_body)
            LOG.warning("tenant=%s %s upstream=%s", tenant, self.path, exc.code)
        except (URLError, OSError) as exc:
            LOG.error("tenant=%s %s upstream unreachable: %s", tenant, self.path, exc)
            self._send(502, "upstream collector unavailable\n")

    # Explicitly reject anything else; the gateway only speaks OTLP/HTTP.
    def do_PUT(self):
        self._send(405, "method not allowed\n")

    def do_DELETE(self):
        self._send(405, "method not allowed\n")

    def do_PATCH(self):
        self._send(405, "method not allowed\n")


def main():
    global ROUTING, LISTEN_PORT
    logging.basicConfig(
        level=os.environ.get("GATEWAY_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,
    )
    ROUTING, LISTEN_PORT = load_config()
    tenants = sorted(e["tenant"] for e in ROUTING.values())
    LOG.info("starting: port=%d tenants=%s", LISTEN_PORT, ",".join(tenants))
    server = ThreadingHTTPServer(("0.0.0.0", LISTEN_PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
