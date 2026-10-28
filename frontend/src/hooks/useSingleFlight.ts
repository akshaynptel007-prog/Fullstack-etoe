import { useCallback, useLayoutEffect, useRef } from 'react'

/**
 * Wraps an async action so it can only run once at a time, and not again
 * within `minIntervalMs` of the previous run finishing (throttle).
 *
 * The lock is a ref, flipped synchronously on the first click. React state
 * alone is not enough: two clicks in the same frame both see the old state
 * before a re-render, and would both fire a request.
 */
export function useSingleFlight<Args extends unknown[]>(
  action: (...args: Args) => Promise<void>,
  minIntervalMs = 0,
  scopeKey?: unknown,
): (...args: Args) => Promise<void> {
  const busy = useRef(false)
  const lastFinished = useRef(0)
  const actionRef = useRef(action)
  const scopeRef = useRef(scopeKey)
  const flightRef = useRef(0)

  useLayoutEffect(() => {
    actionRef.current = action
  })

  return useCallback(
    async (...args: Args) => {
      if (!Object.is(scopeRef.current, scopeKey)) {
        scopeRef.current = scopeKey
        flightRef.current += 1
        busy.current = false
        lastFinished.current = 0
      }
      if (busy.current) return
      if (minIntervalMs > 0 && performance.now() - lastFinished.current < minIntervalMs) return
      const flight = ++flightRef.current
      busy.current = true
      try {
        await actionRef.current(...args)
      } finally {
        // A prior account's request must not unlock or throttle the new
        // account's independent checkout flight when it finally settles.
        if (flight === flightRef.current) {
          busy.current = false
          lastFinished.current = performance.now()
        }
      }
    },
    [minIntervalMs, scopeKey],
  )
}
