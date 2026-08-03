/**
 * Generic editor for the flat config lists — tags, delay profiles, release profiles,
 * remote path mappings, import list exclusions.
 *
 * These have no `/schema`, but they're uniform: a flat record of primitives. Fields are
 * inferred from the data (or from an existing row when adding), so a field added by an
 * upstream release still appears. Labels are humanised, with explicit help where a raw key
 * would be unhelpful.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../../api'
import { Empty, ErrorBox, Spinner } from '../../components'

const NOTES: Record<string, string> = {
  usenetDelay: 'Minutes to hold a usenet grab, so a better release can appear first.',
  torrentDelay: 'Minutes to hold a torrent grab, so a better release can appear first.',
  bypassIfHighestQuality: 'Skip the delay when the release is already your best quality.',
  bypassIfAboveCustomFormatScore: 'Skip the delay when the custom format score is high enough.',
  preferredProtocol: 'Which protocol wins when both have a usable release.',
  label: 'The tag name.',
  host: 'The download client host this mapping applies to.',
  remotePath: 'Path as the download client reports it.',
  localPath: 'The same location as this service sees it.',
  ignored: 'Terms that reject a release outright.',
  required: 'Terms a release must contain.',
}

const humanise = (key: string) =>
  key.replace(/([A-Z])/g, ' $1').replace(/^./, (c) => c.toUpperCase()).trim()

// Never editable: service-local identity and derived state.
const HIDDEN = new Set(['id', 'implementation', 'implementationName', 'infoLink'])

function RowForm({
  serviceId,
  resource,
  record,
  onDone,
}: {
  serviceId: number
  resource: string
  record: Record<string, unknown>
  onDone: () => void
}) {
  const queryClient = useQueryClient()
  const [draft, setDraft] = useState(record)

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ['providers', serviceId, resource] })

  const save = useMutation({
    mutationFn: () =>
      draft.id
        ? api.updateProviderItem(serviceId, resource, Number(draft.id), draft as never)
        : api.createProviderItem(serviceId, resource, draft as never),
    onSuccess: async () => {
      await invalidate()
      onDone()
    },
  })
  const remove = useMutation({
    mutationFn: () => api.deleteProviderItem(serviceId, resource, Number(draft.id)),
    onSuccess: async () => {
      await invalidate()
      onDone()
    },
  })

  const keys = Object.keys(draft).filter((k) => !HIDDEN.has(k))

  return (
    <div className="drawer-backdrop" onClick={onDone}>
      <div className="drawer" onClick={(e) => e.stopPropagation()}>
        <div className="row" style={{ marginBottom: 12 }}>
          <h2 className="grow" style={{ margin: 0 }}>
            {draft.id ? 'Edit' : 'New'} entry
          </h2>
          <button className="small" onClick={onDone}>
            Close
          </button>
        </div>

        {keys.map((key) => {
          const value = draft[key]
          if (Array.isArray(value)) {
            return (
              <div className="field" key={key}>
                <label htmlFor={`l-${key}`}>{humanise(key)}</label>
                <textarea
                  id={`l-${key}`}
                  rows={2}
                  value={value.join('\n')}
                  onChange={(e) =>
                    setDraft((p) => ({
                      ...p,
                      [key]: e.target.value.split('\n').map((s) => s.trim()).filter(Boolean),
                    }))
                  }
                />
                {NOTES[key] ? <div className="subtle">{NOTES[key]}</div> : null}
              </div>
            )
          }
          if (typeof value === 'boolean') {
            return (
              <div className="field" key={key}>
                <label className="row" style={{ gap: 8, marginBottom: 0 }}>
                  <input
                    type="checkbox"
                    style={{ width: 'auto' }}
                    checked={value}
                    onChange={(e) => setDraft((p) => ({ ...p, [key]: e.target.checked }))}
                  />
                  {humanise(key)}
                </label>
                {NOTES[key] ? <div className="subtle">{NOTES[key]}</div> : null}
              </div>
            )
          }
          return (
            <div className="field" key={key}>
              <label htmlFor={`l-${key}`}>{humanise(key)}</label>
              <input
                id={`l-${key}`}
                type={typeof value === 'number' ? 'number' : 'text'}
                value={value === null || value === undefined ? '' : String(value)}
                onChange={(e) =>
                  setDraft((p) => ({
                    ...p,
                    [key]: typeof value === 'number' ? Number(e.target.value) : e.target.value,
                  }))
                }
              />
              {NOTES[key] ? <div className="subtle">{NOTES[key]}</div> : null}
            </div>
          )
        })}

        {save.error ? <ErrorBox>{(save.error as Error).message}</ErrorBox> : null}
        {remove.error ? <ErrorBox>{(remove.error as Error).message}</ErrorBox> : null}

        <div className="row" style={{ marginTop: 14 }}>
          <button className="primary" onClick={() => save.mutate()} disabled={save.isPending}>
            {save.isPending ? 'Saving…' : 'Save'}
          </button>
          <span className="grow" />
          {draft.id ? (
            <button className="danger small" onClick={() => remove.mutate()} disabled={remove.isPending}>
              Delete
            </button>
          ) : null}
        </div>
      </div>
    </div>
  )
}

export default function ListEditor({
  serviceId,
  serviceName,
  resource,
  title,
  blank,
}: {
  serviceId: number
  serviceName: string
  resource: string
  title: string
  /** Shape for a new entry when the list is empty and there's nothing to copy. */
  blank?: Record<string, unknown>
}) {
  const [editing, setEditing] = useState<Record<string, unknown> | null>(null)
  const { data, isLoading, error } = useQuery({
    queryKey: ['providers', serviceId, resource],
    queryFn: () => api.providers(serviceId, resource),
  })

  if (isLoading) return <Spinner label="Loading…" />
  if (error) return <ErrorBox>{(error as Error).message}</ErrorBox>

  const rows = (data ?? []) as unknown as Record<string, unknown>[]
  // Adding needs a shape. Prefer an existing row (so upstream fields come along), then the
  // supplied blank.
  const template = rows[0]
    ? Object.fromEntries(
        Object.entries(rows[0]).filter(([k]) => k !== 'id').map(([k, v]) => [
          k,
          Array.isArray(v) ? [] : typeof v === 'boolean' ? false : typeof v === 'number' ? 0 : '',
        ]),
      )
    : blank

  const columns = rows[0] ? Object.keys(rows[0]).filter((k) => !HIDDEN.has(k)).slice(0, 4) : []

  return (
    <div className="section">
      <div className="row" style={{ marginBottom: 10 }}>
        <h2 className="grow" style={{ margin: 0 }}>
          {title} <span className="subtle">on {serviceName}</span>
        </h2>
        {template ? (
          <button className="primary small" onClick={() => setEditing({ ...template })}>
            Add
          </button>
        ) : null}
      </div>

      {rows.length === 0 ? (
        <Empty title={`No ${title.toLowerCase()}`}>
          {template ? 'Press Add to create one.' : 'Nothing configured.'}
        </Empty>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                {columns.map((c) => (
                  <th key={c}>{humanise(c)}</th>
                ))}
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={String(r.id ?? i)}>
                  {columns.map((c) => (
                    <td key={c} className="subtle">
                      {Array.isArray(r[c])
                        ? (r[c] as unknown[]).join(', ') || '—'
                        : String(r[c] ?? '—')}
                    </td>
                  ))}
                  <td>
                    <button className="small" onClick={() => setEditing(r)}>
                      Edit
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {editing ? (
        <RowForm
          serviceId={serviceId}
          resource={resource}
          record={editing}
          onDone={() => setEditing(null)}
        />
      ) : null}
    </div>
  )
}
