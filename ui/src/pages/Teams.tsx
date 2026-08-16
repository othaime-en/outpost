import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'
import { isSuperAdmin } from '../lib/permissions'
import { api, APIError, type Team } from '../api/client'
import Modal from '../components/Modal'

/**
 * Landing page for the Teams nav item (see AppShell.tsx).
 *
 * MULTI-TEAM MEMBERSHIP MIGRATION — this page's whole branching structure
 * changed. The old version read `user.role`/`user.team_id` off AuthContext
 * (a single team, cached at login) to decide which of three views to show.
 * That single-team assumption is gone, and so is the AuthContext dependency
 * entirely — this page now fetches `api.listTeams()` itself (already
 * correctly scoped server-side: a caller's own teams, or everything for
 * super_admin) and branches on how many teams came back:
 *
 *   - non-super_admin, 0 teams  -> self-serve "create your first team"
 *   - everyone else (super_admin, or non-super_admin with 1+ teams)
 *                               -> grid
 *
 * EDIT after initial ship: this originally auto-redirected a non-super_admin
 * with EXACTLY one team straight to that team's detail page, to preserve
 * the old single-team model's "just take me there" UX. That turned out to
 * be a real usability bug, not a nicety: it made the Teams landing page
 * itself unreachable for the single-team case — clicking "Teams" in the
 * nav, or "← Back to Teams" from a team detail page, just bounced straight
 * back to the same team with no way to see a create-team button or land on
 * a stable "my teams" page at all. Since the grid renders perfectly well
 * with a single card in it, the fix is simply not to special-case that
 * count — 1+ teams always gets the grid, only 0 teams gets the prompt.
 *
 * Because this reads fresh from the API on every mount rather than from
 * AuthContext's cached user object, there's no staleness problem when a
 * user self-serve-creates their first team here: refreshing the list after
 * creation naturally moves them from the 0-team prompt to the grid (now
 * showing their new team) with no manual navigation or full-page reload
 * required.
 */
export default function Teams() {
  const { user } = useAuth()
  const [teams, setTeams] = useState<Team[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  function load() {
    api
      .listTeams()
      .then(setTeams)
      .catch((err) => setError(err instanceof APIError ? err.message : 'Failed to load teams'))
  }

  useEffect(load, [])

  if (error) {
    return (
      <div>
        <h1 className="font-display mb-6 text-2xl font-semibold tracking-tight text-white">Teams</h1>
        <div className="rounded-lg border border-red-900 bg-red-950/40 p-4 text-sm text-red-300">
          {error}
        </div>
      </div>
    )
  }

  if (!teams) {
    return <p className="text-sm text-gray-500">Loading teams…</p>
  }

  const isSuper = isSuperAdmin(user)

  if (!isSuper && teams.length === 0) {
    return <TeamlessPrompt onCreated={load} />
  }

  return <TeamsGrid teams={teams} isSuper={isSuper} onCreated={load} />
}

function TeamlessPrompt({ onCreated }: { onCreated: () => void }) {
  const [showCreate, setShowCreate] = useState(false)
  return (
    <div>
      <h1 className="font-display mb-6 text-2xl font-semibold tracking-tight text-white">Teams</h1>
      <div className="rounded-xl border border-dashed border-gray-800 p-12 text-center">
        <p className="mb-4 text-gray-400">You're not on a team yet.</p>
        <button
          onClick={() => setShowCreate(true)}
          className="rounded-md bg-cyan-500 px-4 py-2 text-sm font-semibold text-gray-950 hover:bg-cyan-400"
        >
          Create a Team
        </button>
        <p className="mt-3 text-xs text-gray-600">
          You'll become its team_admin. Ask an existing team_admin to add you instead if you're
          meant to join one that already exists.
        </p>
      </div>
      {showCreate && (
        <CreateTeamModal
          onClose={() => setShowCreate(false)}
          onCreated={() => {
            setShowCreate(false)
            onCreated()
          }}
        />
      )}
    </div>
  )
}

function TeamsGrid({
  teams,
  isSuper,
  onCreated,
}: {
  teams: Team[]
  isSuper: boolean
  onCreated: () => void
}) {
  const [showCreate, setShowCreate] = useState(false)

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="font-display text-2xl font-semibold tracking-tight text-white">Teams</h1>
          <p className="text-sm text-gray-500">
            {isSuper ? 'Every team on the platform' : 'Teams you belong to'}
          </p>
        </div>
        <button
          onClick={() => setShowCreate(true)}
          className="rounded-md bg-cyan-500 px-4 py-2 text-sm font-semibold text-gray-950 hover:bg-cyan-400"
        >
          + Create Team
        </button>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {teams.map((t) => (
          <Link
            key={t.id}
            to={`/teams/${t.id}`}
            className="rounded-xl border border-gray-800 bg-gray-900 p-4 transition-colors hover:border-cyan-800"
          >
            <div className="font-mono text-base font-semibold text-white">{t.name}</div>
            <div className="mt-1 font-mono text-xs text-gray-500">{t.slug}</div>
          </Link>
        ))}
      </div>

      {showCreate && (
        <CreateTeamModal
          onClose={() => setShowCreate(false)}
          onCreated={() => {
            setShowCreate(false)
            onCreated()
          }}
        />
      )}
    </div>
  )
}

function CreateTeamModal({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const [name, setName] = useState('')
  const [slug, setSlug] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await api.createTeam({ name, slug })
      // No manual navigation here — the parent's onCreated() re-fetches
      // listTeams(), and Teams()'s own branching logic (see module
      // docstring) naturally redirects if this was the user's first team,
      // or the grid just picks up the new team in place otherwise.
      onCreated()
    } catch (err) {
      setError(err instanceof APIError ? err.message : 'Failed to create team')
      setBusy(false)
    }
  }

  return (
    <Modal title="Create a Team" onClose={onClose}>
      <form onSubmit={submit} className="space-y-3">
        <div>
          <label className="mb-1 block text-xs text-gray-500">Team name</label>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Platform Engineering"
            className="w-full rounded-md border border-gray-800 bg-gray-950 px-3 py-1.5 text-sm text-white placeholder-gray-600 focus:border-cyan-600 focus:outline-none"
          />
        </div>
        <div>
          <label className="mb-1 block text-xs text-gray-500">Slug (used in AWS tags)</label>
          <input
            value={slug}
            onChange={(e) => setSlug(e.target.value)}
            placeholder="platform-eng"
            className="w-full rounded-md border border-gray-800 bg-gray-950 px-3 py-1.5 text-sm text-white placeholder-gray-600 focus:border-cyan-600 focus:outline-none"
          />
        </div>
        {error && <p className="text-sm text-red-400">{error}</p>}
        <div className="flex justify-end gap-2 pt-2">
          <button type="button" onClick={onClose} className="rounded-md px-3 py-1.5 text-sm text-gray-400 hover:text-white">
            Cancel
          </button>
          <button
            type="submit"
            disabled={busy || !name || !slug}
            className="rounded-md bg-cyan-500 px-4 py-1.5 text-sm font-semibold text-gray-950 hover:bg-cyan-400 disabled:opacity-50"
          >
            {busy ? 'Creating…' : 'Create Team'}
          </button>
        </div>
      </form>
    </Modal>
  )
}