// Storage can be unavailable (private mode, blocked cookies): never let that
// break the app — fall back to in-memory state.
export function readStorage(store: 'local' | 'session', key: string): string | null {
  try {
    return (store === 'local' ? localStorage : sessionStorage).getItem(key)
  } catch {
    return null
  }
}

export function writeStorage(store: 'local' | 'session', key: string, value: string | null): void {
  try {
    const s = store === 'local' ? localStorage : sessionStorage
    if (value === null) s.removeItem(key)
    else s.setItem(key, value)
  } catch {
    /* ignore */
  }
}
