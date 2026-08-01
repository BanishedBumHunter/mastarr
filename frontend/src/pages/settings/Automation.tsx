/**
 * Upgrade sweep and grab guard — the two things Mastarr does that the *arrs don't.
 *
 * Both act on their own, so both are off by default and both show exactly what they've
 * done. The guard in particular deletes downloads; it must never be able to do that
 * invisibly.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../../api'
import type { AppSettingRow } from '../../api'
import { Empty, ErrorBox, Spinner } from '../../components'

const ACTION_CLASS: Record<string, string> = {
  rejected: 'unreachable',
  allowed: 'plain',
  failed: 'degraded',
}

function SettingControls({ keys }: { keys: string[] }) {
  const queryClient = useQueryClient()
  const { data } = useQuery({ queryKey: ['settings'], queryFn: api.settings })
  const save = useMutation({
    mutationFn: ({ key, value }: { key: string; value: unknown }) =>
      api.updateSetting(key, value),
    onSuccess: (rows) => queryClient.setQueryData(['settings'], rows),
  })

  const rows = (data ?? []).filter((r) => keys.includes(r.key))
  return (
    <div className="settings-list">
      {rows.map((row: AppSettingRow) => (
        <div className="setting-row" key={row.key}>
          <div className="setting-label">
            <label htmlFor={`a-${row.key}`}>{row.label}</label>
            <div className="subtle">{row.help}</div>
            {row.locked ? (
              <div className="subtle">Locked — set by the environment or config file.</div>
            ) : null}
          </div>
          <div className="setting-control">
            {row.type === 'bool' ? (
              <label className="row" style={{ gap: 8, marginBottom: 0 }}>
                <input
                  id={`a-${row.key}`}
                  type="checkbox"
                  style={{ width: 'auto' }}
                  disabled={row.locked}
                  checked={Boolean(row.value)}
                  onChange={(e) => save.mutate({ key: row.key, value: e.target.checked })}
                />
                {row.value ? 'Enabled' : 'Disabled'}
              </label>
            ) : (
              <input
                id={`a-${row.key}`}
                type="number"
                defaultValue={String(row.value ?? '')}
                disabled={row.locked}
                onBlur={(e) => {
                  if (e.target.value !== String(row.value))
                    save.mutate({ key: row.key, value: e.target.value })
                }}
              />
            )}
          </div>
        </div>
      ))}
      {save.error ? <ErrorBox>{(save.error as Error).message}</ErrorBox> : null}
    </div>
  )
}

export default function Automation() {
  const queryClient = useQueryClient()
  const [ran, setRan] = useState<string | null>(null)

  const sweep = useQuery({ queryKey: ['sweep'], queryFn: api.sweepStatus })
  const audit = useQuery({ queryKey: ['guard-audit'], queryFn: api.guardAudit })
  const hook = useQuery({ queryKey: ['guard-url'], queryFn: api.guardWebhookUrl })

  const run = useMutation({
    mutationFn: api.runSweep,
    onSuccess: async (results) => {
      const ok = results.filter((r) => r.ok).length
      setRan(`Issued ${ok} of ${results.length} search commands.`)
      await queryClient.invalidateQueries({ queryKey: ['sweep'] })
    },
  })

  if (sweep.isLoading) return <Spinner label="Loading…" />

  const totalBelow = (sweep.data?.services ?? []).reduce((n, s) => n + s.below_cutoff, 0)

  return (
    <div className="stack">
      <div className="section">
        <h2>Upgrade sweep</h2>
        <p className="subtle" style={{ marginTop: 0 }}>
          Quality profiles can keep replacing a file until it reaches your chosen ceiling —
          but nothing in the *arrs ever goes looking. Upgrades otherwise only happen if a
          better release happens to appear in the RSS window, so anything already below its
          cutoff stays there indefinitely. This sweep asks each service to check.
        </p>

        {sweep.data?.services.length ? (
          <div className="stat-row">
            {sweep.data.services.map((s) => (
              <div className="stat" key={s.service_id}>
                <div className={`stat-value ${s.below_cutoff ? 'warn' : 'ok'}`}>
                  {s.below_cutoff}
                </div>
                <div className="stat-label">{s.service_name} below cutoff</div>
              </div>
            ))}
          </div>
        ) : null}

        <SettingControls keys={['sweep_enabled', 'sweep_interval_hours', 'sweep_include_missing']} />

        <div className="row wrap" style={{ marginTop: 12 }}>
          <button className="primary" onClick={() => run.mutate()} disabled={run.isPending}>
            {run.isPending ? 'Sweeping…' : 'Sweep now'}
          </button>
          {sweep.data?.last_run ? (
            <span className="subtle">
              Last run {new Date(sweep.data.last_run).toLocaleString()}
            </span>
          ) : (
            <span className="subtle">Never run</span>
          )}
          {totalBelow > 0 ? (
            <span className="subtle">{totalBelow} items could be upgraded</span>
          ) : null}
        </div>
        {ran ? <div className="hint-box" style={{ marginTop: 10 }}>{ran}</div> : null}
        {run.error ? <ErrorBox>{(run.error as Error).message}</ErrorBox> : null}
      </div>

      <div className="section">
        <h2>Reject suspicious grabs</h2>
        <p className="subtle" style={{ marginTop: 0 }}>
          A release uploaded days ago for a title released years ago is often a fake or a
          bad re-encode. No *arr can express that rule — they match on release names, never
          on dates.
        </p>
        <div className="hint-box" style={{ marginBottom: 12 }}>
          <b>This undoes rather than prevents.</b> The service grabs on its own and nothing
          asks Mastarr first, so Mastarr is told after the fact and then removes and
          blocklists the download — usually within seconds. It cannot stop the grab
          happening.
        </div>

        <SettingControls
          keys={[
            'grab_guard_enabled',
            'grab_guard_max_days_after_release',
            'grab_guard_min_media_age_days',
          ]}
        />

        {hook.data ? (
          <div style={{ marginTop: 12 }}>
            <label>Webhook URL — add this to each service as a Webhook connection with
              “On Grab” enabled</label>
            <code style={{ display: 'block', padding: 8, wordBreak: 'break-all' }}>
              {hook.data.url}
            </code>
          </div>
        ) : null}
      </div>

      <div className="section">
        <h2>What the guard has done</h2>
        {audit.data && audit.data.length > 0 ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>When</th>
                  <th>Service</th>
                  <th>Release</th>
                  <th>Action</th>
                  <th>Why</th>
                </tr>
              </thead>
              <tbody>
                {audit.data.map((entry, i) => (
                  <tr key={i}>
                    <td className="subtle">{new Date(entry.at).toLocaleString()}</td>
                    <td className="subtle">{entry.service_name}</td>
                    <td>{entry.title}</td>
                    <td>
                      <span className={`badge ${ACTION_CLASS[entry.action] ?? 'plain'}`}>
                        {entry.action}
                      </span>
                    </td>
                    <td className="subtle">
                      {entry.reason}
                      {entry.detail ? ` — ${entry.detail}` : ''}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty title="Nothing yet">
            Every decision the guard makes is recorded here, including the ones it lets
            through.
          </Empty>
        )}
      </div>
    </div>
  )
}
