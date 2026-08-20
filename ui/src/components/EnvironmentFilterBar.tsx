import type { EnvironmentFilters, EnvStatus, EnvType, HealthStatus, Team } from '../api/client'

const STATUS_OPTIONS: EnvStatus[] = ['PENDING', 'PROVISIONING', 'RUNNING', 'DESTROYING', 'FAILED']
const EXPIRY_OPTIONS: { label: string; hours: number | undefined }[] = [
  { label: 'Any time', hours: undefined },
  { label: '< 2h', hours: 2 },
  { label: '< 24h', hours: 24 },
  { label: 'This week', hours: 168 },
]
const SORT_OPTIONS: { label: string; sortBy: EnvironmentFilters['sortBy']; sortDir: EnvironmentFilters['sortDir'] }[] = [
  { label: 'Newest first', sortBy: 'created_at', sortDir: 'desc' },
  { label: 'Oldest first', sortBy: 'created_at', sortDir: 'asc' },
  { label: 'Expiring soonest', sortBy: 'expires_at', sortDir: 'asc' },
  { label: 'Most expensive', sortBy: 'cost_estimate_usd', sortDir: 'desc' },
  { label: 'Least expensive', sortBy: 'cost_estimate_usd', sortDir: 'asc' },
]

interface EnvironmentFilterBarProps {
  filters: EnvironmentFilters
  onChange: (filters: EnvironmentFilters) => void
  teams: Team[]
  showTeamFilter: boolean
}

function chipClass(active: boolean) {
  return `rounded-md border px-2.5 py-1 text-xs font-mono transition-colors ${
    active
      ? 'border-cyan-300 bg-cyan-50 text-cyan-700 dark:border-cyan-700 dark:bg-cyan-950 dark:text-cyan-300'
      : 'border-gray-200 text-gray-600 hover:border-gray-300 hover:text-gray-900 dark:border-gray-800 dark:text-gray-400 dark:hover:border-gray-700 dark:hover:text-gray-200'
  }`
}

export default function EnvironmentFilterBar({
  filters,
  onChange,
  teams,
  showTeamFilter,
}: EnvironmentFilterBarProps) {
  const statuses = filters.status ?? []

  function toggleStatus(s: EnvStatus) {
    const next = statuses.includes(s) ? statuses.filter((x) => x !== s) : [...statuses, s]
    onChange({ ...filters, status: next.length ? next : undefined })
  }

  function toggleEnvType(t: EnvType) {
    onChange({ ...filters, envType: filters.envType === t ? undefined : t })
  }

  const currentSort = SORT_OPTIONS.find(
    (o) => o.sortBy === (filters.sortBy ?? 'created_at') && o.sortDir === (filters.sortDir ?? 'desc')
  )

  const hasNonDefaultFilters =
    statuses.length > 0 ||
    !!filters.envType ||
    !!filters.healthStatus ||
    !!filters.expiringWithinHours ||
    !!filters.includeDestroyed ||
    !!filters.createdByMe ||
    !!filters.teamId

  return (
    <div className="mb-6 flex flex-wrap items-center gap-x-6 gap-y-3 rounded-xl border border-gray-200 bg-gray-50 dark:border-gray-800 dark:bg-gray-900/60 p-4">
      {/* Status chips */}
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="mr-1 text-xs text-gray-500 dark:text-gray-500">Status</span>
        {STATUS_OPTIONS.map((s) => (
          <button key={s} onClick={() => toggleStatus(s)} className={chipClass(statuses.includes(s))}>
            {s}
          </button>
        ))}
      </div>

      {/* Env type chips */}
      <div className="flex items-center gap-1.5">
        <span className="mr-1 text-xs text-gray-500 dark:text-gray-500">Type</span>
        {(['dev', 'staging'] as EnvType[]).map((t) => (
          <button key={t} onClick={() => toggleEnvType(t)} className={chipClass(filters.envType === t)}>
            {t}
          </button>
        ))}
      </div>

      {/* Health dropdown */}
      <div className="flex items-center gap-1.5">
        <span className="text-xs text-gray-500 dark:text-gray-500">Health</span>
        <select
          value={filters.healthStatus ?? ''}
          onChange={(e) =>
            onChange({ ...filters, healthStatus: (e.target.value || undefined) as HealthStatus | undefined })
          }
          className="rounded-md border border-gray-200 bg-white dark:border-gray-800 dark:bg-gray-950 px-2 py-1 text-xs text-gray-700 dark:text-gray-300 focus:border-cyan-600 focus:outline-none"
        >
          <option value="">Any</option>
          <option value="HEALTHY">Healthy</option>
          <option value="DEGRADED">Degraded</option>
          <option value="UNKNOWN">Unknown</option>
        </select>
      </div>

      {/* Expiry quick filters */}
      <div className="flex items-center gap-1.5">
        <span className="mr-1 text-xs text-gray-500 dark:text-gray-500">Expires</span>
        {EXPIRY_OPTIONS.map((opt) => (
          <button
            key={opt.label}
            onClick={() => onChange({ ...filters, expiringWithinHours: opt.hours })}
            className={chipClass(filters.expiringWithinHours === opt.hours)}
          >
            {opt.label}
          </button>
        ))}
      </div>

      {/* Team dropdown — shown for super_admin or anyone on 2+ teams (see
          Dashboard.tsx's showTeamFilter for the multi-team migration note) */}
      {showTeamFilter && (
        <div className="flex items-center gap-1.5">
          <span className="text-xs text-gray-500 dark:text-gray-500">Team</span>
          <select
            value={filters.teamId ?? ''}
            onChange={(e) => onChange({ ...filters, teamId: e.target.value || undefined })}
            className="rounded-md border border-gray-200 bg-white dark:border-gray-800 dark:bg-gray-950 px-2 py-1 text-xs text-gray-700 dark:text-gray-300 focus:border-cyan-600 focus:outline-none"
          >
            <option value="">All teams</option>
            {teams.map((t) => (
              <option key={t.id} value={t.id}>
                {t.slug}
              </option>
            ))}
          </select>
        </div>
      )}

      <div className="ml-auto flex items-center gap-4">
        {/* Toggles */}
        <label className="flex cursor-pointer items-center gap-1.5 text-xs text-gray-600 dark:text-gray-400">
          <input
            type="checkbox"
            checked={!!filters.createdByMe}
            onChange={(e) => onChange({ ...filters, createdByMe: e.target.checked || undefined })}
            className="rounded border-gray-300 bg-white dark:border-gray-700 dark:bg-gray-950 text-cyan-600 dark:text-cyan-500 focus:ring-cyan-600"
          />
          Created by me
        </label>
        <label className="flex cursor-pointer items-center gap-1.5 text-xs text-gray-600 dark:text-gray-400">
          <input
            type="checkbox"
            checked={!!filters.includeDestroyed}
            disabled={statuses.length > 0}
            onChange={(e) => onChange({ ...filters, includeDestroyed: e.target.checked || undefined })}
            className="rounded border-gray-300 bg-white dark:border-gray-700 dark:bg-gray-950 text-cyan-600 dark:text-cyan-500 focus:ring-cyan-600 disabled:opacity-40"
          />
          Show destroyed
        </label>

        {/* Sort */}
        <select
          value={currentSort?.label}
          onChange={(e) => {
            const opt = SORT_OPTIONS.find((o) => o.label === e.target.value)
            if (opt) onChange({ ...filters, sortBy: opt.sortBy, sortDir: opt.sortDir })
          }}
          className="rounded-md border border-gray-200 bg-white dark:border-gray-800 dark:bg-gray-950 px-2 py-1 text-xs text-gray-700 dark:text-gray-300 focus:border-cyan-600 focus:outline-none"
        >
          {SORT_OPTIONS.map((o) => (
            <option key={o.label} value={o.label}>
              {o.label}
            </option>
          ))}
        </select>

        {hasNonDefaultFilters && (
          <button onClick={() => onChange({})} className="text-xs text-gray-500 underline hover:text-gray-700 dark:hover:text-gray-300">
            Clear filters
          </button>
        )}
      </div>
    </div>
  )
}