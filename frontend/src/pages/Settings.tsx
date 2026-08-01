/**
 * Settings — the whole admin surface in one place.
 *
 * Services and Users moved in here from the top nav: they're configuration you touch
 * occasionally, not pages you open daily. The nav now leads with what you actually came
 * to look at.
 */

import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import Services from './Services'
import Users from './Users'
import GeneralSettings from './settings/General'
import ConfigResource from './settings/ConfigResource'
import Indexers from './settings/Indexers'
import ServiceConfig from './settings/ServiceConfig'
import Automation from './settings/Automation'

type Tab = {
  key: string
  label: string
  render: () => JSX.Element
}

const TABS: Tab[] = [
  { key: 'general', label: 'General', render: () => <GeneralSettings /> },
  { key: 'services', label: 'Services', render: () => <Services /> },
  { key: 'configure', label: 'Configure services', render: () => <ServiceConfig /> },
  { key: 'automation', label: 'Automation', render: () => <Automation /> },
  { key: 'users', label: 'Users', render: () => <Users /> },
  {
    key: 'profiles',
    label: 'Quality profiles',
    render: () => <ConfigResource resource="quality_profile" title="Quality profiles" />,
  },
  {
    key: 'formats',
    label: 'Custom formats',
    render: () => <ConfigResource resource="custom_format" title="Custom formats" />,
  },
  {
    key: 'folders',
    label: 'Root folders',
    render: () => <ConfigResource resource="root_folder" title="Root folders" nameField="path" />,
  },
  {
    key: 'clients',
    label: 'Download clients',
    render: () => <ConfigResource resource="download_client" title="Download clients" />,
  },
  { key: 'indexers', label: 'Indexers', render: () => <Indexers /> },
  {
    key: 'naming',
    label: 'Naming',
    render: () => <ConfigResource resource="naming" title="Naming" singleton />,
  },
]

export default function Settings() {
  // Tab lives in the URL so a tab can be linked to and survives a refresh.
  const [params, setParams] = useSearchParams()
  const [fallback, setFallback] = useState('general')
  const active = params.get('tab') ?? fallback
  const current = TABS.find((t) => t.key === active) ?? TABS[0]

  const select = (key: string) => {
    setFallback(key)
    setParams({ tab: key }, { replace: true })
  }

  return (
    <>
      <div className="page-head">
        <h1>Settings</h1>
      </div>

      <div className="tabbar">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            className={tab.key === current.key ? 'active' : ''}
            onClick={() => select(tab.key)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div className="tabpanel">{current.render()}</div>
    </>
  )
}
