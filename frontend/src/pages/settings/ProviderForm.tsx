/**
 * One form renderer for every provider type in every *arr.
 *
 * The services describe their own forms — `/{resource}/schema` returns each implementation
 * with typed, labelled fields — so this renders 69 provider types across download clients,
 * indexers, import lists, notifications and metadata without knowing anything about any of
 * them. A provider added by an upstream release shows up here on its own.
 *
 * Secret fields arrive pre-masked as `********` and are submitted back unchanged unless
 * edited, so the browser never holds a real credential.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../../api'
import type { ProviderField, ProviderRecord } from '../../api'
import { Empty, ErrorBox, Spinner } from '../../components'

const SECRET_PLACEHOLDER = '********'

function Field({
  field,
  onChange,
}: {
  field: ProviderField
  onChange: (value: unknown) => void
}) {
  const id = `f-${field.name}`
  const value = field.value

  // The *arrs express selects as `selectOptions`, regardless of the declared type.
  if (field.selectOptions?.length) {
    return (
      <div className="field">
        <label htmlFor={id}>{field.label ?? field.name}</label>
        <select id={id} value={String(value ?? '')} onChange={(e) => onChange(e.target.value)}>
          {field.selectOptions.map((o) => (
            <option key={String(o.value)} value={String(o.value)}>
              {o.name}
            </option>
          ))}
        </select>
        {field.helpText ? <div className="subtle">{field.helpText}</div> : null}
      </div>
    )
  }

  if (field.type === 'checkbox') {
    return (
      <div className="field">
        <label className="row" style={{ gap: 8, marginBottom: 0 }}>
          <input
            id={id}
            type="checkbox"
            style={{ width: 'auto' }}
            checked={Boolean(value)}
            onChange={(e) => onChange(e.target.checked)}
          />
          {field.label ?? field.name}
        </label>
        {field.helpText ? <div className="subtle">{field.helpText}</div> : null}
      </div>
    )
  }

  const isSecret = Boolean(field.privacy && field.privacy !== 'normal')
  return (
    <div className="field">
      <label htmlFor={id}>{field.label ?? field.name}</label>
      <input
        id={id}
        type={field.type === 'password' || isSecret ? 'password' : 'text'}
        value={value === null || value === undefined ? '' : String(value)}
        placeholder={value === SECRET_PLACEHOLDER ? 'unchanged' : undefined}
        onChange={(e) => onChange(e.target.value)}
      />
      {field.helpText ? <div className="subtle">{field.helpText}</div> : null}
    </div>
  )
}

function Editor({
  serviceId,
  resource,
  record,
  onDone,
}: {
  serviceId: number
  resource: string
  record: ProviderRecord
  onDone: () => void
}) {
  const queryClient = useQueryClient()
  const [draft, setDraft] = useState<ProviderRecord>(record)
  const [testResult, setTestResult] = useState<{ ok: boolean; message: string } | null>(null)
  const [showAdvanced, setShowAdvanced] = useState(false)

  const setField = (name: string, value: unknown) =>
    setDraft((prev) => ({
      ...prev,
      fields: (prev.fields ?? []).map((f) => (f.name === name ? { ...f, value } : f)),
    }))

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ['providers', serviceId, resource] })

  const test = useMutation({
    mutationFn: () => api.testProviderItem(serviceId, resource, draft),
    onSuccess: setTestResult,
  })
  const save = useMutation({
    mutationFn: () =>
      draft.id
        ? api.updateProviderItem(serviceId, resource, draft.id, draft)
        : api.createProviderItem(serviceId, resource, draft),
    onSuccess: async () => {
      await invalidate()
      onDone()
    },
  })
  const remove = useMutation({
    mutationFn: () => api.deleteProviderItem(serviceId, resource, draft.id!),
    onSuccess: async () => {
      await invalidate()
      onDone()
    },
  })

  const visible = (draft.fields ?? []).filter((f) => showAdvanced || !f.advanced)
  const hiddenCount = (draft.fields ?? []).length - visible.length

  return (
    <div className="drawer-backdrop" onClick={onDone}>
      <div className="drawer" onClick={(e) => e.stopPropagation()}>
        <div className="row" style={{ marginBottom: 12 }}>
          <h2 className="grow" style={{ margin: 0 }}>
            {draft.id ? 'Edit' : 'Add'} {draft.implementationName ?? draft.implementation}
          </h2>
          <button className="small" onClick={onDone}>
            Close
          </button>
        </div>

        <div className="field">
          <label htmlFor="pname">Name</label>
          <input
            id="pname"
            value={String(draft.name ?? '')}
            onChange={(e) => setDraft((p) => ({ ...p, name: e.target.value }))}
          />
        </div>

        {'enable' in draft ? (
          <div className="field">
            <label className="row" style={{ gap: 8, marginBottom: 0 }}>
              <input
                type="checkbox"
                style={{ width: 'auto' }}
                checked={Boolean(draft.enable)}
                onChange={(e) => setDraft((p) => ({ ...p, enable: e.target.checked }))}
              />
              Enabled
            </label>
          </div>
        ) : null}

        {visible.map((field) => (
          <Field key={field.name} field={field} onChange={(v) => setField(field.name, v)} />
        ))}

        {hiddenCount > 0 ? (
          <button className="small" onClick={() => setShowAdvanced((v) => !v)}>
            {showAdvanced ? 'Hide' : `Show ${hiddenCount} advanced`} settings
          </button>
        ) : null}

        {testResult ? (
          <div className={testResult.ok ? 'hint-box' : 'error-box'} style={{ marginTop: 12 }}>
            {testResult.message}
          </div>
        ) : null}
        {save.error ? <ErrorBox>{(save.error as Error).message}</ErrorBox> : null}
        {remove.error ? <ErrorBox>{(remove.error as Error).message}</ErrorBox> : null}

        <div className="row wrap" style={{ marginTop: 14 }}>
          <button onClick={() => test.mutate()} disabled={test.isPending}>
            {test.isPending ? 'Testing…' : 'Test'}
          </button>
          <button className="primary" onClick={() => save.mutate()} disabled={save.isPending}>
            {save.isPending ? 'Saving…' : 'Save'}
          </button>
          <span className="grow" />
          {draft.id ? (
            <button
              className="danger small"
              onClick={() => remove.mutate()}
              disabled={remove.isPending}
            >
              Delete
            </button>
          ) : null}
        </div>
      </div>
    </div>
  )
}

export default function ProviderList({
  serviceId,
  serviceName,
  resource,
  title,
}: {
  serviceId: number
  serviceName: string
  resource: string
  title: string
}) {
  const [editing, setEditing] = useState<ProviderRecord | null>(null)
  const [picking, setPicking] = useState(false)

  const items = useQuery({
    queryKey: ['providers', serviceId, resource],
    queryFn: () => api.providers(serviceId, resource),
  })
  const schema = useQuery({
    queryKey: ['provider-schema', serviceId, resource],
    queryFn: () => api.providerSchema(serviceId, resource),
    enabled: picking,
  })

  if (items.isLoading) return <Spinner label="Loading…" />
  if (items.error) return <ErrorBox>{(items.error as Error).message}</ErrorBox>

  return (
    <div className="section">
      <div className="row" style={{ marginBottom: 10 }}>
        <h2 className="grow" style={{ margin: 0 }}>
          {title} <span className="subtle">on {serviceName}</span>
        </h2>
        <button className="primary small" onClick={() => setPicking(true)}>
          Add
        </button>
      </div>

      {items.data && items.data.length === 0 ? (
        <Empty title={`No ${title.toLowerCase()} configured`}>
          Press Add to set one up — Mastarr reads the available options straight from{' '}
          {serviceName}.
        </Empty>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Type</th>
                <th>Status</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {(items.data ?? []).map((item) => (
                <tr key={item.id}>
                  <td>{String(item.name ?? '')}</td>
                  <td className="subtle">
                    {String(item.implementationName ?? item.implementation ?? '')}
                    {item.protocol ? ` · ${item.protocol}` : ''}
                  </td>
                  <td>
                    <span className={`badge ${item.enable === false ? 'plain' : 'online'}`}>
                      {item.enable === false ? 'disabled' : 'enabled'}
                    </span>
                  </td>
                  <td>
                    <button className="small" onClick={() => setEditing(item)}>
                      Edit
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {picking ? (
        <div className="drawer-backdrop" onClick={() => setPicking(false)}>
          <div className="drawer" onClick={(e) => e.stopPropagation()}>
            <div className="row" style={{ marginBottom: 12 }}>
              <h2 className="grow" style={{ margin: 0 }}>
                Choose a type
              </h2>
              <button className="small" onClick={() => setPicking(false)}>
                Close
              </button>
            </div>
            {schema.isLoading ? <Spinner label="Loading options…" /> : null}
            {schema.error ? <ErrorBox>{(schema.error as Error).message}</ErrorBox> : null}
            <div className="lib-grid" style={{ gridTemplateColumns: 'repeat(auto-fill,minmax(200px,1fr))' }}>
              {(schema.data ?? []).map((option) => (
                <button
                  key={option.implementation}
                  className="section"
                  style={{ textAlign: 'left', cursor: 'pointer' }}
                  onClick={() => {
                    setPicking(false)
                    setEditing({ ...option, name: option.implementationName ?? option.implementation })
                  }}
                >
                  <b>{option.implementationName ?? option.implementation}</b>
                  {option.protocol ? (
                    <div className="subtle">{String(option.protocol)}</div>
                  ) : null}
                </button>
              ))}
            </div>
          </div>
        </div>
      ) : null}

      {editing ? (
        <Editor
          serviceId={serviceId}
          resource={resource}
          record={editing}
          onDone={() => setEditing(null)}
        />
      ) : null}
    </div>
  )
}
