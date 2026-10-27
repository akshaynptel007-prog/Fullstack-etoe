import { useEffect, useState } from 'react'
import { Link } from 'wouter'

import type { CheckoutPhase } from '../store/checkout'

const DONE_COPY = {
  CONFIRMED: { tone: 'ok', title: 'Order confirmed!', body: 'Your Nova X Pro is reserved. A confirmation will follow.' },
  REJECTED_SOLD_OUT: { tone: 'warn', title: 'Just missed it', body: 'The last unit went a moment before yours. You were not charged.' },
  REJECTED_DUPLICATE: { tone: 'warn', title: 'Already purchased', body: 'This account already owns a unit from this sale (limit one).' },
  FAILED: { tone: 'err', title: 'We couldn’t complete your order', body: 'Your reservation was released and you were not charged.' },
} as const

function useElapsedSeconds(since: number): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [])
  return Math.max(0, Math.floor((now - since) / 1000))
}

function Queued({ since, orderId }: { since: number; orderId: string }) {
  const elapsed = useElapsedSeconds(since)
  return (
    <div className="notice notice-info" role="status" aria-live="polite">
      <strong>Your unit is reserved — confirming your order…</strong>
      <p>
        {elapsed < 8
          ? 'This usually takes a second or two. Keep this tab open.'
          : 'Demand is very high. Your place is held; we’re still confirming.'}{' '}
        <Link href={`/orders/${orderId}`}>Track order</Link>
      </p>
    </div>
  )
}

export function CheckoutStatus({ phase }: { phase: CheckoutPhase }) {
  switch (phase.kind) {
    case 'submitting':
      return phase.retryInMs ? (
        <div className="notice notice-info" role="status" aria-live="polite">
          Lots of shoppers right now — retrying automatically in {Math.ceil(phase.retryInMs / 1000)}s.
          Don’t refresh; your click is already counted.
        </div>
      ) : null
    case 'queued':
      return <Queued since={phase.since} orderId={phase.orderId} />
    case 'done': {
      const copy = DONE_COPY[phase.status]
      return (
        <div className={`notice notice-${copy.tone}`} role="status" aria-live="polite">
          <strong>{copy.title}</strong>
          <p>
            {copy.body} <Link href="/orders">View my orders</Link>
          </p>
        </div>
      )
    }
    case 'sold_out':
      return (
        <div className="notice notice-warn" role="status" aria-live="polite">
          <strong>Sold out.</strong> All 500 units have been reserved — thanks for joining!
        </div>
      )
    case 'error':
      return (
        <div className="notice notice-err" role="alert">
          {phase.message}
        </div>
      )
    default:
      return null
  }
}
