/**
 * Manual import — file things a service couldn't place on its own.
 *
 * The useful part is that the service explains each rejection, so a file sitting in a
 * folder unimported stops being a mystery. Anything it can't identify is shown but not
 * selectable: importing something the service can't file would just move it somewhere
 * wrong.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, formatBytes } from '../../api'
import type { ImportCandidate } from '../../api'
import { Empty, ErrorBox, Spinner } from '../../components'

export default function ManualImport() {
  const queryClient = useQueryClient()
  const [serviceId, setServiceId] = useState<number | null>(null)
  const [folder, setFolder] = useState('')
  const [submitted, setSubmitted] = useState('')
  const [chosen, setChosen] = useState<Set<string>>(new Set())
  const [move, setMove] = useState(true)
  const [done, setDone] = useState<string | null>(null)

  const services = useQuery({ queryKey: ['services'], queryFn: api.services })
  const usable = (services.data ?? []).filter((s) => s.enabled && s.has_api_key)
  const active = serviceId ?? usable[0]?.id ?? null

  const scan = useQuery({
    queryKey: ['import-candidates', active, submitted],
    queryFn: () => api.importCandidates(active!, submitted),
    enabled: Boolean(active && submitted),
    retry: false,
  })

  const doImport = useMutation({
    mutationFn: () => {
      const files = (scan.data ?? [])
        .filter((c) => chosen.has(c.path))
        .map((c) => ({
          path: c.path,
          media_id: c.media_id!,
          quality: {},
          season_number: c.season_number,
          episode_ids: c.episode_ids,
        }))
      return api.doImport(active!, files, move)
    },
    onSuccess: async () => {
      setDone(`Import queued for ${chosen.size} file(s).`)
      setChosen(new Set())
      await queryClient.invalidateQueries({ queryKey: ['queue'] })
      await scan.refetch()
    },
  })

  const toggle = (c: ImportCandidate) =>
    setChosen((prev) => {
      const next = new Set(prev)
      next.has(c.path) ? next.delete(c.path) : next.add(c.path)
      return next
    })

  if (services.isLoading) return <Spinner label="Loading…" />
  if (usable.length === 0)
    return <Empty title="No services connected">Connect a service with an API key first.</Empty>

  const importable = (scan.data ?? []).filter((c) => c.media_id !== null && !c.rejections.length)

  return (
    <div className="stack">
      <div className="section">
        <h2>Manual import</h2>
        <p className="subtle" style={{ marginTop: 0 }}>
          Point at a folder and the service will say what it can file, and why it can't
          place the rest.
        </p>
        <div className="form-row">
          <div>
            <label htmlFor="mi-svc">Service</label>
            <select
              id="mi-svc"
              value={active ?? ''}
              onChange={(e) => setServiceId(Number(e.target.value))}
            >
              {usable.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          </div>
          <div className="grow">
            <label htmlFor="mi-folder">Folder (as the service sees it)</label>
            <input
              id="mi-folder"
              value={folder}
              placeholder="/data/TV"
              onChange={(e) => setFolder(e.target.value)}
            />
          </div>
          <button
            className="primary"
            onClick={() => {
              setDone(null)
              setChosen(new Set())
              setSubmitted(folder.trim())
            }}
            disabled={!folder.trim()}
          >
            Scan
          </button>
        </div>
      </div>

      {scan.isLoading ? <Spinner label="Scanning…" /> : null}
      {scan.error ? <ErrorBox>{(scan.error as Error).message}</ErrorBox> : null}
      {doImport.error ? <ErrorBox>{(doImport.error as Error).message}</ErrorBox> : null}
      {done ? <div className="hint-box">{done}</div> : null}

      {scan.data ? (
        scan.data.length === 0 ? (
          <Empty title="Nothing to import">
            The service found no importable files in that folder.
          </Empty>
        ) : (
          <div className="section">
            <div className="row wrap" style={{ marginBottom: 10 }}>
              <span className="subtle grow">
                {importable.length} of {scan.data.length} can be imported
              </span>
              <label className="row" style={{ gap: 6, marginBottom: 0 }}>
                <input
                  type="checkbox"
                  style={{ width: 'auto' }}
                  checked={move}
                  onChange={(e) => setMove(e.target.checked)}
                />
                Move files (uncheck to copy)
              </label>
              <button
                className="primary small"
                disabled={chosen.size === 0 || doImport.isPending}
                onClick={() => doImport.mutate()}
              >
                {doImport.isPending ? 'Importing…' : `Import ${chosen.size}`}
              </button>
            </div>

            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th />
                    <th>File</th>
                    <th>Goes to</th>
                    <th>Size</th>
                    <th>Quality</th>
                  </tr>
                </thead>
                <tbody>
                  {scan.data.map((c) => {
                    const ok = c.media_id !== null && c.rejections.length === 0
                    return (
                      <tr key={c.path}>
                        <td style={{ width: 30 }}>
                          <input
                            type="checkbox"
                            style={{ width: 'auto' }}
                            disabled={!ok}
                            checked={chosen.has(c.path)}
                            onChange={() => toggle(c)}
                          />
                        </td>
                        <td>
                          <div style={{ wordBreak: 'break-all' }}>{c.name}</div>
                          {c.rejections.length > 0 ? (
                            <div className="subtle" style={{ color: 'var(--warn)' }}>
                              {c.rejections.join(' · ')}
                            </div>
                          ) : null}
                        </td>
                        <td className="subtle">
                          {c.media_title ?? '—'}
                          {c.season_number !== null ? ` · S${c.season_number}` : ''}
                        </td>
                        <td className="subtle">{formatBytes(c.size_bytes)}</td>
                        <td className="subtle">{c.quality ?? '—'}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )
      ) : null}
    </div>
  )
}
