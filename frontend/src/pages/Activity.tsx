/** Unified activity — what's downloading now, what happened recently, what's still missing. */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, formatBytes } from '../api'
import { Empty, ErrorBox, PartialWarning, Spinner } from '../components'

type Tab = 'queue' | 'history' | 'wanted' | 'blocklist'

function QueueTab() {
  const queryClient = useQueryClient()
  const { data, isLoading, error } = useQuery({
    queryKey: ['queue'],
    queryFn: api.queue,
    // Downloads move; this is the one view worth polling aggressively.
    refetchInterval: 10000,
  })

  const remove = useMutation({
    mutationFn: ({ serviceId, id, blocklist }: { serviceId: number; id: number; blocklist: boolean }) =>
      api.removeFromQueue(serviceId, id, blocklist),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['queue'] }),
  })
  if (isLoading) return <Spinner label="Loading queue…" />
  if (error) return <ErrorBox>{(error as Error).message}</ErrorBox>
  if (!data?.items.length)
    return <Empty title="Nothing downloading">The queue is empty.</Empty>

  return (
    <>
      <PartialWarning failures={data.failures} />
      {remove.error ? <ErrorBox>{(remove.error as Error).message}</ErrorBox> : null}
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Title</th>
              <th>Progress</th>
              <th>Size</th>
              <th>Client</th>
              <th>Status</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {data.items.map((item) => {
              const done = item.size_bytes - item.size_left_bytes
              const pct = item.size_bytes ? (done / item.size_bytes) * 100 : 0
              return (
                <tr key={`${item.id}-${item.title}`}>
                  <td>
                    <div>{item.media_title ?? item.title}</div>
                    {item.error_message ? (
                      <div className="subtle" style={{ color: 'var(--danger)' }}>
                        {item.error_message}
                      </div>
                    ) : null}
                  </td>
                  <td style={{ minWidth: 140 }}>
                    <div className="bar">
                      <div className="bar-fill" style={{ width: `${pct}%` }} />
                    </div>
                    <span className="subtle">{Math.round(pct)}%</span>
                  </td>
                  <td className="subtle">{formatBytes(item.size_bytes)}</td>
                  <td className="subtle">
                    {item.download_client ?? '—'}
                    {item.service_name ? (
                      <div style={{ fontSize: 11 }}>{item.service_name}</div>
                    ) : null}
                  </td>
                  <td>
                    <span className={`badge ${item.error_message ? 'unreachable' : 'plain'}`}>
                      {item.status}
                    </span>
                  </td>
                  <td>
                    <div className="row">
                      <button
                        className="small"
                        title="Remove from the queue"
                        disabled={remove.isPending || !item.service_id}
                        onClick={() =>
                          remove.mutate({ serviceId: item.service_id!, id: item.id, blocklist: false })
                        }
                      >
                        Remove
                      </button>
                      <button
                        className="small danger"
                        title="Remove and blocklist, so it isn't grabbed again"
                        disabled={remove.isPending || !item.service_id}
                        onClick={() =>
                          remove.mutate({ serviceId: item.service_id!, id: item.id, blocklist: true })
                        }
                      >
                        Block
                      </button>
                    </div>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </>
  )
}

function HistoryTab() {
  const [pageSize, setPageSize] = useState(50)
  const { data, isLoading, error } = useQuery({
    queryKey: ['history', pageSize],
    queryFn: () => api.history(pageSize),
  })
  if (isLoading) return <Spinner label="Loading history…" />
  if (error) return <ErrorBox>{(error as Error).message}</ErrorBox>

  return (
    <>
      <PartialWarning failures={data?.failures ?? []} />
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>When</th>
              <th>Event</th>
              <th>Title</th>
              <th>Quality</th>
            </tr>
          </thead>
          <tbody>
            {(data?.items ?? []).map((item) => (
              <tr key={`${item.id}-${item.date}`}>
                <td className="subtle">
                  {item.date ? new Date(item.date).toLocaleString() : '—'}
                </td>
                <td>
                  <span className="badge plain">{item.event_type}</span>
                </td>
                <td>{item.media_title ?? item.title}</td>
                <td className="subtle">{item.quality ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="row" style={{ marginTop: 12 }}>
        <button onClick={() => setPageSize((n) => n + 50)} disabled={pageSize >= 200}>
          {pageSize >= 200 ? 'Showing the maximum' : 'Show more'}
        </button>
        <span className="subtle">Showing the {pageSize} most recent events</span>
      </div>
    </>
  )
}

function WantedTab() {
  const { data, isLoading, error } = useQuery({ queryKey: ['wanted'], queryFn: api.wanted })
  if (isLoading) return <Spinner label="Loading…" />
  if (error) return <ErrorBox>{(error as Error).message}</ErrorBox>
  if (!data?.items.length)
    return <Empty title="Nothing missing">Everything monitored has been downloaded.</Empty>

  return (
    <>
      <PartialWarning failures={data.failures} />
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Title</th>
              <th>Year</th>
              <th>Service</th>
              <th>Have</th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((item) => (
              <tr key={`${item.service_id}-${item.item_id}`}>
                <td>{item.title}</td>
                <td className="subtle">{item.year ?? '—'}</td>
                <td className="subtle">{item.service_name}</td>
                <td className="subtle">
                  {item.have_count}/{item.total_count}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  )
}

function BlocklistTab() {
  const queryClient = useQueryClient()
  const { data, isLoading, error } = useQuery({ queryKey: ['blocklist'], queryFn: api.blocklist })
  const unblock = useMutation({
    mutationFn: ({ serviceId, id }: { serviceId: number; id: number }) =>
      api.removeFromBlocklist(serviceId, id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['blocklist'] }),
  })

  if (isLoading) return <Spinner label="Loading…" />
  if (error) return <ErrorBox>{(error as Error).message}</ErrorBox>
  if (!data?.items.length)
    return (
      <Empty title="Nothing blocklisted">
        Releases you block — or that the grab guard rejects — appear here, and won't be
        grabbed again until you remove them.
      </Empty>
    )

  return (
    <>
      <PartialWarning failures={data.failures} />
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>When</th>
              <th>Release</th>
              <th>Title</th>
              <th>Why</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {data.items.map((b) => (
              <tr key={`${b.id}-${b.title}`}>
                <td className="subtle">{b.date ? new Date(b.date).toLocaleString() : '—'}</td>
                <td style={{ wordBreak: 'break-all' }}>{b.title}</td>
                <td className="subtle">{b.media_title ?? '—'}</td>
                <td className="subtle">{b.message ?? '—'}</td>
                <td>
                  <button
                    className="small"
                    title="Allow this release to be grabbed again"
                    disabled={unblock.isPending || !b.service_id}
                    onClick={() => unblock.mutate({ serviceId: b.service_id!, id: b.id })}
                  >
                    Unblock
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {unblock.error ? <ErrorBox>{(unblock.error as Error).message}</ErrorBox> : null}
    </>
  )
}

export default function Activity() {
  const [tab, setTab] = useState<Tab>('queue')
  return (
    <>
      <div className="page-head">
        <h1>Activity</h1>
        <div className="seg">
          {(['queue', 'history', 'wanted', 'blocklist'] as Tab[]).map((t) => (
            <button key={t} className={tab === t ? 'active' : ''} onClick={() => setTab(t)}>
              {t === 'wanted' ? 'Missing' : t}
            </button>
          ))}
        </div>
      </div>
      {tab === 'queue' ? <QueueTab /> : null}
      {tab === 'history' ? <HistoryTab /> : null}
      {tab === 'wanted' ? <WantedTab /> : null}
      {tab === 'blocklist' ? <BlocklistTab /> : null}
    </>
  )
}
