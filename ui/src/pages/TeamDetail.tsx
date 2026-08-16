import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'
import { isSuperAdmin } from '../lib/permissions'
import { api, APIError, type TeamRole, type TeamDetail as TeamDetailData, type TeamMember } from '../api/client'
import StatusBadge from '../components/StatusBadge'
import HealthIndicator from '../components/HealthIndicator'
import CostBadge from '../components/CostBadge'
import Modal from '../components/Modal'
import Toast, { type ToastState } from '../components/Toast'
import { formatRelativeTime, shortId } from '../lib/format'

// MULTI-TEAM CHANGE: 'super_admin' is no longer a valid team-scoped role at
// all — TeamMembership.role is DB-constrained to member|team_admin on the
// backend, and AddMemberRequest/UpdateMemberRoleRequest reject anything
// else at the schema layer (422).
const TEAM_ROLES: TeamRole[] = ['member', 'team_admin']

export default function TeamDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { user } = useAuth()
  const [team, setTeam] = useState<TeamDetailData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [toast, setToast] = useState<ToastState | null>(null)
  const [removeTarget, setRemoveTarget] = useState<TeamMember | null>(null)
  const [showDeleteTeam, setShowDeleteTeam] = useState(false)
  const [busy, setBusy] = useState(false)

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
      <div>
        <BackLink />
        <div className="rounded-lg border border-red-900 bg-red-950/40 p-4 text-sm text-red-300">
          {error}
        </div>
      </div>
    )
  }
  if (!team) {
    return <p className="text-sm text-gray-500">Loading team…</p>
  }


  const myMembership = team.members.find((m) => m.id === user?.id)
  const canManageMembers = isSuperAdmin(user) || myMembership?.team_role === 'team_admin'
  const canDeleteTeam = canManageMembers // same scoping: team_admin (own team) / super_admin (any)
  const blockingEnvironments = team.environments.filter((e) => e.status !== 'DESTROYED')

  async function promoteToAdmin(memberId: string) {
    if (!team) return
    setBusy(true)
    try {
      await api.updateMemberRole(team.id, memberId, 'team_admin')
      setToast({ kind: 'success', message: 'Promoted to team_admin' })
      load()
    } catch (err) {
      setToast({ kind: 'error', message: err instanceof APIError ? err.message : 'Failed to promote' })
    } finally {
      setBusy(false)
    }
  }

  async function confirmRemove() {
    if (!team || !removeTarget) return
    setBusy(true)
    try {
      await api.removeTeamMember(team.id, removeTarget.id)
      setToast({
        kind: 'success',
        message: removeTarget.id === user?.id ? 'You left the team' : `Removed @${removeTarget.username}`,
      })
      setRemoveTarget(null)
      if (removeTarget.id === user?.id) {
        // Leaving this team — Teams.tsx re-fetches listTeams() fresh on its
        // own mount, so no AuthContext refresh is needed here either.
        navigate('/teams')
      } else {
        load()
      }
    } catch (err) {
      setToast({ kind: 'error', message: err instanceof APIError ? err.message : 'Failed to remove member' })
    } finally {
      setBusy(false)
    }
  }

  async function confirmDeleteTeam() {
    if (!team) return
    setBusy(true)
    try {
      await api.deleteTeam(team.id)
      navigate('/teams')
    } catch (err) {
      setToast({ kind: 'error', message: err instanceof APIError ? err.message : 'Failed to delete team' })
      setBusy(false)
    }
  }

  return (
    <div className="space-y-8">
      <BackLink />

      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="font-display text-2xl font-semibold tracking-tight text-white">{team.name}</h1>
          <p className="font-mono text-sm text-gray-500">{team.slug}</p>
        </div>
        {canDeleteTeam && (
          <button
            onClick={() => setShowDeleteTeam(true)}
            className="rounded-md border border-red-900 px-3 py-1.5 text-xs font-semibold text-red-400 hover:bg-red-950"
          >
            Delete Team
          </button>
        )}
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
              {team.members.map((m) => {
                const isSelf = m.id === user?.id
                const canRemoveThis = isSelf || canManageMembers
                const canPromoteThis = canManageMembers && m.team_role === 'member'
                return (
                  <tr key={m.id} className="border-b border-gray-800 last:border-0">
                    <td className="py-2 font-mono text-gray-200">
                      {m.username}
                      {isSelf && <span className="ml-2 text-xs text-gray-600">(you)</span>}
                    </td>
                    <td className="py-2 text-gray-500">{m.email ?? '—'}</td>
                    <td className="py-2 text-right text-xs text-gray-500 uppercase">{m.team_role}</td>
                    <td className="py-2 pl-4 text-right">
                      <div className="flex justify-end gap-2">
                        {canPromoteThis && (
                          <button
                            onClick={() => promoteToAdmin(m.id)}
                            disabled={busy}
                            className="text-xs text-cyan-400 hover:underline disabled:opacity-50"
                          >
                            Promote
                          </button>
                        )}
                        {canRemoveThis && (
                          <button
                            onClick={() => setRemoveTarget(m)}
                            disabled={busy}
                            className="text-xs text-red-400 hover:underline disabled:opacity-50"
                          >
                            {isSelf ? 'Leave' : 'Remove'}
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                )
              })}
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

      {/* Remove/leave confirmation */}
      {removeTarget && (
        <Modal
          title={removeTarget.id === user?.id ? 'Leave this team?' : `Remove @${removeTarget.username}?`}
          onClose={() => setRemoveTarget(null)}
        >
          <p className="mb-5 text-sm text-gray-400">
            {removeTarget.id === user?.id
              ? "You'll lose access to this team's environments and members list. You can be re-added later."
              : `@${removeTarget.username} will lose access to this team's environments and members list.`}
            {removeTarget.team_role === 'team_admin' && (
              <span className="mt-2 block text-amber-400">
                If this is the team's last team_admin, removal will be blocked — promote another
                member first.
              </span>
            )}
          </p>
          <div className="flex justify-end gap-2">
            <button
              onClick={() => setRemoveTarget(null)}
              className="rounded-md px-3 py-1.5 text-sm text-gray-400 hover:text-white"
            >
              Cancel
            </button>
            <button
              onClick={confirmRemove}
              disabled={busy}
              className="rounded-md bg-red-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-red-500 disabled:opacity-50"
            >
              {busy ? 'Removing…' : removeTarget.id === user?.id ? 'Leave Team' : 'Remove'}
            </button>
          </div>
        </Modal>
      )}

      {/* Delete team confirmation */}
      {showDeleteTeam && (
        <Modal title={`Delete ${team.name}?`} onClose={() => setShowDeleteTeam(false)}>
          {blockingEnvironments.length > 0 ? (
            <div>
              <p className="mb-3 text-sm text-gray-400">
                This team has {blockingEnvironments.length} environment(s) that aren't DESTROYED yet.
                Destroy (or resolve any FAILED ones) before deleting the team:
              </p>
              <ul className="mb-5 max-h-40 space-y-1 overflow-y-auto rounded-md border border-gray-800 bg-gray-950 p-3">
                {blockingEnvironments.map((e) => (
                  <li key={e.id} className="flex items-center justify-between text-xs">
                    <span className="font-mono text-gray-300">{e.name}</span>
                    <StatusBadge status={e.status} />
                  </li>
                ))}
              </ul>
              <div className="flex justify-end">
                <button
                  onClick={() => setShowDeleteTeam(false)}
                  className="rounded-md px-3 py-1.5 text-sm text-gray-400 hover:text-white"
                >
                  Close
                </button>
              </div>
            </div>
          ) : (
            <div>
              <p className="mb-5 text-sm text-gray-400">
                All {team.members.length} member(s) will lose access to this team immediately. This
                cannot be undone.
              </p>
              <div className="flex justify-end gap-2">
                <button
                  onClick={() => setShowDeleteTeam(false)}
                  className="rounded-md px-3 py-1.5 text-sm text-gray-400 hover:text-white"
                >
                  Cancel
                </button>
                <button
                  onClick={confirmDeleteTeam}
                  disabled={busy}
                  className="rounded-md bg-red-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-red-500 disabled:opacity-50"
                >
                  {busy ? 'Deleting…' : 'Delete Team'}
                </button>
              </div>
            </div>
          )}
        </Modal>
      )}

      <Toast toast={toast} onDismiss={() => setToast(null)} />
    </div>
  )
}

function BackLink() {
  return (
    <Link to="/teams" className="mb-4 inline-block text-xs text-gray-500 hover:text-gray-300">
      ← Back to Teams
    </Link>
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
  const [username, setUsername] = useState('')
  const [role, setRole] = useState<TeamRole>('member')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

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
          onChange={(e) => setRole(e.target.value as TeamRole)}
          className="rounded-md border border-gray-800 bg-gray-950 px-3 py-1.5 text-sm text-white focus:border-cyan-600 focus:outline-none"
        >
          {TEAM_ROLES.map((r) => (
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