import { useSyncExternalStore } from 'react'

const subscribe = (cb: () => void) => {
  document.addEventListener('visibilitychange', cb)
  return () => document.removeEventListener('visibilitychange', cb)
}

export function usePageVisible(): boolean {
  return useSyncExternalStore(subscribe, () => document.visibilityState !== 'hidden', () => true)
}

/** Resolves once the tab is visible — background tabs don't poll. */
export function waitUntilVisible(signal: AbortSignal): Promise<void> {
  if (document.visibilityState !== 'hidden') return Promise.resolve()
  return new Promise((resolve, reject) => {
    const onChange = () => {
      if (document.visibilityState === 'hidden') return
      cleanup()
      resolve()
    }
    const onAbort = () => {
      cleanup()
      reject(signal.reason)
    }
    const cleanup = () => {
      document.removeEventListener('visibilitychange', onChange)
      signal.removeEventListener('abort', onAbort)
    }
    document.addEventListener('visibilitychange', onChange)
    signal.addEventListener('abort', onAbort, { once: true })
  })
}
