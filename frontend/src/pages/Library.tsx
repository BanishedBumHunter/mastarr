/**
 * Unified library — browse and manage everything from one grid.
 *
 * The whole library arrives in one payload (hundreds of items, not millions), so search,
 * sort and filtering are instant and local. Round-tripping per keystroke would make the
 * page feel worse for no benefit.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { api, formatBytes, posterUrl } from '../api'
import type { LibraryItem } from '../api'
import { Empty, ErrorBox, PartialWarning, ProgressBar, Spinner } from '../components'
import ItemDetail from './ItemDetail'

type SortKey = 'title' | 'added' | 'size' | 'progress'

function Card({ item, onOpen }: { item: LibraryItem; onOpen: () => void }) {
  const poster = posterUrl(item.service_id, item.poster)
  const missing = item.monitored && item.have_count < item.total_count

  return (
    <button className="lib-card" onClick={onOpen} title={item.title}>
      <div className="lib-poster-wrap">
        {poster ? (
          <img className="lib-poster" src={poster} alt="" loading="lazy" />
        ) : (
          <div className="lib-poster lib-poster-empty">{item.title.slice(0, 1)}</div>
        )}
        {!item.monitored ? <span className="lib-flag plain">paused</span> : null}
        {missing ? <span className="lib-flag warn">missing</span> : null}
      </div>
      <div className="lib-title">{item.title}</div>
      <div className="lib-sub">
        {item.year ?? ''}
        {item.size_bytes ? ` · ${formatBytes(item.size_bytes)}` : ''}
      </div>
      {item.total_count > 1 ? (
        <ProgressBar
          value={item.have_count}
          total={item.total_count}
          label={`${item.have_count}/${item.total_count}`}
        />
      ) : null}
    </button>
  )
}

export default function Library() {
  const queryClient = useQueryClient()
  const [kind, setKind] = useState<string>('all')
  const [search, setSearch] = useState('')
  const [sort, setSort] = useState<SortKey>('title')
  const [onlyMissing, setOnlyMissing] = useState(false)
  const [onlyUnmonitored, setOnlyUnmonitored] = useState(false)
  const [selected, setSelected] = useState<LibraryItem | null>(null)

  const { data, isLoading, error } = useQuery({
    queryKey: ['library'],
    queryFn: () => api.library(),
    staleTime: 60000,
  })

  const refresh = useMutation({
    mutationFn: async () => {
      await queryClient.invalidateQueries({ queryKey: ['library'] })
    },
  })

  const kinds = useMemo(
    () => [...new Set((data?.items ?? []).map((i) => i.media_kind))].sort(),
    [data],
  )

  const visible = useMemo(() => {
    const needle = search.trim().toLowerCase()
    const items = (data?.items ?? []).filter((i) => {
      if (kind !== 'all' && i.media_kind !== kind) return false
      if (onlyMissing && !(i.monitored && i.have_count < i.total_count)) return false
      if (onlyUnmonitored && i.monitored) return false
      if (needle && !i.title.toLowerCase().includes(needle)) return false
      return true
    })
    const sorted = [...items]
    sorted.sort((a, b) => {
      switch (sort) {
        case 'added':
          return (b.added ?? '').localeCompare(a.added ?? '')
        case 'size':
          return b.size_bytes - a.size_bytes
        case 'progress':
          return (
            a.have_count / Math.max(a.total_count, 1) -
            b.have_count / Math.max(b.total_count, 1)
          )
        default:
          return (a.sort_title ?? a.title).localeCompare(b.sort_title ?? b.title)
      }
    })
    return sorted
  }, [data, kind, search, sort, onlyMissing, onlyUnmonitored])

  if (isLoading) return <Spinner label="Loading library…" />
  if (error) return <ErrorBox>{(error as Error).message}</ErrorBox>

  const totalSize = visible.reduce((sum, i) => sum + i.size_bytes, 0)

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Library</h1>
          <div className="subtle">
            {visible.length} of {data?.items.length ?? 0} items · {formatBytes(totalSize)}
          </div>
        </div>
        <button onClick={() => refresh.mutate()} disabled={refresh.isPending}>
          Refresh
        </button>
      </div>

      <PartialWarning failures={data?.failures ?? []} />

      <div className="section" style={{ marginBottom: 14 }}>
        <div className="row wrap">
          {/* The shows/movies toggle, built from whatever types are actually connected. */}
          <div className="seg">
            <button className={kind === 'all' ? 'active' : ''} onClick={() => setKind('all')}>
              All
            </button>
            {kinds.map((k) => (
              <button
                key={k}
                className={kind === k ? 'active' : ''}
                onClick={() => setKind(k)}
              >
                {k === 'series' ? 'Shows' : k === 'movie' ? 'Movies' : k}
              </button>
            ))}
          </div>

          <input
            className="grow"
            placeholder="Search titles…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            style={{ minWidth: 180 }}
          />

          <select
            value={sort}
            onChange={(e) => setSort(e.target.value as SortKey)}
            style={{ width: 'auto' }}
          >
            <option value="title">Sort: title</option>
            <option value="added">Sort: recently added</option>
            <option value="size">Sort: largest</option>
            <option value="progress">Sort: least complete</option>
          </select>

          <label className="row" style={{ marginBottom: 0, gap: 6 }}>
            <input
              type="checkbox"
              checked={onlyMissing}
              style={{ width: 'auto' }}
              onChange={(e) => setOnlyMissing(e.target.checked)}
            />
            Missing
          </label>
          <label className="row" style={{ marginBottom: 0, gap: 6 }}>
            <input
              type="checkbox"
              checked={onlyUnmonitored}
              style={{ width: 'auto' }}
              onChange={(e) => setOnlyUnmonitored(e.target.checked)}
            />
            Paused
          </label>
        </div>
      </div>

      {visible.length === 0 ? (
        <Empty title="Nothing matches">
          {data?.items.length
            ? 'Try clearing the search or filters.'
            : 'No library items found. Check your services are connected and have API keys.'}
        </Empty>
      ) : (
        <div className="lib-grid">
          {visible.map((item) => (
            <Card
              key={`${item.service_id}-${item.item_id}`}
              item={item}
              onOpen={() => setSelected(item)}
            />
          ))}
        </div>
      )}

      {selected ? (
        <ItemDetail
          serviceId={selected.service_id!}
          itemId={selected.item_id}
          onClose={() => setSelected(null)}
        />
      ) : null}
    </>
  )
}
