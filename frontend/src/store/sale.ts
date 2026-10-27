import { create } from 'zustand'

import type { Sale, SaleState, SaleStatus } from '../api/types'

export type LiveMode = 'connecting' | 'sse' | 'polling' | 'closed'

interface SaleStoreState {
  sale: Sale | null
  status: SaleStatus | null
  /** serverNow = Date.now() + clockOffsetMs (see useServerClock). */
  clockOffsetMs: number
  liveMode: LiveMode
  /** Units optimistically held by this tab while its checkout is in flight. */
  optimisticHold: number
  setSale: (sale: Sale) => void
  setStatus: (status: SaleStatus) => void
  setClockOffset: (ms: number) => void
  setLiveMode: (mode: LiveMode) => void
  hold: () => void
  releaseHold: () => void
}

export const useSaleStore = create<SaleStoreState>()((set) => ({
  sale: null,
  status: null,
  clockOffsetMs: 0,
  liveMode: 'connecting',
  optimisticHold: 0,
  setSale: (sale) => set({ sale }),
  setStatus: (status) =>
    set((s) => {
      // Ignore out-of-order snapshots (SSE + polling can briefly overlap).
      if (s.status && status.server_time_ms < s.status.server_time_ms) return s
      return { status }
    }),
  setClockOffset: (clockOffsetMs) => set({ clockOffsetMs }),
  setLiveMode: (liveMode) => set({ liveMode }),
  hold: () => set({ optimisticHold: 1 }),
  releaseHold: () => set({ optimisticHold: 0 }),
}))

export const serverNow = (): number => Date.now() + useSaleStore.getState().clockOffsetMs

/** The state the UI should show right now, combining server status and the synced clock. */
export function effectiveState(sale: Sale, status: SaleStatus | null, now: number): SaleState {
  if (now >= Date.parse(sale.ends_at)) return 'ended'
  if (status && status.remaining <= 0) return 'sold_out'
  if (status?.state === 'sold_out' || status?.state === 'ended') return status.state
  return now < Date.parse(sale.starts_at) ? 'upcoming' : 'live'
}

export function displayedRemaining(status: SaleStatus | null, sale: Sale, hold: number): number {
  return Math.max(0, (status?.remaining ?? sale.total_stock) - hold)
}
