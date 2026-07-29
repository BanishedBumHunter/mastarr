/**
 * Requests.
 *
 * Admins see everything and can approve or decline. Requesters see only their own — and
 * that scoping happens server-side, so another user's requests never reach the browser.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, REQUEST_STATUS, MEDIA_STATUS } from '../api'
import { Empty, ErrorBox, Spinner } from '../components'
import { useAuth } from '../auth'

const STATUS_CLASS: Record<number, string> = {
  1: 'unauthorized', // pending
  2: 'online', // approved
  3: 'unreachable', // declined
}

export default function Requests() {
  const { isAdmin, user } = useAuth()
  const queryClient = useQueryClient()

  const capabilities = useQuery({
    queryKey: ['discover-capabilities'],
    queryFn: api.discoverCapabilities,
  })
  const available = capabilities.data?.available ?? false

  const { data, isLoading, error } = useQuery({
    queryKey: ['requests'],
    queryFn: () => api.requests(false),
    enabled: available,
  })

  const decide = useMutation({
    mutationFn: ({ id, approve }: { id: number; approve: boolean }) =>
      api.decideRequest(id, approve),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['requests'] }),
  })

  if (capabilities.isLoading) return <Spinner label="Loading…" />

  if (!available) {
    return (
      <>
        <div className="page-head">
          <h1>Requests</h1>
        </div>
        <Empty title="Requests aren't available yet">
          {capabilities.data?.message ??
            'No Jellyseerr or Overseerr instance is connected.'}
        </Empty>
      </>
    )
  }

  // A Requester with no Jellyseerr mapping can't be scoped safely, so the server returns
  // nothing. Explain that rather than showing a bare empty list.
  const unmapped = !isAdmin && user && user.jellyseerr_user_id === null

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Requests</h1>
          <div className="subtle">
            {isAdmin ? 'All requests across your users' : 'Your requests'}
          </div>
        </div>
      </div>

      {unmapped ? (
        <div className="hint-box" style={{ marginBottom: 14 }}>
          Your account isn’t linked to a Jellyseerr user yet, so your requests can’t be
          shown. Ask an administrator to link it under Users.
        </div>
      ) : null}

      {isLoading ? <Spinner label="Loading requests…" /> : null}
      {error ? <ErrorBox>{(error as Error).message}</ErrorBox> : null}
      {decide.error ? <ErrorBox>{(decide.error as Error).message}</ErrorBox> : null}

      {data && data.length === 0 && !unmapped ? (
        <Empty title="No requests yet">
          Head to Discover to search for something and request it.
        </Empty>
      ) : null}

      {data && data.length > 0 ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th />
                <th>Title</th>
                <th>Type</th>
                {isAdmin ? <th>Requested by</th> : null}
                <th>Status</th>
                <th>Library</th>
                {isAdmin ? <th /> : null}
              </tr>
            </thead>
            <tbody>
              {data.map((req) => (
                <tr key={req.id}>
                  <td style={{ width: 44 }}>
                    {req.poster_url ? (
                      <img
                        src={req.poster_url}
                        alt=""
                        loading="lazy"
                        style={{ width: 36, borderRadius: 3 }}
                      />
                    ) : null}
                  </td>
                  <td>{req.title ?? `#${req.id}`}</td>
                  <td className="subtle">{req.media_kind === 'tv' ? 'TV' : 'Film'}</td>
                  {isAdmin ? <td className="subtle">{req.requested_by ?? '—'}</td> : null}
                  <td>
                    <span className={`badge ${STATUS_CLASS[req.status] ?? 'plain'}`}>
                      {REQUEST_STATUS[req.status] ?? req.status}
                    </span>
                  </td>
                  <td className="subtle">
                    {req.media_status ? MEDIA_STATUS[req.media_status] ?? '—' : '—'}
                  </td>
                  {isAdmin ? (
                    <td>
                      {req.status === 1 ? (
                        <div className="row">
                          <button
                            className="small primary"
                            onClick={() => decide.mutate({ id: req.id, approve: true })}
                            disabled={decide.isPending}
                          >
                            Approve
                          </button>
                          <button
                            className="small danger"
                            onClick={() => decide.mutate({ id: req.id, approve: false })}
                            disabled={decide.isPending}
                          >
                            Decline
                          </button>
                        </div>
                      ) : null}
                    </td>
                  ) : null}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </>
  )
}
