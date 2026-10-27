import { backoffDelay, parseRetryAfter, sleep } from '../lib/backoff'

export const API_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? '/api/v1'

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly retryAfterMs: number | undefined

  constructor(status: number, code: string, message: string, retryAfterMs?: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.retryAfterMs = retryAfterMs
  }

  /** Network failures, timeouts, 429 and 5xx are worth retrying; 4xx are not. */
  get retryable(): boolean {
    return this.status === 0 || this.status === 429 || this.status >= 500
  }
}

export interface RequestOptions {
  method?: 'GET' | 'POST'
  body?: unknown
  token?: string | null
  headers?: Record<string, string>
  signal?: AbortSignal
  timeoutMs?: number
}

export interface ApiResponse<T> {
  data: T
  status: number
  headers: Headers
}

/**
 * fetch() with a hard timeout and a uniform error model. A request can never
 * hang the UI: after `timeoutMs` it fails with a retryable TIMEOUT error.
 */
export async function request<T>(path: string, opts: RequestOptions = {}): Promise<ApiResponse<T>> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), opts.timeoutMs ?? 8000)
  const forwardAbort = () => controller.abort()
  opts.signal?.addEventListener('abort', forwardAbort, { once: true })

  const headers: Record<string, string> = { Accept: 'application/json', ...opts.headers }
  if (opts.body !== undefined) headers['Content-Type'] = 'application/json'
  if (opts.token) headers.Authorization = `Bearer ${opts.token}`

  try {
    const res = await fetch(`${API_BASE}${path}`, {
      method: opts.method ?? 'GET',
      headers,
      body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
      signal: controller.signal,
    })
    const text = await res.text()
    let json: unknown = null
    try {
      json = text ? JSON.parse(text) : null
    } catch {
      json = null // e.g. an HTML error page from a proxy
    }
    if (!res.ok) {
      const err = (json as { error?: { code?: string; message?: string } } | null)?.error
      throw new ApiError(
        res.status,
        err?.code ?? `HTTP_${res.status}`,
        err?.message ?? (res.statusText || 'Request failed'),
        parseRetryAfter(res.headers.get('Retry-After')),
      )
    }
    return { data: json as T, status: res.status, headers: res.headers }
  } catch (error) {
    if (error instanceof ApiError) throw error
    if (opts.signal?.aborted) throw error // cancelled by the caller: not an API failure
    const timedOut = controller.signal.aborted
    throw new ApiError(
      0,
      timedOut ? 'TIMEOUT' : 'NETWORK',
      timedOut ? 'The request timed out.' : 'Network error — check your connection.',
    )
  } finally {
    clearTimeout(timer)
    opts.signal?.removeEventListener('abort', forwardAbort)
  }
}

export interface RetryOptions {
  retries: number
  baseMs?: number
  maxMs?: number
  signal?: AbortSignal
  onRetry?: (attempt: number, delayMs: number, error: ApiError) => void
}

/** Retries retryable ApiErrors with jittered backoff, honouring Retry-After. */
export async function withRetry<T>(fn: () => Promise<T>, opts: RetryOptions): Promise<T> {
  for (let attempt = 0; ; attempt++) {
    try {
      return await fn()
    } catch (error) {
      if (!(error instanceof ApiError) || !error.retryable || attempt >= opts.retries) throw error
      const delay = backoffDelay(attempt, {
        baseMs: opts.baseMs ?? 400,
        maxMs: opts.maxMs ?? 5000,
        retryAfterMs: error.retryAfterMs,
      })
      opts.onRetry?.(attempt + 1, delay, error)
      await sleep(delay, opts.signal)
    }
  }
}
