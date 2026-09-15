import http from 'k6/http';
import { check, sleep } from 'k6';

// Sustained realistic traffic for the observability-platform examples
// (insurance-direct + retail-collector). Adapted from
// poc-observability-infrastructure/load/poc-load.js with the banking
// scenario removed — only the two tenants used in this test remain:
//   insurance -> ubix (direct OTLP, Variant B)
//   retail    -> digiflow (local collector, Variant A)
//
// Run via examples/scripts/load-k6.ps1|.sh (grafana/k6 in Docker, no local install).
//
// Env (wrappers pass these; defaults = Docker Desktop host mapping):
//   INSURANCE_URL, RETAIL_URL, VUS, RAMP_MIN, STEADY_MIN, CHAOS_MODE
//
// Tenant separation happens server-side (gateway overwrites project.id and the
// collector fans out per-tenant with X-Scope-OrgID), so no OTLP headers are
// needed here. The k6 `tenant` tag below is load-side grouping only.
//
// Retail drives the collector lane: POST /orders, GET /orders/{id},
// POST /orders/{id}/cancel. Catalog: PROD-001/002/003 (see retail
// CreateOrderUseCase); qty 0 -> 400 (bean validation), unknown product -> 422,
// double cancel -> 409, missing id -> 404.

const INSURANCE_URL = __ENV.INSURANCE_URL || 'http://host.docker.internal:8083';
const RETAIL_URL = __ENV.RETAIL_URL || 'http://host.docker.internal:8084';
const VUS = parseInt(__ENV.VUS || '10', 10);
const RAMP_MIN = parseFloat(__ENV.RAMP_MIN || '2');
const STEADY_MIN = parseFloat(__ENV.STEADY_MIN || '5');
const CHAOS_MODE = (__ENV.CHAOS_MODE || 'off').toLowerCase();

// Seeds (see insurance/retail src/main/resources/data.sql).
const POLICY_ACTIVE_FULL = 'b1c2e8d0-2222-4b3b-8d2b-000000000001'; // ACTIVE limit 100000
const POLICY_ACTIVE_SMALL = 'b1c2e8d0-2222-4b3b-8d2b-000000000002'; // ACTIVE limit 50000
const POLICY_INACTIVE = 'b1c2e8d0-2222-4b3b-8d2b-000000000003'; // INACTIVE limit 75000
const POLICY_MISSING = 'b1c2e8d0-2222-4b3b-8d2b-000000009999'; // valid UUID, never seeded -> 404
const ORDER_MISSING = '00000000-0000-0000-0000-000000000000'; // valid UUID, never an order -> 404
const RETAIL_PRODUCTS = ['PROD-001', 'PROD-002', 'PROD-003']; // synthetic catalog (CreateOrderUseCase)

const DOWN_MIN = STEADY_MIN <= 2 ? 0.5 : 1;

export const options = {
  scenarios: {
    insurance: {
      executor: 'ramping-vus',
      exec: 'insurance',
      startVUs: 0,
      stages: [
        { duration: `${RAMP_MIN}m`, target: VUS },
        { duration: `${STEADY_MIN}m`, target: VUS },
        { duration: `${DOWN_MIN}m`, target: 0 },
      ],
      gracefulRampDown: '30s',
    },
    retail: {
      executor: 'ramping-vus',
      exec: 'retail',
      startVUs: 0,
      stages: [
        { duration: `${RAMP_MIN}m`, target: VUS },
        { duration: `${STEADY_MIN}m`, target: VUS },
        { duration: `${DOWN_MIN}m`, target: 0 },
      ],
      gracefulRampDown: '30s',
    },
  },
  thresholds: {
    checks: ['rate>0.99'],
    http_req_duration:
      CHAOS_MODE === 'latency' ? ['p(95)<4000'] : ['p(95)<2000'],
  },
};

function jsonHeaders() {
  return { 'Content-Type': 'application/json' };
}

function tag(tenant, outcome) {
  return { headers: jsonHeaders(), tags: { tenant, outcome } };
}

// Weighted pick over [0,100): entries are [upperBoundExclusive, value].
function pick(table, r) {
  const roll = r === undefined ? Math.random() * 100 : r;
  for (const [bound, value] of table) {
    if (roll < bound) return value;
  }
  return table[table.length - 1][1];
}

export function insurance() {
  // Insurance claims never drain (canCover is non-cumulative), so static seeds suffice.
  const kind = pick([
    [55, 'approved'],
    [65, 'high_value'],
    [75, 'exhaustion'],
    [80, 'inactive'],
    [85, 'notfound'],
    [88, 'coverage'],
    [90, 'invalid'],
    [100, 'read'],
  ]);

  let res;
  let expected;
  let outcome = kind;

  if (kind === 'approved') {
    res = http.post(
      `${INSURANCE_URL}/policies/${POLICY_ACTIVE_FULL}/claims`,
      JSON.stringify({ amount: 1000.0 }),
      tag('insurance', 'approved'),
    );
    expected = 201;
  } else if (kind === 'high_value') {
    // 60000 > 50000 high-value threshold (coverage 100000 still covers -> risk rejects).
    res = http.post(
      `${INSURANCE_URL}/policies/${POLICY_ACTIVE_FULL}/claims`,
      JSON.stringify({ amount: 60000.0 }),
      tag('insurance', 'high_value'),
    );
    expected = 422;
  } else if (kind === 'exhaustion') {
    // 45000 > 80% of 50000 (=40000) but < 50000 high-value -> coverage_exhaustion.
    res = http.post(
      `${INSURANCE_URL}/policies/${POLICY_ACTIVE_SMALL}/claims`,
      JSON.stringify({ amount: 45000.0 }),
      tag('insurance', 'coverage_exhaustion'),
    );
    expected = 422;
    outcome = 'coverage_exhaustion';
  } else if (kind === 'inactive') {
    res = http.post(
      `${INSURANCE_URL}/policies/${POLICY_INACTIVE}/claims`,
      JSON.stringify({ amount: 1000.0 }),
      tag('insurance', 'inactive'),
    );
    expected = 422;
  } else if (kind === 'notfound') {
    res = http.post(
      `${INSURANCE_URL}/policies/${POLICY_MISSING}/claims`,
      JSON.stringify({ amount: 1000.0 }),
      tag('insurance', 'notfound'),
    );
    expected = 404;
  } else if (kind === 'coverage') {
    // 200000 > 100000 limit -> canCover fails before risk -> 422.
    res = http.post(
      `${INSURANCE_URL}/policies/${POLICY_ACTIVE_FULL}/claims`,
      JSON.stringify({ amount: 200000.0 }),
      tag('insurance', 'coverage_exceeded'),
    );
    expected = 422;
    outcome = 'coverage_exceeded';
  } else if (kind === 'invalid') {
    // Bean validation (@DecimalMin 0.01) -> 400.
    res = http.post(
      `${INSURANCE_URL}/policies/${POLICY_ACTIVE_FULL}/claims`,
      JSON.stringify({ amount: 0 }),
      tag('insurance', 'invalid'),
    );
    expected = 400;
  } else {
    // No GET claim endpoint exists: reads are approved POSTs with small
    // variation (still 201), tagged outcome=read so dashboards can split them.
    const amount = (500 + Math.random() * 1000).toFixed(2);
    res = http.post(
      `${INSURANCE_URL}/policies/${POLICY_ACTIVE_FULL}/claims`,
      JSON.stringify({ amount: parseFloat(amount) }),
      tag('insurance', 'read'),
    );
    expected = 201;
    outcome = 'read';
  }

  check(res, { [`insurance:${outcome} status ${expected}`]: (r) => r.status === expected });
  sleep(0.3 + Math.random() * 0.5);
}

// Per-VU state for the retail order lifecycle: last created id (reads),
// one cancellable id (cancel -> 200), one cancelled id (double-cancel -> 409).
// (Top-level `let` is VU-scoped in k6: each VU gets its own copy.)
let lastOrderId = null;
let cancellableOrderId = null;
let cancelledOrderId = null;

function retailProduct() {
  return RETAIL_PRODUCTS[Math.floor(Math.random() * RETAIL_PRODUCTS.length)];
}

function retailCreate(checkOutcome) {
  const res = http.post(
    `${RETAIL_URL}/orders`,
    JSON.stringify({ productId: retailProduct(), quantity: 1 + Math.floor(Math.random() * 5) }),
    tag('retail', checkOutcome),
  );
  if (res.status === 201) {
    try {
      const id = res.json('id');
      lastOrderId = id;
      cancellableOrderId = id;
    } catch (e) {
      // leave VU state untouched; the status check below still applies
    }
  }
  return res;
}

export function retail() {
  // Retail order lifecycle through the collector lane.
  // Status map (see OrderController + GlobalExceptionHandler):
  // created 201, cancel 200, double-cancel 409, qty 0 -> 400 (bean
  // validation @Min), unknown product -> 422, missing id -> 404.
  const kind = pick([
    [40, 'created'],
    [55, 'cancel'],
    [60, 'conflict'],
    [68, 'invalid'],
    [76, 'unknown'],
    [84, 'notfound'],
    [100, 'read'],
  ]);

  let res;
  let expected;
  let outcome = kind;

  if (kind === 'created') {
    res = retailCreate('created');
    expected = 201;
  } else if (kind === 'cancel') {
    if (cancellableOrderId) {
      const id = cancellableOrderId;
      cancellableOrderId = null;
      res = http.post(`${RETAIL_URL}/orders/${id}/cancel`, null, tag('retail', 'cancel'));
      expected = 200;
      if (res.status === 200) cancelledOrderId = id;
    } else {
      // No cancellable order yet: create one and cancel it inline (200).
      const created = retailCreate('cancel');
      if (created.status === 201) {
        try {
          const id = created.json('id');
          cancellableOrderId = null;
          res = http.post(`${RETAIL_URL}/orders/${id}/cancel`, null, tag('retail', 'cancel'));
          expected = 200;
          if (res.status === 200) cancelledOrderId = id;
        } catch (e) {
          res = created;
          expected = 201;
          outcome = 'created';
        }
      } else {
        res = created;
        expected = 201;
        outcome = 'created';
      }
    }
  } else if (kind === 'conflict') {
    if (cancelledOrderId) {
      // Already cancelled -> 409 (OrderAlreadyCancelledException -> CONFLICT).
      res = http.post(`${RETAIL_URL}/orders/${cancelledOrderId}/cancel`, null, tag('retail', 'conflict'));
      expected = 409;
    } else {
      res = retailCreate('created');
      expected = 201;
      outcome = 'created';
    }
  } else if (kind === 'invalid') {
    // Bean validation (@Min(1)) rejects before the use case -> 400.
    res = http.post(
      `${RETAIL_URL}/orders`,
      JSON.stringify({ productId: retailProduct(), quantity: 0 }),
      tag('retail', 'invalid'),
    );
    expected = 400;
  } else if (kind === 'unknown') {
    // Known-shape request, unknown catalog product -> 422.
    res = http.post(
      `${RETAIL_URL}/orders`,
      JSON.stringify({ productId: 'NOPE-9999', quantity: 1 }),
      tag('retail', 'unknown_product'),
    );
    expected = 422;
    outcome = 'unknown_product';
  } else if (kind === 'notfound') {
    // Valid UUID, never an order -> 404 (cancel path also 404s; alternate).
    if (Math.random() < 0.5) {
      res = http.get(`${RETAIL_URL}/orders/${ORDER_MISSING}`, tag('retail', 'notfound'));
    } else {
      res = http.post(`${RETAIL_URL}/orders/${ORDER_MISSING}/cancel`, null, tag('retail', 'notfound'));
    }
    expected = 404;
  } else {
    // Reads: GET last created (200) or a missing id (404).
    if (lastOrderId) {
      res = http.get(`${RETAIL_URL}/orders/${lastOrderId}`, tag('retail', 'read'));
      expected = 200;
    } else {
      res = http.get(`${RETAIL_URL}/orders/${ORDER_MISSING}`, tag('retail', 'read'));
      expected = 404;
    }
    outcome = 'read';
  }

  check(res, { [`retail:${outcome} status ${expected}`]: (r) => r.status === expected });
  sleep(0.3 + Math.random() * 0.5);
}
