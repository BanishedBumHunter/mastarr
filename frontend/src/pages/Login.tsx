/** Sign-in and first-run setup. Both render before any authenticated tree is mounted. */

import { useState } from 'react'
import { useAuth } from '../auth'
import { ErrorBox } from '../components'

export default function Login({ mode }: { mode: 'login' | 'setup' }) {
  const { login, setup } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const isSetup = mode === 'setup'

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    setError(null)
    setBusy(true)
    try {
      await (isSetup ? setup(username, password) : login(username, password))
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="auth-screen">
      <form className="auth-box" onSubmit={submit}>
        <div className="brand">
          mast<span>arr</span>
        </div>
        <p className="subtle">
          {isSetup
            ? 'Create the administrator account for this instance.'
            : 'Sign in to your control plane.'}
        </p>

        <div className="field">
          <label htmlFor="username">Username</label>
          <input
            id="username"
            value={username}
            autoComplete="username"
            autoFocus
            onChange={(event) => setUsername(event.target.value)}
          />
        </div>

        <div className="field">
          <label htmlFor="password">Password</label>
          <input
            id="password"
            type="password"
            value={password}
            autoComplete={isSetup ? 'new-password' : 'current-password'}
            placeholder={isSetup ? 'At least 8 characters' : undefined}
            onChange={(event) => setPassword(event.target.value)}
          />
        </div>

        {error ? <ErrorBox>{error}</ErrorBox> : null}

        <button
          type="submit"
          className="primary"
          disabled={busy || !username || (isSetup && password.length < 8) || !password}
        >
          {busy ? 'Working…' : isSetup ? 'Create admin account' : 'Sign in'}
        </button>
      </form>
    </div>
  )
}
