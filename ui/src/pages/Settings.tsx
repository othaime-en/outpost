import { useEffect, useState } from 'react'
import { useAuth } from '../hooks/useAuth'
import { api, APIError, type Role, type Team, type User } from '../api/client'

const ROLES: Role[] = ['member', 'team_admin', 'super_admin']

export default function Settings() {
  const { user } = useAuth()
  if (!user) return null

  return (
    <div className="space-y-10">
      <h1 className="font-display text-2xl font-semibold tracking-tight text-white">Settings</h1>
      <ApiKeySection />
      {user.role === 'super_admin' && <PlatformAdminSection />}
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

/**
 * super_admin-only. Team creation and member management have moved to the
 * Teams tab (see pages/Teams.tsx, pages/TeamDetail.tsx) now that both are
 * open to any authenticated user rather than super_admin-only — see
 * routers/teams.py's module docstring for that RBAC change.
 *
 * What's left here is deliberately team-agnostic: PATCH /users/{id}/role
 * works even for a user with no team_id at all (right after their first
 * GitHub login), which is exactly why it lives in routers/users.py rather
 * than routers/teams.py — see that router's own docstring. Settings is the
 * natural home for a team-agnostic admin action; a per-team page isn't.
 */
function PlatformAdminSection() {
  const [users, setUsers] = useState<User[]>([])
  const [teams, setTeams] = useState<Team[]>([])
  const [error, setError] = useState<string | null>(null)
  const [updatingUserId, setUpdatingUserId] = useState<string | null>(null)

  useEffect(() => {
    api
      .listUsers()
      .then(setUsers)
      .catch((err) => setError(err instanceof APIError ? err.message : 'Failed to load users'))
    api.listTeams().then(setTeams).catch(() => setTeams([]))
  }, [])

  async function updateRole(userId: string, newRole: Role) {
    setUpdatingUserId(userId)
    setError(null)
    try {
      const updated = await api.changeUserRole(userId, newRole)
      setUsers((prev) => prev.map((u) => (u.id === userId ? updated : u)))
    } catch (err) {
      setError(err instanceof APIError ? err.message : 'Failed to change role')
    } finally {
      setUpdatingUserId(null)
    }
  }

  const teamSlugById = new Map(teams.map((t) => [t.id, t.slug]))

  return (
    <Section title="Platform Admin">
      <p className="mb-4 text-sm text-gray-400">
        Change any user's role — including users not yet assigned to a team. To create a team or
        manage a team's members, use the{' '}
        <a href="/teams" className="text-cyan-400 hover:underline">
          Teams
        </a>{' '}
        tab instead.
      </p>
      {error && <p className="mb-3 text-sm text-red-400">{error}</p>}

      <table className="w-full text-sm">
        <tbody>
          {users.map((u) => (
            <tr key={u.id} className="border-b border-gray-800 last:border-0">
              <td className="py-2 font-mono text-gray-200">{u.username}</td>
              <td className="py-2 text-gray-500">
                {u.team_id ? teamSlugById.get(u.team_id) ?? 'unknown team' : (
                  <span className="text-amber-500">no team</span>
                )}
              </td>
              <td className="py-2 text-right">
                <select
                  value={u.role}
                  disabled={updatingUserId === u.id}
                  onChange={(e) => updateRole(u.id, e.target.value as Role)}
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
          {users.length === 0 && (
            <tr>
              <td className="py-3 text-gray-600">No users yet.</td>
            </tr>
          )}
        </tbody>
      </table>
    </Section>
  )
}