/**
 * Interactive search — see every release and choose one yourself.
 *
 * The value isn't only picking: it's that the service explains itself. Each release
 * carries whether it was rejected and why, so "nothing downloaded" stops being a mystery
 * and becomes a decision you can act on — including grabbing a rejected release anyway.
 */

import { useMutation, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api, formatBytes } from '../api'
import type { Release } from '../api'
import { Empty, ErrorBox, Spinner } from '../components'

export default function ReleasePicker({
  serviceId,
  itemId,
  title,
  episodeId,
  onClose,
}: {
  serviceId: number
  itemId: number
  title: string
  episodeId?: number
  onClose: () => void
}) {
  const [grabbed, setGrabbed] = useState<string | null>(null)
  const [showRejected, setShowRejected] = useState(false)

  const search = useQuery({
    queryKey: ['releases', serviceId, itemId, episodeId],
    queryFn: () => api.searchReleases(serviceId, itemId, episodeId),
    // Every indexer is queried synchronously; this genuinely takes a while.
    retry: false,
    staleTime: 60000,
  })

  const grab = useMutation({
    mutationFn: (r: Release) => api.grabRelease(serviceId, r.guid, r.indexer_id ?? 0),
    onSuccess: (_d, r) => setGrabbed(r.guid),
  })

  const all = search.data ?? []
  const accepted = all.filter((r) => !r.rejected)
  const rejected = all.filter((r) => r.rejected)
  const visible = showRejected ? all : accepted

  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <div className="drawer" onClick={(e) => e.stopPropagation()} style={{ width: 'min(1100px, 100%)' }}>
        <div className="row" style={{ marginBottom: 12 }}>
          <h2 className="grow" style={{ margin: 0 }}>
            Releases for {title}
          </h2>
          <button className="small" onClick={onClose}>
            Close
          </button>
        </div>

        {search.isLoading ? (
          <div className="stack">
            <Spinner label="Searching every indexer — this usually takes 10–30 seconds…" />
          </div>
        ) : null}
        {search.error ? <ErrorBox>{(search.error as Error).message}</ErrorBox> : null}
        {grab.error ? <ErrorBox>{(grab.error as Error).message}</ErrorBox> : null}

        {search.data ? (
          <>
            <div className="row wrap" style={{ marginBottom: 10 }}>
              <span className="subtle grow">
                {accepted.length} usable of {all.length} found
                {rejected.length ? ` · ${rejected.length} rejected by your profile` : ''}
              </span>
              {rejected.length > 0 ? (
                <label className="row" style={{ gap: 6, marginBottom: 0 }}>
                  <input
                    type="checkbox"
                    style={{ width: 'auto' }}
                    checked={showRejected}
                    onChange={(e) => setShowRejected(e.target.checked)}
                  />
                  Show rejected
                </label>
              ) : null}
            </div>

            {visible.length === 0 ? (
              <Empty title="Nothing usable found">
                {rejected.length
                  ? 'Every release was rejected by your quality profile. Tick “Show rejected” to see why — you can still grab one.'
                  : 'No indexer returned anything for this.'}
              </Empty>
            ) : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Release</th>
                      <th>Quality</th>
                      <th>Size</th>
                      <th>Age</th>
                      <th>Indexer</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {visible.map((r) => (
                      <tr key={r.guid}>
                        <td>
                          <div style={{ wordBreak: 'break-all' }}>{r.title}</div>
                          {r.rejections.length > 0 ? (
                            <div className="subtle" style={{ color: 'var(--warn)' }}>
                              {r.rejections.join(' · ')}
                            </div>
                          ) : null}
                        </td>
                        <td className="subtle">{r.quality ?? '—'}</td>
                        <td className="subtle">{formatBytes(r.size_bytes)}</td>
                        <td className="subtle">
                          {r.age_hours === null
                            ? '—'
                            : r.age_hours < 48
                              ? `${Math.round(r.age_hours)}h`
                              : `${Math.round(r.age_hours / 24)}d`}
                        </td>
                        <td className="subtle">
                          {r.indexer ?? '—'}
                          {r.seeders !== null ? ` · ${r.seeders} seed` : ''}
                        </td>
                        <td>
                          {grabbed === r.guid ? (
                            <span className="badge online">Grabbed</span>
                          ) : (
                            <button
                              className={`small ${r.rejected ? '' : 'primary'}`}
                              onClick={() => grab.mutate(r)}
                              disabled={grab.isPending}
                            >
                              {r.rejected ? 'Grab anyway' : 'Grab'}
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        ) : null}
      </div>
    </div>
  )
}
