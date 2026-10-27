export type SaleState = 'upcoming' | 'live' | 'sold_out' | 'ended'
export type OrderStatus =
  | 'PENDING'
  | 'CONFIRMED'
  | 'REJECTED_SOLD_OUT'
  | 'REJECTED_DUPLICATE'
  | 'FAILED'

export interface Product {
  id: number
  sku: string
  name: string
  description: string
  price_cents: number
  currency: string
}

export interface Sale {
  id: number
  name: string
  starts_at: string
  ends_at: string
  total_stock: number
  product: Product
}

export interface SaleStatus {
  sale_id: number
  state: SaleState
  remaining: number
  total_stock: number
  starts_at: string
  ends_at: string
  server_time_ms: number
}

export interface User {
  id: string
  email: string
}

export interface TokenResponse {
  access_token: string
  token_type: 'bearer'
  expires_in: number
  user: User
}

export interface CheckoutAccepted {
  order_id: string
  status: OrderStatus
  status_url: string
  poll_after_ms: number
  duplicate: boolean
}

export interface Order {
  order_id: string
  sale_id: number
  status: OrderStatus
  terminal: boolean
  poll_after_ms: number | null
  amount_cents: number | null
  reserved_at: string | null
  processed_at: string | null
}

export interface OrderListItem {
  order_id: string
  status: OrderStatus
  amount_cents: number
  currency: string
  sale_id: number
  sale_name: string
  product_name: string
  reserved_at: string
  processed_at: string
}

export interface SaleStats {
  sale_id: number
  total_stock: number
  db_stock: number
  redis_stock: number | null
  reservations: number
  confirmed: number
  rejected_sold_out: number
  rejected_duplicate: number
  failed: number
  queue_depth: number | null
  oversold: boolean
  consistent: boolean
}
