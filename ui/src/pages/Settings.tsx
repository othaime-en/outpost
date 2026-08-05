import { useEffect, useState } from 'react'
import { useAuth } from '../hooks/useAuth'
import { api, APIError, type Role, type Team, type User } from '../api/client'

const ROLES: Role[] = ['member', 'team_admin', 'super_admin']

export default function Settings() {
  const { user } = useAuth()
  if (!user) return null

  return (
    <div className="space-y-10">
      <h1 className="text-xl font-semibold text-white">Settings</h1>
      <ApiKeySection />
      {(user.role === 'team_admin' || user.role === 'super_admin') && user.team_id && (
        <TeamMembersSection teamId={user.team_id} currentUserRole={user.role} />
      )}
      {user.role === 'super_admin' && <SuperAdminSection />}
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h2 className="mb-3 font-mono text-xs uppercase tracking-wide text-cyan-400">{title}</h2>
      <div className="rounded-xl border border-gray-800 bg-gray-900 p-5">{children}</div>
    </section>
  )
}

function ApiKeySection() {
  const [key, setKey] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function generate() {
    setBusy(true)
    setError(null)
    try {
      const result = await api.generateApiKey()
      setKey(result.api_key)
    } catch (err) {
      setError(err instanceof APIError ? err.message : 'Failed to generate API key')
    } finally {
      setBusy(false)
    }
  }

  async function copy() {
    if (!key) return
    await navigator.clipboard.writeText(key)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  return (
    <Section title="API Key">
      <p className="mb-4 text-sm text-gray-400">
        Generate a key for the <code className="text-gray-300">idplite</code> CLI. Each key generation
        invalidates the previous one.
      </p>
      {!key && (
        <button
          onClick={generate}
          disabled={busy}
          className="rounded-md bg-cyan-500 px-4 py-2 text-sm font-semibold text-gray-950 hover:bg-cyan-400 disabled:opacity-50"
        >
          {busy ? 'Generating…' : 'Generate API Key'}
        </button>
      )}
      {key && (
        <div>
          <div className="mb-2 flex items-center gap-2">
            <code className="flex-1 truncate rounded-md border border-gray-800 bg-gray-950 px-3 py-2 text-sm text-cyan-300">
              {key}
            </code>
            <button
              onClick={copy}
              className="rounded-md border border-gray-700 px-3 py-2 text-xs text-gray-300 hover:bg-gray-800"
            >
              {copied ? 'Copied ✓' : 'Copy'}
            </button>
          </div>
          <p className="text-xs text-red-400">
            This key will not be shown again. Store it in your CLI config (<code>~/.idplite/config.yaml</code>).
          </p>
        </div>
      )}
      {error && <p className="mt-2 text-sm text-red-400">{error}</p>}
    </Section>
  )
}

function TeamMembersSection({
  teamId,
  currentUserRole,
}: {
  teamId: string
  currentUserRole: Role
}) {
  const [members, setMembers] = useState<User[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [username, setUsername] = useState('')
  const [role, setRole] = useState<Role>('member')
  const [busy, setBusy] = useState(false)

  const assignableRoles = currentUserRole === 'super_admin' ? ROLES : ROLES.filter((r) => r !== 'super_admin')

  function load() {
    api
      .listTeamMembers(teamId)
      .then(setMembers)
      .catch((err) => setError(err instanceof APIError ? err.message : 'Failed to load members'))
  }

  useEffect(load, [teamId])

  async function addMember(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await api.addTeamMember(teamId, { github_username: username, role })
      setUsername('')
      setRole('member')
      load()
    } catch (err) {
      setError(err instanceof APIError ? err.message : 'Failed to add member')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Section title="Team Members">
      {error && <p className="mb-3 text-sm text-red-400">{error}</p>}
      {members && (
        <table className="mb-5 w-full text-sm">
          <tbody>
            {members.map((m) => (
              <tr key={m.id} className="border-b border-gray-800 last:border-0">
                <td className="py-2 font-mono text-gray-200">{m.username}</td>
                <td className="py-2 text-gray-500">{m.email ?? '—'}</td>
                <td className="py-2 text-right text-xs text-gray-500 uppercase">{m.role}</td>
              </tr>
            ))}
            {members.length === 0 && (
              <tr>
                <td className="py-3 text-gray-600">No members yet.</td>
              </tr>
            )}
          </tbody>
        </table>
      )}

      <form onSubmit={addMember} className="flex flex-wrap items-end gap-3">
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
    </Section>
  )
}

/**
 * super_admin-only. The plan (Section 6.7) calls for a flat "all users"
 * table with inline role dropdowns — but the API has no "list all users"
 * endpoint, only GET /teams/{id}/members. This browses team-by-team
 * instead: pick a team, see its members, change role inline via
 * PATCH /users/{id}/role. Team creation is included here too since a
 * super_admin needs somewhere to create teams before they can manage
 * members — the plan doesn't specify where, and this is the natural spot.
 */
function SuperAdminSection() {
  const [teams, setTeams] = useState<Team[]>([])
  const [selectedTeamId, setSelectedTeamId] = useState<string>('')
  const [members, setMembers] = useState<User[]>([])
  const [error, setError] = useState<string | null>(null)
  const [teamName, setTeamName] = useState('')
  const [teamSlug, setTeamSlug] = useState('')
  const [creatingTeam, setCreatingTeam] = useState(false)
  const [updatingUserId, setUpdatingUserId] = useState<string | null>(null)

  function loadTeams() {
    api
      .listTeams()
      .then((t) => {
        setTeams(t)
        if (!selectedTeamId && t.length > 0) setSelectedTeamId(t[0].id)
      })
      .catch((err) => setError(err instanceof APIError ? err.message : 'Failed to load teams'))
  }

  useEffect(loadTeams, [])

  useEffect(() => {
    if (!selectedTeamId) {
      setMembers([])
      return
    }
    api
      .listTeamMembers(selectedTeamId)
      .then(setMembers)
      .catch((err) => setError(err instanceof APIError ? err.message : 'Failed to load members'))
  }, [selectedTeamId])

  async function createTeam(e: React.FormEvent) {
    e.preventDefault()
    setCreatingTeam(true)
    setError(null)
    try {
      const team = await api.createTeam({ name: teamName, slug: teamSlug })
      setTeamName('')
      setTeamSlug('')
      loadTeams()
      setSelectedTeamId(team.id)
    } catch (err) {
      setError(err instanceof APIError ? err.message : 'Failed to create team')
    } finally {
      setCreatingTeam(false)
    }
  }

  async function updateRole(userId: string, newRole: Role) {
    setUpdatingUserId(userId)
    setError(null)
    try {
      const updated = await api.changeUserRole(userId, newRole)
      setMembers((prev) => prev.map((m) => (m.id === userId ? updated : m)))
    } catch (err) {
      setError(err instanceof APIError ? err.message : 'Failed to change role')
    } finally {
      setUpdatingUserId(null)
    }
  }

  return (
    <Section title="Teams & Roles (super_admin)">
      {error && <p className="mb-3 text-sm text-red-400">{error}</p>}

      <form onSubmit={createTeam} className="mb-6 flex flex-wrap items-end gap-3 border-b border-gray-800 pb-6">
        <div>
          <label className="mb-1 block text-xs text-gray-500">New team name</label>
          <input
            value={teamName}
            onChange={(e) => setTeamName(e.target.value)}
            placeholder="Platform Engineering"
            className="rounded-md border border-gray-800 bg-gray-950 px-3 py-1.5 text-sm text-white placeholder-gray-600 focus:border-cyan-600 focus:outline-none"
          />
        </div>
        <div>
          <label className="mb-1 block text-xs text-gray-500">Slug</label>
          <input
            value={teamSlug}
            onChange={(e) => setTeamSlug(e.target.value)}
            placeholder="platform-eng"
            className="rounded-md border border-gray-800 bg-gray-950 px-3 py-1.5 text-sm text-white placeholder-gray-600 focus:border-cyan-600 focus:outline-none"
          />
        </div>
        <button
          type="submit"
          disabled={creatingTeam || !teamName || !teamSlug}
          className="rounded-md border border-cyan-800 px-4 py-1.5 text-sm font-semibold text-cyan-400 hover:bg-cyan-950 disabled:opacity-50"
        >
          Create Team
        </button>
      </form>

      {teams.length === 0 ? (
        <p className="text-sm text-gray-600">No teams yet — create one above.</p>
      ) : (
        <>
          <label className="mb-1 block text-xs text-gray-500">Team</label>
          <select
            value={selectedTeamId}
            onChange={(e) => setSelectedTeamId(e.target.value)}
            className="mb-4 rounded-md border border-gray-800 bg-gray-950 px-3 py-1.5 text-sm text-white focus:border-cyan-600 focus:outline-none"
          >
            {teams.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name} ({t.slug})
              </option>
            ))}
          </select>

          <table className="w-full text-sm">
            <tbody>
              {members.map((m) => (
                <tr key={m.id} className="border-b border-gray-800 last:border-0">
                  <td className="py-2 font-mono text-gray-200">{m.username}</td>
                  <td className="py-2 text-right">
                    <select
                      value={m.role}
                      disabled={updatingUserId === m.id}
                      onChange={(e) => updateRole(m.id, e.target.value as Role)}
                      className="rounded-md border border-gray-800 bg-gray-950 px-2 py-1 text-xs text-gray-300 focus:border-cyan-600 focus:outline-none disabled:opacity-50"
                    >
                      {ROLES.map((r) => (
                        <option key={r} value={r}>
                          {r}
                        </option>
                      ))}
                    </select>
                  </td>
                </tr>
              ))}
              {members.length === 0 && (
                <tr>
                  <td className="py-3 text-gray-600">No members in this team yet.</td>
                </tr>
              )}
            </tbody>
          </table>
        </>
      )}
    </Section>
  )
}