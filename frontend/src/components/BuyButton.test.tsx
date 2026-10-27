import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { BuyButton } from './BuyButton'

const base = {
  signedIn: true,
  priceLabel: '₹49,999',
  onBuy: () => undefined,
  onSignIn: () => undefined,
}

describe('BuyButton', () => {
  it('is disabled before the sale opens', () => {
    render(<BuyButton {...base} saleState="upcoming" phase={{ kind: 'idle' }} />)
    expect(screen.getByRole('button')).toBeDisabled()
    expect(screen.getByRole('button')).toHaveTextContent('Opens soon')
  })

  it('locks while the reservation is in flight', () => {
    render(<BuyButton {...base} saleState="live" phase={{ kind: 'submitting', attempt: 0 }} />)
    const button = screen.getByRole('button')
    expect(button).toBeDisabled()
    expect(button).toHaveAttribute('aria-busy', 'true')
    expect(button).toHaveTextContent('Reserving your device')
  })

  it('asks anonymous users to sign in instead of buying', async () => {
    const onSignIn = vi.fn()
    const onBuy = vi.fn()
    render(<BuyButton {...base} signedIn={false} onBuy={onBuy} onSignIn={onSignIn} saleState="live" phase={{ kind: 'idle' }} />)
    await userEvent.click(screen.getByRole('button', { name: /sign in to buy/i }))
    expect(onSignIn).toHaveBeenCalledOnce()
    expect(onBuy).not.toHaveBeenCalled()
  })

  it('shows sold out as a terminal state', () => {
    render(<BuyButton {...base} saleState="sold_out" phase={{ kind: 'idle' }} />)
    expect(screen.getByRole('button')).toBeDisabled()
    expect(screen.getByRole('button')).toHaveTextContent('Sold out')
  })
})
