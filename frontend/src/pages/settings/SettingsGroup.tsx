/**
 * A flat settings object on one service — naming, media management, grab rules.
 *
 * These have no `/schema`, so fields are inferred from the values themselves. That keeps
 * it generic (a new field in an upstream release still appears) at the cost of prettier
 * labels, so the ones that matter get an explicit description.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api } from '../../api'
import { ErrorBox, Spinner } from '../../components'

// The handful worth explaining. Everything else renders with its raw key humanised.
const NOTES: Record<string, string> = {
  minimumAge:
    'Minutes a usenet release must exist before it can be grabbed. Gives a post time to ' +
    'propagate and settle — 0 means grab the instant it appears.',
  retention: 'Ignore usenet releases older than this many days. 0 = no limit.',
  maximumSize: 'Reject releases larger than this many MB. 0 = no limit.',
  rssSyncInterval: 'How often to check indexers for new releases, in minutes.',
  renameEpisodes: 'Rename files to match your naming scheme when importing.',
  renameMovies: 'Rename files to match your naming scheme when importing.',
  deleteEmptyFolders: 'Remove empty folders during a disk scan.',
  createEmptySeriesFolders: 'Create series folders during a disk scan.',
  skipFreeSpaceCheckWhenImporting: 'Skip the free-space check when importing.',
  copyUsingHardlinks: 'Use hardlinks instead of copying, when seeding torrents.',
}

function humanise(key: string): string {
  return key
    .replace(/([A-Z])/g, ' $1')
    .replace(/^./, (c) => c.toUpperCase())
    .trim()
}

export default function SettingsGroup({
  serviceId,
  serviceName,
  group,
  title,
}: {
  serviceId: number
  serviceName: string
  group: string
  title: string
}) {
  const queryClient = useQueryClient()
  const { data, isLoading, error } = useQuery({
    queryKey: ['settings-group', serviceId, group],
    queryFn: () => api.settingsGroup(serviceId, group),
  })
  const [draft, setDraft] = useState<Record<string, unknown>>({})
  const [saved, setSaved] = useState(false)

  useEffect(() => setDraft(data ?? {}), [data])

  const save = useMutation({
    mutationFn: () => api.updateSettingsGroup(serviceId, group, draft),
    onSuccess: async (result) => {
      setDraft(result)
      setSaved(true)
      await queryClient.invalidateQueries({ queryKey: ['settings-group', serviceId, group] })
    },
  })

  if (isLoading) return <Spinner label="Loading…" />
  if (error) return <ErrorBox>{(error as Error).message}</ErrorBox>

  // `id` is service-local plumbing, never something to edit.
  const keys = Object.keys(draft).filter((k) => k !== 'id')
  const dirty = JSON.stringify(draft) !== JSON.stringify(data ?? {})

  return (
    <div className="section">
      <h2>
        {title} <span className="subtle">on {serviceName}</span>
      </h2>

      <div className="settings-list">
        {keys.map((key) => {
          const value = draft[key]
          const note = NOTES[key]
          return (
            <div className="setting-row" key={key}>
              <div className="setting-label">
                <label htmlFor={`g-${key}`}>{humanise(key)}</label>
                {note ? <div className="subtle">{note}</div> : null}
              </div>
              <div className="setting-control">
                {typeof value === 'boolean' ? (
                  <label className="row" style={{ gap: 8, marginBottom: 0 }}>
                    <input
                      id={`g-${key}`}
                      type="checkbox"
                      style={{ width: 'auto' }}
                      checked={value}
                      onChange={(e) => {
                        setSaved(false)
                        setDraft((p) => ({ ...p, [key]: e.target.checked }))
                      }}
                    />
                    {value ? 'On' : 'Off'}
                  </label>
                ) : typeof value === 'number' ? (
                  <input
                    id={`g-${key}`}
                    type="number"
                    value={String(value)}
                    onChange={(e) => {
                      setSaved(false)
                      setDraft((p) => ({ ...p, [key]: Number(e.target.value) }))
                    }}
                  />
                ) : (
                  <input
                    id={`g-${key}`}
                    value={value === null || value === undefined ? '' : String(value)}
                    onChange={(e) => {
                      setSaved(false)
                      setDraft((p) => ({ ...p, [key]: e.target.value }))
                    }}
                  />
                )}
              </div>
            </div>
          )
        })}
      </div>

      {save.error ? <ErrorBox>{(save.error as Error).message}</ErrorBox> : null}
      <div className="row" style={{ marginTop: 14 }}>
        <button className="primary" onClick={() => save.mutate()} disabled={!dirty || save.isPending}>
          {save.isPending ? 'Saving…' : 'Save'}
        </button>
        {saved && !dirty ? <span className="badge online">Saved</span> : null}
      </div>
    </div>
  )
}
