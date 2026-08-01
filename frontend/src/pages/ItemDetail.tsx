/**
 * Item detail drawer — the everyday management surface.
 *
 * Monitor, search, season toggles and delete live here. Rare configuration (custom
 * formats, naming, import lists) deliberately isn't reimplemented: there's a deep link to
 * the native app instead. Rebuilding four admin UIs for a handful of set-once settings
 * would be a lot of surface to maintain and the part most likely to break upstream.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, formatBytes, posterUrl } from '../api'
import type { Season } from '../api'
import { ErrorBox, ProgressBar, Spinner } from '../components'
import ReleasePicker from './ReleasePicker'

function SeasonBlock({
  season,
  serviceId,
  itemId,
  onChanged,
}: {
  season: Season
  serviceId: number
  itemId: number
  onChanged: () => void
}) {
  const [open, setOpen] = useState(false)
  const toggle = useMutation({
    mutationFn: () =>
      api.setSeasonMonitored(serviceId, itemId, season.season_number, !season.monitored),
    onSuccess: onChanged,
  })

  const label = season.season_number === 0 ? 'Specials' : `Season ${season.season_number}`

  return (
    <div className="season">
      <div className="row wrap">
        <button className="small" onClick={() => setOpen((v) => !v)}>
          {open ? '▾' : '▸'}
        </button>
        <b className="grow">{label}</b>
        <span className="subtle">
          {season.episode_file_count}/{season.episode_count}
          {season.size_bytes ? ` · ${formatBytes(season.size_bytes)}` : ''}
        </span>
        <button
          className="small"
          onClick={() => toggle.mutate()}
          disabled={toggle.isPending}
        >
          {season.monitored ? 'Pause' : 'Monitor'}
        </button>
      </div>
      <ProgressBar value={season.episode_file_count} total={season.episode_count} label="" />

      {open ? (
        <div className="ep-list">
          {season.episodes.map((ep) => (
            <div key={ep.id} className="ep">
              <code>
                E{String(ep.episode_number).padStart(2, '0')}
              </code>
              <span className="grow">{ep.title ?? '—'}</span>
              <span className="subtle">
                {ep.air_date ? new Date(ep.air_date).toLocaleDateString() : ''}
              </span>
              <span className={`badge ${ep.has_file ? 'online' : 'plain'}`}>
                {ep.has_file ? 'have' : ep.monitored ? 'wanted' : 'paused'}
              </span>
            </div>
          ))}
          {season.episodes.length === 0 ? (
            <div className="subtle">No episode records.</div>
          ) : null}
        </div>
      ) : null}
      {toggle.error ? <ErrorBox>{(toggle.error as Error).message}</ErrorBox> : null}
    </div>
  )
}

export default function ItemDetail({
  serviceId,
  itemId,
  onClose,
}: {
  serviceId: number
  itemId: number
  onClose: () => void
}) {
  const queryClient = useQueryClient()
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [picking, setPicking] = useState(false)
  const [editing, setEditing] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['library-item', serviceId, itemId],
    queryFn: () => api.libraryItem(serviceId, itemId),
  })

  const afterChange = async () => {
    await refetch()
    await queryClient.invalidateQueries({ queryKey: ['library'] })
  }

  const monitor = useMutation({
    mutationFn: (monitored: boolean) => api.setMonitored(serviceId, itemId, monitored),
    onSuccess: afterChange,
  })
  const search = useMutation({
    mutationFn: () => api.searchItem(serviceId, itemId),
    onSuccess: () => setNotice('Search queued — check Activity for progress.'),
  })
  const remove = useMutation({
    mutationFn: (deleteFiles: boolean) => api.deleteItem(serviceId, itemId, deleteFiles),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['library'] })
      onClose()
    },
  })

  // Only fetched once the editor is opened — profiles and root folders are two extra
  // round trips per service and most detail views never need them.
  const options = useQuery({
    queryKey: ['library-options', serviceId],
    queryFn: () => api.libraryOptions(serviceId),
    enabled: editing,
  })
  const edit = useMutation({
    mutationFn: (data: { quality_profile_id?: number; root_folder_path?: string }) =>
      api.editItem(serviceId, itemId, data),
    onSuccess: async () => {
      setEditing(false)
      await afterChange()
    },
  })

  const item = data?.item
  const poster = item ? posterUrl(item.service_id, item.poster) : null

  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <div className="drawer" onClick={(e) => e.stopPropagation()}>
        <div className="row" style={{ marginBottom: 12 }}>
          <h2 className="grow" style={{ margin: 0 }}>
            {item?.title ?? 'Loading…'}
          </h2>
          <button className="small" onClick={onClose}>
            Close
          </button>
        </div>

        {isLoading ? <Spinner label="Loading…" /> : null}
        {error ? <ErrorBox>{(error as Error).message}</ErrorBox> : null}

        {item ? (
          <div className="stack">
            <div className="row wrap" style={{ alignItems: 'flex-start' }}>
              {poster ? (
                <img className="detail-poster" src={poster} alt="" />
              ) : null}
              <div className="grow stack" style={{ gap: 8 }}>
                <div className="meta-row">
                  {item.year ? <span>{item.year}</span> : null}
                  <span>
                    Source <b>{item.service_name}</b>
                  </span>
                  {item.status ? <span>{item.status}</span> : null}
                  {item.network || item.studio ? (
                    <span>{item.network ?? item.studio}</span>
                  ) : null}
                  {item.size_bytes ? <span>{formatBytes(item.size_bytes)}</span> : null}
                </div>
                {item.overview ? <p className="subtle">{item.overview}</p> : null}
                {item.total_count > 1 ? (
                  <ProgressBar
                    value={item.have_count}
                    total={item.total_count}
                    label={`${item.have_count} of ${item.total_count} episodes`}
                  />
                ) : null}
                {item.path ? (
                  <div className="subtle">
                    <code>{item.path}</code>
                  </div>
                ) : null}
              </div>
            </div>

            <div className="row wrap">
              <button
                onClick={() => monitor.mutate(!item.monitored)}
                disabled={monitor.isPending}
              >
                {item.monitored ? 'Pause monitoring' : 'Resume monitoring'}
              </button>
              <button
                className="primary"
                onClick={() => search.mutate()}
                disabled={search.isPending}
              >
                {search.isPending ? 'Queuing…' : 'Search now'}
              </button>
              {/* Automatic search takes whatever the profile allows; this shows every
                  release and why each was or wasn't acceptable. */}
              <button onClick={() => setPicking(true)}>Choose a release…</button>
              <button onClick={() => setEditing((v) => !v)}>
                {editing ? 'Cancel edit' : 'Edit…'}
              </button>
              {data?.native_url ? (
                <a className="btn" href={data.native_url} target="_blank" rel="noreferrer">
                  Open in {item.service_name} ↗
                </a>
              ) : null}
              <span className="grow" />
              {confirmDelete ? (
                <>
                  <span className="subtle">Remove from {item.service_name}?</span>
                  <button
                    className="danger small"
                    onClick={() => remove.mutate(false)}
                    disabled={remove.isPending}
                  >
                    Keep files
                  </button>
                  <button
                    className="danger small"
                    onClick={() => remove.mutate(true)}
                    disabled={remove.isPending}
                  >
                    Delete files too
                  </button>
                  <button className="small" onClick={() => setConfirmDelete(false)}>
                    Cancel
                  </button>
                </>
              ) : (
                <button className="danger small" onClick={() => setConfirmDelete(true)}>
                  Remove
                </button>
              )}
            </div>

            {notice ? <div className="hint-box">{notice}</div> : null}
            {monitor.error ? <ErrorBox>{(monitor.error as Error).message}</ErrorBox> : null}
            {search.error ? <ErrorBox>{(search.error as Error).message}</ErrorBox> : null}
            {remove.error ? <ErrorBox>{(remove.error as Error).message}</ErrorBox> : null}

            {editing ? (
              <div className="section">
                <h2>Edit</h2>
                {options.isLoading ? <Spinner label="Loading options…" /> : null}
                {options.error ? <ErrorBox>{(options.error as Error).message}</ErrorBox> : null}
                {options.data ? (
                  <div className="form-row">
                    <div>
                      <label htmlFor="qp">Quality profile</label>
                      <select
                        id="qp"
                        defaultValue={String(item.quality_profile_id ?? '')}
                        onChange={(e) =>
                          edit.mutate({ quality_profile_id: Number(e.target.value) })
                        }
                      >
                        {options.data.quality_profiles.map((p) => (
                          <option key={p.id} value={p.id}>
                            {p.name}
                            {p.upgrade_allowed
                              ? ` — upgrades to ${p.cutoff_name ?? '?'}`
                              : ' — no upgrades'}
                          </option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <label htmlFor="rf">Root folder</label>
                      <select
                        id="rf"
                        defaultValue=""
                        onChange={(e) =>
                          e.target.value && edit.mutate({ root_folder_path: e.target.value })
                        }
                      >
                        <option value="">Leave where it is</option>
                        {options.data.root_folders.map((f) => (
                          <option key={f.id} value={f.path}>
                            {f.path}
                          </option>
                        ))}
                      </select>
                    </div>
                  </div>
                ) : null}
                <p className="subtle" style={{ marginBottom: 0 }}>
                  Changing the root folder asks {item.service_name} to move the files. It
                  does that on its own schedule.
                </p>
                {edit.error ? <ErrorBox>{(edit.error as Error).message}</ErrorBox> : null}
              </div>
            ) : null}

            {picking ? (
              <ReleasePicker
                serviceId={serviceId}
                itemId={itemId}
                title={item.title}
                onClose={() => setPicking(false)}
              />
            ) : null}

            {data.seasons.length > 0 ? (
              <div>
                <h2>Seasons</h2>
                <div className="stack" style={{ gap: 10 }}>
                  {data.seasons.map((season) => (
                    <SeasonBlock
                      key={season.season_number}
                      season={season}
                      serviceId={serviceId}
                      itemId={itemId}
                      onChanged={afterChange}
                    />
                  ))}
                </div>
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  )
}
