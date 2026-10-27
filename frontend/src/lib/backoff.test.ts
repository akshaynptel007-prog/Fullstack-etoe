import { backoffDelay, parseRetryAfter } from './backoff'

describe('backoffDelay', () => {
  it('grows exponentially and is capped', () => {
    const fixed = { baseMs: 100, maxMs: 1000, random: () => 1 }
    expect([0, 1, 2, 3, 4, 10].map((a) => backoffDelay(a, fixed))).toEqual([100, 200, 400, 800, 1000, 1000])
  })

  it('applies equal jitter (between half and full delay)', () => {
    expect(backoffDelay(2, { baseMs: 100, maxMs: 10_000, random: () => 0 })).toBe(200)
    expect(backoffDelay(2, { baseMs: 100, maxMs: 10_000, random: () => 1 })).toBe(400)
  })

  it('never retries sooner than Retry-After', () => {
    expect(backoffDelay(0, { baseMs: 100, maxMs: 1000, retryAfterMs: 3000, random: () => 0 })).toBe(3000)
  })
})

describe('parseRetryAfter', () => {
  it('parses seconds and HTTP dates', () => {
    expect(parseRetryAfter('2')).toBe(2000)
    expect(parseRetryAfter(new Date(10_000).toUTCString(), 4_000)).toBe(6000)
    expect(parseRetryAfter(null)).toBeUndefined()
    expect(parseRetryAfter('garbage')).toBeUndefined()
  })
})
