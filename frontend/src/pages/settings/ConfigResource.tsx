/**
 * One cross-stack config resource: see it everywhere, copy it between services.
 *
 * The flow is deliberately preview-then-confirm. Config writes land in someone's real
 * media stack, and "apply to all" is exactly the button that silently overwrites a
 * profile you spent an evening tuning. So nothing is written until you've seen, per
 * service, whether it would be created, updated, left alone, or refused.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../../api'
import type { ApplyResult, ConfigItem, SyncPreview, TargetPlan } from '../../api'
import { Empty, ErrorBox, Spinner } from '../../components'

const ACTION_CLASS: Record<string, string> = {
  create: 'online',
  update: 'degraded',
  identical: 'plain',
  incompatible: 'unauthorized',
  error: 'unreachable',
}

const ACTION_LABEL: Record<string, string> = {
  create: 'Will be created',
  update: 'Will be changed',
  identical: 'Already matches',
  incompatible: 'Not applicable',
  error: 'Error',
}

function short(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'object') return JSON.stringify(value).slice(0, 80)
  return String(value).slice(0, 80)
}

function PreviewPanel({
  preview,
  onApply,
  applying,
  results,
  onClose,
}: {
  preview: SyncPreview
  onApply: (ids: number[]) => void
  applying: boolean
  results: ApplyResult[] | null
  onClose: () => void
}) {
  const actionable = preview.targets.filter(
    (t) => t.action === 'create' || t.action === 'update',
  )
  const [chosen, setChosen] = useState<number[]>(actionable.map((t) => t.service_id))

  const toggle = (id: number) =>
    setChosen((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]))

  const overwriting = preview.targets.filter(
    (t) => t.action === 'update' && chosen.includes(t.service_id),
  )

  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <div className="drawer" onClick={(e) => e.stopPropagation()}>
        <div className="row" style={{ marginBottom: 12 }}>
          <h2 className="grow" style={{ margin: 0 }}>
            Copy “{preview.item_name}”
          </h2>
          <button className="small" onClick={onClose}>
            Close
          </button>
        </div>
        <p className="subtle">
          From <b>{preview.source_service_name}</b>. Nothing has been changed yet.
        </p>

        <div className="stack" style={{ gap: 10 }}>
          {preview.targets.map((target: TargetPlan) => {
            const selectable = target.action === 'create' || target.action === 'update'
            return (
              <div key={target.service_id} className="season">
                <div className="row wrap">
                  {selectable ? (
                    <input
                      type="checkbox"
                      style={{ width: 'auto' }}
                      checked={chosen.includes(target.service_id)}
                      onChange={() => toggle(target.service_id)}
                      disabled={!!results}
                    />
                  ) : null}
                  <b className="grow">{target.service_name}</b>
                  <span className={`badge ${ACTION_CLASS[target.action]}`}>
                    {ACTION_LABEL[target.action]}
                  </span>
                </div>

                {target.reason ? (
                  <div className="subtle" style={{ marginTop: 4 }}>
                    {target.reason}
                  </div>
                ) : null}

                {target.changes.length > 0 ? (
                  <div className="table-wrap" style={{ marginTop: 8 }}>
                    <table>
                      <thead>
                        <tr>
                          <th>Field</th>
                          <th>Now</th>
                          <th>After</th>
                        </tr>
                      </thead>
                      <tbody>
                        {target.changes.map((c) => (
                          <tr key={c.field}>
                            <td>
                              <code>{c.field}</code>
                            </td>
                            <td className="subtle">{short(c.current)}</td>
                            <td>{short(c.proposed)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : null}
              </div>
            )
          })}
        </div>

        {results ? (
          <div className="stack" style={{ gap: 6, marginTop: 14 }}>
            <h2>Result</h2>
            {results.map((r) => (
              <div key={r.service_id} className="row">
                <span className="grow">{r.service_name}</span>
                <span className={`badge ${r.ok ? 'online' : 'unreachable'}`}>
                  {r.ok ? ACTION_LABEL[r.action] ?? r.action : 'Failed'}
                </span>
                {r.detail ? <span className="subtle">{r.detail}</span> : null}
              </div>
            ))}
          </div>
        ) : (
          <div className="stack" style={{ marginTop: 14 }}>
            {overwriting.length > 0 ? (
              <div className="hint-box">
                <b>This will overwrite existing settings</b> on{' '}
                {overwriting.map((t) => t.service_name).join(', ')}. Check the changes above.
              </div>
            ) : null}
            <div className="row">
              <button
                className="primary"
                disabled={applying || chosen.length === 0}
                onClick={() => onApply(chosen)}
              >
                {applying
                  ? 'Applying…'
                  : `Apply to ${chosen.length} service${chosen.length === 1 ? '' : 's'}`}
              </button>
              <button onClick={onClose}>Cancel</button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

export default function ConfigResource({
  resource,
  title,
  nameField = 'name',
  singleton = false,
}: {
  resource: string
  title: string
  nameField?: string
  singleton?: boolean
}) {
  const queryClient = useQueryClient()
  const [preview, setPreview] = useState<SyncPreview | null>(null)
  const [results, setResults] = useState<ApplyResult[] | null>(null)

  const { data, isLoading, error } = useQuery({
    queryKey: ['config', resource],
    queryFn: () => api.configItems(resource),
  })
  const info = useQuery({ queryKey: ['config-resources'], queryFn: api.configResources })
  const note = info.data?.resources.find((r) => r.key === resource)?.note

  const startPreview = useMutation({
    mutationFn: (item: ConfigItem) =>
      api.configPreview({
        resource,
        source_service_id: item.service_id,
        item_id: Number(item.item.id ?? 0),
      }),
    onSuccess: (p) => {
      setResults(null)
      setPreview(p)
    },
  })

  const apply = useMutation({
    mutationFn: (ids: number[]) =>
      api.configApply({
        resource,
        source_service_id: preview!.source_service_id,
        item_id: Number(
          data?.find((d) => d.service_id === preview!.source_service_id)?.item.id ?? 0,
        ),
        target_service_ids: ids,
      }),
    onSuccess: async (r) => {
      setResults(r)
      await queryClient.invalidateQueries({ queryKey: ['config', resource] })
    },
  })

  if (isLoading) return <Spinner label="Loading…" />
  if (error) return <ErrorBox>{(error as Error).message}</ErrorBox>

  const grouped = new Map<string, ConfigItem[]>()
  for (const entry of data ?? []) {
    const bucket = grouped.get(entry.service_name)
    if (bucket) bucket.push(entry)
    else grouped.set(entry.service_name, [entry])
  }

  return (
    <div className="stack">
      <div className="section">
        <h2>{title}</h2>
        {note ? <p className="subtle">{note}</p> : null}
        {startPreview.error ? (
          <ErrorBox>{(startPreview.error as Error).message}</ErrorBox>
        ) : null}

        {grouped.size === 0 ? (
          <Empty title="Nothing to show">
            No connected service exposes {title.toLowerCase()}.
          </Empty>
        ) : (
          <div className="stack" style={{ gap: 14 }}>
            {[...grouped.entries()].map(([service, items]) => (
              <div key={service}>
                <div className="row" style={{ marginBottom: 6 }}>
                  <b>{service}</b>
                  <span className="badge plain">{items[0].service_type}</span>
                </div>
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>{singleton ? 'Setting' : 'Name'}</th>
                        <th>Details</th>
                        <th />
                      </tr>
                    </thead>
                    <tbody>
                      {items.map((entry, index) => (
                        <tr key={`${entry.service_id}-${index}`}>
                          <td>
                            {singleton
                              ? 'Naming scheme'
                              : String(entry.item[nameField] ?? `#${entry.item.id}`)}
                          </td>
                          <td className="subtle">
                            {Object.entries(entry.item)
                              .filter(
                                ([k, v]) =>
                                  !['id', 'name', 'path', 'specifications', 'items'].includes(k) &&
                                  typeof v !== 'object',
                              )
                              .slice(0, 3)
                              .map(([k, v]) => `${k}: ${v}`)
                              .join(' · ') || '—'}
                          </td>
                          <td>
                            <button
                              className="small"
                              onClick={() => startPreview.mutate(entry)}
                              disabled={startPreview.isPending}
                            >
                              Copy to…
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {preview ? (
        <PreviewPanel
          preview={preview}
          applying={apply.isPending}
          results={results}
          onApply={(ids) => apply.mutate(ids)}
          onClose={() => {
            setPreview(null)
            setResults(null)
          }}
        />
      ) : null}
    </div>
  )
}
