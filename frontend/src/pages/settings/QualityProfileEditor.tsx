/**
 * Quality profile editor.
 *
 * A profile's `items` is an ordered list, **worst first**, where an entry is either a
 * single quality or a *group* of qualities treated as equivalent. Order is preference:
 * later means better.
 *
 * Sonarr and Radarr both display best-at-top, and so does this — which means the list is
 * reversed on load and reversed again on save. Getting that backwards silently inverts
 * someone's entire quality preference while looking completely normal, so `toDisplay` and
 * `toStorage` are the only places that ordering is touched, and they have a round-trip
 * test.
 *
 * `cutoff` is the id of the entry where upgrading stops. It can reference either a single
 * quality or a group, so both have to resolve.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api } from '../../api'
import { Empty, ErrorBox, Spinner } from '../../components'

interface QualityRef {
  id: number
  name: string
}

interface ProfileItem {
  id?: number
  name?: string | null
  quality?: QualityRef | null
  items?: ProfileItem[]
  allowed: boolean
}

interface FormatItem {
  format: number
  name: string
  score: number
}

interface Profile {
  id?: number
  name: string
  upgradeAllowed: boolean
  cutoff: number
  items: ProfileItem[]
  minFormatScore?: number
  cutoffFormatScore?: number
  formatItems?: FormatItem[]
  [k: string]: unknown
}

/** Storage is worst-first; the UI shows best-first. */
const toDisplay = (items: ProfileItem[]): ProfileItem[] => [...items].reverse()
const toStorage = (items: ProfileItem[]): ProfileItem[] => [...items].reverse()

/** An entry's id: a group carries its own, a single quality uses the quality's. */
const entryId = (item: ProfileItem): number => item.quality?.id ?? item.id ?? -1
const entryName = (item: ProfileItem): string =>
  item.quality?.name ?? item.name ?? `Group ${item.id}`
const isGroup = (item: ProfileItem): boolean => !item.quality && Array.isArray(item.items)

function ProfileForm({
  serviceId,
  initial,
  onDone,
}: {
  serviceId: number
  initial: Profile
  onDone: () => void
}) {
  const queryClient = useQueryClient()
  const [name, setName] = useState(initial.name ?? '')
  const [upgrade, setUpgrade] = useState(Boolean(initial.upgradeAllowed))
  const [cutoff, setCutoff] = useState<number>(initial.cutoff)
  const [rows, setRows] = useState<ProfileItem[]>(toDisplay(initial.items ?? []))
  const [formats, setFormats] = useState<FormatItem[]>(initial.formatItems ?? [])
  const [minScore, setMinScore] = useState(initial.minFormatScore ?? 0)
  const [cutoffScore, setCutoffScore] = useState(initial.cutoffFormatScore ?? 0)
  const [expanded, setExpanded] = useState<Set<number>>(new Set())

  const allowed = rows.filter((r) => r.allowed)

  // A cutoff pointing at a disallowed quality is silently broken — the service will never
  // reach it. Pull it back to the best allowed entry instead of letting it dangle.
  useEffect(() => {
    if (allowed.length && !allowed.some((r) => entryId(r) === cutoff)) {
      setCutoff(entryId(allowed[0]))
    }
  }, [rows]) // eslint-disable-line react-hooks/exhaustive-deps

  const move = (index: number, delta: number) =>
    setRows((prev) => {
      const next = [...prev]
      const target = index + delta
      if (target < 0 || target >= next.length) return prev
      ;[next[index], next[target]] = [next[target], next[index]]
      return next
    })

  const setAllowed = (index: number, value: boolean) =>
    setRows((prev) => prev.map((r, i) => (i === index ? { ...r, allowed: value } : r)))

  const dissolveGroup = (index: number) =>
    setRows((prev) => {
      const group = prev[index]
      if (!isGroup(group)) return prev
      const members = (group.items ?? []).map((m) => ({ ...m, allowed: group.allowed }))
      return [...prev.slice(0, index), ...members, ...prev.slice(index + 1)]
    })

  const groupWithNext = (index: number) =>
    setRows((prev) => {
      const a = prev[index]
      const b = prev[index + 1]
      if (!a || !b || isGroup(a) || isGroup(b)) return prev
      // Ids above 1000 avoid colliding with real quality ids, which is how the *arrs
      // themselves distinguish group ids.
      const newId = Math.max(1000, ...prev.map((r) => r.id ?? 0)) + 1
      const group: ProfileItem = {
        id: newId,
        name: `${entryName(b)} / ${entryName(a)}`,
        allowed: a.allowed || b.allowed,
        items: [b, a],
      }
      return [...prev.slice(0, index), group, ...prev.slice(index + 2)]
    })

  const save = useMutation({
    mutationFn: () => {
      const payload: Profile = {
        ...initial,
        name,
        upgradeAllowed: upgrade,
        cutoff,
        items: toStorage(rows),
        formatItems: formats,
        minFormatScore: minScore,
        cutoffFormatScore: cutoffScore,
      }
      return initial.id
        ? api.updateProviderItem(serviceId, 'quality_profile', initial.id, payload as never)
        : api.createProviderItem(serviceId, 'quality_profile', payload as never)
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['providers', serviceId, 'quality_profile'] })
      onDone()
    },
  })

  const remove = useMutation({
    mutationFn: () => api.deleteProviderItem(serviceId, 'quality_profile', initial.id!),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['providers', serviceId, 'quality_profile'] })
      onDone()
    },
  })

  return (
    <div className="drawer-backdrop" onClick={onDone}>
      <div className="drawer" onClick={(e) => e.stopPropagation()} style={{ width: 'min(900px,100%)' }}>
        <div className="row" style={{ marginBottom: 12 }}>
          <h2 className="grow" style={{ margin: 0 }}>
            {initial.id ? 'Edit' : 'New'} quality profile
          </h2>
          <button className="small" onClick={onDone}>
            Close
          </button>
        </div>

        <div className="field">
          <label htmlFor="qp-name">Name</label>
          <input id="qp-name" value={name} onChange={(e) => setName(e.target.value)} />
        </div>

        <div className="section" style={{ marginBottom: 12 }}>
          <label className="row" style={{ gap: 8, marginBottom: 8 }}>
            <input
              type="checkbox"
              style={{ width: 'auto' }}
              checked={upgrade}
              onChange={(e) => setUpgrade(e.target.checked)}
            />
            <b>Keep upgrading</b>
          </label>
          <p className="subtle" style={{ marginTop: 0 }}>
            Grab whatever is acceptable now, then keep replacing it with something better
            until it reaches the quality below. With this off, the first acceptable release
            is kept forever.
          </p>
          <div className="field" style={{ marginBottom: 0 }}>
            <label htmlFor="qp-cutoff">Upgrade until</label>
            <select
              id="qp-cutoff"
              value={cutoff}
              disabled={!upgrade}
              onChange={(e) => setCutoff(Number(e.target.value))}
            >
              {allowed.map((r) => (
                <option key={entryId(r)} value={entryId(r)}>
                  {entryName(r)}
                </option>
              ))}
            </select>
            {allowed.length === 0 ? (
              <div className="subtle">Tick at least one quality below first.</div>
            ) : null}
          </div>
        </div>

        <h2>Qualities</h2>
        <p className="subtle" style={{ marginTop: 0 }}>
          Best at the top. Tick what's acceptable; order sets preference when several are.
        </p>

        <div className="stack" style={{ gap: 4 }}>
          {rows.map((row, index) => (
            <div key={`${entryId(row)}-${index}`} className="quality-row">
              <input
                type="checkbox"
                style={{ width: 'auto' }}
                checked={row.allowed}
                onChange={(e) => setAllowed(index, e.target.checked)}
              />
              <span className="grow">
                {isGroup(row) ? (
                  <>
                    <button
                      className="small"
                      onClick={() =>
                        setExpanded((p) => {
                          const n = new Set(p)
                          n.has(index) ? n.delete(index) : n.add(index)
                          return n
                        })
                      }
                    >
                      {expanded.has(index) ? '▾' : '▸'}
                    </button>{' '}
                    <b>{entryName(row)}</b>{' '}
                    <span className="badge plain">group of {row.items?.length ?? 0}</span>
                  </>
                ) : (
                  entryName(row)
                )}
                {entryId(row) === cutoff && upgrade ? (
                  <span className="badge online" style={{ marginLeft: 6 }}>
                    upgrade stops here
                  </span>
                ) : null}
              </span>

              <button className="small" onClick={() => move(index, -1)} disabled={index === 0}>
                ↑
              </button>
              <button
                className="small"
                onClick={() => move(index, 1)}
                disabled={index === rows.length - 1}
              >
                ↓
              </button>
              {isGroup(row) ? (
                <button className="small" onClick={() => dissolveGroup(index)}>
                  Ungroup
                </button>
              ) : (
                <button
                  className="small"
                  onClick={() => groupWithNext(index)}
                  disabled={index === rows.length - 1 || isGroup(rows[index + 1])}
                  title="Treat this and the one below as equivalent"
                >
                  Group
                </button>
              )}
            </div>
          ))}
        </div>

        {rows.map((row, index) =>
          isGroup(row) && expanded.has(index) ? (
            <div key={`exp-${index}`} className="ep-list" style={{ marginLeft: 30 }}>
              {(row.items ?? []).map((m) => (
                <div className="ep" key={entryId(m)}>
                  <span className="grow">{entryName(m)}</span>
                </div>
              ))}
            </div>
          ) : null,
        )}

        {formats.length > 0 ? (
          <>
            <h2 style={{ marginTop: 18 }}>Custom format scores</h2>
            <div className="settings-list">
              {formats.map((f, i) => (
                <div className="setting-row" key={f.format}>
                  <div className="setting-label">
                    <label>{f.name}</label>
                  </div>
                  <div className="setting-control">
                    <input
                      type="number"
                      value={f.score}
                      onChange={(e) =>
                        setFormats((prev) =>
                          prev.map((x, j) =>
                            j === i ? { ...x, score: Number(e.target.value) } : x,
                          ),
                        )
                      }
                    />
                  </div>
                </div>
              ))}
              <div className="setting-row">
                <div className="setting-label">
                  <label htmlFor="minfs">Minimum score to grab</label>
                </div>
                <div className="setting-control">
                  <input
                    id="minfs"
                    type="number"
                    value={minScore}
                    onChange={(e) => setMinScore(Number(e.target.value))}
                  />
                </div>
              </div>
              <div className="setting-row">
                <div className="setting-label">
                  <label htmlFor="cutfs">Score to stop upgrading</label>
                </div>
                <div className="setting-control">
                  <input
                    id="cutfs"
                    type="number"
                    value={cutoffScore}
                    onChange={(e) => setCutoffScore(Number(e.target.value))}
                  />
                </div>
              </div>
            </div>
          </>
        ) : null}

        {save.error ? <ErrorBox>{(save.error as Error).message}</ErrorBox> : null}
        {remove.error ? <ErrorBox>{(remove.error as Error).message}</ErrorBox> : null}

        <div className="row wrap" style={{ marginTop: 16 }}>
          <button
            className="primary"
            onClick={() => save.mutate()}
            disabled={save.isPending || !name.trim() || allowed.length === 0}
          >
            {save.isPending ? 'Saving…' : 'Save'}
          </button>
          <button onClick={onDone}>Cancel</button>
          <span className="grow" />
          {initial.id ? (
            <button className="danger small" onClick={() => remove.mutate()} disabled={remove.isPending}>
              Delete
            </button>
          ) : null}
        </div>
      </div>
    </div>
  )
}

export default function QualityProfileEditor({
  serviceId,
  serviceName,
}: {
  serviceId: number
  serviceName: string
}) {
  const [editing, setEditing] = useState<Profile | null>(null)

  const profiles = useQuery({
    queryKey: ['providers', serviceId, 'quality_profile'],
    queryFn: () => api.providers(serviceId, 'quality_profile'),
  })
  const template = useQuery({
    queryKey: ['qp-schema', serviceId],
    queryFn: () => api.qualityProfileSchema(serviceId),
    enabled: false,
  })

  if (profiles.isLoading) return <Spinner label="Loading profiles…" />
  if (profiles.error) return <ErrorBox>{(profiles.error as Error).message}</ErrorBox>

  return (
    <div className="section">
      <div className="row" style={{ marginBottom: 10 }}>
        <h2 className="grow" style={{ margin: 0 }}>
          Quality profiles <span className="subtle">on {serviceName}</span>
        </h2>
        <button
          className="primary small"
          onClick={async () => {
            const blank = await template.refetch()
            if (blank.data) setEditing({ ...(blank.data as unknown as Profile), name: '' })
          }}
        >
          New profile
        </button>
      </div>

      {profiles.data && profiles.data.length === 0 ? (
        <Empty title="No quality profiles">Create one to control what gets grabbed.</Empty>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Upgrades</th>
                <th>Accepts</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {((profiles.data ?? []) as unknown as Profile[]).map((p) => {
                const allowedNames = (p.items ?? [])
                  .filter((i) => i.allowed)
                  .map(entryName)
                const cutoffName =
                  (p.items ?? []).find((i) => entryId(i) === p.cutoff) ?? null
                return (
                  <tr key={p.id}>
                    <td>{p.name}</td>
                    <td>
                      {p.upgradeAllowed ? (
                        <span className="badge online">
                          until {cutoffName ? entryName(cutoffName) : '?'}
                        </span>
                      ) : (
                        <span className="badge plain">off</span>
                      )}
                    </td>
                    <td className="subtle">
                      {allowedNames.length
                        ? `${allowedNames.length}: ${allowedNames.slice(-3).reverse().join(', ')}${allowedNames.length > 3 ? '…' : ''}`
                        : 'nothing'}
                    </td>
                    <td>
                      <button className="small" onClick={() => setEditing(p)}>
                        Edit
                      </button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {editing ? (
        <ProfileForm serviceId={serviceId} initial={editing} onDone={() => setEditing(null)} />
      ) : null}
    </div>
  )
}
