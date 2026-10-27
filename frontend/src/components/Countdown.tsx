import { splitDuration } from '../lib/format'

export function Countdown({ msLeft }: { msLeft: number }) {
  const { h, m, s } = splitDuration(msLeft)
  return (
    <div className="countdown" role="timer" aria-live="off" aria-label={`Sale opens in ${h}:${m}:${s}`}>
      {[
        [h, 'hrs'],
        [m, 'min'],
        [s, 'sec'],
      ].map(([value, unit]) => (
        <div key={unit} className="countdown-cell">
          <span className="countdown-value">{value}</span>
          <span className="countdown-unit">{unit}</span>
        </div>
      ))}
    </div>
  )
}
