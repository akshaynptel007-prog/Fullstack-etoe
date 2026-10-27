import type { SaleStatus } from '../api/types'
import { pollIntervalMs } from './useSaleStream'

const status = (state: SaleStatus['state'], startsInMs: number, now: number): SaleStatus => ({
  sale_id: 1,
  state,
  remaining: 10,
  total_stock: 10,
  starts_at: new Date(now + startsInMs).toISOString(),
  ends_at: new Date(now + 3_600_000).toISOString(),
  server_time_ms: now,
})

describe('pollIntervalMs (dynamic polling)', () => {
  const now = Date.now()
  it('polls rarely far from the start, fast when live, never when final', () => {
    expect(pollIntervalMs(status('upcoming', 10 * 60_000, now), now)).toBe(30_000)
    expect(pollIntervalMs(status('upcoming', 30_000, now), now)).toBe(5_000)
    expect(pollIntervalMs(status('live', -1000, now), now)).toBe(1_500)
    expect(pollIntervalMs(status('sold_out', -1000, now), now)).toBeNull()
  })
})
