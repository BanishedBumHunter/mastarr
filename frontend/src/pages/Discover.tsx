/**
 * Discover — search and request, backed by Jellyseerr/Overseerr.
 *
 * The browse experience is proxied rather than reimplemented: Jellyseerr already does
 * TMDB search, trending and the request lifecycle properly. Mastarr's job is to put it
 * behind the same auth and shell as everything else.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../api'
import type { DiscoverResult } from '../api'
import { Empty, ErrorBox, Spinner } from '../components'

function ResultCard({
  result,
  onRequest,
  pending,
}: {
  result: DiscoverResult
  onRequest: () => void
  pending: boolean
}) {
  // Available / requested / requestable, decided by Jellyseerr's own mediaInfo.
  const state = result.available
    ? { label: 'In library', cls: 'online' }
    : result.already_requested
      ? { label: 'Requested', cls: 'unauthorized' }
      : null

  return (
    <div className="lib-card discover-card">
      <div className="lib-poster-wrap">
        {result.poster_url ? (
          <img className="lib-poster" src={result.poster_url} alt="" loading="lazy" />
        ) : (
          <div className="lib-poster lib-poster-empty">{result.title.slice(0, 1)}</div>
        )}
        <span className="lib-flag plain">{result.media_kind === 'tv' ? 'TV' : 'Film'}</span>
      </div>
      <div className="lib-title">{result.title}</div>
      <div className="lib-sub">
        {result.year ?? ''}
        {result.vote_average ? ` · ★ ${result.vote_average.toFixed(1)}` : ''}
      </div>
      {state ? (
        <span className={`badge ${state.cls}`}>{state.label}</span>
      ) : (
        <button className="small primary" onClick={onRequest} disabled={pending}>
          {pending ? 'Requesting…' : 'Request'}
        </button>
      )}
    </div>
  )
}

export default function Discover() {
  const queryClient = useQueryClient()
  const [query, setQuery] = useState('')
  const [submitted, setSubmitted] = useState('')
  const [feed, setFeed] = useState('trending')
  const [busy, setBusy] = useState<number | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const capabilities = useQuery({
    queryKey: ['discover-capabilities'],
    queryFn: api.discoverCapabilities,
  })

  const available = capabilities.data?.available ?? false

  const results = useQuery({
    queryKey: ['discover', submitted, feed],
    queryFn: () =>
      submitted ? api.discoverSearch(submitted) : api.discoverFeed(feed),
    enabled: available,
  })

  const request = useMutation({
    mutationFn: (result: DiscoverResult) =>
      api.createRequest(result.tmdb_id, result.media_kind),
    onMutate: (result) => setBusy(result.tmdb_id),
    onSuccess: async (_data, result) => {
      setNotice(`Requested “${result.title}”.`)
      await queryClient.invalidateQueries({ queryKey: ['discover'] })
      await queryClient.invalidateQueries({ queryKey: ['requests'] })
    },
    onSettled: () => setBusy(null),
  })

  if (capabilities.isLoading) return <Spinner label="Loading…" />

  if (!available) {
    return (
      <>
        <div className="page-head">
          <h1>Discover</h1>
        </div>
        <Empty title="Media browsing isn't available yet">
          {capabilities.data?.message ??
            'No Jellyseerr or Overseerr instance is connected.'}
        </Empty>
      </>
    )
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Discover</h1>
          <div className="subtle">
            {submitted
              ? `${results.data?.total_results ?? 0} results for “${submitted}”`
              : 'Browse what’s popular, or search for something specific'}
          </div>
        </div>
      </div>

      <div className="section" style={{ marginBottom: 14 }}>
        <form
          className="row wrap"
          onSubmit={(e) => {
            e.preventDefault()
            setSubmitted(query.trim())
          }}
        >
          <input
            className="grow"
            placeholder="Search for a film or show…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <button className="primary" type="submit">
            Search
          </button>
          {submitted ? (
            <button
              type="button"
              onClick={() => {
                setQuery('')
                setSubmitted('')
              }}
            >
              Clear
            </button>
          ) : (
            <div className="seg">
              {['trending', 'movies', 'tv'].map((f) => (
                <button
                  type="button"
                  key={f}
                  className={feed === f ? 'active' : ''}
                  onClick={() => setFeed(f)}
                >
                  {f === 'tv' ? 'TV' : f}
                </button>
              ))}
            </div>
          )}
        </form>
      </div>

      {notice ? <div className="hint-box" style={{ marginBottom: 14 }}>{notice}</div> : null}
      {request.error ? <ErrorBox>{(request.error as Error).message}</ErrorBox> : null}
      {results.error ? <ErrorBox>{(results.error as Error).message}</ErrorBox> : null}

      {results.isLoading ? <Spinner label="Loading…" /> : null}

      {results.data && results.data.results.length === 0 ? (
        <Empty title="Nothing found">Try a different search term.</Empty>
      ) : null}

      {results.data && results.data.results.length > 0 ? (
        <div className="lib-grid">
          {results.data.results.map((result) => (
            <ResultCard
              key={`${result.media_kind}-${result.tmdb_id}`}
              result={result}
              pending={busy === result.tmdb_id}
              onRequest={() => request.mutate(result)}
            />
          ))}
        </div>
      ) : null}
    </>
  )
}
