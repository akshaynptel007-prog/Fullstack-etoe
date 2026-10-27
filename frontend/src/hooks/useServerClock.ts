import { useEffect } from 'react'

import { api } from '../api/endpoints'
import { useSaleStore } from '../store/sale'

/**
 * NTP-style clock sync: take a few samples of the server clock, keep the one
 * with the smallest round trip, and correct for half of it. The countdown is
 * then driven locally — no polling at all before the sale starts — yet every
 * client flips to "live" within a few ms of the server.
 */
export async function measureClockOffset(samples = 3): Promise<number> {
  let best = { rtt: Number.POSITIVE_INFINITY, offset: 0 }
  for (let i = 0; i < samples; i++) {
    const sentAt = Date.now()
    const t0 = performance.now()
    const { data } = await api.serverTime()
    const rtt = performance.now() - t0
    const offset = data.server_time_ms - (sentAt + rtt / 2)
    if (rtt < best.rtt) best = { rtt, offset }
  }
  return Math.round(best.offset)
}

export function useServerClock(): void {
  const setClockOffset = useSaleStore((s) => s.setClockOffset)
  useEffect(() => {
    let cancelled = false
    const sync = () => {
      measureClockOffset()
        .then((offset) => !cancelled && setClockOffset(offset))
        .catch(() => undefined) // keep the previous offset; the server still enforces the start time
    }
    sync()
    // Laptops sleep and clocks drift: resync when the tab comes back.
    const onVisible = () => document.visibilityState === 'visible' && sync()
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      cancelled = true
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [setClockOffset])
}
