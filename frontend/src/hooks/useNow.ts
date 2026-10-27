import { useEffect, useState } from 'react'

import { serverNow } from '../store/sale'

/** Server-synced "now", re-rendering only the component that uses it. */
export function useServerNow(intervalMs = 250): number {
  const [now, setNow] = useState(serverNow)
  useEffect(() => {
    const id = setInterval(() => setNow(serverNow()), intervalMs)
    return () => clearInterval(id)
  }, [intervalMs])
  return now
}
