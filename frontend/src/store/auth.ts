import { create } from 'zustand'

import type { User } from '../api/types'
import { readStorage, writeStorage } from '../lib/storage'
import { useCheckoutStore } from './checkout'
import { useSaleStore } from './sale'

const KEY = 'flashsale.session'

function resetAccountState(): void {
  useCheckoutStore.getState().reset()
  useSaleStore.getState().releaseHold()
}

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
    resetAccountState()
    set({ token, user })
  },
  signOut: () => {
    writeStorage('local', KEY, null)
    resetAccountState()
    set({ token: null, user: null })
  },
}))
