// Flash-sale spike: thousands of signed-in users hammer Buy the instant the
// sale opens, while browsers poll the public stock status.
//
// Pass/fail is decided by thresholds:
//   - zero transport errors / 5xx (every request gets a fast, deliberate answer:
//     202 reserved, 200 already reserved, 409 sold out, 429 slow down)
//   - p95 latency budget on checkout
//   - at most STOCK reservations accepted (no oversell at the HTTP layer;
//     loadtest/run.sh then verifies the database after the queue drains)
import http from 'k6/http'
import { check } from 'k6'
import { SharedArray } from 'k6/data'
import { Counter } from 'k6/metrics'

const BASE = __ENV.BASE_URL || 'http://localhost:8080'
const SALE = __ENV.SALE_ID || '1'
const RATE = Number(__ENV.RATE || 1500)
const DURATION = __ENV.DURATION || '10s'
const STOCK = Number(__ENV.STOCK || 500)

// Parsed once and shared read-only by all VUs (not one copy per VU).
const tokens = new SharedArray('tokens', () => JSON.parse(open('/data/tokens.json')))

const accepted = new Counter('checkout_accepted') // 202: a unit was reserved
const duplicate = new Counter('checkout_duplicate') // 200: same order returned
const soldOut = new Counter('checkout_sold_out') // 409
const limited = new Counter('checkout_rate_limited') // 429

http.setResponseCallback(http.expectedStatuses(200, 202, 409, 429))

export const options = {
  discardResponseBodies: false,
  scenarios: {
    checkout_spike: {
      executor: 'ramping-arrival-rate',
      exec: 'checkout',
      startRate: 0,
      timeUnit: '1s',
      preAllocatedVUs: 1500,
      maxVUs: 4000,
      stages: [
        { target: RATE, duration: '2s' }, // 8:00:00 PM — the stampede
        { target: RATE, duration: DURATION },
        { target: 0, duration: '2s' },
      ],
    },
    status_pollers: {
      executor: 'constant-arrival-rate',
      exec: 'status',
      rate: 500,
      timeUnit: '1s',
      duration: '14s',
      preAllocatedVUs: 100,
      maxVUs: 400,
    },
  },
  thresholds: {
    'http_req_failed{scenario:checkout_spike}': ['rate==0'],
    'http_req_failed{scenario:status_pollers}': ['rate==0'],
    'http_req_duration{scenario:checkout_spike}': ['p(95)<250', 'p(99)<1000'],
    'http_req_duration{scenario:status_pollers}': ['p(95)<200'],
    checkout_accepted: [`count<=${STOCK}`],
    dropped_iterations: ['count==0'],
  },
}

export function checkout() {
  const token = tokens[Math.floor(Math.random() * tokens.length)]
  const res = http.post(`${BASE}/api/v1/sales/${SALE}/checkout`, null, {
    headers: { Authorization: `Bearer ${token}`, 'User-Agent': 'Mozilla/5.0 (k6 flash-sale test)' },
    tags: { name: 'checkout' },
    timeout: '10s',
  })
  if (res.status === 202) accepted.add(1)
  else if (res.status === 200) duplicate.add(1)
  else if (res.status === 409) soldOut.add(1)
  else if (res.status === 429) limited.add(1)
  check(res, { 'deliberate answer (200/202/409/429)': (r) => [200, 202, 409, 429].includes(r.status) })
}

export function status() {
  const res = http.get(`${BASE}/api/v1/sales/${SALE}/status`, {
    headers: { 'User-Agent': 'Mozilla/5.0 (k6 poller)' },
    tags: { name: 'status' },
  })
  check(res, { 'status 200': (r) => r.status === 200 })
}
