/**
 * Mastarr's own settings.
 *
 * A value set by the environment or config file is shown *locked with its source* rather
 * than editable: saving an edit that a higher layer then overrides is the kind of thing
 * you lose an hour to.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api } from '../../api'
import type { AppSettingRow } from '../../api'
import { ErrorBox, Spinner } from '../../components'

const SOURCE_LABEL: Record<string, string> = {
  env: 'set by an environment variable',
  file: 'set in config.yml',
  database: 'saved here',
  default: 'using the built-in default',
}

function Row({ row, onSave }: { row: AppSettingRow; onSave: (v: unknown) => void }) {
  const asText =
    row.type === 'list[str]'
      ? ((row.value as string[]) ?? []).join('\n')
      : String(row.value ?? '')
  const [draft, setDraft] = useState(asText)

  // Re-sync when the server sends a new effective value (e.g. after another save).
  useEffect(() => setDraft(asText), [asText])
  const dirty = draft !== asText

  return (
    <div className="setting-row">
      <div className="setting-label">
        <label htmlFor={row.key}>{row.label}</label>
        <div className="subtle">{row.help}</div>
        <div className="subtle" style={{ fontSize: 11.5 }}>
          Currently {SOURCE_LABEL[row.source] ?? row.source}.
        </div>
      </div>

      <div className="setting-control">
        {row.type === 'enum' ? (
          <select
            id={row.key}
            value={draft}
            disabled={row.locked}
            onChange={(e) => setDraft(e.target.value)}
          >
            {row.choices?.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        ) : row.type === 'list[str]' ? (
          <textarea
            id={row.key}
            rows={3}
            value={draft}
            disabled={row.locked}
            placeholder="192.168.1.10"
            onChange={(e) => setDraft(e.target.value)}
          />
        ) : (
          <input
            id={row.key}
            type="number"
            value={draft}
            disabled={row.locked}
            min={row.min}
            max={row.max}
            onChange={(e) => setDraft(e.target.value)}
          />
        )}

        <div className="row">
          <button
            className="small primary"
            disabled={row.locked || !dirty}
            onClick={() => onSave(draft)}
          >
            Save
          </button>
          {row.stored_value !== null && row.stored_value !== undefined && !row.locked ? (
            <button className="small" onClick={() => onSave(null)}>
              Reset to default
            </button>
          ) : null}
          {row.locked ? (
            <span className="badge plain">locked — change it at the source</span>
          ) : null}
        </div>
      </div>
    </div>
  )
}

export default function GeneralSettings() {
  const queryClient = useQueryClient()
  const { data, isLoading, error } = useQuery({ queryKey: ['settings'], queryFn: api.settings })
  const about = useQuery({ queryKey: ['about'], queryFn: api.about })

  const save = useMutation({
    mutationFn: ({ key, value }: { key: string; value: unknown }) =>
      api.updateSetting(key, value),
    onSuccess: (rows) => queryClient.setQueryData(['settings'], rows),
  })

  if (isLoading) return <Spinner label="Loading settings…" />
  if (error) return <ErrorBox>{(error as Error).message}</ErrorBox>

  return (
    <div className="stack">
      <div className="section">
        <h2>General</h2>
        {save.error ? <ErrorBox>{(save.error as Error).message}</ErrorBox> : null}
        <div className="settings-list">
          {(data ?? []).map((row) => (
            <Row
              key={row.key}
              row={row}
              onSave={(value) => save.mutate({ key: row.key, value })}
            />
          ))}
        </div>
      </div>

      <div className="section">
        <h2>About</h2>
        <div className="meta-row">
          <span>
            Version <b>{about.data?.version ?? '—'}</b>
          </span>
          <span>
            Database schema <b>v{about.data?.schema_version ?? '—'}</b>
          </span>
          <span>
            Data directory <code>{about.data?.data_dir ?? '—'}</code>
          </span>
          {about.data?.config_file ? (
            <span>
              Config file <code>{about.data.config_file}</code>
            </span>
          ) : null}
        </div>
        <p className="subtle" style={{ marginBottom: 0 }}>
          Encryption and session secrets are deliberately not editable here — they live in
          the environment or a private file on the data volume.
        </p>
      </div>
    </div>
  )
}
