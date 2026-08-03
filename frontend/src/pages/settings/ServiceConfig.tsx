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
import QualityProfileEditor from './QualityProfileEditor'
import QualityDefinitions from './QualityDefinitions'
import CustomFormatEditor from './CustomFormatEditor'
import RootFolders from './RootFolders'
import ListEditor from './ListEditor'

const PROVIDER_TABS: { key: string; label: string }[] = [
  { key: 'download_client', label: 'Download clients' },
  { key: 'indexer', label: 'Indexers' },
  { key: 'import_list', label: 'Import lists' },
  { key: 'notification', label: 'Notifications' },
  { key: 'metadata', label: 'Metadata' },
]

const GROUP_TABS: { key: string; label: string }[] = [
  { key: 'indexer_options', label: 'Grab rules' },
  { key: 'download_client_options', label: 'Download handling' },
  { key: 'media_management', label: 'Media management' },
  { key: 'naming', label: 'Naming' },
  { key: 'host', label: 'General / host' },
  { key: 'ui', label: 'UI preferences' },
]

// Purpose-built editors — these have shapes a generic renderer can't do justice to.
const CUSTOM_TABS: { key: string; label: string }[] = [
  { key: 'quality_profile', label: 'Quality profiles' },
  { key: 'quality_definition', label: 'Quality sizes' },
  { key: 'custom_format', label: 'Custom formats' },
  { key: 'root_folder', label: 'Root folders' },
]

// Flat lists the generic editor handles. `blank` seeds an Add when the list is empty.
const LIST_TABS: { key: string; label: string; blank?: Record<string, unknown> }[] = [
  { key: 'tag', label: 'Tags', blank: { label: '' } },
  { key: 'delay_profile', label: 'Delay profiles' },
  { key: 'release_profile', label: 'Release profiles' },
  {
    key: 'remote_path_mapping',
    label: 'Remote path mappings',
    blank: { host: '', remotePath: '', localPath: '' },
  },
  { key: 'import_list_exclusion', label: 'Import list exclusions' },
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
  const custom = CUSTOM_TABS.find((c) => c.key === section)
  const list = LIST_TABS.find((l) => l.key === section)

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
              <optgroup label="Quality & profiles">
                {CUSTOM_TABS.map((t) => (
                  <option key={t.key} value={t.key}>
                    {t.label}
                  </option>
                ))}
              </optgroup>
              <optgroup label="Lists">
                {LIST_TABS.map((t) => (
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

      {custom ? (
        section === 'quality_profile' ? (
          <QualityProfileEditor key={service.id} serviceId={service.id} serviceName={service.name} />
        ) : section === 'quality_definition' ? (
          <QualityDefinitions key={service.id} serviceId={service.id} serviceName={service.name} />
        ) : section === 'custom_format' ? (
          <CustomFormatEditor key={service.id} serviceId={service.id} serviceName={service.name} />
        ) : (
          <RootFolders key={service.id} serviceId={service.id} serviceName={service.name} />
        )
      ) : list ? (
        <ListEditor
          key={`${service.id}-${list.key}`}
          serviceId={service.id}
          serviceName={service.name}
          resource={list.key}
          title={list.label}
          blank={list.blank}
        />
      ) : isGroup ? (
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
