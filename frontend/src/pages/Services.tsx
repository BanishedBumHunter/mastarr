/**
 * Service management + discovery.
 *
 * Discovery is presented in the same two phases the backend implements: scan finds
 * candidates without credentials, then a key confirms identity.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../api'
import type { Discovered } from '../api'
import { Empty, ErrorBox, Spinner } from '../components'

function DiscoveryPanel() {
  const queryClient = useQueryClient()
  const [hosts, setHosts] = useState('')
  const [found, setFound] = useState<Discovered[] | null>(null)
  const [keys, setKeys] = useState<Record<string, string>>({})

  const scan = useMutation({
    mutationFn: () =>
      api.scan(
        hosts
          .split(/[\s,]+/)
          .map((h) => h.trim())
          .filter(Boolean),
      ),
    onSuccess: setFound,
  })

  const add = useMutation({
    mutationFn: async (candidate: Discovered) => {
      const apiKey = keys[candidate.url] ?? ''
      // Confirm identity before saving, so the stored type is proven rather than guessed
      // from the port.
      const identified = apiKey
        ? await api.identify(candidate.url, apiKey, candidate.service_type)
        : candidate
      const type = identified.service_type ?? candidate.service_type
      if (!type) throw new Error('Could not determine the service type. Check the API key.')

      return api.createService({
        name: identified.app_name ?? type.charAt(0).toUpperCase() + type.slice(1),
        service_type: type,
        url: candidate.url,
        api_key: apiKey || undefined,
      })
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['services'] })
      await queryClient.invalidateQueries({ queryKey: ['dashboard'] })
      setFound(
        (prev) => prev?.map((c) => ({ ...c, already_configured: true })) ?? null,
      )
    },
  })

  return (
    <div className="section">
      <h2>Discover services</h2>
      <p className="subtle" style={{ marginTop: 0 }}>
        Probes the standard *arr ports. No API keys are needed to find services — only to
        confirm what they are.
      </p>

      <div className="form-row">
        <div className="grow">
          <label htmlFor="hosts">Hosts to scan</label>
          <input
            id="hosts"
            value={hosts}
            placeholder="192.168.1.250, nas.local"
            onChange={(event) => setHosts(event.target.value)}
          />
        </div>
        <button
          className="primary"
          onClick={() => scan.mutate()}
          disabled={scan.isPending || !hosts.trim()}
        >
          {scan.isPending ? 'Scanning…' : 'Scan'}
        </button>
      </div>

      {scan.error ? <ErrorBox>{(scan.error as Error).message}</ErrorBox> : null}
      {add.error ? <ErrorBox>{(add.error as Error).message}</ErrorBox> : null}

      {found !== null ? (
        found.length === 0 ? (
          <p className="subtle">No *arr services responded on those hosts.</p>
        ) : (
          <div className="table-wrap" style={{ marginTop: 14 }}>
            <table>
              <thead>
                <tr>
                  <th>Found at</th>
                  <th>Looks like</th>
                  <th>API key</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {found.map((candidate) => (
                  <tr key={candidate.url}>
                    <td>
                      <code>{candidate.url}</code>
                    </td>
                    <td>
                      {candidate.service_type ?? 'unknown'}
                      {candidate.confirmed ? (
                        <span className="badge online" style={{ marginLeft: 6 }}>
                          confirmed
                        </span>
                      ) : null}
                      <div className="subtle" style={{ fontSize: 11.5 }}>
                        {candidate.detail}
                      </div>
                    </td>
                    <td style={{ minWidth: 190 }}>
                      <input
                        type="password"
                        placeholder="Paste API key"
                        value={keys[candidate.url] ?? ''}
                        disabled={candidate.already_configured}
                        onChange={(event) =>
                          setKeys((prev) => ({ ...prev, [candidate.url]: event.target.value }))
                        }
                      />
                    </td>
                    <td>
                      {candidate.already_configured ? (
                        <span className="badge plain">Added</span>
                      ) : (
                        <button
                          className="small primary"
                          onClick={() => add.mutate(candidate)}
                          disabled={add.isPending}
                        >
                          Add
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      ) : null}
    </div>
  )
}

function AddServiceForm() {
  const queryClient = useQueryClient()
  const { data: types } = useQuery({ queryKey: ['types'], queryFn: api.serviceTypes })
  const [form, setForm] = useState({ name: '', service_type: '', url: '', api_key: '' })

  const create = useMutation({
    mutationFn: () =>
      api.createService({
        name: form.name,
        service_type: form.service_type,
        url: form.url,
        api_key: form.api_key || undefined,
      }),
    onSuccess: async () => {
      setForm({ name: '', service_type: '', url: '', api_key: '' })
      await queryClient.invalidateQueries({ queryKey: ['services'] })
      await queryClient.invalidateQueries({ queryKey: ['dashboard'] })
    },
  })

  const selected = types?.find((t) => t.type === form.service_type)

  return (
    <div className="section">
      <h2>Add manually</h2>
      <div className="form-row">
        <div>
          <label htmlFor="stype">Type</label>
          {/* Options come from the backend registry, so a new adapter appears here with
              no frontend change. */}
          <select
            id="stype"
            value={form.service_type}
            onChange={(event) => {
              const type = event.target.value
              const match = types?.find((t) => t.type === type)
              setForm((prev) => ({
                ...prev,
                service_type: type,
                name: prev.name || (match?.display_name ?? ''),
              }))
            }}
          >
            <option value="">Choose…</option>
            {types?.map((type) => (
              <option key={type.type} value={type.type}>
                {type.display_name} (API {type.api_version})
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="sname">Name</label>
          <input
            id="sname"
            value={form.name}
            onChange={(event) => setForm((prev) => ({ ...prev, name: event.target.value }))}
          />
        </div>
        <div>
          <label htmlFor="surl">URL</label>
          <input
            id="surl"
            value={form.url}
            placeholder={
              selected ? `http://192.168.1.250:${selected.default_port}` : 'http://host:port'
            }
            onChange={(event) => setForm((prev) => ({ ...prev, url: event.target.value }))}
          />
        </div>
        <div>
          <label htmlFor="skey">API key</label>
          <input
            id="skey"
            type="password"
            value={form.api_key}
            onChange={(event) => setForm((prev) => ({ ...prev, api_key: event.target.value }))}
          />
        </div>
        <button
          className="primary"
          onClick={() => create.mutate()}
          disabled={create.isPending || !form.name || !form.service_type || !form.url}
        >
          Add service
        </button>
      </div>
      {create.error ? <ErrorBox>{(create.error as Error).message}</ErrorBox> : null}
    </div>
  )
}

export default function Services() {
  const queryClient = useQueryClient()
  const { data: services, isLoading, error } = useQuery({
    queryKey: ['services'],
    queryFn: api.services,
  })

  const invalidate = async () => {
    await queryClient.invalidateQueries({ queryKey: ['services'] })
    await queryClient.invalidateQueries({ queryKey: ['dashboard'] })
  }

  const remove = useMutation({ mutationFn: api.deleteService, onSuccess: invalidate })
  const toggle = useMutation({
    mutationFn: ({ id, enabled }: { id: number; enabled: boolean }) =>
      api.updateService(id, { enabled }),
    onSuccess: invalidate,
  })
  const setKey = useMutation({
    mutationFn: ({ id, key }: { id: number; key: string }) =>
      api.updateService(id, { api_key: key }),
    onSuccess: invalidate,
  })

  return (
    <>
      <div className="page-head">
        <h1>Services</h1>
      </div>

      <div className="stack">
        <DiscoveryPanel />
        <AddServiceForm />

        <div className="section">
          <h2>Connected services</h2>
          {isLoading ? <Spinner label="Loading…" /> : null}
          {error ? <ErrorBox>{(error as Error).message}</ErrorBox> : null}

          {services && services.length === 0 ? (
            <Empty title="Nothing connected yet">
              Scan your network above, or add a service by hand.
            </Empty>
          ) : null}

          {services && services.length > 0 ? (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Type</th>
                    <th>URL</th>
                    <th>API key</th>
                    <th>Last seen</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {services.map((service) => (
                    <tr key={service.id}>
                      <td>
                        {service.name}
                        {service.managed_by_config ? (
                          <span className="badge plain" style={{ marginLeft: 6 }}>
                            config.yml
                          </span>
                        ) : null}
                        {!service.enabled ? (
                          <span className="badge plain" style={{ marginLeft: 6 }}>
                            disabled
                          </span>
                        ) : null}
                      </td>
                      <td>{service.service_type}</td>
                      <td>
                        <code>{service.url}</code>
                      </td>
                      <td>
                        {service.has_api_key ? (
                          <span className="badge online">set</span>
                        ) : (
                          <input
                            type="password"
                            placeholder="Add key"
                            style={{ minWidth: 140 }}
                            onKeyDown={(event) => {
                              if (event.key !== 'Enter') return
                              const value = event.currentTarget.value
                              if (value) setKey.mutate({ id: service.id, key: value })
                            }}
                          />
                        )}
                      </td>
                      <td className="subtle">
                        {service.last_status ?? '—'}
                        {service.last_version ? ` · ${service.last_version}` : ''}
                      </td>
                      <td>
                        <div className="row">
                          <button
                            className="small"
                            disabled={service.managed_by_config || toggle.isPending}
                            onClick={() =>
                              toggle.mutate({ id: service.id, enabled: !service.enabled })
                            }
                          >
                            {service.enabled ? 'Disable' : 'Enable'}
                          </button>
                          <button
                            className="small danger"
                            disabled={service.managed_by_config || remove.isPending}
                            onClick={() => remove.mutate(service.id)}
                          >
                            Remove
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}

          {setKey.error ? <ErrorBox>{(setKey.error as Error).message}</ErrorBox> : null}
          {remove.error ? <ErrorBox>{(remove.error as Error).message}</ErrorBox> : null}
        </div>
      </div>
    </>
  )
}
