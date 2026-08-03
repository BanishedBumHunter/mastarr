/**
 * System operations — updates, backups, logs, scheduled tasks, restart.
 *
 * Updates lead and fan out across the whole stack, because "is anything out of date?" is
 * a question about the stack, not about one service. Everything below the fold is
 * per-service: backups belong to the service that took them, and merging four services'
 * logs into one stream is how you lose the line you were looking for.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, formatBytes } from '../../api'
import type { LogRecord, ScheduledTask, Service } from '../../api'
import { ErrorBox, PartialWarning, Spinner } from '../../components'

const LEVELS = ['', 'fatal', 'error', 'warn', 'info', 'debug', 'trace']

function when(value: string | null): string {
  if (!value) return '—'
  return new Date(value).toLocaleString()
}

function interval(minutes: number): string {
  if (!minutes) return 'disabled'
  if (minutes % 1440 === 0) return `every ${minutes / 1440}d`
  if (minutes % 60 === 0) return `every ${minutes / 60}h`
  return `every ${minutes}m`
}

/* ------------------------------------------------------------------- updates */

function Updates() {
  const queryClient = useQueryClient()
  const { data, isLoading, error } = useQuery({
    queryKey: ['fleet-updates'],
    queryFn: () => api.fleetUpdates(),
  })
  const [expanded, setExpanded] = useState<number | null>(null)

  const install = useMutation({
    mutationFn: (serviceId: number) => api.installUpdate(serviceId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['fleet-updates'] }),
  })

  if (isLoading) return <Spinner label="Checking versions…" />
  if (error) return <ErrorBox>{(error as Error).message}</ErrorBox>
  if (!data) return null

  const behind = data.services.filter((s) => s.update_available)

  return (
    <div className="stack">
      <PartialWarning failures={data.failures} />
      <p className="subtle">
        {behind.length === 0
          ? 'Every service is on its newest release.'
          : `${behind.length} of ${data.services.length} services have a newer release available.`}
      </p>

      <table className="grid">
        <thead>
          <tr>
            <th>Service</th>
            <th>Running</th>
            <th>Available</th>
            <th>Released</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {data.services.map((s) => (
            <>
              <tr key={s.service_id}>
                <td>
                  <b>{s.service_name}</b>{' '}
                  <span className="subtle">{s.service_type}</span>
                </td>
                <td>
                  <code>{s.current_version || '—'}</code>
                </td>
                <td>
                  {s.update_available ? (
                    <span className="badge warn">{s.latest_version}</span>
                  ) : (
                    <span className="badge online">current</span>
                  )}
                </td>
                <td className="subtle">{when(s.release_date)}</td>
                <td className="row" style={{ justifyContent: 'flex-end' }}>
                  {s.update_available ? (
                    <>
                      <button
                        className="small"
                        onClick={() =>
                          setExpanded(expanded === s.service_id ? null : s.service_id)
                        }
                      >
                        {expanded === s.service_id ? 'Hide changes' : "What's new"}
                      </button>
                      {/* A containerised *arr still reports installable:true and will
                          unpack a build over itself, which the next `docker run` throws
                          away. The backend gates on isDocker; here we say why. */}
                      {s.installable ? (
                        <button
                          className="small primary"
                          onClick={() => install.mutate(s.service_id)}
                          disabled={install.isPending}
                        >
                          Install
                        </button>
                      ) : (
                        <span className="subtle" title={s.blocked_reason}>
                          pull a new image
                        </span>
                      )}
                    </>
                  ) : null}
                </td>
              </tr>
              {expanded === s.service_id ? (
                <tr key={`${s.service_id}-changes`}>
                  <td colSpan={5}>
                    <div className="changelog">
                      {s.changes_new.length > 0 ? (
                        <>
                          <b>New</b>
                          <ul>
                            {s.changes_new.map((c, i) => (
                              <li key={i}>{c}</li>
                            ))}
                          </ul>
                        </>
                      ) : null}
                      {s.changes_fixed.length > 0 ? (
                        <>
                          <b>Fixed</b>
                          <ul>
                            {s.changes_fixed.map((c, i) => (
                              <li key={i}>{c}</li>
                            ))}
                          </ul>
                        </>
                      ) : null}
                      {s.changes_new.length === 0 && s.changes_fixed.length === 0 ? (
                        <span className="subtle">No changelog published for this release.</span>
                      ) : null}
                    </div>
                  </td>
                </tr>
              ) : null}
            </>
          ))}
        </tbody>
      </table>
      {install.error ? <ErrorBox>{(install.error as Error).message}</ErrorBox> : null}
    </div>
  )
}

/* ------------------------------------------------------------------- backups */

function Backups({ serviceId, serviceName }: { serviceId: number; serviceName: string }) {
  const queryClient = useQueryClient()
  const [confirm, setConfirm] = useState<number | null>(null)
  const key = ['backups', serviceId]

  const { data, isLoading, error } = useQuery({ queryKey: key, queryFn: () => api.backups(serviceId) })
  const refresh = () => queryClient.invalidateQueries({ queryKey: key })

  const create = useMutation({ mutationFn: () => api.createBackup(serviceId) })
  const remove = useMutation({
    mutationFn: (id: number) => api.deleteBackup(serviceId, id),
    onSuccess: () => {
      setConfirm(null)
      refresh()
    },
  })

  return (
    <div className="stack">
      <div className="row">
        <button
          className="primary"
          onClick={() => create.mutate()}
          disabled={create.isPending}
        >
          {create.isPending ? 'Requesting…' : 'Back up now'}
        </button>
        <button onClick={refresh}>Refresh</button>
        <span className="grow" />
        <span className="subtle">
          {data?.length ?? 0} held by {serviceName}
        </span>
      </div>
      {create.isSuccess ? (
        <div className="hint-box">
          Backup queued. {serviceName} runs it as a scheduled command, so give it a moment
          and hit Refresh.
        </div>
      ) : null}
      {create.error ? <ErrorBox>{(create.error as Error).message}</ErrorBox> : null}
      {error ? <ErrorBox>{(error as Error).message}</ErrorBox> : null}
      {isLoading ? <Spinner label="Loading backups…" /> : null}

      {data && data.length > 0 ? (
        <table className="grid">
          <thead>
            <tr>
              <th>Taken</th>
              <th>Name</th>
              <th>Kind</th>
              <th>Size</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {data.map((b) => (
              <tr key={b.id}>
                <td>{when(b.time)}</td>
                <td>
                  <code>{b.name}</code>
                </td>
                <td>
                  <span className="badge plain">{b.kind || 'manual'}</span>
                </td>
                <td>{formatBytes(b.size_bytes)}</td>
                <td className="row" style={{ justifyContent: 'flex-end' }}>
                  {/* Proxied through Mastarr — a direct link would need the service's
                      API key in the browser. */}
                  <a className="btn small" href={api.backupDownloadUrl(serviceId, b.id)}>
                    Download
                  </a>
                  {confirm === b.id ? (
                    <>
                      <button
                        className="danger small"
                        onClick={() => remove.mutate(b.id)}
                        disabled={remove.isPending}
                      >
                        Really delete
                      </button>
                      <button className="small" onClick={() => setConfirm(null)}>
                        Cancel
                      </button>
                    </>
                  ) : (
                    <button className="danger small" onClick={() => setConfirm(b.id)}>
                      Delete
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
      {data && data.length === 0 && !isLoading ? (
        <p className="subtle">
          No backups yet. {serviceName} takes one on a schedule — check Scheduled tasks
          below to see when.
        </p>
      ) : null}
      {remove.error ? <ErrorBox>{(remove.error as Error).message}</ErrorBox> : null}
    </div>
  )
}

/* ---------------------------------------------------------------------- logs */

function LogRow({ record }: { record: LogRecord }) {
  const [open, setOpen] = useState(false)
  const level = record.level.toLowerCase()
  const tone = level === 'fatal' || level === 'error' ? 'bad' : level === 'warn' ? 'warn' : 'plain'
  return (
    <>
      <tr className={record.exception ? 'clickable' : undefined} onClick={() => record.exception && setOpen((v) => !v)}>
        <td className="nowrap subtle">{when(record.time)}</td>
        <td>
          <span className={`badge ${tone}`}>{record.level || '—'}</span>
        </td>
        <td className="subtle nowrap">{record.logger}</td>
        <td>
          {record.message}
          {record.exception ? (
            <span className="subtle"> — {open ? 'hide' : 'show'} stack trace</span>
          ) : null}
        </td>
      </tr>
      {open && record.exception ? (
        <tr>
          <td colSpan={4}>
            <pre className="trace">{record.exception}</pre>
          </td>
        </tr>
      ) : null}
    </>
  )
}

function Logs({ serviceId }: { serviceId: number }) {
  const [page, setPage] = useState(1)
  const [level, setLevel] = useState('')
  const [fileId, setFileId] = useState<number | null>(null)

  const { data, isLoading, error } = useQuery({
    queryKey: ['logs', serviceId, page, level],
    queryFn: () => api.logs(serviceId, page, 50, level || undefined),
    enabled: fileId === null,
  })
  const files = useQuery({
    queryKey: ['log-files', serviceId],
    queryFn: () => api.logFiles(serviceId),
  })
  const contents = useQuery({
    queryKey: ['log-file', serviceId, fileId],
    queryFn: () => api.logFileText(serviceId, fileId as number),
    enabled: fileId !== null,
  })

  const pages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1

  return (
    <div className="stack">
      <div className="row wrap">
        <label htmlFor="loglevel">Level</label>
        <select
          id="loglevel"
          value={level}
          onChange={(e) => {
            setLevel(e.target.value)
            setPage(1)
            setFileId(null)
          }}
        >
          {LEVELS.map((l) => (
            <option key={l} value={l}>
              {l === '' ? 'All levels' : l}
            </option>
          ))}
        </select>

        <label htmlFor="logfile">File</label>
        <select
          id="logfile"
          value={fileId === null ? '' : String(fileId)}
          onChange={(e) => setFileId(e.target.value === '' ? null : Number(e.target.value))}
        >
          <option value="">Live (searchable)</option>
          {(files.data ?? []).map((f) => (
            <option key={f.id} value={f.id}>
              {f.filename}
            </option>
          ))}
        </select>

        <span className="grow" />
        {fileId === null && data ? (
          <>
            <span className="subtle">
              {data.total.toLocaleString()} records · page {data.page} of {pages}
            </span>
            <button className="small" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
              ← Newer
            </button>
            <button className="small" disabled={page >= pages} onClick={() => setPage((p) => p + 1)}>
              Older →
            </button>
          </>
        ) : null}
      </div>

      {error ? <ErrorBox>{(error as Error).message}</ErrorBox> : null}
      {contents.error ? <ErrorBox>{(contents.error as Error).message}</ErrorBox> : null}
      {isLoading || contents.isLoading ? <Spinner label="Loading logs…" /> : null}

      {fileId !== null && contents.data !== undefined ? (
        <pre className="trace logfile">{contents.data}</pre>
      ) : null}

      {fileId === null && data ? (
        <table className="grid logs">
          <thead>
            <tr>
              <th>Time</th>
              <th>Level</th>
              <th>Source</th>
              <th>Message</th>
            </tr>
          </thead>
          <tbody>
            {data.records.map((r) => (
              <LogRow key={r.id} record={r} />
            ))}
          </tbody>
        </table>
      ) : null}
      {fileId === null && data && data.records.length === 0 ? (
        <p className="subtle">Nothing logged at this level.</p>
      ) : null}
    </div>
  )
}

/* --------------------------------------------------------------------- tasks */

function Tasks({ serviceId, serviceName }: { serviceId: number; serviceName: string }) {
  const queryClient = useQueryClient()
  const key = ['tasks', serviceId]
  const { data, isLoading, error } = useQuery({ queryKey: key, queryFn: () => api.tasks(serviceId) })
  const [ran, setRan] = useState<string | null>(null)

  const run = useMutation({
    mutationFn: (task: ScheduledTask) => api.runTask(serviceId, task.task_name),
    onSuccess: (_result, task) => {
      setRan(task.name)
      queryClient.invalidateQueries({ queryKey: key })
    },
  })

  const [confirmRestart, setConfirmRestart] = useState(false)
  const restart = useMutation({
    mutationFn: () => api.restartService(serviceId),
    onSuccess: () => setConfirmRestart(false),
  })

  return (
    <div className="stack">
      {isLoading ? <Spinner label="Loading tasks…" /> : null}
      {error ? <ErrorBox>{(error as Error).message}</ErrorBox> : null}
      {ran ? <div className="hint-box">Queued “{ran}”. Watch Logs for the result.</div> : null}

      {data ? (
        <table className="grid">
          <thead>
            <tr>
              <th>Task</th>
              <th>Runs</th>
              <th>Last run</th>
              <th>Took</th>
              <th>Next</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {data.map((t) => (
              <tr key={t.id}>
                <td>
                  <b>{t.name}</b>
                </td>
                <td className="subtle">{interval(t.interval_minutes)}</td>
                <td className="subtle">{when(t.last_execution)}</td>
                <td className="subtle">{t.last_duration?.split('.')[0] ?? '—'}</td>
                <td className="subtle">{when(t.next_execution)}</td>
                <td style={{ textAlign: 'right' }}>
                  <button
                    className="small"
                    onClick={() => run.mutate(t)}
                    disabled={run.isPending}
                  >
                    Run now
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
      {run.error ? <ErrorBox>{(run.error as Error).message}</ErrorBox> : null}

      <div className="section">
        <h2>Restart</h2>
        <p className="subtle">
          Restarts {serviceName} itself. Whether it comes back is up to whatever runs the
          container — Mastarr only asks.
        </p>
        <div className="row">
          {confirmRestart ? (
            <>
              <span className="subtle">Restart {serviceName} now?</span>
              <button
                className="danger small"
                onClick={() => restart.mutate()}
                disabled={restart.isPending}
              >
                Yes, restart
              </button>
              <button className="small" onClick={() => setConfirmRestart(false)}>
                Cancel
              </button>
            </>
          ) : (
            <button className="danger" onClick={() => setConfirmRestart(true)}>
              Restart {serviceName}
            </button>
          )}
        </div>
        {restart.isSuccess ? (
          <div className="hint-box">
            Restart requested. {serviceName} will be unreachable for a few seconds.
          </div>
        ) : null}
        {restart.error ? <ErrorBox>{(restart.error as Error).message}</ErrorBox> : null}
      </div>
    </div>
  )
}

/* --------------------------------------------------------------------- shell */

const SECTIONS = [
  { key: 'backups', label: 'Backups' },
  { key: 'logs', label: 'Logs' },
  { key: 'tasks', label: 'Scheduled tasks' },
] as const

export default function System() {
  const { data: services, isLoading, error } = useQuery({
    queryKey: ['services'],
    queryFn: () => api.services(),
  })
  const [serviceId, setServiceId] = useState<number | null>(null)
  const [section, setSection] = useState<string>('backups')

  // Jellyseerr has no backups, no /log, no /system/task — it is not an *arr. Filtering it
  // out of the picker beats offering it and returning "unsupported" on every tab.
  const eligible = (services ?? []).filter((s: Service) => s.service_type !== 'jellyseerr')
  const selected = eligible.find((s) => s.id === serviceId) ?? eligible[0] ?? null

  return (
    <div className="stack">
      <div className="section">
        <h2>Updates</h2>
        <Updates />
      </div>

      <div className="section">
        <h2>Per-service operations</h2>
        {isLoading ? <Spinner label="Loading services…" /> : null}
        {error ? <ErrorBox>{(error as Error).message}</ErrorBox> : null}

        {eligible.length === 0 && !isLoading ? (
          <p className="subtle">No services connected yet.</p>
        ) : null}

        {selected ? (
          <>
            <div className="row wrap" style={{ marginBottom: 12 }}>
              <label htmlFor="sysservice">Service</label>
              <select
                id="sysservice"
                value={String(selected.id)}
                onChange={(e) => setServiceId(Number(e.target.value))}
              >
                {eligible.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>
              <span className="grow" />
              <div className="tabs small">
                {SECTIONS.map((s) => (
                  <button
                    key={s.key}
                    className={section === s.key ? 'tab active' : 'tab'}
                    onClick={() => setSection(s.key)}
                  >
                    {s.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Keyed on the service so switching services resets paging and open rows
                rather than showing one service's page 7 against another's log. */}
            {section === 'backups' ? (
              <Backups key={selected.id} serviceId={selected.id} serviceName={selected.name} />
            ) : null}
            {section === 'logs' ? <Logs key={selected.id} serviceId={selected.id} /> : null}
            {section === 'tasks' ? (
              <Tasks key={selected.id} serviceId={selected.id} serviceName={selected.name} />
            ) : null}
          </>
        ) : null}
      </div>
    </div>
  )
}
