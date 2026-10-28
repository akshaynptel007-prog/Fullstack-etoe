import { type FormEvent, useEffect, useState } from 'react'
import { Link } from 'wouter'

import { ApiError } from '../api/client'
import { api } from '../api/endpoints'
import type { SaleStats } from '../api/types'
import { readStorage, writeStorage } from '../lib/storage'
import { useSaleStore } from '../store/sale'

const KEY = 'flashsale.adminKey'

/** Admin console: monitor inventory invariants and reset the sale. */
export default function AdminPage() {
  const sale = useSaleStore((s) => s.sale)
  const [adminKey, setAdminKey] = useState(() => readStorage('session', KEY) ?? '')
  const [stats, setStats] = useState<SaleStats | null>(null)
  const [message, setMessage] = useState<string | null>(null)

  useEffect(() => {
    if (!sale || !adminKey) return
    let cancelled = false
    const load = () =>
      api
        .adminStats(sale.id, adminKey)
        .then(({ data }) => !cancelled && setStats(data))
        .catch((e: unknown) => !cancelled && setMessage(e instanceof ApiError ? e.message : String(e)))
    void load()
    const id = setInterval(load, 1500)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [sale, adminKey])

  async function reset(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!sale) return
    const form = new FormData(event.currentTarget)
    try {
      const { data: updatedSale } = await api.adminReset(sale.id, adminKey, {
        stock: Number(form.get('stock')),
        starts_in_seconds: Number(form.get('starts_in')),
        duration_minutes: Number(form.get('duration')),
      })
      useSaleStore.getState().setSale(updatedSale)
      setMessage('Sale schedule and inventory updated.')
    } catch (e) {
      setMessage(e instanceof ApiError ? e.message : String(e))
    }
  }

  return (
    <main className="page narrow">
      <Link href="/" className="page-back">← Back to sale</Link>
      <section className="card">
        <h1>Sale console</h1>
        <label>
          Admin key
          <input
            type="password"
            value={adminKey}
            onChange={(e) => {
              setAdminKey(e.target.value)
              writeStorage('session', KEY, e.target.value)
            }}
            placeholder="X-Admin-Key (local: local-admin-key)"
          />
        </label>
        {message && <p className="notice notice-info">{message}</p>}
      </section>

      {stats && (
        <section className="card">
          <h2>Invariants</h2>
          <div className="stats">
            <Stat label="Total stock" value={stats.total_stock} />
            <Stat label="Confirmed" value={stats.confirmed} />
            <Stat label="DB stock" value={stats.db_stock} />
            <Stat label="Redis tokens" value={stats.redis_stock ?? '—'} />
            <Stat label="Reservations" value={stats.reservations} />
            <Stat label="Queue depth" value={stats.queue_depth ?? '—'} />
            <Stat label="Rejected (sold out)" value={stats.rejected_sold_out} />
            <Stat label="Rejected (duplicate)" value={stats.rejected_duplicate} />
          </div>
          <p className={stats.consistent && !stats.oversold ? 'ok' : 'err'}>
            confirmed + db_stock = total_stock → {stats.consistent ? 'holds' : 'VIOLATED'} · oversold:{' '}
            {stats.oversold ? 'YES' : 'no'}
          </p>
        </section>
      )}

      <section className="card">
        <h2>Reset sale</h2>
        <form className="reset" onSubmit={reset}>
          <label>
            Stock <input name="stock" type="number" min={0} defaultValue={500} />
          </label>
          <label>
            Starts in (s) <input name="starts_in" type="number" min={0} defaultValue={30} />
          </label>
          <label>
            Duration (min) <input name="duration" type="number" min={1} defaultValue={60} />
          </label>
          <button type="submit" disabled={!adminKey || !sale}>
            Reset
          </button>
        </form>
      </section>
    </main>
  )
}

function Stat({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="stat">
      <span className="stat-value">{value}</span>
      <span className="stat-label">{label}</span>
    </div>
  )
}
