/**
 * SuggestArr's approval queue.
 *
 * A card grid rather than a table: the decision is "do I want to watch this", and that is
 * made from a poster, a synopsis and — most of all — what it was suggested *from*. A row
 * of titles with no reason attached makes every approval a coin flip.
 *
 * Selection is deliberate. SuggestArr caps a batch at 100 and rate limits decisions to
 * 20/minute, so this batches rather than firing one request per card.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../api'
import type { Suggestion } from '../api'
import { Empty, ErrorBox, Spinner } from '../components'

const STATUSES: { key: string; label: string }[] = [
  { key: 'awaiting_approval', label: 'Awaiting approval' },
  { key: 'queued', label: 'Queued' },
  { key: 'submitted', label: 'Requested' },
  { key: 'rejected', label: 'Rejected' },
  { key: 'failed', label: 'Failed' },
]

function Card({
  item,
  selected,
  onToggle,
}: {
  item: Suggestion
  selected: boolean
  onToggle: () => void
}) {
  return (
    <button
      type="button"
      className={selected ? 'suggestion selected' : 'suggestion'}
      onClick={onToggle}
      aria-pressed={selected}
    >
      {item.poster_url ? (
        <img className="suggestion-poster" src={item.poster_url} alt="" loading="lazy" />
      ) : (
        <div className="suggestion-poster placeholder" />
      )}
      <div className="suggestion-body">
        <div className="row" style={{ gap: 6 }}>
          <b className="grow">{item.title}</b>
          {item.year ? <span className="subtle">{item.year}</span> : null}
        </div>
        <div className="meta-row">
          {item.media_kind ? <span>{item.media_kind === 'tv' ? 'Series' : 'Movie'}</span> : null}
          {item.rating ? <span>★ {item.rating.toFixed(1)}</span> : null}
          {item.requested_by ? <span>for {item.requested_by}</span> : null}
        </div>
        {/* The reason. Without it this is just a list of titles. */}
        {item.source_title ? (
          <div className="suggestion-because">because you watched {item.source_title}</div>
        ) : null}
        {item.overview ? <p className="subtle clamp">{item.overview}</p> : null}
      </div>
      <span className="suggestion-check" aria-hidden="true">
        {selected ? '✓' : ''}
      </span>
    </button>
  )
}

export default function Suggestions() {
  const queryClient = useQueryClient()
  const [status, setStatus] = useState('awaiting_approval')
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [notice, setNotice] = useState<string | null>(null)

  const availability = useQuery({
    queryKey: ['suggestions-availability'],
    queryFn: () => api.suggestionsAvailability(),
  })

  const enabled = availability.data?.available === true
  const { data, isLoading, error } = useQuery({
    queryKey: ['suggestions', status, page, search],
    queryFn: () => api.suggestions(status, page, 24, search),
    enabled,
  })

  const decide = useMutation({
    mutationFn: (action: string) => api.decideSuggestions([...selected], action),
    onSuccess: async (result, action) => {
      setNotice(`${result.updated} ${result.updated === 1 ? 'suggestion' : 'suggestions'} ${
        action === 'approve'
          ? 'approved — requests are on their way.'
          : action === 'blacklist'
            ? 'blacklisted. They will not be suggested again.'
            : action === 'retry'
              ? 'queued for another attempt.'
              : 'rejected.'
      }`)
      setSelected(new Set())
      await queryClient.invalidateQueries({ queryKey: ['suggestions'] })
    },
  })

  const toggle = (id: number) =>
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  if (availability.isLoading) return <Spinner label="Checking for SuggestArr…" />

  if (!enabled) {
    return (
      <div className="section">
        <h2>Suggestions</h2>
        <p className="subtle">
          {availability.data?.message ??
            'No SuggestArr connected. Add one under Settings → Services.'}
        </p>
        <p className="subtle">
          SuggestArr logs in with a username and password rather than an API key, so both
          are needed before this page can do anything.
        </p>
      </div>
    )
  }

  const items = data?.items ?? []
  const allSelected = items.length > 0 && items.every((i) => selected.has(i.id))

  return (
    <div className="stack">
      <div className="row wrap">
        <div className="tabs">
          {STATUSES.map((s) => (
            <button
              key={s.key}
              className={status === s.key ? 'tab active' : 'tab'}
              onClick={() => {
                setStatus(s.key)
                setPage(1)
                setSelected(new Set())
              }}
            >
              {s.label}
            </button>
          ))}
        </div>
        <span className="grow" />
        <input
          placeholder="Search titles…"
          value={search}
          onChange={(e) => {
            setSearch(e.target.value)
            setPage(1)
          }}
        />
      </div>

      {notice ? <div className="hint-box">{notice}</div> : null}
      {error ? <ErrorBox>{(error as Error).message}</ErrorBox> : null}
      {decide.error ? <ErrorBox>{(decide.error as Error).message}</ErrorBox> : null}
      {isLoading ? <Spinner label="Loading suggestions…" /> : null}

      {items.length > 0 ? (
        <div className="row wrap sticky-actions">
          <button
            className="small"
            onClick={() =>
              setSelected(allSelected ? new Set() : new Set(items.map((i) => i.id)))
            }
          >
            {allSelected ? 'Clear selection' : `Select all ${items.length}`}
          </button>
          <span className="subtle grow">
            {selected.size > 0 ? `${selected.size} selected` : 'Select what you want'}
          </span>
          {status === 'awaiting_approval' ? (
            <>
              <button
                className="primary"
                disabled={selected.size === 0 || decide.isPending}
                onClick={() => decide.mutate('approve')}
              >
                Approve
              </button>
              <button
                disabled={selected.size === 0 || decide.isPending}
                onClick={() => decide.mutate('reject')}
              >
                Reject
              </button>
              {/* Reject clears this queue; blacklist is the one that sticks. Worth
                  spelling out, because the buttons look interchangeable. */}
              <button
                className="danger"
                disabled={selected.size === 0 || decide.isPending}
                onClick={() => decide.mutate('blacklist')}
                title="Never suggest these again"
              >
                Never suggest
              </button>
            </>
          ) : null}
          {status === 'failed' ? (
            <button
              className="primary"
              disabled={selected.size === 0 || decide.isPending}
              onClick={() => decide.mutate('retry')}
            >
              Retry
            </button>
          ) : null}
        </div>
      ) : null}

      <div className="suggestion-grid">
        {items.map((item) => (
          <Card
            key={item.id}
            item={item}
            selected={selected.has(item.id)}
            onToggle={() => toggle(item.id)}
          />
        ))}
      </div>

      {!isLoading && items.length === 0 ? (
        <Empty title="Nothing here">
          {status === 'awaiting_approval'
            ? 'SuggestArr has no proposals waiting. It adds them when its next run finds something you have not seen.'
            : 'No suggestions with this status.'}
        </Empty>
      ) : null}

      {data && data.pages > 1 ? (
        <div className="row">
          <span className="subtle grow">
            {data.total} total · page {data.page} of {data.pages}
          </span>
          <button className="small" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
            ← Previous
          </button>
          <button
            className="small"
            disabled={page >= data.pages}
            onClick={() => setPage((p) => p + 1)}
          >
            Next →
          </button>
        </div>
      ) : null}
    </div>
  )
}
