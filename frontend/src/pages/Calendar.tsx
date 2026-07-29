/**
 * Unified calendar — every service on one timeline.
 *
 * Agenda-by-day is the default rather than a month grid: a control plane is read
 * top-to-bottom, and a grid wastes most of its area on empty cells while truncating the
 * busy days you actually care about.
 */

import { useQuery } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { api, posterUrl } from '../api'
import type { CalendarEntry, DateKind } from '../api'
import { Empty, ErrorBox, Spinner } from '../components'
import { PartialWarning } from '../components'

const DATE_KIND_LABEL: Record<DateKind, string> = {
  air: 'Airs',
  digital: 'Digital',
  physical: 'Physical',
  cinema: 'Cinema',
  release: 'Release',
}

function dayKey(iso: string): string {
  return iso.slice(0, 10)
}

function formatDayHeading(key: string): string {
  const date = new Date(`${key}T00:00:00`)
  const today = new Date()
  const todayKey = today.toISOString().slice(0, 10)
  const tomorrow = new Date(today.getTime() + 86400000).toISOString().slice(0, 10)

  const label = date.toLocaleDateString(undefined, {
    weekday: 'long',
    day: 'numeric',
    month: 'short',
  })
  if (key === todayKey) return `Today · ${label}`
  if (key === tomorrow) return `Tomorrow · ${label}`
  return label
}

function EntryRow({ entry }: { entry: CalendarEntry }) {
  const poster = posterUrl(entry.service_id, entry.poster)
  const time = new Date(entry.date).toLocaleTimeString(undefined, {
    hour: '2-digit',
    minute: '2-digit',
  })

  // Downloaded / missing / upcoming, in one glance.
  const state = entry.has_file
    ? 'online'
    : new Date(entry.date) < new Date()
      ? 'unreachable'
      : 'plain'

  return (
    <div className="cal-entry">
      {poster ? (
        <img className="cal-poster" src={poster} alt="" loading="lazy" />
      ) : (
        <div className="cal-poster cal-poster-empty" />
      )}
      <div className="grow">
        <div className="row wrap" style={{ gap: 8 }}>
          <b>{entry.parent_title ?? entry.title}</b>
          {entry.season_number !== null && entry.episode_number !== null ? (
            <code>
              S{String(entry.season_number).padStart(2, '0')}E
              {String(entry.episode_number).padStart(2, '0')}
            </code>
          ) : null}
          {!entry.monitored ? <span className="badge plain">unmonitored</span> : null}
        </div>
        {entry.parent_title ? <div className="subtle">{entry.title}</div> : null}
      </div>
      <div className="cal-meta">
        <span className={`badge ${state}`}>
          {entry.has_file ? 'Downloaded' : DATE_KIND_LABEL[entry.date_kind]}
        </span>
        <span className="subtle">{entry.media_kind === 'series' ? time : entry.service_name}</span>
      </div>
    </div>
  )
}

export default function Calendar() {
  const [daysForward, setDaysForward] = useState(28)
  const [kindFilter, setKindFilter] = useState<string>('all')
  const [hideDownloaded, setHideDownloaded] = useState(false)

  const { data, isLoading, error } = useQuery({
    queryKey: ['calendar', daysForward],
    queryFn: () => api.calendar(7, daysForward),
    refetchInterval: 300000,
  })

  const grouped = useMemo(() => {
    const entries = (data?.entries ?? []).filter((e) => {
      if (kindFilter !== 'all' && e.media_kind !== kindFilter) return false
      if (hideDownloaded && e.has_file) return false
      return true
    })
    const map = new Map<string, CalendarEntry[]>()
    for (const entry of entries) {
      const key = dayKey(entry.date)
      const bucket = map.get(key)
      if (bucket) bucket.push(entry)
      else map.set(key, [entry])
    }
    return [...map.entries()].sort(([a], [b]) => a.localeCompare(b))
  }, [data, kindFilter, hideDownloaded])

  const kinds = useMemo(
    () => [...new Set((data?.entries ?? []).map((e) => e.media_kind))].sort(),
    [data],
  )

  if (isLoading) return <Spinner label="Loading calendar…" />
  if (error) return <ErrorBox>{(error as Error).message}</ErrorBox>

  const total = data?.entries.length ?? 0

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Calendar</h1>
          <div className="subtle">
            {total} item{total === 1 ? '' : 's'} across your services
          </div>
        </div>
        <div className="row wrap">
          <select
            value={kindFilter}
            onChange={(e) => setKindFilter(e.target.value)}
            style={{ width: 'auto' }}
          >
            <option value="all">All types</option>
            {kinds.map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </select>
          <select
            value={daysForward}
            onChange={(e) => setDaysForward(Number(e.target.value))}
            style={{ width: 'auto' }}
          >
            <option value={7}>Next 7 days</option>
            <option value={28}>Next 4 weeks</option>
            <option value={90}>Next 3 months</option>
          </select>
          <label className="row" style={{ marginBottom: 0, gap: 6 }}>
            <input
              type="checkbox"
              checked={hideDownloaded}
              style={{ width: 'auto' }}
              onChange={(e) => setHideDownloaded(e.target.checked)}
            />
            Hide downloaded
          </label>
        </div>
      </div>

      <PartialWarning failures={data?.failures ?? []} />

      {grouped.length === 0 ? (
        <Empty title="Nothing scheduled">
          No upcoming releases in this window. Try widening the range.
        </Empty>
      ) : (
        <div className="stack">
          {grouped.map(([day, entries]) => (
            <div key={day} className="section">
              <h2>{formatDayHeading(day)}</h2>
              <div className="cal-day">
                {entries.map((entry) => (
                  <EntryRow
                    key={`${entry.service_id}-${entry.item_id}-${entry.date}-${entry.episode_number}`}
                    entry={entry}
                  />
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </>
  )
}
