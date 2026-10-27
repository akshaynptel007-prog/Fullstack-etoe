export interface BackoffOptions {
  baseMs: number
  maxMs: number
  /** Server-provided Retry-After always wins as a lower bound. */
  retryAfterMs?: number | undefined
  random?: () => number
}

/**
 * Exponential backoff with "equal jitter": half the delay is fixed, half is
 * random. The randomness de-synchronises clients so a failure at 8:00:00 PM
 * does not turn into 100k retries at exactly 8:00:01 PM (thundering herd).
 */
export function backoffDelay(attempt: number, opts: BackoffOptions): number {
  const random = opts.random ?? Math.random
  const exp = Math.min(opts.maxMs, opts.baseMs * 2 ** Math.max(0, attempt))
  const jittered = exp / 2 + random() * (exp / 2)
  return Math.round(Math.max(jittered, opts.retryAfterMs ?? 0))
}

export function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) return reject(signal.reason)
    const timer = setTimeout(() => {
      signal?.removeEventListener('abort', onAbort)
      resolve()
    }, ms)
    const onAbort = () => {
      clearTimeout(timer)
      reject(signal?.reason)
    }
    signal?.addEventListener('abort', onAbort, { once: true })
  })
}

export function parseRetryAfter(value: string | null, now = Date.now()): number | undefined {
  if (!value) return undefined
  const seconds = Number(value)
  if (Number.isFinite(seconds)) return Math.max(0, seconds * 1000)
  const date = Date.parse(value)
  return Number.isNaN(date) ? undefined : Math.max(0, date - now)
}
