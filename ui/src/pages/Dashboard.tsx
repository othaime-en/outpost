import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useEnvironments } from '../hooks/useEnvironments'
import { useAuth } from '../hooks/useAuth'
import { useEnvironmentActions } from '../hooks/useEnvironmentActions'
import { api, type EnvironmentFilters, type Team } from '../api/client'
import EnvironmentCard from '../components/EnvironmentCard'
import EnvironmentFilterBar from '../components/EnvironmentFilterBar'

export default function Dashboard() {
  const { user } = useAuth()
  const [filters, setFilters] = useState<EnvironmentFilters>({})
  const { environments, loading, error, refresh } = useEnvironments(filters)
  const [teams, setTeams] = useState<Team[]>([])
  const actions = useEnvironmentActions(refresh)

  // The team filter dropdown only matters for super_admin (everyone else is
  // already scoped to their own team server-side), so only super_admin pays
  // for the extra request.
  useEffect(() => {
    if (user?.role === 'super_admin') {
      api.listTeams().then(setTeams).catch(() => setTeams([]))
    }
  }, [user?.role])

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="font-display text-2xl font-semibold tracking-tight text-white">
            Environments
          </h1>
          <p className="text-sm text-gray-500">
            {user?.role === 'super_admin' ? 'All teams' : 'Your team'}
          </p>
        </div>
        <Link
          to="/new"
          className="rounded-md bg-cyan-500 px-4 py-2 text-sm font-semibold text-gray-950 hover:bg-cyan-400"
        >
          + New Environment
        </Link>
      </div>

      <EnvironmentFilterBar
        filters={filters}
        onChange={setFilters}
        teams={teams}
        showTeamFilter={user?.role === 'super_admin'}
      />

      {loading && <p className="text-sm text-gray-500">Loading environments…</p>}

      {error && !loading && (
        <div className="rounded-lg border border-red-900 bg-red-950/40 p-4 text-sm text-red-300">
          {error}
        </div>
      )}

      {!loading && !error && environments.length === 0 && (
        <div className="rounded-xl border border-dashed border-gray-800 p-12 text-center">
          <p className="mb-4 text-gray-400">
            {Object.keys(filters).length > 0
              ? 'No environments match these filters.'
              : 'No environments yet.'}
          </p>
          <Link to="/new" className="text-cyan-400 hover:underline text-sm">
            Provision your first environment →
          </Link>
        </div>
      )}

      {!loading && !error && environments.length > 0 && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {environments.map((env) => (
            <EnvironmentCard
              key={env.id}
              env={env}
              onDestroy={actions.promptDestroy}
              onExtend={actions.promptExtend}
            />
          ))}
        </div>
      )}

      {actions.modals()}
    </div>
  )
}