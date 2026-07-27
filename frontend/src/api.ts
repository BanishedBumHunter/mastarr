/**
 * API client.
 *
 * Auth is entirely cookie-based (`credentials: 'include'`) — the frontend never holds a
 * token, so there is nothing for XSS to exfiltrate. Bearer tokens exist for scripts, via
 * POST /api/auth/token.
 */

export type ServiceStatus =
  | 'online'
  | 'degraded'
  | 'unauthorized'
  | 'unreachable'
  | 'unknown'

export type Role = 'admin' | 'requester'

export interface User {
  id: number
  username: string
  role: Role
  is_active: boolean
  created_at: string
}

export interface AuthState {
  needs_setup: boolean
  authenticated: boolean
  user: User | null
}

export interface HealthIssue {
  source: string
  severity: 'ok' | 'notice' | 'warning' | 'error'
  message: string
  wiki_url: string | null
}

export interface DiskSpace {
  path: string
  label: string | null
  free_bytes: number
  total_bytes: number
}

export interface ServiceSnapshot {
  service_id: number | null
  name: string
  service_type: string
  url: string
  status: ServiceStatus
  version: string | null
  app_name: string | null
  error: string | null
  health_issues: HealthIssue[]
  disk_space: DiskSpace[]
  queue_count: number | null
  checked_at: string | null
}

export interface DashboardTotals {
  services: number
  online: number
  degraded: number
  unauthorized: number
  unreachable: number
  unknown: number
  health_issues: number
  queued_items: number
}

export interface Dashboard {
  generated_at: string
  totals: DashboardTotals
  services: ServiceSnapshot[]
}

export interface Service {
  id: number
  name: string
  service_type: string
  url: string
  enabled: boolean
  has_api_key: boolean
  managed_by_config: boolean
  last_status: string | null
  last_version: string | null
  last_checked_at: string | null
}

export interface ServiceType {
  type: string
  display_name: string
  api_version: string
  default_port: number
  manages_media: boolean
  unsupported: string[]
}

export interface Discovered {
  url: string
  host: string
  port: number
  service_type: string | null
  app_name: string | null
  version: string | null
  confirmed: boolean
  reachable: boolean
  needs_api_key: boolean
  already_configured: boolean
  detail: string | null
}

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message)
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    ...init,
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', ...(init.headers ?? {}) },
  })

  if (!response.ok) {
    let detail = `Request failed (${response.status})`
    try {
      const body = await response.json()
      // FastAPI validation errors arrive as an array of objects.
      if (typeof body.detail === 'string') detail = body.detail
      else if (Array.isArray(body.detail)) detail = body.detail[0]?.msg ?? detail
    } catch {
      /* non-JSON error body — keep the generic message */
    }
    throw new ApiError(detail, response.status)
  }

  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

const body = (data: unknown) => ({ body: JSON.stringify(data) })

export const api = {
  authState: () => request<AuthState>('/api/auth/state'),
  setup: (username: string, password: string) =>
    request<User>('/api/auth/setup', { method: 'POST', ...body({ username, password }) }),
  login: (username: string, password: string) =>
    request<User>('/api/auth/login', { method: 'POST', ...body({ username, password }) }),
  logout: () => request<void>('/api/auth/logout', { method: 'POST' }),

  dashboard: (refresh = false) =>
    request<Dashboard>(`/api/dashboard${refresh ? '?refresh=true' : ''}`),

  services: () => request<Service[]>('/api/services'),
  serviceTypes: () => request<ServiceType[]>('/api/services/types'),
  createService: (data: {
    name: string
    service_type: string
    url: string
    api_key?: string
  }) => request<Service>('/api/services', { method: 'POST', ...body(data) }),
  updateService: (id: number, data: Record<string, unknown>) =>
    request<Service>(`/api/services/${id}`, { method: 'PATCH', ...body(data) }),
  deleteService: (id: number) =>
    request<void>(`/api/services/${id}`, { method: 'DELETE' }),

  scan: (hosts: string[]) =>
    request<Discovered[]>('/api/discovery/scan', { method: 'POST', ...body({ hosts }) }),
  identify: (url: string, apiKey: string, serviceType?: string | null) =>
    request<Discovered>('/api/discovery/identify', {
      method: 'POST',
      ...body({ url, api_key: apiKey, service_type: serviceType ?? null }),
    }),

  users: () => request<User[]>('/api/users'),
  createUser: (data: { username: string; password: string; role: Role }) =>
    request<User>('/api/users', { method: 'POST', ...body(data) }),
  updateUser: (id: number, data: Record<string, unknown>) =>
    request<User>(`/api/users/${id}`, { method: 'PATCH', ...body(data) }),
  deleteUser: (id: number) => request<void>(`/api/users/${id}`, { method: 'DELETE' }),

  requestCapabilities: () =>
    request<{ message: string; can_submit: boolean; discovery_available: boolean }>(
      '/api/requests/capabilities',
    ),
}

export function formatBytes(bytes: number): string {
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1)
  return `${(bytes / 1024 ** index).toFixed(index === 0 ? 0 : 1)} ${units[index]}`
}

export const STATUS_LABEL: Record<ServiceStatus, string> = {
  online: 'Online',
  degraded: 'Degraded',
  unauthorized: 'Needs API key',
  unreachable: 'Unreachable',
  unknown: 'Unknown',
}
