/** Shared presentational pieces. */

import type { ReactNode } from 'react'
import { STATUS_LABEL, formatBytes } from './api'
import type { DiskSpace, HealthIssue, ServiceFailure, ServiceStatus } from './api'

export function StatusBadge({ status }: { status: ServiceStatus }) {
  return <span className={`badge ${status}`}>{STATUS_LABEL[status]}</span>
}

export function Spinner({ label }: { label?: string }) {
  return (
    <span className="row subtle">
      <span className="spinner" /> {label}
    </span>
  )
}

export function ErrorBox({ children }: { children: ReactNode }) {
  return <div className="error-box">{children}</div>
}

export function Stat({
  value,
  label,
  tone,
}: {
  value: number | string
  label: string
  tone?: 'ok' | 'warn' | 'danger'
}) {
  return (
    <div className="stat">
      <div className={`stat-value ${tone ?? ''}`}>{value}</div>
      <div className="stat-label">{label}</div>
    </div>
  )
}

export function HealthList({ issues }: { issues: HealthIssue[] }) {
  if (!issues.length) return null
  return (
    <ul className="issues">
      {issues.map((issue, index) => (
        <li key={index} className={`issue ${issue.severity}`}>
          <span className="sev">{issue.severity}</span>
          <span className="grow">
            {issue.message}{' '}
            {issue.wiki_url ? (
              <a href={issue.wiki_url} target="_blank" rel="noreferrer">
                docs
              </a>
            ) : null}
          </span>
        </li>
      ))}
    </ul>
  )
}

export function DiskBar({ disk }: { disk: DiskSpace }) {
  const used = Math.max(disk.total_bytes - disk.free_bytes, 0)
  const percent = disk.total_bytes > 0 ? (used / disk.total_bytes) * 100 : 0
  const tone = percent >= 90 ? 'danger' : percent >= 75 ? 'warn' : ''

  return (
    <div className="disk">
      <div className="disk-head">
        <span className="disk-path">{disk.label || disk.path}</span>
        <span>
          {formatBytes(disk.free_bytes)} free of {formatBytes(disk.total_bytes)}
        </span>
      </div>
      <div className="bar">
        <div className={`bar-fill ${tone}`} style={{ width: `${Math.min(percent, 100)}%` }} />
      </div>
    </div>
  )
}

export function Empty({
  title,
  children,
}: {
  title: string
  children?: ReactNode
}) {
  return (
    <div className="empty">
      <h2>{title}</h2>
      <div className="subtle">{children}</div>
    </div>
  )
}

export function PartialWarning({ failures }: { failures: ServiceFailure[] }) {
  /**
   * Says which service is missing from an aggregated view.
   *
   * Silently showing partial data would be worse than an error: the user would believe
   * their library really is that small, or that nothing is scheduled.
   */
  if (!failures.length) return null
  return (
    <div className="hint-box" style={{ marginBottom: 14 }}>
      <b>Showing partial results.</b>{' '}
      {failures.map((f) => `${f.service_name} (${f.error})`).join(' · ')}
    </div>
  )
}

export function ProgressBar({
  value,
  total,
  label,
}: {
  value: number
  total: number
  label?: string
}) {
  const percent = total > 0 ? Math.min((value / total) * 100, 100) : 0
  const tone = percent >= 100 ? '' : percent > 0 ? 'warn' : 'danger'
  return (
    <div className="disk">
      <div className="disk-head">
        <span>{label ?? `${value}/${total}`}</span>
        <span>{Math.round(percent)}%</span>
      </div>
      <div className="bar">
        <div className={`bar-fill ${tone}`} style={{ width: `${percent}%` }} />
      </div>
    </div>
  )
}
