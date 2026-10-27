import type { LiveMode } from '../store/sale'

interface Props {
  remaining: number
  total: number
  liveMode: LiveMode
}

const LIVE_LABEL: Record<LiveMode, string> = {
  connecting: 'connecting…',
  sse: 'live',
  polling: 'updating',
  closed: 'final',
}

export function StockMeter({ remaining, total, liveMode }: Props) {
  const pct = total > 0 ? Math.round((remaining / total) * 100) : 0
  const low = remaining > 0 && pct <= 10
  return (
    <div className="stock">
      <div className="stock-head">
        <span>
          <strong>{remaining.toLocaleString('en-IN')}</strong> of {total.toLocaleString('en-IN')} left
          {low && <span className="stock-low"> · almost gone</span>}
        </span>
        <span className={`live-dot live-${liveMode}`}>{LIVE_LABEL[liveMode]}</span>
      </div>
      <div
        className="stock-bar"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={total}
        aria-valuenow={remaining}
        aria-label="Units remaining"
      >
        <div className={`stock-fill${low ? ' is-low' : ''}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}
