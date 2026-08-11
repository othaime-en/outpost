import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'
import { api, APIError, type Role, type TeamDetail as TeamDetailData } from '../api/client'
import StatusBadge from '../components/StatusBadge'
import HealthIndicator from '../components/HealthIndicator'
import CostBadge from '../components/CostBadge'
import { formatRelativeTime, shortId } from '../lib/format'

const ROLES: Role[] = ['member', 'team_admin', 'super_admin']

export default function TeamDetail() {
  const { id } = useParams<{ id: string }>()
  const { user } = useAuth()
  const [team, setTeam] = useState<TeamDetailData | null>(null)
  const [error, setError] = useState<string | null>(null)

  function load() {
    if (!id) return
    api
      .getTeam(id)
      .then(setTeam)
      .catch((err) => setError(err instanceof APIError ? err.message : 'Failed to load team'))
  }

  useEffect(load, [id])

  if (error) {
    return (
      <div className="rounded-lg border border-red-900 bg-red-950/40 p-4 text-sm text-red-300">
        {error}
      </div>
    )
  }
  if (!team) {
    return <p className="text-sm text-gray-500">Loading team…</p>
  }

  const canManageMembers = user?.role === 'super_admin' || (user?.role === 'team_admin' && user.team_id === team.id)

  return (
    <div className="space-y-8">
      <div>
        <h1 className="font-display text-2xl font-semibold tracking-tight text-white">{team.name}</h1>
        <p className="font-mono text-sm text-gray-500">{team.slug}</p>
      </div>

      {/* Overview */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <Stat label="Members" value={String(team.members.length)} />
        <Stat label="Active environments" value={String(team.active_environment_count)} />
        <Stat label="Est. monthly cost" value={`$${team.estimated_monthly_cost_usd.toFixed(2)}`} />
        <Stat label="Created" value={formatRelativeTime(team.created_at)} />
      </div>

      {/* Members */}
      <section>
        <h2 className="mb-3 font-mono text-xs uppercase tracking-wide text-cyan-400">Members</h2>
        <div className="rounded-xl border border-gray-800 bg-gray-900 p-5">
          <table className="w-full text-sm">
            <tbody>
              {team.members.map((m) => (
                <tr key={m.id} className="border-b border-gray-800 last:border-0">
                  <td className="py-2 font-mono text-gray-200">{m.username}</td>
                  <td className="py-2 text-gray-500">{m.email ?? '—'}</td>
                  <td className="py-2 text-right text-xs text-gray-500 uppercase">{m.role}</td>
                </tr>
              ))}
              {team.members.length === 0 && (
                <tr>
                  <td className="py-3 text-gray-600">No members yet.</td>
                </tr>
              )}
            </tbody>
          </table>

          {canManageMembers && <AddMemberForm teamId={team.id} onAdded={load} />}
        </div>
      </section>

      {/* Environments */}
      <section>
        <h2 className="mb-3 font-mono text-xs uppercase tracking-wide text-cyan-400">Environments</h2>
        <div className="rounded-xl border border-gray-800 bg-gray-900">
          {team.environments.length === 0 && (
            <p className="p-5 text-sm text-gray-600">No environments for this team yet.</p>
          )}
          {team.environments.map((env) => (
            <Link
              key={env.id}
              to={`/environments/${env.id}`}
              className="flex items-center justify-between gap-3 border-b border-gray-800 px-5 py-3 text-sm last:border-0 hover:bg-gray-800/50"
            >
              <div className="flex min-w-0 items-center gap-2">
                <HealthIndicator status={env.health_status} />
                <span className="truncate font-mono text-gray-200">{env.name}</span>
                <span className="font-mono text-xs text-gray-600">{shortId(env.id)}</span>
              </div>
              <div className="flex items-center gap-3">
                <span className="hidden font-mono text-xs uppercase text-gray-500 sm:inline">{env.env_type}</span>
                <CostBadge costUsd={env.cost_estimate_usd} />
                <StatusBadge status={env.status} />
              </div>
            </Link>
          ))}
        </div>
      </section>
    </div>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900 p-4">
      <div className="text-xs text-gray-500">{label}</div>
      <div className="mt-1 font-mono text-lg font-semibold text-white">{value}</div>
    </div>
  )
}

function AddMemberForm({ teamId, onAdded }: { teamId: string; onAdded: () => void }) {
  const { user } = useAuth()
  const [username, setUsername] = useState('')
  const [role, setRole] = useState<Role>('member')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const assignableRoles = user?.role === 'super_admin' ? ROLES : ROLES.filter((r) => r !== 'super_admin')

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await api.addTeamMember(teamId, { github_username: username, role })
      setUsername('')
      setRole('member')
      onAdded()
    } catch (err) {
      setError(err instanceof APIError ? err.message : 'Failed to add member')
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit} className="mt-5 flex flex-wrap items-end gap-3 border-t border-gray-800 pt-5">
      {error && <p className="w-full text-sm text-red-400">{error}</p>}
      <div>
        <label className="mb-1 block text-xs text-gray-500">GitHub username</label>
        <input
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          placeholder="octocat"
          className="rounded-md border border-gray-800 bg-gray-950 px-3 py-1.5 text-sm text-white
                     placeholder-gray-600 focus:border-cyan-600 focus:outline-none"
        />
      </div>
      <div>
        <label className="mb-1 block text-xs text-gray-500">Role</label>
        <select
          value={role}
          onChange={(e) => setRole(e.target.value as Role)}
          className="rounded-md border border-gray-800 bg-gray-950 px-3 py-1.5 text-sm text-white focus:border-cyan-600 focus:outline-none"
        >
          {assignableRoles.map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </select>
      </div>
      <button
        type="submit"
        disabled={busy || !username}
        className="rounded-md bg-cyan-500 px-4 py-1.5 text-sm font-semibold text-gray-950 hover:bg-cyan-400 disabled:opacity-50"
      >
        Add Member
      </button>
    </form>
  )
}