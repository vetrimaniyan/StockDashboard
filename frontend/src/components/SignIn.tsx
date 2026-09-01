/**
 * Token sign-in (NFR-4.5).
 *
 * Shown when the API answers 401. The token is exchanged immediately for an
 * httpOnly session cookie and never kept in component state beyond the
 * submit, nor in localStorage: anything a script can read, a script can
 * exfiltrate, and the cookie exists precisely so scripts cannot.
 */

import { useState } from 'react'
import { api } from '../api'

export function SignIn({ onSignedIn }: { onSignedIn: () => void }) {
  const [token, setToken] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await api.signIn(token.trim())
      setToken('')
      onSignedIn()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'That token was not accepted.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="min-h-screen grid place-items-center p-6">
      <form
        onSubmit={submit}
        className="w-full max-w-md rounded border border-[var(--border)] bg-[var(--panel)] p-5"
      >
        <h1 className="text-lg font-semibold">Alpha-500</h1>
        <p className="text-[var(--muted)] leading-snug mt-1">
          This dashboard needs an access token. Ask the operator for one — each
          reviewer gets their own, so any can be withdrawn without affecting
          the rest.
        </p>

        <label className="block mt-4" htmlFor="token">
          <span className="text-[var(--muted)]">Access token</span>
          <input
            id="token"
            type="password"
            autoComplete="off"
            spellCheck={false}
            value={token}
            onChange={(e) => setToken(e.target.value)}
            className="mt-1 w-full rounded border border-[var(--border)] bg-[var(--bg)] px-2 py-1.5 font-mono"
            placeholder="paste the token"
          />
        </label>

        {error && (
          <p className="mt-3 rounded border border-[var(--down)] bg-[rgba(239,95,107,0.1)] p-2 text-[var(--down)]">
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={busy || token.trim().length === 0}
          className="mt-4 w-full rounded border border-[var(--border)] px-3 py-1.5 hover:border-[var(--accent)] disabled:opacity-50"
        >
          {busy ? 'Checking…' : 'Sign in'}
        </button>

        <p className="text-[var(--muted)] leading-snug mt-4">
          Decision support only. This application places no orders and holds no
          broker credentials. Market data is licensed for personal use and must
          not be redistributed.
        </p>
      </form>
    </div>
  )
}
