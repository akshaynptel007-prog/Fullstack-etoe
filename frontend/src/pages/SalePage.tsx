import { useEffect, useState } from 'react'

import { AuthPanel } from '../components/AuthPanel'
import { BuyButton } from '../components/BuyButton'
import { CheckoutStatus } from '../components/CheckoutStatus'
import { Countdown } from '../components/Countdown'
import { PhoneArt } from '../components/PhoneArt'
import { StockMeter } from '../components/StockMeter'
import { useCheckout } from '../hooks/useCheckout'
import { useServerNow } from '../hooks/useNow'
import { useSaleStream } from '../hooks/useSaleStream'
import { formatMoney, formatTime } from '../lib/format'
import { useAuthStore } from '../store/auth'
import { displayedRemaining, effectiveState, useSaleStore } from '../store/sale'

const STATE_BADGE = {
  upcoming: 'Opens soon',
  live: 'Live now',
  sold_out: 'Sold out',
  ended: 'Ended',
} as const

export default function SalePage() {
  const sale = useSaleStore((s) => s.sale)
  const status = useSaleStore((s) => s.status)
  const hold = useSaleStore((s) => s.optimisticHold)
  const liveMode = useSaleStore((s) => s.liveMode)
  const signedIn = useAuthStore((s) => s.token !== null)
  const [showAuth, setShowAuth] = useState(false)
  const now = useServerNow(250)
  const { phase, buy } = useCheckout(sale?.id)

  useSaleStream(sale?.id)

  // Pre-fetch the order-tracking chunk while the browser is idle, so the
  // post-purchase screen is instant even under load.
  useEffect(() => {
    const prefetch = () => void import('./OrdersPage')
    if ('requestIdleCallback' in window) {
      const id = requestIdleCallback(prefetch, { timeout: 5000 })
      return () => cancelIdleCallback(id)
    }
    const id = setTimeout(prefetch, 2000)
    return () => clearTimeout(id)
  }, [])

  if (!sale) return null

  const state = effectiveState(sale, status, now)
  const remaining = displayedRemaining(status, sale, hold)
  const msToStart = Date.parse(sale.starts_at) - now
  const price = formatMoney(sale.product.price_cents, sale.product.currency)

  return (
    <main className="page">
      <section className="hero">
        <div className="hero-art">
          <PhoneArt />
        </div>
        <div className="hero-body">
          <div className="hero-meta">
            <span className="eyebrow">{sale.name}</span>
            <span className={`badge badge-${state}`}>{STATE_BADGE[state]}</span>
          </div>
          <h1>{sale.product.name}</h1>
          <p className="desc">{sale.product.description}</p>
          <p className="price">
            {price} <span className="price-note">· limit 1 per customer</span>
          </p>

          {state === 'upcoming' && (
            <div className="opens">
              <span className="opens-label">Opens {formatTime(sale.starts_at)}</span>
              <Countdown msLeft={msToStart} />
            </div>
          )}

          <StockMeter remaining={remaining} total={sale.total_stock} liveMode={liveMode} />

          <BuyButton
            saleState={state}
            signedIn={signedIn}
            phase={phase}
            priceLabel={price}
            onBuy={() => void buy()}
            onSignIn={() => setShowAuth(true)}
          />
          <CheckoutStatus phase={phase} />
          {!signedIn && (showAuth || state === 'upcoming') && (
            <AuthPanel onDone={() => setShowAuth(false)} />
          )}
        </div>
      </section>

      <section className="facts" aria-label="How this sale works">
        <div>
          <h2>Fair for everyone</h2>
          <p>One unit per account. Every click is counted once — no need to refresh or tap again.</p>
        </div>
        <div>
          <h2>Instant answer</h2>
          <p>Your unit is held the moment you tap Buy; we confirm the order a second later.</p>
        </div>
        <div>
          <h2>Never oversold</h2>
          <p>Stock is counted atomically, so if you’re confirmed, a phone is truly yours.</p>
        </div>
      </section>
    </main>
  )
}
