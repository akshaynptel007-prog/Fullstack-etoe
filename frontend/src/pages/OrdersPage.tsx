import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'wouter'

import { ApiError } from '../api/client'
import { api } from '../api/endpoints'
import type { Order, OrderListItem, OrderStatus } from '../api/types'
import { AuthPanel } from '../components/AuthPanel'
import { Spinner } from '../components/Spinner'
import { useOrderPolling } from '../hooks/useOrderPolling'
import { formatMoney, formatTime } from '../lib/format'
import { useAuthStore } from '../store/auth'

const STATUS_LABEL: Record<OrderStatus, string> = {
  PENDING: 'Confirming…',
  CONFIRMED: 'Confirmed',
  REJECTED_SOLD_OUT: 'Sold out',
  REJECTED_DUPLICATE: 'Duplicate',
  FAILED: 'Failed',
}

function StatusPill({ status }: { status: OrderStatus }) {
  return <span className={`pill pill-${status.toLowerCase()}`}>{STATUS_LABEL[status]}</span>
}

function OrderTracker({ orderId }: { orderId: string }) {
  const [order, setOrder] = useState<Order | null>(null)
  const [error, setError] = useState<string | null>(null)
  const onResolved = useCallback((o: Order) => setOrder(o), [])
  const onError = useCallback((e: ApiError) => setError(e.message), [])
  useOrderPolling(orderId, onResolved, onError)

  return (
    <section className="card">
      <h1>Order tracking</h1>
      <p className="mono">{orderId}</p>
      {error ? (
        <div className="notice notice-err" role="alert">{error}</div>
      ) : order ? (
        <p>
          Status: <StatusPill status={order.status} />
        </p>
      ) : (
        <p role="status" aria-live="polite">
          <Spinner /> Confirming your order…
        </p>
      )}
      <Link href="/orders">All my orders</Link>
    </section>
  )
}

function OrderList() {
  const [orders, setOrders] = useState<OrderListItem[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    api
      .orders()
      .then(({ data }) => setOrders(data))
      .catch((e: unknown) => setError(e instanceof ApiError ? e.message : 'Could not load orders.'))
  }, [])

  if (error) return <div className="notice notice-err">{error}</div>
  if (!orders) return <Spinner />
  if (orders.length === 0) return <p>No orders yet. <Link href="/">Go to the sale</Link></p>
  return (
    <table className="orders">
      <thead>
        <tr>
          <th>Product</th>
          <th>Status</th>
          <th>Amount</th>
          <th>Reserved</th>
        </tr>
      </thead>
      <tbody>
        {orders.map((o) => (
          <tr key={o.order_id}>
            <td>
              <Link href={`/orders/${o.order_id}`}>{o.product_name}</Link>
              <div className="muted">{o.sale_name}</div>
            </td>
            <td>
              <StatusPill status={o.status} />
            </td>
            <td>{formatMoney(o.amount_cents, o.currency)}</td>
            <td>{formatTime(o.reserved_at)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

export default function OrdersPage() {
  const params = useParams<{ id?: string }>()
  const signedIn = useAuthStore((s) => s.token !== null)
  if (!signedIn) {
    return (
      <main className="page narrow">
        <h1>My orders</h1>
        <AuthPanel />
      </main>
    )
  }
  return (
    <main className="page narrow">
      {params.id ? <OrderTracker orderId={params.id} /> : (
        <section className="card">
          <h1>My orders</h1>
          <OrderList />
        </section>
      )}
    </main>
  )
}
