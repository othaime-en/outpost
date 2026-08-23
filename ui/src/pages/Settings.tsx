import { useEffect, useState } from 'react'
import { useAuth } from '../hooks/useAuth'
import { isSuperAdmin } from '../lib/permissions'
import { api, APIError, type PlatformRole, type User } from '../api/client'

const PLATFORM_ROLES: PlatformRole[] = ['user', 'super_admin']

export default function Settings() {
  const { user } = useAuth()
  if (!user) return null

  return (
    <div className="space-y-10">
      <h1 className="font-display text-2xl font-semibold tracking-tight text-gray-900 dark:text-white">Settings</h1>
      <ApiKeySection />
      {isSuperAdmin(user) && <PlatformAdminSection />}
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h2 className="mb-3 font-mono text-xs uppercase tracking-wide text-cyan-600 dark:text-cyan-400">{title}</h2>
      <div className="rounded-xl border border-gray-200 bg-white dark:border-gray-800 dark:bg-gray-900 p-5">{children}</div>
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
      <p className="mb-4 text-sm text-gray-600 dark:text-gray-400">
        Generate a key for the <code className="text-gray-700 dark:text-gray-300">outpost</code> CLI. Each key generation
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
            <code className="flex-1 truncate rounded-md border border-gray-200 bg-gray-50 dark:border-gray-800 dark:bg-gray-950 px-3 py-2 text-sm text-cyan-700 dark:text-cyan-300">
              {key}
            </code>
            <button
              onClick={copy}
              className="rounded-md border border-gray-300 dark:border-gray-700 px-3 py-2 text-xs text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800"
            >
              {copied ? 'Copied ✓' : 'Copy'}
            </button>
          </div>
          <p className="text-xs text-red-600 dark:text-red-400">
            This key will not be shown again. Store it in your CLI config (<code>~/.outpost/config.yaml</code>).
          </p>
        </div>
      )}
      {error && <p className="mt-2 text-sm text-red-600 dark:text-red-400">{error}</p>}
    </Section>
  )
}

function PlatformAdminSection() {
  const [users, setUsers] = useState<User[]>([])
  const [error, setError] = useState<string | null>(null)
  const [updatingUserId, setUpdatingUserId] = useState<string | null>(null)

  useEffect(() => {
    api
      .listUsers()
      .then(setUsers)
      .catch((err) => setError(err instanceof APIError ? err.message : 'Failed to load users'))
  }, [])

  async function updateRole(userId: string, newRole: PlatformRole) {
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

  return (
    <Section title="Platform Admin">
      <p className="mb-4 text-sm text-gray-600 dark:text-gray-400">
        Change any user's platform role — including users not yet assigned to a team. To create a
        team or manage a team's members, use the{' '}
        <a href="/teams" className="text-cyan-600 dark:text-cyan-400 hover:underline">
          Teams
        </a>{' '}
        tab instead.
      </p>
      {error && <p className="mb-3 text-sm text-red-600 dark:text-red-400">{error}</p>}

      <table className="w-full text-sm">
        <tbody>
          {users.map((u) => (
            <tr key={u.id} className="border-b border-gray-200 dark:border-gray-800 last:border-0">
              <td className="py-2 font-mono text-gray-800 dark:text-gray-200">{u.username}</td>
              <td className="py-2 text-gray-500 dark:text-gray-500">
                {u.team_memberships.length > 0 ? (
                  u.team_memberships.map((m) => m.team_slug).join(', ')
                ) : (
                  <span className="text-amber-600 dark:text-amber-500">no team</span>
                )}
              </td>
              <td className="py-2 text-right">
                <select
                  value={u.platform_role}
                  disabled={updatingUserId === u.id}
                  onChange={(e) => updateRole(u.id, e.target.value as PlatformRole)}
                  className="rounded-md border border-gray-300 bg-white dark:border-gray-800 dark:bg-gray-950 px-2 py-1 text-xs text-gray-700 dark:text-gray-300 focus:border-cyan-600 focus:outline-none disabled:opacity-50"
                >
                  {PLATFORM_ROLES.map((r) => (
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
              <td className="py-3 text-gray-400 dark:text-gray-600">No users yet.</td>
            </tr>
          )}
        </tbody>
      </table>
    </Section>
  )
}