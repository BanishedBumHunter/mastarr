/**
 * First-run wizard.
 *
 * Replaces the bare "create an admin account" screen. A fresh install otherwise lands on
 * an empty Library with no hint that services need connecting — the wizard walks the
 * three steps that actually make Mastarr useful, and is skippable for anyone who'd rather
 * poke at Settings themselves.
 */

import { useState } from 'react'
import type { FormEvent } from 'react'
import { useMutation as useRQMutation } from '@tanstack/react-query'
import { api } from '../api'
import type { Discovered } from '../api'
import { ErrorBox, Spinner } from '../components'
import { useAuth } from '../auth'

type Step = 'account' | 'scan' | 'done'

export default function Wizard({ startAt = 'account' }: { startAt?: Step }) {
  const { setup, refresh } = useAuth()
  const [step, setStep] = useState<Step>(startAt)

  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const [hosts, setHosts] = useState('')
  const [found, setFound] = useState<Discovered[] | null>(null)
  const [keys, setKeys] = useState<Record<string, string>>({})
  const [added, setAdded] = useState<Record<string, boolean>>({})

  const createAccount = async (event: FormEvent) => {
    event.preventDefault()
    setError(null)
    setBusy(true)
    try {
      await setup(username, password)
      setStep('scan')
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const scan = useRQMutation({
    mutationFn: () =>
      api.scan(hosts.split(/[\s,]+/).map((h) => h.trim()).filter(Boolean)),
    onSuccess: setFound,
  })

  const add = useRQMutation({
    mutationFn: async (candidate: Discovered) => {
      const apiKey = keys[candidate.url] ?? ''
      const identified = apiKey
        ? await api.identify(candidate.url, apiKey, candidate.service_type)
        : candidate
      const type = identified.service_type ?? candidate.service_type
      if (!type) throw new Error('Could not determine the service type. Check the API key.')
      return api.createService({
        name: identified.app_name ?? type.charAt(0).toUpperCase() + type.slice(1),
        service_type: type,
        url: candidate.url,
        api_key: apiKey || undefined,
      })
    },
    // Only this row — the same per-row bug that bit the Services page.
    onSuccess: (_r, candidate) => setAdded((prev) => ({ ...prev, [candidate.url]: true })),
  })

  const finish = async () => {
    await refresh()
    window.location.href = '/'
  }

  return (
    <div className="auth-screen">
      <div className="auth-box" style={{ maxWidth: step === 'account' ? 380 : 720 }}>
        <div className="brand">
          mast<span>arr</span>
        </div>

        {step === 'account' ? (
          <form onSubmit={createAccount}>
            <p className="subtle">
              Step 1 of 3 — create the administrator account for this instance.
            </p>
            <div className="field">
              <label htmlFor="username">Username</label>
              <input
                id="username"
                value={username}
                autoComplete="username"
                autoFocus
                onChange={(e) => setUsername(e.target.value)}
              />
            </div>
            <div className="field">
              <label htmlFor="password">Password</label>
              <input
                id="password"
                type="password"
                value={password}
                autoComplete="new-password"
                placeholder="At least 8 characters"
                onChange={(e) => setPassword(e.target.value)}
              />
            </div>
            {error ? <ErrorBox>{error}</ErrorBox> : null}
            <button
              type="submit"
              className="primary"
              disabled={busy || !username || password.length < 8}
            >
              {busy ? 'Creating…' : 'Create account'}
            </button>
          </form>
        ) : null}

        {step === 'scan' ? (
          <>
            <p className="subtle">
              Step 2 of 3 — find your *arr services. Enter the address of whatever runs
              them, usually your NAS. No API keys needed to find them.
            </p>
            <div className="form-row">
              <div className="grow">
                <label htmlFor="whosts">Host or IP</label>
                <input
                  id="whosts"
                  value={hosts}
                  autoFocus
                  placeholder="192.168.1.10"
                  onChange={(e) => setHosts(e.target.value)}
                />
              </div>
              <button
                className="primary"
                onClick={() => scan.mutate()}
                disabled={scan.isPending || !hosts.trim()}
              >
                {scan.isPending ? 'Scanning…' : 'Scan'}
              </button>
            </div>

            {scan.error ? <ErrorBox>{(scan.error as Error).message}</ErrorBox> : null}
            {add.error ? <ErrorBox>{(add.error as Error).message}</ErrorBox> : null}
            {scan.isPending ? <Spinner label="Looking…" /> : null}

            {found !== null ? (
              found.length === 0 ? (
                <p className="subtle">
                  Nothing responded there. Check the address, or add services by hand later
                  in Settings.
                </p>
              ) : (
                <div className="table-wrap" style={{ marginTop: 12 }}>
                  <table>
                    <thead>
                      <tr>
                        <th>Found</th>
                        <th>API key</th>
                        <th />
                      </tr>
                    </thead>
                    <tbody>
                      {found.map((candidate) => (
                        <tr key={candidate.url}>
                          <td>
                            <div>{candidate.service_type ?? 'unknown'}</div>
                            <code style={{ fontSize: 11 }}>{candidate.url}</code>
                          </td>
                          <td style={{ minWidth: 180 }}>
                            <input
                              type="password"
                              placeholder="Paste API key"
                              disabled={added[candidate.url]}
                              value={keys[candidate.url] ?? ''}
                              onChange={(e) =>
                                setKeys((prev) => ({ ...prev, [candidate.url]: e.target.value }))
                              }
                            />
                          </td>
                          <td>
                            {added[candidate.url] ? (
                              <span className="badge online">Added</span>
                            ) : (
                              <button
                                className="small primary"
                                onClick={() => add.mutate(candidate)}
                                disabled={add.isPending}
                              >
                                Add
                              </button>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )
            ) : null}

            <div className="row" style={{ marginTop: 14 }}>
              <button className="primary" onClick={() => setStep('done')}>
                Continue
              </button>
              <button onClick={() => void finish()}>Skip for now</button>
            </div>
            <p className="subtle" style={{ fontSize: 11.5 }}>
              Find each key in the service’s own UI under Settings → General → Security.
            </p>
          </>
        ) : null}

        {step === 'done' ? (
          <>
            <p className="subtle">Step 3 of 3 — you’re set up.</p>
            <ul className="subtle" style={{ paddingLeft: 18, lineHeight: 1.8 }}>
              <li>
                <b>Library</b> — everything you have, in one grid.
              </li>
              <li>
                <b>Calendar</b> — what’s coming, across every service.
              </li>
              <li>
                <b>Discover</b> — search and request, if you connected Jellyseerr.
              </li>
              <li>
                <b>Settings</b> — services, users and stack-wide configuration.
              </li>
            </ul>
            <button className="primary" onClick={() => void finish()}>
              Open Mastarr
            </button>
          </>
        ) : null}
      </div>
    </div>
  )
}
