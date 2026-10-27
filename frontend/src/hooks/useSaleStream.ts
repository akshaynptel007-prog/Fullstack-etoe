import { useEffect } from 'react'

import { API_BASE } from '../api/client'
import { api } from '../api/endpoints'
import type { SaleStatus } from '../api/types'
import { backoffDelay, sleep } from '../lib/backoff'
import { serverNow, useSaleStore } from '../store/sale'
import { waitUntilVisible } from './usePageVisibility'

const SSE_FAILURES_BEFORE_FALLBACK = 3
const SSE_RETRY_AFTER_FALLBACK_MS = 30_000

/** How often to poll when SSE is unavailable — adapts to the sale's phase. */
export function pollIntervalMs(status: SaleStatus | null, now: number): number | null {
  if (!status) return 2000
  if (status.state === 'sold_out' || status.state === 'ended') return null // nothing will change
  const untilStart = Date.parse(status.starts_at) - now
  if (untilStart > 60_000) return 30_000 // far from the start: stock can't move
  if (untilStart > 5_000) return 5_000
  return 1_500 // live: the status endpoint is edge-cached for 1 s anyway
}

/**
 * Live stock updates. Prefers Server-Sent Events (one-way push, plain HTTP,
 * CDN/proxy friendly, auto-reconnect built in); after repeated failures it
 * falls back to adaptive polling of the micro-cached status endpoint and
 * periodically tries SSE again.
 */
export function useSaleStream(saleId: number | undefined): void {
  useEffect(() => {
    if (saleId === undefined) return
    const { setStatus, setLiveMode } = useSaleStore.getState()
    const controller = new AbortController()
    let source: EventSource | null = null
    let failures = 0

    const onStatus = (event: MessageEvent<string>) => {
      failures = 0
      setLiveMode('sse')
      setStatus(JSON.parse(event.data) as SaleStatus)
    }

    const openStream = () => {
      if (controller.signal.aborted) return
      if (typeof EventSource === 'undefined') {
        void poll()
        return
      }
      setLiveMode('connecting')
      source = new EventSource(`${API_BASE}/sales/${saleId}/events`)
      source.addEventListener('status', onStatus as EventListener)
      source.addEventListener('end', () => {
        source?.close()
        setLiveMode('closed') // sold out / ended: stop all live traffic
      })
      source.onerror = () => {
        failures += 1
        if (failures >= SSE_FAILURES_BEFORE_FALLBACK) {
          source?.close()
          source = null
          void poll()
        }
        // otherwise EventSource reconnects by itself (server sends `retry:`)
      }
    }

    const poll = async () => {
      setLiveMode('polling')
      const pollingUntil = Date.now() + SSE_RETRY_AFTER_FALLBACK_MS
      let attempt = 0
      try {
        while (!controller.signal.aborted) {
          await waitUntilVisible(controller.signal)
          let delay: number | null
          try {
            const { data } = await api.saleStatus(saleId, controller.signal)
            setStatus(data)
            attempt = 0
            delay = pollIntervalMs(data, serverNow())
            if (delay === null) {
              setLiveMode('closed')
              return
            }
          } catch {
            delay = backoffDelay(attempt++, { baseMs: 1000, maxMs: 15_000 })
          }
          // Jitter de-synchronises 100k pollers.
          await sleep(delay * (0.8 + Math.random() * 0.4), controller.signal)
          if (typeof EventSource !== 'undefined' && Date.now() > pollingUntil) break
        }
      } catch {
        return // aborted
      }
      failures = 0
      openStream() // give SSE another chance
    }

    openStream()
    return () => {
      controller.abort()
      source?.close()
    }
  }, [saleId])
}
