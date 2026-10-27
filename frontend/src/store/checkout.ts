import { create } from 'zustand'

import type { OrderStatus } from '../api/types'

export type CheckoutPhase =
  | { kind: 'idle' }
  | { kind: 'submitting'; attempt: number; retryInMs?: number }
  | { kind: 'queued'; orderId: string; since: number }
  | { kind: 'done'; orderId: string; status: Exclude<OrderStatus, 'PENDING'> }
  | { kind: 'sold_out' }
  | { kind: 'error'; message: string; retryable: boolean }

interface CheckoutState {
  phase: CheckoutPhase
  setPhase: (phase: CheckoutPhase) => void
  reset: () => void
}

export const useCheckoutStore = create<CheckoutState>()((set) => ({
  phase: { kind: 'idle' },
  setPhase: (phase) => set({ phase }),
  reset: () => set({ phase: { kind: 'idle' } }),
}))
