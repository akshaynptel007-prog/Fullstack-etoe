# Frontend strategy

Targets from the case study: **bundle < 200 KB**, **Time-to-Interactive < 1.5 s**, no API spam from
rapid clicks, and graceful loading and failure without freezing.

## 1. Click spam: lock, throttle, idempotency

`src/hooks/useSingleFlight.ts` wraps the buy action:

- A **ref** (`busy.current`) flips synchronously inside the click handler. React state alone is not
  enough: two clicks in the same frame both see the old state before a re-render, and both would
  send a request. The ref closes that window.
- A 300 ms **throttle** after completion absorbs bounce and double-taps after an error.
- The button stays **disabled** for the whole lifecycle (`submitting → queued → done`), with
  `aria-busy` and `touch-action: manipulation` (no 300 ms tap delay on mobile).
- The safety net is the server: checkout is idempotent per user, so even a second tab gets the
  same `order_id` back with `200`.

The unit test fires a triple-click plus another click while the request is in flight, and asserts
exactly one call.

### Debounce or throttle?

**Debounce** delays the action until the clicks stop, which would add latency to the first click.
In a race for 500 units, that latency costs the sale. **Throttling with a leading edge** (fire
immediately, ignore the rest) is the right primitive, and the single-flight lock is its strongest
form.

## 2. Optimistic UI and graceful waiting

| Phase | What the user sees | Mechanism |
|---|---|---|
| click | "Reserving your device…", stock −1 immediately | `optimisticHold` in the sale store |
| `202` | "You're in! Confirming your order…" (copy changes to "demand is very high, your place is held" after 8 s) | `useOrderPolling` |
| retryable error (429/503/timeout) | "Lots of shoppers — retrying in 2 s. Don't refresh; your click is counted." | `withRetry` + `Retry-After` |
| `409 SOLD_OUT` | terminal "Sold out" state, hold rolled back | |
| `CONFIRMED` / `REJECTED_*` | honest final message + link to orders | |

Nothing blocks the main thread: every network call has a hard timeout (`AbortController`), and
every failure maps to a visible state.

## 3. Sale status: SSE vs WebSockets vs polling

See [ADR-0003](adr/0003-sse-with-polling-fallback.md). Summary:

- **Before the sale**, nothing polls. The countdown runs locally from an NTP-style clock offset
  (best of 3 `GET /time` samples, corrected by RTT/2). The server's Redis clock is still the
  authority on when the sale opens.
- **Live stock** uses **Server-Sent Events**. Updates flow server → client only, so WebSockets'
  bidirectional channel buys nothing here. SSE is plain HTTP, so it passes through CloudFront, ALB
  and NGINX unmodified, reconnects automatically, and costs one in-memory queue per connection on
  the server.
- **Fallback:** after 3 SSE errors, or if the server sheds streams with `503`, the client polls
  `GET /status`. That endpoint is cached for 1 s at the edge with request collapsing. The interval
  **adapts**: 30 s when far from the start, 5 s in the last minute, 1.5 s live, and it stops once sold
  out or ended. It is jittered and paused in background tabs. SSE is retried after 30 s.
- **Order status** uses polling of the `202` tracking URL with exponential backoff and jitter,
  starting at the server-provided `poll_after_ms`. A pending order is short-lived and needs no
  persistent connection.

## 4. Bundle budget (< 200 KB)

| Choice | Saving |
|---|---|
| React 18 instead of 19 | measured: entry chunk 247 KB → 168 KB minified (−79 KB); every API used here exists in 18 |
| zustand (≈1 KB) instead of Redux Toolkit | ≈ 15 KB |
| wouter (≈2 KB) instead of React Router | ≈ 20 KB |
| no UI kit, hand-written CSS (7.8 KB) | tens of KB |
| inline SVG product art | no image requests at all |
| system font stack | no font files |
| route-level `lazy()` for Orders and Admin | off the critical path |

Result (`npm run check:size`): **177 KB minified total, 58 KB gzip total, 56 KB gzip initial.**
The check runs inside the Docker build (`frontend/Dockerfile`) and in CI, so an oversized bundle
cannot ship. The budget uses the strict reading of "< 200 KB": all JS+CSS, minified, *uncompressed*.

## 5. Time-to-Interactive (< 1.5 s)

| Technique | Where |
|---|---|
| Critical CSS + skeleton inlined in `index.html` (first paint before any JS) | `index.html` |
| `<link rel="preload" as="fetch">` for `/api/v1/sales/current`, so the data downloads in parallel with the JS | `index.html` |
| One small entry chunk; Orders/Admin chunks prefetched with `requestIdleCallback` and on link hover | `SalePage.tsx`, `Header.tsx` |
| Content-hashed assets with `Cache-Control: immutable`; `index.html` is `no-cache` | NGINX / `deploy.sh` |
| Pre-compressed `.gz` assets (`gzip_static`); Brotli at CloudFront | `vite.config.ts` |
| CDN edge delivery (CloudFront, HTTP/2 + HTTP/3) | `infra/terraform/modules/edge` |
| Status snapshot fetched on mount, so real stock shows before SSE connects | `useSaleStream.ts` |

CI runs Lighthouse (desktop preset, median of 3) against the compose stack. It asserts
`interactive ≤ 1.5 s`, `LCP ≤ 1.5 s`, `TBT ≤ 200 ms`, `CLS ≤ 0.1` and script size ≤ 200 KB
(`frontend/lighthouserc.json`).

## 6. Asset pre-fetching and CDN

- Static files never touch the API: S3 + CloudFront on AWS, NGINX locally.
- Hashed assets are cached for a year at the edge and in the browser. Deploys upload new hashes
  and keep old ones, so tabs holding the previous `index.html` keep working mid-deploy.
- The sale page prefetches the order-tracking chunk while idle, so the post-purchase screen loads
  instantly even when the network is congested at 8:00 PM.

## State management

Three small zustand stores (`auth`, `sale`, `checkout`) with selector subscriptions. The countdown
and stock meter re-render without re-rendering the page. `useServerNow` ticks only in the
components that need it.
