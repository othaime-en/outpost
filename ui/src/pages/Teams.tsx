import { useEffect, useState } from 'react'
import { Link, Navigate } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'
import { api, APIError, type Team } from '../api/client'
import Modal from '../components/Modal'

/**
 * Landing page for the new Teams nav item (see AppShell.tsx).
 *
 * - super_admin: a grid of every team on the platform, plus "Create Team".
 * - team_admin / member with a team: redirected straight to their own
 *   team's detail page — there's nothing useful to show at a "list" of one.
 * - a teamless user: a self-serve "create your team" prompt.
 */
export default function Teams() {
  const { user } = useAuth()

  if (user && user.role !== 'super_admin' && user.team_id) {
    return <Navigate to={`/teams/${user.team_id}`} replace />
  }

  if (user && user.role !== 'super_admin' && !user.team_id) {
    return <TeamlessPrompt />
  }

  return <AllTeamsGrid />
}

function TeamlessPrompt() {
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
      {showCreate && <CreateTeamModal onClose={() => setShowCreate(false)} />}
    </div>
  )
}

function AllTeamsGrid() {
  const [teams, setTeams] = useState<Team[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [showCreate, setShowCreate] = useState(false)

  function load() {
    api
      .listTeams()
      .then(setTeams)
      .catch((err) => setError(err instanceof APIError ? err.message : 'Failed to load teams'))
  }

  useEffect(load, [])

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <h1 className="font-display text-2xl font-semibold tracking-tight text-white">Teams</h1>
        <button
          onClick={() => setShowCreate(true)}
          className="rounded-md bg-cyan-500 px-4 py-2 text-sm font-semibold text-gray-950 hover:bg-cyan-400"
        >
          + Create Team
        </button>
      </div>

      {error && (
        <div className="mb-4 rounded-lg border border-red-900 bg-red-950/40 p-4 text-sm text-red-300">
          {error}
        </div>
      )}

      {teams && teams.length === 0 && (
        <div className="rounded-xl border border-dashed border-gray-800 p-12 text-center text-gray-400">
          No teams yet.
        </div>
      )}

      {teams && teams.length > 0 && (
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
      )}

      {showCreate && (
        <CreateTeamModal
          onClose={() => setShowCreate(false)}
          onCreated={() => {
            setShowCreate(false)
            load()
          }}
        />
      )}
    </div>
  )
}

function CreateTeamModal({ onClose, onCreated }: { onClose: () => void; onCreated?: () => void }) {
  const [name, setName] = useState('')
  const [slug, setSlug] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const team = await api.createTeam({ name, slug })
      if (onCreated) {
        onCreated()
      } else {
        // Teamless-user path: no list to refresh, just go straight to the
        // new team's detail page. A full reload picks up the user's
        // updated role/team_id from a fresh /auth/me on next navigation.
        window.location.href = `/teams/${team.id}`
      }
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