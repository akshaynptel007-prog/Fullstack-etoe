const moneyFormatters = new Map<string, Intl.NumberFormat>()

export function formatMoney(cents: number, currency: string): string {
  let fmt = moneyFormatters.get(currency)
  if (!fmt) {
    fmt = new Intl.NumberFormat('en-IN', { style: 'currency', currency, maximumFractionDigits: 0 })
    moneyFormatters.set(currency, fmt)
  }
  return fmt.format(cents / 100)
}

export function splitDuration(ms: number): { h: string; m: string; s: string } {
  const total = Math.max(0, Math.ceil(ms / 1000))
  const pad = (n: number) => String(n).padStart(2, '0')
  return { h: pad(Math.floor(total / 3600)), m: pad(Math.floor((total % 3600) / 60)), s: pad(total % 60) }
}

export function formatTime(iso: string): string {
  return new Date(iso).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' })
}
