import { type FormEvent, useState } from 'react'

import { ApiError } from '../api/client'
import { api } from '../api/endpoints'
import { useAuthStore } from '../store/auth'
import { Spinner } from './Spinner'

export function AuthPanel({ onDone }: { onDone?: () => void }) {
  const [mode, setMode] = useState<'login' | 'register'>('register')
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState(false)
  const signIn = useAuthStore((s) => s.signIn)

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (pending) return
    const form = new FormData(event.currentTarget)
    const email = String(form.get('email') ?? '')
    const password = String(form.get('password') ?? '')
    setPending(true)
    setError(null)
    try {
      const { data } = await (mode === 'login' ? api.login : api.register)(email, password)
      signIn(data.access_token, data.user, data.expires_in)
      onDone?.()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Something went wrong.')
    } finally {
      setPending(false)
    }
  }

  return (
    <form className="auth" onSubmit={submit} noValidate={false}>
      <div className="auth-tabs" role="tablist">
        {(['register', 'login'] as const).map((m) => (
          <button
            key={m}
            type="button"
            role="tab"
            aria-selected={mode === m}
            className={mode === m ? 'is-active' : ''}
            onClick={() => setMode(m)}
          >
            {m === 'register' ? 'Create account' : 'Sign in'}
          </button>
        ))}
      </div>
      <p className="auth-hint">Sign in before the sale opens so checkout is a single tap.</p>
      <label>
        Email
        <input name="email" type="email" autoComplete="email" required />
      </label>
      <label>
        Password
        <input
          name="password"
          type="password"
          minLength={8}
          maxLength={72}
          autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
          required
        />
      </label>
      {error && (
        <p className="auth-error" role="alert">
          {error}
        </p>
      )}
      <button type="submit" className="auth-submit" disabled={pending}>
        {pending && <Spinner />}
        {mode === 'login' ? 'Sign in' : 'Create account'}
      </button>
    </form>
  )
}
