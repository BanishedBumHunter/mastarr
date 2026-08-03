/**
 * Custom format editor.
 *
 * A format is a name plus a list of *conditions*. `customformat/schema` describes the 8
 * condition types (Release Title, Language, Source, Resolution…) with their fields, so the
 * condition form is rendered from the schema exactly like a provider — no per-type code.
 *
 * Each condition also carries `negate` (must NOT match) and `required` (must match, rather
 * than merely contributing), which is where most of the expressive power lives.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../../api'
import type { ProviderField } from '../../api'
import { Empty, ErrorBox, Spinner } from '../../components'

interface Spec {
  name?: string
  implementation?: string
  implementationName?: string
  negate?: boolean
  required?: boolean
  fields?: ProviderField[]
  [k: string]: unknown
}

interface Format {
  id?: number
  name?: string
  includeCustomFormatWhenRenaming?: boolean
  specifications?: Spec[]
  [k: string]: unknown
}

function Editor({
  serviceId,
  initial,
  onDone,
}: {
  serviceId: number
  initial: Format
  onDone: () => void
}) {
  const queryClient = useQueryClient()
  const [draft, setDraft] = useState<Format>(initial)
  const [adding, setAdding] = useState(false)

  const schema = useQuery({
    queryKey: ['provider-schema', serviceId, 'custom_format'],
    queryFn: () => api.providerSchema(serviceId, 'custom_format'),
    enabled: adding,
  })

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ['providers', serviceId, 'custom_format'] })

  const save = useMutation({
    mutationFn: () =>
      draft.id
        ? api.updateProviderItem(serviceId, 'custom_format', draft.id, draft as never)
        : api.createProviderItem(serviceId, 'custom_format', draft as never),
    onSuccess: async () => {
      await invalidate()
      onDone()
    },
  })
  const remove = useMutation({
    mutationFn: () => api.deleteProviderItem(serviceId, 'custom_format', draft.id!),
    onSuccess: async () => {
      await invalidate()
      onDone()
    },
  })

  const setSpec = (index: number, patch: Partial<Spec>) =>
    setDraft((p) => ({
      ...p,
      specifications: (p.specifications ?? []).map((s, i) =>
        i === index ? { ...s, ...patch } : s,
      ),
    }))

  const setSpecField = (index: number, fieldName: string, value: unknown) =>
    setDraft((p) => ({
      ...p,
      specifications: (p.specifications ?? []).map((s, i) =>
        i === index
          ? {
              ...s,
              fields: (s.fields ?? []).map((f) =>
                f.name === fieldName ? { ...f, value } : f,
              ),
            }
          : s,
      ),
    }))

  return (
    <div className="drawer-backdrop" onClick={onDone}>
      <div className="drawer" onClick={(e) => e.stopPropagation()}>
        <div className="row" style={{ marginBottom: 12 }}>
          <h2 className="grow" style={{ margin: 0 }}>
            {draft.id ? 'Edit' : 'New'} custom format
          </h2>
          <button className="small" onClick={onDone}>
            Close
          </button>
        </div>

        <div className="field">
          <label htmlFor="cf-name">Name</label>
          <input
            id="cf-name"
            value={String(draft.name ?? '')}
            onChange={(e) => setDraft((p) => ({ ...p, name: e.target.value }))}
          />
        </div>

        <h2>Conditions</h2>
        <p className="subtle" style={{ marginTop: 0 }}>
          A release matches this format when its conditions are satisfied. Mark one
          <b> required</b> to make it mandatory, or <b>negate</b> to match when it does
          <i> not</i> apply.
        </p>

        <div className="stack" style={{ gap: 10 }}>
          {(draft.specifications ?? []).map((spec, i) => (
            <div className="season" key={i}>
              <div className="row wrap">
                <b className="grow">{spec.implementationName ?? spec.implementation}</b>
                <button
                  className="small danger"
                  onClick={() =>
                    setDraft((p) => ({
                      ...p,
                      specifications: (p.specifications ?? []).filter((_, j) => j !== i),
                    }))
                  }
                >
                  Remove
                </button>
              </div>
              <div className="field">
                <label htmlFor={`sn-${i}`}>Label</label>
                <input
                  id={`sn-${i}`}
                  value={String(spec.name ?? '')}
                  onChange={(e) => setSpec(i, { name: e.target.value })}
                />
              </div>
              {(spec.fields ?? []).map((f) => (
                <div className="field" key={f.name}>
                  <label htmlFor={`sf-${i}-${f.name}`}>{f.label ?? f.name}</label>
                  {f.selectOptions?.length ? (
                    <select
                      id={`sf-${i}-${f.name}`}
                      value={String(f.value ?? '')}
                      onChange={(e) => setSpecField(i, f.name, e.target.value)}
                    >
                      {f.selectOptions.map((o) => (
                        <option key={String(o.value)} value={String(o.value)}>
                          {o.name}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <input
                      id={`sf-${i}-${f.name}`}
                      value={f.value === null || f.value === undefined ? '' : String(f.value)}
                      onChange={(e) => setSpecField(i, f.name, e.target.value)}
                    />
                  )}
                  {f.helpText ? <div className="subtle">{f.helpText}</div> : null}
                </div>
              ))}
              <div className="row wrap">
                <label className="row" style={{ gap: 6, marginBottom: 0 }}>
                  <input
                    type="checkbox"
                    style={{ width: 'auto' }}
                    checked={Boolean(spec.negate)}
                    onChange={(e) => setSpec(i, { negate: e.target.checked })}
                  />
                  Negate
                </label>
                <label className="row" style={{ gap: 6, marginBottom: 0 }}>
                  <input
                    type="checkbox"
                    style={{ width: 'auto' }}
                    checked={Boolean(spec.required)}
                    onChange={(e) => setSpec(i, { required: e.target.checked })}
                  />
                  Required
                </label>
              </div>
            </div>
          ))}
        </div>

        <button className="small" style={{ marginTop: 10 }} onClick={() => setAdding(true)}>
          Add condition
        </button>

        {adding ? (
          <div className="section" style={{ marginTop: 10 }}>
            {schema.isLoading ? <Spinner label="Loading condition types…" /> : null}
            <div className="row wrap">
              {(schema.data ?? []).map((option) => (
                <button
                  key={String(option.implementation)}
                  className="small"
                  onClick={() => {
                    setDraft((p) => ({
                      ...p,
                      specifications: [
                        ...(p.specifications ?? []),
                        { ...(option as unknown as Spec), name: String(option.implementationName ?? '') },
                      ],
                    }))
                    setAdding(false)
                  }}
                >
                  {String(option.implementationName ?? option.implementation)}
                </button>
              ))}
            </div>
            <button className="small" onClick={() => setAdding(false)} style={{ marginTop: 8 }}>
              Cancel
            </button>
          </div>
        ) : null}

        {save.error ? <ErrorBox>{(save.error as Error).message}</ErrorBox> : null}
        {remove.error ? <ErrorBox>{(remove.error as Error).message}</ErrorBox> : null}

        <div className="row" style={{ marginTop: 16 }}>
          <button
            className="primary"
            onClick={() => save.mutate()}
            disabled={save.isPending || !String(draft.name ?? '').trim()}
          >
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

export default function CustomFormatEditor({
  serviceId,
  serviceName,
}: {
  serviceId: number
  serviceName: string
}) {
  const [editing, setEditing] = useState<Format | null>(null)
  const { data, isLoading, error } = useQuery({
    queryKey: ['providers', serviceId, 'custom_format'],
    queryFn: () => api.providers(serviceId, 'custom_format'),
  })

  if (isLoading) return <Spinner label="Loading…" />
  if (error) return <ErrorBox>{(error as Error).message}</ErrorBox>

  const formats = (data ?? []) as unknown as Format[]

  return (
    <div className="section">
      <div className="row" style={{ marginBottom: 10 }}>
        <h2 className="grow" style={{ margin: 0 }}>
          Custom formats <span className="subtle">on {serviceName}</span>
        </h2>
        <button
          className="primary small"
          onClick={() => setEditing({ name: '', specifications: [] })}
        >
          New format
        </button>
      </div>

      {formats.length === 0 ? (
        <Empty title="No custom formats">
          Custom formats score releases on things quality alone can't express — release
          group, language, source.
        </Empty>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Conditions</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {formats.map((f) => (
                <tr key={f.id}>
                  <td>{f.name}</td>
                  <td className="subtle">
                    {(f.specifications ?? [])
                      .map((s) => s.implementationName ?? s.implementation)
                      .join(', ') || '—'}
                  </td>
                  <td>
                    <button className="small" onClick={() => setEditing(f)}>
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
        <Editor serviceId={serviceId} initial={editing} onDone={() => setEditing(null)} />
      ) : null}
    </div>
  )
}
