import { Link } from 'wouter'

import { useAuthStore } from '../store/auth'

const prefetchOrders = () => void import('../pages/OrdersPage')

export function Header() {
  const user = useAuthStore((s) => s.user)
  const signOut = useAuthStore((s) => s.signOut)
  return (
    <header className="header">
      <Link href="/" className="brand" aria-label="Flash Sale home">
        <span>FlashSale</span>
      </Link>
      <nav className="nav">
        {user && (
          <Link href="/orders" onMouseEnter={prefetchOrders} onFocus={prefetchOrders}>
            My orders
          </Link>
        )}
        {user ? (
          <button type="button" className="link-button" onClick={signOut} title={user.email}>
            Sign out
          </button>
        ) : null}
      </nav>
    </header>
  )
}
