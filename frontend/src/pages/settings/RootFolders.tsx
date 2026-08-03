/**
 * Root folders — add and remove the paths a service files media into.
 *
 * Paths are as the *service* sees them inside its own container, which is the usual source
 * of confusion, so existing folders are listed as examples and accessibility is shown.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, formatBytes } from '../../api'
import { Empty, ErrorBox, Spinner } from '../../components'

interface RootFolder {
  id: number
  path: string
  accessible?: boolean
  freeSpace?: number | null
  [k: string]: unknown
}

export default function RootFolders({
  serviceId,
  serviceName,
}: {
  serviceId: number
  serviceName: string
}) {
  const queryClient = useQueryClient()
  const [path, setPath] = useState('')
  const { data, isLoading, error } = useQuery({
    queryKey: ['providers', serviceId, 'root_folder'],
    queryFn: () => api.providers(serviceId, 'root_folder'),
  })

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ['providers', serviceId, 'root_folder'] })

  const add = useMutation({
    mutationFn: () =>
      api.createProviderItem(serviceId, 'root_folder', { path: path.trim() } as never),
    onSuccess: async () => {
      setPath('')
      await invalidate()
    },
  })
  const remove = useMutation({
    mutationFn: (id: number) => api.deleteProviderItem(serviceId, 'root_folder', id),
    onSuccess: invalidate,
  })

  if (isLoading) return <Spinner label="Loading…" />
  if (error) return <ErrorBox>{(error as Error).message}</ErrorBox>

  const folders = (data ?? []) as unknown as RootFolder[]

  return (
    <div className="section">
      <h2>
        Root folders <span className="subtle">on {serviceName}</span>
      </h2>
      <p className="subtle" style={{ marginTop: 0 }}>
        Paths as {serviceName} sees them inside its own container — not as your NAS sees
        them.
      </p>

      <div className="form-row">
        <div className="grow">
          <label htmlFor="rf-path">New root folder</label>
          <input
            id="rf-path"
            value={path}
            placeholder={folders[0]?.path ?? '/data/TV'}
            onChange={(e) => setPath(e.target.value)}
          />
        </div>
        <button
          className="primary"
          onClick={() => add.mutate()}
          disabled={!path.trim() || add.isPending}
        >
          {add.isPending ? 'Adding…' : 'Add'}
        </button>
      </div>
      {add.error ? <ErrorBox>{(add.error as Error).message}</ErrorBox> : null}
      {remove.error ? <ErrorBox>{(remove.error as Error).message}</ErrorBox> : null}

      {folders.length === 0 ? (
        <Empty title="No root folders">Media can't be added until one exists.</Empty>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Path</th>
                <th>Free</th>
                <th>Status</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {folders.map((f) => (
                <tr key={f.id}>
                  <td>
                    <code>{f.path}</code>
                  </td>
                  <td className="subtle">
                    {f.freeSpace ? formatBytes(f.freeSpace) : '—'}
                  </td>
                  <td>
                    <span className={`badge ${f.accessible === false ? 'unreachable' : 'online'}`}>
                      {f.accessible === false ? 'not accessible' : 'ok'}
                    </span>
                  </td>
                  <td>
                    <button
                      className="small danger"
                      onClick={() => remove.mutate(f.id)}
                      disabled={remove.isPending}
                    >
                      Remove
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
