/**
 * The Requester surface.
 *
 * A placeholder shell for build priority 6. Rich discovery/browse is deliberately not
 * reimplemented here — it is an Overseerr/Jellyseerr-backed feature, surfaced through
 * Mastarr's auth and UI shell once an OverseerrAdapter is connected.
 *
 * It reports honestly rather than showing a dead search box.
 */

import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import { Empty, ErrorBox, Spinner } from '../components'
import { useAuth } from '../auth'

export default function Requests() {
  const { user } = useAuth()
  const { data, isLoading, error } = useQuery({
    queryKey: ['request-capabilities'],
    queryFn: api.requestCapabilities,
  })

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Requests</h1>
          <div className="subtle">Signed in as {user?.username}</div>
        </div>
      </div>

      {isLoading ? <Spinner label="Loading…" /> : null}
      {error ? <ErrorBox>{(error as Error).message}</ErrorBox> : null}

      {data && !data.discovery_available ? (
        <Empty title="Media browsing isn't available yet">{data.message}</Empty>
      ) : null}
    </>
  )
}
