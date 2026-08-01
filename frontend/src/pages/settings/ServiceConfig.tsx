/**
 * Per-service configuration — the tab that replaces opening the *arr UIs.
 *
 * Pick a service, pick what to configure. Everything is rendered from the service's own
 * schema, so this works for any *arr type without knowing anything about it.
 */

import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../../api'
import { Empty, ErrorBox, Spinner } from '../../components'
import ProviderList from './ProviderForm'
import SettingsGroup from './SettingsGroup'

const PROVIDER_TABS: { key: string; label: string }[] = [
  { key: 'download_client', label: 'Download clients' },
  { key: 'indexer', label: 'Indexers' },
  { key: 'import_list', label: 'Import lists' },
  { key: 'notification', label: 'Notifications' },
  { key: 'metadata', label: 'Metadata' },
]

const GROUP_TABS: { key: string; label: string }[] = [
  { key: 'indexer_options', label: 'Grab rules' },
  { key: 'media_management', label: 'Media management' },
  { key: 'naming', label: 'Naming' },
]

export default function ServiceConfig() {
  const { data: services, isLoading, error } = useQuery({
    queryKey: ['services'],
    queryFn: api.services,
  })
  const [serviceId, setServiceId] = useState<number | null>(null)
  const [section, setSection] = useState('download_client')

  if (isLoading) return <Spinner label="Loading services…" />
  if (error) return <ErrorBox>{(error as Error).message}</ErrorBox>

  const usable = (services ?? []).filter((s) => s.enabled && s.has_api_key)
  if (usable.length === 0) {
    return (
      <Empty title="No services to configure">
        Connect a service with an API key first, on the Services tab.
      </Empty>
    )
  }

  const active = serviceId ?? usable[0].id
  const service = usable.find((s) => s.id === active) ?? usable[0]
  const isGroup = GROUP_TABS.some((g) => g.key === section)

  return (
    <div className="stack">
      <div className="section">
        <div className="row wrap">
          <div>
            <label htmlFor="svc">Service</label>
            <select
              id="svc"
              value={service.id}
              onChange={(e) => setServiceId(Number(e.target.value))}
              style={{ width: 'auto' }}
            >
              {usable.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name} ({s.service_type})
                </option>
              ))}
            </select>
          </div>
          <div className="grow">
            <label htmlFor="sec">Configure</label>
            <select
              id="sec"
              value={section}
              onChange={(e) => setSection(e.target.value)}
              style={{ width: 'auto' }}
            >
              <optgroup label="Providers">
                {PROVIDER_TABS.map((t) => (
                  <option key={t.key} value={t.key}>
                    {t.label}
                  </option>
                ))}
              </optgroup>
              <optgroup label="Settings">
                {GROUP_TABS.map((t) => (
                  <option key={t.key} value={t.key}>
                    {t.label}
                  </option>
                ))}
              </optgroup>
            </select>
          </div>
          <a className="btn" href={service.url} target="_blank" rel="noreferrer">
            Open {service.name} ↗
          </a>
        </div>
        <p className="subtle" style={{ marginBottom: 0 }}>
          Options are read live from {service.name}, so everything it supports appears here —
          including anything added by a future update.
        </p>
      </div>

      {isGroup ? (
        <SettingsGroup
          key={`${service.id}-${section}`}
          serviceId={service.id}
          serviceName={service.name}
          group={section}
          title={GROUP_TABS.find((g) => g.key === section)?.label ?? section}
        />
      ) : (
        <ProviderList
          key={`${service.id}-${section}`}
          serviceId={service.id}
          serviceName={service.name}
          resource={section}
          title={PROVIDER_TABS.find((t) => t.key === section)?.label ?? section}
        />
      )}
    </div>
  )
}
