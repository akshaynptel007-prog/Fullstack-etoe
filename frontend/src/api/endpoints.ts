import { useAuthStore } from '../store/auth'
import { request, withRetry } from './client'
import type {
  CheckoutAccepted,
  Order,
  OrderListItem,
  Sale,
  SaleStats,
  SaleStatus,
  TokenResponse,
} from './types'

const token = () => useAuthStore.getState().token

export const api = {
  serverTime: () => request<{ server_time_ms: number }>('/time', { timeoutMs: 3000 }),

  // Matches the <link rel="preload"> in index.html (same URL, mode, credentials).
  currentSale: () => withRetry(() => request<Sale>('/sales/current'), { retries: 3 }),

  saleStatus: (saleId: number, signal?: AbortSignal) =>
    request<SaleStatus>(`/sales/${saleId}/status`, { signal, timeoutMs: 4000 }),

  register: (email: string, password: string) =>
    request<TokenResponse>('/auth/register', { method: 'POST', body: { email, password } }),

  login: (email: string, password: string) =>
    request<TokenResponse>('/auth/login', { method: 'POST', body: { email, password } }),

  checkout: (saleId: number) =>
    request<CheckoutAccepted>(`/sales/${saleId}/checkout`, {
      method: 'POST',
      token: token(),
      timeoutMs: 6000,
    }),

  order: (orderId: string, signal?: AbortSignal) =>
    request<Order>(`/orders/${orderId}`, { token: token(), signal, timeoutMs: 5000 }),

  orders: () => request<OrderListItem[]>('/orders', { token: token() }),

  adminStats: (saleId: number, adminKey: string) =>
    request<SaleStats>(`/admin/sales/${saleId}/stats`, { headers: { 'X-Admin-Key': adminKey } }),

  adminReset: (
    saleId: number,
    adminKey: string,
    body: { stock: number; starts_in_seconds: number; duration_minutes: number },
  ) =>
    request<Sale>(`/admin/sales/${saleId}/reset`, {
      method: 'POST',
      body,
      headers: { 'X-Admin-Key': adminKey },
    }),
}
