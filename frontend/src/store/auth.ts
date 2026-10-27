import { create } from 'zustand'

import type { User } from '../api/types'
import { readStorage, writeStorage } from '../lib/storage'

const KEY = 'flashsale.session'

interface Session {
  token: string
  user: User
  expiresAt: number
}

interface AuthState {
  token: string | null
  user: User | null
  signIn: (token: string, user: User, expiresInSeconds: number) => void
  signOut: () => void
}

function restore(): Session | null {
  const raw = readStorage('local', KEY)
  if (!raw) return null
  try {
    const session = JSON.parse(raw) as Session
    return session.expiresAt > Date.now() ? session : null
  } catch {
    return null
  }
}

const initial = restore()

export const useAuthStore = create<AuthState>()((set) => ({
  token: initial?.token ?? null,
  user: initial?.user ?? null,
  signIn: (token, user, expiresInSeconds) => {
    const session: Session = { token, user, expiresAt: Date.now() + expiresInSeconds * 1000 }
    writeStorage('local', KEY, JSON.stringify(session))
    set({ token, user })
  },
  signOut: () => {
    writeStorage('local', KEY, null)
    set({ token: null, user: null })
  },
}))
