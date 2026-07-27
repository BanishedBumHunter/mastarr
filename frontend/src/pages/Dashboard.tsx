/**
 * The unified health dashboard.
 *
 * Every service renders a card whatever its state. An unreachable service shows a card
 * with its error, never a missing tile or an error boundary — the backend guarantees a
 * total snapshot, and this component is written to trust that.
 */

import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api } from '../api'
import type { ServiceSnapshot } from '../api'
import { DiskBar, Empty, ErrorBox, HealthList, Spinner, Stat, StatusBadge } from '../components'

function ServiceCard({ snapshot }: { snapshot: ServiceSnapshot }) {
  return (
    <div className={`card status-${snapshot.status}`}>
      <div className="card-head">
        <div>
          <div className="card-title">{snapshot.name}</div>
          <div className="card-url">{snapshot.url}</div>
        </div>
        <StatusBadge status={snapshot.status} />
      </div>

      <div className="meta-row">
        <span>
          Type <b>{snapshot.app_name ?? snapshot.service_type}</b>
        </span>
        {snapshot.version ? (
          <span>
            Version <b>{snapshot.version}</b>
          </span>
        ) : null}
        {snapshot.queue_count !== null ? (
          <span>
            Queue <b>{snapshot.queue_count}</b>
          </span>
        ) : null}
      </div>

      {snapshot.error ? <ErrorBox>{snapshot.error}</ErrorBox> : null}

      {snapshot.status === 'unauthorized' ? (
        <div className="hint-box">
          Add this service's API key to see health, queue and disk usage. It's in the
          service's own UI under <b>Settings → General → Security</b>.{' '}
          <Link to="/services">Manage services →</Link>
        </div>
      ) : null}

      <HealthList issues={snapshot.health_issues} />

      {snapshot.disk_space.length > 0 ? (
        <div className="stack" style={{ gap: 8 }}>
          {snapshot.disk_space.map((disk) => (
            <DiskBar key={disk.path} disk={disk} />
          ))}
        </div>
      ) : null}
    </div>
  )
}

export default function Dashboard() {
  const queryClient = useQueryClient()
  const { data, isLoading, error, isFetching } = useQuery({
    queryKey: ['dashboard'],
    queryFn: () => api.dashboard(),
    // The backend caches per-service results for ~5s, so polling is cheap.
    refetchInterval: 15000,
  })

  const refresh = async () => {
    await api.dashboard(true)
    await queryClient.invalidateQueries({ queryKey: ['dashboard'] })
  }

  if (isLoading) return <Spinner label="Loading dashboard…" />
  if (error) return <ErrorBox>{(error as Error).message}</ErrorBox>
  if (!data) return null

  const { totals, services } = data

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Dashboard</h1>
          <div className="subtle">
            {totals.services} service{totals.services === 1 ? '' : 's'} connected
            {data.generated_at
              ? ` · updated ${new Date(data.generated_at).toLocaleTimeString()}`
              : ''}
          </div>
        </div>
        <div className="row">
          {isFetching ? <span className="spinner" /> : null}
          <button onClick={() => void refresh()}>Refresh</button>
        </div>
      </div>

      {services.length === 0 ? (
        <Empty title="No services connected yet">
          Run a scan to find the *arr services on your network, or add one by hand.{' '}
          <Link to="/services">Get started →</Link>
        </Empty>
      ) : (
        <>
          <div className="stat-row">
            <Stat value={totals.services} label="Services" />
            <Stat value={totals.online} label="Online" tone={totals.online ? 'ok' : undefined} />
            <Stat
              value={totals.degraded}
              label="Degraded"
              tone={totals.degraded ? 'warn' : undefined}
            />
            <Stat
              value={totals.unreachable + totals.unknown}
              label="Unreachable"
              tone={totals.unreachable + totals.unknown ? 'danger' : undefined}
            />
            <Stat
              value={totals.unauthorized}
              label="Need keys"
              tone={totals.unauthorized ? 'warn' : undefined}
            />
            <Stat
              value={totals.health_issues}
              label="Health issues"
              tone={totals.health_issues ? 'warn' : undefined}
            />
            <Stat value={totals.queued_items} label="Queued" />
          </div>

          <div className="card-grid">
            {services.map((snapshot) => (
              <ServiceCard key={snapshot.service_id ?? snapshot.url} snapshot={snapshot} />
            ))}
          </div>
        </>
      )}
    </>
  )
}
