import { useEffect, useRef } from 'react'

import { ApiError } from '../api/client'
import { api } from '../api/endpoints'
import type { Order } from '../api/types'
import { backoffDelay, sleep } from '../lib/backoff'
import { waitUntilVisible } from './usePageVisibility'

/**
 * Polls the tracking URL returned by `202 Accepted` until the order reaches a
 * terminal state. Exponential backoff with jitter (starting at the server's
 * `poll_after_ms`), paused while the tab is hidden, cancelled on unmount.
 */
export function useOrderPolling(
  orderId: string | null,
  onResolved: (order: Order) => void,
  onError?: (error: ApiError) => void,
): void {
  const resolvedRef = useRef(onResolved)
  const errorRef = useRef(onError)
  useEffect(() => {
    resolvedRef.current = onResolved
    errorRef.current = onError
  })

  useEffect(() => {
    if (!orderId) return
    const controller = new AbortController()
    void (async () => {
      let attempt = 0
      let baseMs = 800
      try {
        while (!controller.signal.aborted) {
          await waitUntilVisible(controller.signal)
          let retryAfterMs: number | undefined
          try {
            const { data } = await api.order(orderId, controller.signal)
            if (data.terminal) {
              resolvedRef.current(data)
              return
            }
            baseMs = data.poll_after_ms ?? baseMs
          } catch (error) {
            if (controller.signal.aborted) return
            if (error instanceof ApiError && !error.retryable) {
              errorRef.current?.(error)
              return
            }
            retryAfterMs = error instanceof ApiError ? error.retryAfterMs : undefined
          }
          await sleep(
            backoffDelay(attempt++, { baseMs, maxMs: 8000, retryAfterMs }),
            controller.signal,
          )
        }
      } catch {
        /* aborted */
      }
    })()
    return () => controller.abort()
  }, [orderId])
}
