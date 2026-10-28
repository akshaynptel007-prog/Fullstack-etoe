import { lazy, Suspense, useEffect, useState } from 'react'
import { Route, Switch } from 'wouter'

import { ApiError } from './api/client'
import { api } from './api/endpoints'
import { ErrorBoundary } from './components/ErrorBoundary'
import { Header } from './components/Header'
import { PageBackLink } from './components/PageBackLink'
import { Spinner } from './components/Spinner'
import { useServerClock } from './hooks/useServerClock'
import SalePage from './pages/SalePage'
import { useSaleStore } from './store/sale'

// Route-level code splitting: the sale page ships in the entry chunk; the
// rest loads on demand (and is prefetched while idle).
const OrdersPage = lazy(() => import('./pages/OrdersPage'))
const AdminPage = lazy(() => import('./pages/AdminPage'))

function useCurrentSale(): string | null {
  const setSale = useSaleStore((s) => s.setSale)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    api
      .currentSale()
      .then(({ data }) => setSale(data))
      .catch((e: unknown) =>
        setError(e instanceof ApiError && e.status === 404 ? 'No sale is scheduled right now.' : 'Could not load the sale. Please refresh.'),
      )
  }, [setSale])
  return error
}

export function App() {
  useServerClock()
  const error = useCurrentSale()
  return (
    <ErrorBoundary>
      <Header />
      {error && (
        <main className="page">
          <div className="notice notice-err" role="alert">{error}</div>
        </main>
      )}
      <Suspense
        fallback={
          <main className="page">
            <Spinner />
          </main>
        }
      >
        <Switch>
          <Route path="/" component={SalePage} />
          <Route path="/orders" component={OrdersPage} />
          <Route path="/orders/:id" component={OrdersPage} />
          <Route path="/admin" component={AdminPage} />
          <Route>
            <main className="page">
              <PageBackLink href="/" label="Home" />
              <p>Page not found.</p>
            </main>
          </Route>
        </Switch>
      </Suspense>
      <footer className="footer">Prices include GST · One unit per customer · FlashSale reference application</footer>
    </ErrorBoundary>
  )
}
