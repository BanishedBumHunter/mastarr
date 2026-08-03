/**
 * Quality definitions — the size limits, in MB per minute.
 *
 * The other half of what actually blocks a grab. A release can be exactly the quality you
 * asked for and still be rejected for exceeding the cap here, which is invisible unless
 * you go looking.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api } from '../../api'
import { ErrorBox, Spinner } from '../../components'

interface Definition {
  id: number
  title: string
  quality: { id: number; name: string }
  minSize: number | null
  maxSize: number | null
  preferredSize: number | null
  [k: string]: unknown
}

export default function QualityDefinitions({
  serviceId,
  serviceName,
}: {
  serviceId: number
  serviceName: string
}) {
  const queryClient = useQueryClient()
  const { data, isLoading, error } = useQuery({
    queryKey: ['providers', serviceId, 'quality_definition'],
    queryFn: () => api.providers(serviceId, 'quality_definition'),
  })
  const [rows, setRows] = useState<Definition[]>([])
  const [dirty, setDirty] = useState<Set<number>>(new Set())

  useEffect(() => setRows((data ?? []) as unknown as Definition[]), [data])

  const save = useMutation({
    mutationFn: async () => {
      // Only the rows actually touched — the *arrs accept individual PUTs and sending 30
      // unchanged records back would be noise in their history.
      for (const row of rows.filter((r) => dirty.has(r.id))) {
        await api.updateProviderItem(serviceId, 'quality_definition', row.id, row as never)
      }
    },
    onSuccess: async () => {
      setDirty(new Set())
      await queryClient.invalidateQueries({
        queryKey: ['providers', serviceId, 'quality_definition'],
      })
    },
  })

  const edit = (id: number, field: keyof Definition, value: string) =>
    setRows((prev) =>
      prev.map((r) =>
        r.id === id ? { ...r, [field]: value === '' ? null : Number(value) } : r,
      ),
    )

  if (isLoading) return <Spinner label="Loading…" />
  if (error) return <ErrorBox>{(error as Error).message}</ErrorBox>

  return (
    <div className="section">
      <div className="row" style={{ marginBottom: 8 }}>
        <h2 className="grow" style={{ margin: 0 }}>
          Quality sizes <span className="subtle">on {serviceName}</span>
        </h2>
        <button
          className="primary small"
          disabled={dirty.size === 0 || save.isPending}
          onClick={() => save.mutate()}
        >
          {save.isPending ? 'Saving…' : `Save ${dirty.size || ''}`}
        </button>
      </div>
      <p className="subtle" style={{ marginTop: 0 }}>
        Megabytes per minute of runtime. A release outside these bounds is rejected even if
        its quality is acceptable.
      </p>

      {save.error ? <ErrorBox>{(save.error as Error).message}</ErrorBox> : null}

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Quality</th>
              <th>Min</th>
              <th>Preferred</th>
              <th>Max</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td>{r.quality?.name ?? r.title}</td>
                {(['minSize', 'preferredSize', 'maxSize'] as const).map((field) => (
                  <td key={field} style={{ width: 110 }}>
                    <input
                      type="number"
                      step="0.1"
                      value={r[field] === null || r[field] === undefined ? '' : String(r[field])}
                      onChange={(e) => {
                        edit(r.id, field, e.target.value)
                        setDirty((p) => new Set(p).add(r.id))
                      }}
                    />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
