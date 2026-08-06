/**
 * Typed HTTP client for the IDP Lite API.
 *
 * Every request goes through here so that:
 *   - the Bearer token is attached consistently
 *   - API errors are normalized into a single shape the UI can render
 *
 * The token is set explicitly via setToken() — it's never read from
 * localStorage. It lives only in this module's private field plus
 * AuthContext's React state, both of which are wiped on a full page reload.
 * That's intentional (see hooks/useAuth.tsx).
 *
 * NOTE: these types are hand-mirrored from the Pydantic response
 * models in api/app/schemas/*.py (not generated), so if a backend schema
 * changes, this file needs a matching edit. Two known backend gaps that
 * shape the UI below:
 *   1. EnvironmentResponse only carries team_id / created_by as raw UUIDs
 *      — no team slug or creator username. There's no "resolve a user by
 *      id" endpoint, so the UI can only say "you" (comparing against the
 *      logged-in user) or fall back to a shortened id.
 *   2. There's no "list all users" endpoint — only GET /teams/{id}/members.
 *      Settings' role-management view is therefore team-scoped rather than
 *      a flat user table (see pages/Settings.tsx for how that's handled).
 */

const API_BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

export type Role = 'member' | 'team_admin' | 'super_admin'
export type EnvType = 'dev' | 'staging'
export type EnvStatus =
  | 'PENDING'
  | 'PROVISIONING'
  | 'RUNNING'
  | 'DESTROYING'
  | 'DESTROYED'
  | 'FAILED'
export type HealthStatus = 'HEALTHY' | 'DEGRADED' | 'UNKNOWN'

export interface User {
  id: string
  username: string
  email: string | null
  role: Role
  team_id: string | null
}

export interface ApiKeyResponse {
  api_key: string
  note: string
}

export interface Environment {
  id: string
  name: string
  team_id: string
  created_by: string
  env_type: EnvType
  status: EnvStatus
  ttl_hours: number
  expires_at: string
  aws_region: string
  outputs: Record<string, string> | null
  health_status: HealthStatus
  health_checked_at: string | null
  cost_estimate_usd: number | null
  created_at: string
  destroyed_at: string | null
}

export interface CreateEnvironmentBody {
  name: string
  env_type: EnvType
  ttl_hours: number
  aws_region?: string
}

export interface CreateEnvironmentResult {
  env_id: string
  status: string
}

export interface CostBreakdown {
  ecs_fargate: number
  rds_postgres: number
  cloudwatch_logs: number
  secrets_manager: number
  total_monthly: number
  env_type: string
  note: string
}

export interface RunbookResult {
  content_md: string
  generated_at: string
}

export interface AuditLogEntry {
  id: string
  environment_id: string | null
  actor_id: string | null
  action: string
  actor_type: 'user' | 'system' | 'cron'
  metadata: Record<string, unknown> | null
  created_at: string
}

export interface PaginatedAuditLogs {
  total: number
  page: number
  page_size: number
  items: AuditLogEntry[]
}

export interface AuditQueryParams {
  environment_id?: string
  action?: string
  actor_type?: string
  page?: number
  page_size?: number
}

export interface Team {
  id: string
  name: string
  slug: string
}

export interface CreateTeamBody {
  name: string
  slug: string
}

export interface AddMemberBody {
  github_username: string
  role: Role
}

export class APIError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
    this.name = 'APIError'
  }
}

class APIClient {
  private token: string | null = null

  setToken(token: string | null) {
    this.token = token
  }

  private async request<T>(path: string, opts: RequestInit = {}): Promise<T> {
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      ...(opts.headers as Record<string, string> | undefined),
    }
    if (this.token) {
      headers['Authorization'] = `Bearer ${this.token}`
    }

    const resp = await fetch(`${API_BASE}${path}`, { ...opts, headers })

    if (!resp.ok) {
      const body = await resp.json().catch(() => ({ detail: `HTTP ${resp.status}` }))
      throw new APIError(resp.status, body.detail ?? `HTTP ${resp.status}`)
    }

    if (resp.status === 204) {
      return undefined as T
    }
    return resp.json()
  }

  // --- Auth ---------------------------------------------------------------
  getMe = () => this.request<User>('/auth/me')
  generateApiKey = () => this.request<ApiKeyResponse>('/auth/api-key', { method: 'POST' })

  // --- Environments ---------------------------------------------------------
  listEnvironments = () => this.request<Environment[]>('/environments/')

  getEnvironment = (id: string) => this.request<Environment>(`/environments/${id}`)

  createEnvironment = (body: CreateEnvironmentBody) =>
    this.request<CreateEnvironmentResult>('/environments/', {
      method: 'POST',
      body: JSON.stringify(body),
    })

  destroyEnvironment = (id: string) =>
    this.request<CreateEnvironmentResult>(`/environments/${id}`, { method: 'DELETE' })

  extendTTL = (id: string, extendHours: number) =>
    this.request<{ expires_at: string }>(`/environments/${id}/ttl`, {
      method: 'PATCH',
      body: JSON.stringify({ extend_hours: extendHours }),
    })

  getRunbook = (id: string) => this.request<RunbookResult>(`/environments/${id}/runbook`)

  getCostPreview = (envType: EnvType) =>
    this.request<CostBreakdown>(`/environments/cost-preview?env_type=${envType}`)

  // --- Audit ------------------------------------------------------------
  listAuditLogs = (params: AuditQueryParams = {}) => {
    const qs = new URLSearchParams()
    if (params.environment_id) qs.set('environment_id', params.environment_id)
    if (params.action) qs.set('action', params.action)
    if (params.actor_type) qs.set('actor_type', params.actor_type)
    qs.set('page', String(params.page ?? 1))
    qs.set('page_size', String(params.page_size ?? 50))
    return this.request<PaginatedAuditLogs>(`/audit/?${qs.toString()}`)
  }

  // --- Teams (super_admin for list/create; team_admin+ for members) -------
  listTeams = () => this.request<Team[]>('/teams/')

  createTeam = (body: CreateTeamBody) =>
    this.request<Team>('/teams/', { method: 'POST', body: JSON.stringify(body) })

  listTeamMembers = (teamId: string) => this.request<User[]>(`/teams/${teamId}/members`)

  addTeamMember = (teamId: string, body: AddMemberBody) =>
    this.request<User>(`/teams/${teamId}/members`, {
      method: 'POST',
      body: JSON.stringify(body),
    })

  // --- Users --------------------------------------------------------------
  changeUserRole = (userId: string, role: Role) =>
    this.request<User>(`/users/${userId}/role`, {
      method: 'PATCH',
      body: JSON.stringify({ role }),
    })
}

export const api = new APIClient()