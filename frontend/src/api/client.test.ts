import { ApiError, request, withRetry } from './client'

function respond(status: number, body: unknown, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json', ...headers } })
}

describe('request', () => {
  it('maps error bodies to ApiError with Retry-After', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      respond(429, { error: { code: 'RATE_LIMITED', message: 'slow down' } }, { 'Retry-After': '3' }),
    )
    const error = await request('/x').catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ status: 429, code: 'RATE_LIMITED', retryAfterMs: 3000, retryable: true })
  })

  it('treats non-JSON proxy error pages gracefully', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('<html>502</html>', { status: 502 }))
    await expect(request('/x')).rejects.toMatchObject({ status: 502, code: 'HTTP_502', retryable: true })
  })

  it('times out instead of hanging', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(
      (_url, init) =>
        new Promise((_resolve, reject) => {
          init?.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
        }),
    )
    await expect(request('/x', { timeoutMs: 20 })).rejects.toMatchObject({ status: 0, code: 'TIMEOUT' })
  })
})

describe('withRetry', () => {
  it('retries retryable errors and then succeeds', async () => {
    const fn = vi
      .fn<() => Promise<string>>()
      .mockRejectedValueOnce(new ApiError(503, 'QUEUE_UNAVAILABLE', 'busy'))
      .mockResolvedValueOnce('ok')
    const onRetry = vi.fn()
    await expect(withRetry(fn, { retries: 2, baseMs: 1, maxMs: 2, onRetry })).resolves.toBe('ok')
    expect(fn).toHaveBeenCalledTimes(2)
    expect(onRetry).toHaveBeenCalledOnce()
  })

  it('does not retry client errors such as SOLD_OUT', async () => {
    const fn = vi.fn<() => Promise<string>>().mockRejectedValue(new ApiError(409, 'SOLD_OUT', 'gone'))
    await expect(withRetry(fn, { retries: 5, baseMs: 1 })).rejects.toMatchObject({ code: 'SOLD_OUT' })
    expect(fn).toHaveBeenCalledOnce()
  })
})
