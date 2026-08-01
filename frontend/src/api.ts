/**
 * API client.
 *
 * Auth is entirely cookie-based (`credentials: 'include'`) — the frontend never holds a
 * token, so there is nothing for XSS to exfiltrate. Bearer tokens exist for scripts, via
 * POST /api/auth/token.
 */

export interface QueueItemT {
  id: number
  service_id: number | null
  service_name: string | null
  title: string
  status: string
  media_title: string | null
  quality: string | null
  size_bytes: number
  size_left_bytes: number
  download_client: string | null
  indexer: string | null
  error_message: string | null
  estimated_completion: string | null
}

export interface HistoryItemT {
  id: number
  event_type: string
  title: string
  media_title: string | null
  quality: string | null
  date: string | null
  source_title: string | null
}

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
  jellyseerr_user_id: number | null
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


// ------------------------------------------------------------- unified views

export type DateKind = 'air' | 'digital' | 'physical' | 'cinema' | 'release'

export interface ServiceFailure {
  service_id: number | null
  service_name: string
  service_type: string
  error: string
}

export interface CalendarEntry {
  service_id: number | null
  service_type: string
  service_name: string
  media_kind: string
  item_id: number
  title: string
  parent_title: string | null
  date: string
  date_kind: DateKind
  season_number: number | null
  episode_number: number | null
  has_file: boolean
  monitored: boolean
  overview: string | null
  runtime_minutes: number | null
  poster: string | null
}

export interface CalendarResponse {
  start: string
  end: string
  entries: CalendarEntry[]
  failures: ServiceFailure[]
}

export interface LibraryItem {
  service_id: number | null
  service_type: string
  service_name: string
  media_kind: string
  item_id: number
  title: string
  sort_title: string | null
  year: number | null
  overview: string | null
  poster: string | null
  status: string | null
  monitored: boolean
  path: string | null
  quality_profile_id: number | null
  size_bytes: number
  added: string | null
  genres: string[]
  runtime_minutes: number | null
  network: string | null
  studio: string | null
  remote_id: string | null
  have_count: number
  total_count: number
}

export interface Episode {
  id: number
  season_number: number
  episode_number: number
  title: string | null
  air_date: string | null
  has_file: boolean
  monitored: boolean
  runtime_minutes: number | null
  size_bytes: number
  overview: string | null
}

export interface Season {
  season_number: number
  monitored: boolean
  episode_count: number
  episode_file_count: number
  size_bytes: number
  episodes: Episode[]
}

export interface LibraryDetail {
  item: LibraryItem
  seasons: Season[]
  native_url: string | null
}

export interface DiscoverResult {
  tmdb_id: number
  media_kind: 'movie' | 'tv'
  title: string
  year: number | null
  overview: string | null
  poster_url: string | null
  backdrop_url: string | null
  vote_average: number | null
  media_status: number | null
  already_requested: boolean
  available: boolean
}

export interface DiscoverPage {
  page: number
  total_pages: number
  total_results: number
  results: DiscoverResult[]
}

export interface MediaRequest {
  id: number
  media_kind: string
  status: number
  title: string | null
  year: number | null
  poster_url: string | null
  tmdb_id: number | null
  requested_by: string | null
  requested_by_id: number | null
  created_at: string | null
  media_status: number | null
}

export interface Capabilities {
  backend: string | null
  available: boolean
  can_request: boolean
  message: string | null
}

export interface JellyseerrUser {
  id: number
  display_name: string
  email: string | null
}

export interface AppSettingRow {
  key: string
  value: unknown
  stored_value: unknown
  source: 'env' | 'file' | 'database' | 'default'
  locked: boolean
  label: string
  help: string
  type: string
  choices?: string[]
  min?: number
  max?: number
}

export interface ConfigResourceInfo {
  key: string
  portability: 'any' | 'same_media_kind'
  note: string
}

export interface ConfigItem {
  service_id: number
  service_name: string
  service_type: string
  media_kind: string | null
  item: Record<string, unknown>
}

export interface FieldDiff {
  field: string
  current: unknown
  proposed: unknown
}

export type SyncAction = 'create' | 'update' | 'identical' | 'incompatible' | 'error'

export interface TargetPlan {
  service_id: number
  service_name: string
  service_type: string
  action: SyncAction
  reason: string | null
  target_item_id: number | null
  changes: FieldDiff[]
}

export interface SyncPreview {
  resource: string
  source_service_id: number
  source_service_name: string
  item_name: string
  targets: TargetPlan[]
}

export interface ApplyResult {
  service_id: number
  service_name: string
  action: SyncAction
  ok: boolean
  detail: string | null
}

export interface IndexerOverview {
  available: boolean
  message?: string
  service_id?: number
  service_name?: string
  native_url?: string
  applications: { id: number; name: string; implementation: string; sync_level: string }[]
  indexers: {
    id: number
    name: string
    implementation: string
    enabled: boolean
    protocol: string | null
    priority: number | null
    stats?: { queries: number; grabs: number; failures: number } | null
  }[]
}

export interface ProviderField {
  name: string
  label?: string
  helpText?: string
  value?: unknown
  type?: string
  privacy?: string
  advanced?: boolean
  selectOptions?: { value: unknown; name: string; hint?: string }[]
}

export interface ProviderRecord {
  id?: number
  name?: string
  implementation?: string
  implementationName?: string
  protocol?: string
  enable?: boolean
  fields?: ProviderField[]
  [k: string]: unknown
}

export interface SweepService {
  service_id: number
  service_name: string
  below_cutoff: number
}

export interface SweepStatus {
  enabled: boolean
  interval_hours: number
  last_run: string | null
  running: boolean
  services: SweepService[]
  last_results: { service_name: string; command: string; ok: boolean; detail: string | null }[]
}

export interface GuardAudit {
  at: string
  service_name: string
  title: string
  action: 'rejected' | 'allowed' | 'failed'
  reason: string
  detail: string | null
}

export interface Release {
  guid: string
  title: string
  indexer: string | null
  indexer_id: number | null
  protocol: string | null
  quality: string | null
  size_bytes: number
  seeders: number | null
  leechers: number | null
  age_hours: number | null
  published: string | null
  rejected: boolean
  rejections: string[]
  download_allowed: boolean
  custom_format_score: number | null
}

export interface ImportCandidate {
  path: string
  name: string
  size_bytes: number
  quality: string | null
  media_title: string | null
  media_id: number | null
  season_number: number | null
  episode_ids: number[]
  rejections: string[]
}

export interface BlocklistItem {
  id: number
  service_id: number | null
  service_name: string | null
  title: string
  media_title: string | null
  quality: string | null
  indexer: string | null
  protocol: string | null
  date: string | null
  message: string | null
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
  createUser: (data: { username: string; password: string; role: Role; jellyseerr_user_id?: number | null }) =>
    request<User>('/api/users', { method: 'POST', ...body(data) }),
  updateUser: (id: number, data: Record<string, unknown>) =>
    request<User>(`/api/users/${id}`, { method: 'PATCH', ...body(data) }),
  deleteUser: (id: number) => request<void>(`/api/users/${id}`, { method: 'DELETE' }),

  // ----------------------------------------------------------- unified views

  calendar: (daysBack = 7, daysForward = 28) =>
    request<CalendarResponse>(
      `/api/calendar?days_back=${daysBack}&days_forward=${daysForward}`,
    ),

  library: (mediaKind?: string) =>
    request<{ items: LibraryItem[]; failures: ServiceFailure[] }>(
      `/api/library${mediaKind ? `?media_kind=${encodeURIComponent(mediaKind)}` : ''}`,
    ),
  libraryItem: (serviceId: number, itemId: number) =>
    request<LibraryDetail>(`/api/library/${serviceId}/${itemId}`),
  setMonitored: (serviceId: number, itemId: number, monitored: boolean) =>
    request<LibraryItem>(`/api/library/${serviceId}/${itemId}/monitor`, {
      method: 'POST',
      ...body({ monitored }),
    }),
  setSeasonMonitored: (
    serviceId: number,
    itemId: number,
    seasonNumber: number,
    monitored: boolean,
  ) =>
    request<LibraryItem>(`/api/library/${serviceId}/${itemId}/season-monitor`, {
      method: 'POST',
      ...body({ season_number: seasonNumber, monitored }),
    }),
  searchItem: (serviceId: number, itemId: number) =>
    request<{ status: string }>(`/api/library/${serviceId}/${itemId}/search`, {
      method: 'POST',
    }),
  deleteItem: (serviceId: number, itemId: number, deleteFiles = false) =>
    request<void>(
      `/api/library/${serviceId}/${itemId}?delete_files=${deleteFiles}`,
      { method: 'DELETE' },
    ),

  queue: () =>
    request<{ items: QueueItemT[]; failures: ServiceFailure[] }>('/api/activity/queue'),
  history: (pageSize = 50) =>
    request<{ items: HistoryItemT[]; failures: ServiceFailure[] }>(
      `/api/activity/history?page_size=${pageSize}`,
    ),
  wanted: () =>
    request<{ items: LibraryItem[]; failures: ServiceFailure[] }>('/api/activity/wanted'),

  discoverCapabilities: () => request<Capabilities>('/api/discover/capabilities'),
  discoverSearch: (q: string, page = 1) =>
    request<DiscoverPage>(
      `/api/discover/search?q=${encodeURIComponent(q)}&page=${page}`,
    ),
  discoverFeed: (kind = 'trending', page = 1) =>
    request<DiscoverPage>(`/api/discover/feed?kind=${kind}&page=${page}`),
  createRequest: (tmdbId: number, mediaKind: 'movie' | 'tv') =>
    request<MediaRequest>('/api/discover/request', {
      method: 'POST',
      ...body({ tmdb_id: tmdbId, media_kind: mediaKind }),
    }),
  requests: (mineOnly = false) =>
    request<MediaRequest[]>(`/api/discover/requests?mine_only=${mineOnly}`),
  decideRequest: (requestId: number, approve: boolean) =>
    request<MediaRequest>(
      `/api/discover/requests/${requestId}/decide?approve=${approve}`,
      { method: 'POST' },
    ),
  jellyseerrUsers: () => request<JellyseerrUser[]>('/api/discover/users'),

  // ------------------------------------------------------- settings & config

  settings: () => request<AppSettingRow[]>('/api/settings'),
  updateSetting: (key: string, value: unknown) =>
    request<AppSettingRow[]>('/api/settings', { method: 'PUT', ...body({ key, value }) }),
  about: () =>
    request<{ version: string; schema_version: number; data_dir: string; config_file: string | null }>(
      '/api/settings/about',
    ),

  configResources: () =>
    request<{ resources: ConfigResourceInfo[] }>('/api/config/resources'),
  configItems: (resource: string) => request<ConfigItem[]>(`/api/config/${resource}`),
  configPreview: (data: {
    resource: string
    source_service_id: number
    item_id?: number
    target_service_ids?: number[]
  }) => request<SyncPreview>('/api/config/preview', { method: 'POST', ...body(data) }),
  configApply: (data: {
    resource: string
    source_service_id: number
    item_id?: number
    target_service_ids: number[]
  }) =>
    request<ApplyResult[]>('/api/config/apply?confirm=true', {
      method: 'POST',
      ...body(data),
    }),

  indexerOverview: () => request<IndexerOverview>('/api/config/indexers/overview'),

  // ------------------------------------------------ per-service provider config

  providerKinds: () =>
    request<{ providers: string[]; settings_groups: string[] }>('/api/providers/kinds'),
  providerSchema: (serviceId: number, resource: string) =>
    request<ProviderRecord[]>(`/api/providers/${serviceId}/${resource}/schema`),
  providers: (serviceId: number, resource: string) =>
    request<ProviderRecord[]>(`/api/providers/${serviceId}/${resource}`),
  createProviderItem: (serviceId: number, resource: string, data: ProviderRecord) =>
    request<ProviderRecord>(`/api/providers/${serviceId}/${resource}`, {
      method: 'POST',
      ...body({ data }),
    }),
  updateProviderItem: (
    serviceId: number,
    resource: string,
    itemId: number,
    data: ProviderRecord,
  ) =>
    request<ProviderRecord>(`/api/providers/${serviceId}/${resource}/${itemId}`, {
      method: 'PUT',
      ...body({ data }),
    }),
  deleteProviderItem: (serviceId: number, resource: string, itemId: number) =>
    request<void>(`/api/providers/${serviceId}/${resource}/${itemId}`, { method: 'DELETE' }),
  testProviderItem: (serviceId: number, resource: string, data: ProviderRecord) =>
    request<{ ok: boolean; message: string }>(
      `/api/providers/${serviceId}/${resource}/test`,
      { method: 'POST', ...body({ data }) },
    ),
  settingsGroup: (serviceId: number, name: string) =>
    request<Record<string, unknown>>(`/api/providers/${serviceId}/settings/${name}`),
  updateSettingsGroup: (serviceId: number, name: string, data: Record<string, unknown>) =>
    request<Record<string, unknown>>(`/api/providers/${serviceId}/settings/${name}`, {
      method: 'PUT',
      ...body({ data }),
    }),

  // ------------------------------------------------------------- automation

  sweepStatus: () => request<SweepStatus>('/api/automation/sweep'),
  runSweep: () =>
    request<{ service_name: string; command: string; ok: boolean; detail: string | null }[]>(
      '/api/automation/sweep/run',
      { method: 'POST' },
    ),
  guardAudit: () => request<GuardAudit[]>('/api/automation/guard/audit'),
  // ------------------------------------------------------------ manual control

  libraryOptions: (serviceId: number) =>
    request<{
      quality_profiles: { id: number; name: string; cutoff_name: string | null; upgrade_allowed: boolean }[]
      root_folders: { id: number; path: string; accessible: boolean; free_space_bytes: number | null }[]
    }>(`/api/library/${serviceId}/options`),
  editItem: (
    serviceId: number,
    itemId: number,
    data: { quality_profile_id?: number; root_folder_path?: string; monitored?: boolean },
  ) =>
    request<LibraryItem>(`/api/library/${serviceId}/${itemId}`, {
      method: 'PATCH',
      ...body(data),
    }),
  lookupMedia: (serviceId: number, term: string) =>
    request<{ title: string; year: number | null; overview: string | null; poster_url: string | null; remote_id: string | null; already_added: boolean }[]>(
      `/api/library/${serviceId}/lookup?term=${encodeURIComponent(term)}`,
    ),
  addMedia: (
    serviceId: number,
    data: { remote_id: string; quality_profile_id: number; root_folder_path: string; monitored?: boolean; search_on_add?: boolean },
  ) =>
    request<{ id: number; title: string }>(`/api/library/${serviceId}/add`, {
      method: 'POST',
      ...body(data),
    }),

  searchReleases: (serviceId: number, itemId: number, episodeId?: number) =>
    request<Release[]>(
      `/api/manual/${serviceId}/releases?item_id=${itemId}` +
        (episodeId ? `&episode_id=${episodeId}` : ''),
    ),
  grabRelease: (serviceId: number, guid: string, indexerId: number) =>
    request<{ status: string }>(`/api/manual/${serviceId}/grab`, {
      method: 'POST',
      ...body({ guid, indexer_id: indexerId }),
    }),
  importCandidates: (serviceId: number, folder: string) =>
    request<ImportCandidate[]>(
      `/api/manual/${serviceId}/import?folder=${encodeURIComponent(folder)}`,
    ),
  doImport: (
    serviceId: number,
    files: { path: string; media_id: number; quality: object; season_number?: number | null; episode_ids?: number[] }[],
    move = true,
  ) =>
    request<{ status: string }>(`/api/manual/${serviceId}/import`, {
      method: 'POST',
      ...body({ files, move }),
    }),
  removeFromQueue: (serviceId: number, queueId: number, blocklist = false) =>
    request<void>(
      `/api/manual/${serviceId}/queue/${queueId}?blocklist=${blocklist}`,
      { method: 'DELETE' },
    ),
  blocklist: () =>
    request<{ items: BlocklistItem[]; failures: ServiceFailure[] }>('/api/manual/blocklist'),
  removeFromBlocklist: (serviceId: number, itemId: number) =>
    request<void>(`/api/manual/${serviceId}/blocklist/${itemId}`, { method: 'DELETE' }),

  guardWebhookUrl: () =>
    request<{ url: string; method: string; note: string }>(
      '/api/automation/guard/webhook-url',
    ),
  testIndexer: (id: number) =>
    request<{ ok: boolean }>(`/api/config/indexers/${id}/test`, { method: 'POST' }),
}

/** Poster URL for an *arr-hosted cover, routed through Mastarr's proxy. */
export function posterUrl(serviceId: number | null, poster: string | null): string | null {
  if (!poster || serviceId === null) return null
  // Jellyseerr posters are already absolute TMDB CDN URLs — never proxy those.
  if (poster.startsWith('http')) return poster
  return `/api/images/${serviceId}/${poster}`
}

/** Jellyseerr's mediaInfo.status vocabulary. */
export const MEDIA_STATUS: Record<number, string> = {
  1: 'Unknown',
  2: 'Pending',
  3: 'Processing',
  4: 'Partially available',
  5: 'Available',
}

export const REQUEST_STATUS: Record<number, string> = {
  1: 'Pending',
  2: 'Approved',
  3: 'Declined',
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
