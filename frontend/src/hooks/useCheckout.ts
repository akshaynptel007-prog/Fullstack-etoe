import { useCallback } from 'react'

import { ApiError, withRetry } from '../api/client'
import { api } from '../api/endpoints'
import type { Order } from '../api/types'
import { useAuthStore } from '../store/auth'
import { useCheckoutStore } from '../store/checkout'
import { useSaleStore } from '../store/sale'
import { useOrderPolling } from './useOrderPolling'
import { useSingleFlight } from './useSingleFlight'

/**
 * The buy flow:
 *   click ─► lock UI + optimistic hold ─► POST checkout (retry 429/5xx with
 *   jitter, safe because the server is idempotent per user) ─► 202 queued
 *   ─► poll tracking URL ─► confirmed / rejected
 */
export function useCheckout(saleId: number | undefined) {
  const phase = useCheckoutStore((s) => s.phase)
  const setPhase = useCheckoutStore((s) => s.setPhase)
  const sessionToken = useAuthStore((s) => s.token)

  const buy = useSingleFlight(async () => {
    if (saleId === undefined) return
    const token = useAuthStore.getState().token
    if (!token) return
    const { hold, releaseHold } = useSaleStore.getState()
    setPhase({ kind: 'submitting', attempt: 0 })
    hold() // optimistic: show our unit as taken immediately
    try {
      const { data } = await withRetry(() => api.checkout(saleId), {
        retries: 4,
        baseMs: 500,
        maxMs: 4000,
        onRetry: (attempt, delayMs) => {
          if (useAuthStore.getState().token !== token) return
          setPhase({ kind: 'submitting', attempt, retryInMs: delayMs })
        },
      })
      if (useAuthStore.getState().token !== token) return
      setPhase({ kind: 'queued', orderId: data.order_id, since: Date.now() })
    } catch (error) {
      if (useAuthStore.getState().token !== token) return
      const e = error instanceof ApiError ? error : new ApiError(0, 'UNKNOWN', String(error))
      if (e.code === 'SOLD_OUT') {
        setPhase({ kind: 'sold_out' })
      } else if (e.status === 401) {
        useAuthStore.getState().signOut()
        setPhase({ kind: 'error', message: 'Your session expired — sign in to continue.', retryable: false })
      } else if (e.code === 'SALE_NOT_STARTED') {
        setPhase({ kind: 'error', message: 'Not quite yet — the sale opens in a moment.', retryable: true })
      } else {
        setPhase({ kind: 'error', message: e.message, retryable: e.retryable || e.status === 409 })
      }
    } finally {
      if (useAuthStore.getState().token === token) {
        releaseHold() // the server's own counter now reflects the reservation
      }
    }
  }, 300, sessionToken)

  const onResolved = useCallback(
    (order: Order) => {
      if (useAuthStore.getState().token !== sessionToken) return
      if (order.status === 'PENDING') return
      setPhase({ kind: 'done', orderId: order.order_id, status: order.status })
    },
    [sessionToken, setPhase],
  )
  const onPollError = useCallback(
    (error: ApiError) => {
      if (useAuthStore.getState().token !== sessionToken) return
      setPhase({ kind: 'error', message: error.message, retryable: false })
    },
    [sessionToken, setPhase],
  )
  useOrderPolling(phase.kind === 'queued' ? phase.orderId : null, onResolved, onPollError)

  return { phase, buy }
}
