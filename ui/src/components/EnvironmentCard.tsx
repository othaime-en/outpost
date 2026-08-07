import { Link } from 'react-router-dom'
import type { Environment } from '../api/client'
import StatusBadge from './StatusBadge'
import HealthIndicator from './HealthIndicator'
import CostBadge from './CostBadge'
import TTLCountdown from './TTLCountdown'
import { formatRelativeTime, shortId } from '../lib/format'

const DESTROYABLE = new Set(['RUNNING', 'FAILED'])

interface EnvironmentCardProps {
  env: Environment
  onDestroy: (env: Environment) => void
  onExtend: (env: Environment) => void
}

export default function EnvironmentCard({ env, onDestroy, onExtend }: EnvironmentCardProps) {
  const canDestroy = DESTROYABLE.has(env.status)
  const canExtend = env.status === 'RUNNING'

  return (
    <div className="flex flex-col gap-3 rounded-xl border border-gray-800 bg-gray-900 p-4">
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <HealthIndicator status={env.health_status} />
          <Link
            to={`/environments/${env.id}`}
            className="truncate font-mono text-base font-semibold text-white hover:text-cyan-400"
            title={env.name}
          >
            {env.name}
          </Link>
        </div>
        <StatusBadge status={env.status} />
      </div>

      <div className="flex items-center gap-2 text-xs text-gray-500">
        <span className="rounded bg-gray-800 px-1.5 py-0.5 font-mono uppercase tracking-wide">
          {env.env_type}
        </span>
        <span className="font-mono">{env.team_slug}</span>
        <span title={env.id} className="font-mono text-gray-600">
          {shortId(env.id)}
        </span>
      </div>

      <div className="flex items-center justify-between text-sm">
        <div className="flex flex-col gap-0.5">
          <span className="text-xs text-gray-500">
            {env.status === 'DESTROYED' ? 'destroyed' : 'expires in'}
          </span>
          {env.status === 'DESTROYED' ? (
            <span className="font-mono text-sm text-gray-500">—</span>
          ) : (
            <TTLCountdown expiresAt={env.expires_at} />
          )}
        </div>
        <div className="flex flex-col items-end gap-0.5">
          <span className="text-xs text-gray-500">est. cost</span>
          <CostBadge costUsd={env.cost_estimate_usd} />
        </div>
      </div>

      <div className="text-xs text-gray-600">
        Created by <span className="text-gray-400">@{env.created_by_username}</span> ·{' '}
        {formatRelativeTime(env.created_at)}
      </div>

      <div className="mt-1 flex items-center gap-2 border-t border-gray-800 pt-3">
        <button
          onClick={() => onDestroy(env)}
          disabled={!canDestroy}
          className="flex-1 rounded-md border border-red-900 px-2 py-1.5 text-xs font-semibold text-red-400
                     hover:bg-red-950 disabled:cursor-not-allowed disabled:border-gray-800 disabled:text-gray-700"
        >
          Destroy
        </button>
        <button
          onClick={() => onExtend(env)}
          disabled={!canExtend}
          className="flex-1 rounded-md border border-amber-900 px-2 py-1.5 text-xs font-semibold text-amber-400
                     hover:bg-amber-950 disabled:cursor-not-allowed disabled:border-gray-800 disabled:text-gray-700"
        >
          Extend TTL
        </button>
        <Link
          to={`/environments/${env.id}`}
          className="flex-1 rounded-md border border-cyan-900 px-2 py-1.5 text-center text-xs font-semibold text-cyan-400
                     hover:bg-cyan-950"
        >
          Details
        </Link>
      </div>
    </div>
  )
}