/**
 * Indexers, via Prowlarr.
 *
 * Prowlarr owns the indexer list and syncs it outward to the *arrs itself. Mastarr shows
 * that reach rather than writing indexers into each service — doing both would duplicate
 * entries and fight Prowlarr's own sync.
 */

import { useMutation, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../../api'
import { Empty, ErrorBox, Spinner } from '../../components'

export default function Indexers() {
  const [tested, setTested] = useState<Record<number, boolean>>({})
  const { data, isLoading, error } = useQuery({
    queryKey: ['indexers'],
    queryFn: api.indexerOverview,
  })

  const test = useMutation({
    mutationFn: (id: number) => api.testIndexer(id),
    onSuccess: (r, id) => setTested((prev) => ({ ...prev, [id]: r.ok })),
  })

  if (isLoading) return <Spinner label="Loading indexers…" />
  if (error) return <ErrorBox>{(error as Error).message}</ErrorBox>

  if (!data?.available) {
    return (
      <Empty title="No Prowlarr connected">
        {data?.message ?? 'Add a Prowlarr service to manage indexers centrally.'}
      </Empty>
    )
  }

  return (
    <div className="stack">
      <div className="section">
        <h2>Indexers</h2>
        <p className="subtle">
          Managed by <b>{data.service_name}</b>, which pushes them to your other services
          automatically.{' '}
          {data.native_url ? (
            <a href={data.native_url} target="_blank" rel="noreferrer">
              Add or edit in Prowlarr ↗
            </a>
          ) : null}
        </p>

        {data.indexers.length === 0 ? (
          <Empty title="No indexers configured">Add some in Prowlarr to get started.</Empty>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Protocol</th>
                  <th>Priority</th>
                  <th>Queries</th>
                  <th>Grabs</th>
                  <th>Status</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {data.indexers.map((idx) => (
                  <tr key={idx.id}>
                    <td>{idx.name}</td>
                    <td className="subtle">{idx.protocol ?? '—'}</td>
                    <td className="subtle">{idx.priority ?? '—'}</td>
                    <td className="subtle">{idx.stats?.queries ?? '—'}</td>
                    <td className="subtle">{idx.stats?.grabs ?? '—'}</td>
                    <td>
                      <span className={`badge ${idx.enabled ? 'online' : 'plain'}`}>
                        {idx.enabled ? 'enabled' : 'disabled'}
                      </span>
                      {tested[idx.id] !== undefined ? (
                        <span
                          className={`badge ${tested[idx.id] ? 'online' : 'unreachable'}`}
                          style={{ marginLeft: 6 }}
                        >
                          {tested[idx.id] ? 'test ok' : 'test failed'}
                        </span>
                      ) : null}
                    </td>
                    <td>
                      <button
                        className="small"
                        onClick={() => test.mutate(idx.id)}
                        disabled={test.isPending}
                      >
                        Test
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="section">
        <h2>Synced to</h2>
        {data.applications.length === 0 ? (
          <p className="subtle">
            Prowlarr isn’t configured to sync to any applications yet, so these indexers
            won’t reach your *arr services.
          </p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Application</th>
                  <th>Type</th>
                  <th>Sync level</th>
                </tr>
              </thead>
              <tbody>
                {data.applications.map((app) => (
                  <tr key={app.id}>
                    <td>{app.name}</td>
                    <td className="subtle">{app.implementation}</td>
                    <td>
                      <span className="badge plain">{app.sync_level ?? 'unknown'}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
