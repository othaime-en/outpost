import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useEnvironments } from '../hooks/useEnvironments'
import { useAuth } from '../hooks/useAuth'
import { api, APIError, type Environment, type EnvironmentFilters, type Team } from '../api/client'
import EnvironmentCard from '../components/EnvironmentCard'
import EnvironmentFilterBar from '../components/EnvironmentFilterBar'
import Modal from '../components/Modal'
import Toast, { type ToastState } from '../components/Toast'

export default function Dashboard() {
  const { user } = useAuth()
  const [filters, setFilters] = useState<EnvironmentFilters>({})
  const { environments, loading, error, refresh } = useEnvironments(filters)
  const [teams, setTeams] = useState<Team[]>([])
  const [destroyTarget, setDestroyTarget] = useState<Environment | null>(null)
  const [extendTarget, setExtendTarget] = useState<Environment | null>(null)
  const [extendHours, setExtendHours] = useState(24)
  const [busy, setBusy] = useState(false)
  const [toast, setToast] = useState<ToastState | null>(null)

  // The team filter dropdown only matters for super_admin (everyone else is
  // already scoped to their own team server-side), so only super_admin pays
  // for the extra request.
  useEffect(() => {
    if (user?.role === 'super_admin') {
      api.listTeams().then(setTeams).catch(() => setTeams([]))
    }
  }, [user?.role])

  async function confirmDestroy() {
    if (!destroyTarget) return
    setBusy(true)
    try {
      await api.destroyEnvironment(destroyTarget.id)
      setToast({ kind: 'success', message: `Destroying ${destroyTarget.name}…` })
      setDestroyTarget(null)
      refresh()
    } catch (err) {
      setToast({ kind: 'error', message: err instanceof APIError ? err.message : 'Destroy failed' })
    } finally {
      setBusy(false)
    }
  }

  async function confirmExtend() {
    if (!extendTarget) return
    setBusy(true)
    try {
      await api.extendTTL(extendTarget.id, extendHours)
      setToast({ kind: 'success', message: `Extended ${extendTarget.name} by ${extendHours}h` })
      setExtendTarget(null)
      refresh()
    } catch (err) {
      setToast({ kind: 'error', message: err instanceof APIError ? err.message : 'Extend failed' })
    } finally {
      setBusy(false)
    }
  }

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
              onDestroy={setDestroyTarget}
              onExtend={(e) => {
                setExtendHours(24)
                setExtendTarget(e)
              }}
            />
          ))}
        </div>
      )}

      {destroyTarget && (
        <Modal title={`Destroy ${destroyTarget.name}?`} onClose={() => setDestroyTarget(null)}>
          <p className="mb-5 text-sm text-gray-400">
            This tears down all AWS resources for this environment. The environment record and its
            audit trail are kept — this cannot be undone.
          </p>
          <div className="flex justify-end gap-2">
            <button
              onClick={() => setDestroyTarget(null)}
              className="rounded-md px-3 py-1.5 text-sm text-gray-400 hover:text-white"
            >
              Cancel
            </button>
            <button
              onClick={confirmDestroy}
              disabled={busy}
              className="rounded-md bg-red-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-red-500 disabled:opacity-50"
            >
              {busy ? 'Destroying…' : 'Destroy'}
            </button>
          </div>
        </Modal>
      )}

      {extendTarget && (
        <Modal title={`Extend TTL — ${extendTarget.name}`} onClose={() => setExtendTarget(null)}>
          <label className="mb-1 block text-xs text-gray-500">Extend by (hours)</label>
          <input
            type="number"
            min={1}
            max={168}
            value={extendHours}
            onChange={(e) => setExtendHours(Number(e.target.value))}
            className="mb-5 w-full rounded-md border border-gray-800 bg-gray-950 px-3 py-2 text-sm text-white
                       focus:border-cyan-600 focus:outline-none"
          />
          <div className="flex justify-end gap-2">
            <button
              onClick={() => setExtendTarget(null)}
              className="rounded-md px-3 py-1.5 text-sm text-gray-400 hover:text-white"
            >
              Cancel
            </button>
            <button
              onClick={confirmExtend}
              disabled={busy || extendHours < 1}
              className="rounded-md bg-amber-500 px-3 py-1.5 text-sm font-semibold text-gray-950 hover:bg-amber-400 disabled:opacity-50"
            >
              {busy ? 'Extending…' : 'Extend'}
            </button>
          </div>
        </Modal>
      )}

      <Toast toast={toast} onDismiss={() => setToast(null)} />
    </div>
  )
}