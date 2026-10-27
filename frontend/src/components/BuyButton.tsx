import type { SaleState } from '../api/types'
import type { CheckoutPhase } from '../store/checkout'
import { Spinner } from './Spinner'

interface Props {
  saleState: SaleState
  signedIn: boolean
  phase: CheckoutPhase
  priceLabel: string
  onBuy: () => void
  onSignIn: () => void
}

function label(props: Props): { text: string; enabled: boolean; busy: boolean } {
  const { saleState, signedIn, phase, priceLabel } = props
  if (phase.kind === 'submitting')
    return { text: phase.attempt > 0 ? 'High demand — retrying…' : 'Reserving your device…', enabled: false, busy: true }
  if (phase.kind === 'queued') return { text: 'You’re in! Confirming…', enabled: false, busy: true }
  if (phase.kind === 'done')
    return { text: phase.status === 'CONFIRMED' ? 'Order confirmed' : 'Order not completed', enabled: false, busy: false }
  if (phase.kind === 'sold_out' || saleState === 'sold_out') return { text: 'Sold out', enabled: false, busy: false }
  if (saleState === 'ended') return { text: 'Sale ended', enabled: false, busy: false }
  if (!signedIn) return { text: 'Sign in to buy', enabled: true, busy: false }
  if (saleState === 'upcoming') return { text: 'Opens soon', enabled: false, busy: false }
  if (phase.kind === 'error') return { text: phase.retryable ? 'Try again' : 'Unavailable', enabled: phase.retryable, busy: false }
  return { text: `Buy now · ${priceLabel}`, enabled: true, busy: false }
}

/**
 * The button locks on the first click (see useSingleFlight) and stays
 * disabled for the whole request/queue lifecycle, so rapid clicks, double
 * taps and held Enter keys never produce more than one request.
 */
export function BuyButton(props: Props) {
  const { text, enabled, busy } = label(props)
  const needsAuth = !props.signedIn && enabled
  return (
    <button
      type="button"
      className={`buy-button${busy ? ' is-busy' : ''}`}
      disabled={!enabled}
      aria-busy={busy}
      onClick={needsAuth ? props.onSignIn : props.onBuy}
    >
      {busy && <Spinner label={text} />}
      <span>{text}</span>
    </button>
  )
}
