import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, APIError, type CostBreakdown, type EnvType, type Team } from '../api/client'

const NAME_PATTERN = /^[a-z0-9-]+$/

export default function NewEnvironment() {
  const navigate = useNavigate()
  const [teams, setTeams] = useState<Team[] | null>(null)
  const [teamsError, setTeamsError] = useState<string | null>(null)
  const [teamId, setTeamId] = useState('')

  const [name, setName] = useState('')
  const [envType, setEnvType] = useState<EnvType>('dev')
  const [ttlHours, setTtlHours] = useState(24)
  const [preview, setPreview] = useState<CostBreakdown | null>(null)
  const [previewError, setPreviewError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)

  useEffect(() => {
    api
      .listTeams()
      .then((result) => {
        setTeams(result)
        if (result.length >= 1) setTeamId(result[0].id)
      })
      .catch((err) => setTeamsError(err instanceof APIError ? err.message : 'Failed to load teams'))
  }, [])

  // Cost preview updates automatically whenever env_type changes.
  useEffect(() => {
    let cancelled = false
    api
      .getCostPreview(envType)
      .then((result) => {
        if (!cancelled) {
          setPreview(result)
          setPreviewError(null)
        }
      })
      .catch((err) => {
        if (!cancelled) setPreviewError(err instanceof APIError ? err.message : 'Could not load estimate')
      })
    return () => {
      cancelled = true
    }
  }, [envType])

  const nameValid = name.length > 0 && NAME_PATTERN.test(name)
  const nameTouched = name.length > 0

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!nameValid) {
      setFormError('Name must be lowercase alphanumeric with hyphens only.')
      return
    }
    if (!teamId) {
      setFormError('Select a team for this environment.')
      return
    }
    setFormError(null)
    setSubmitting(true)
    try {
      const result = await api.createEnvironment({ name, team_id: teamId, env_type: envType, ttl_hours: ttlHours })
      navigate('/', { state: { justCreated: result.env_id } })
    } catch (err) {
      setFormError(err instanceof APIError ? err.message : 'Failed to create environment')
      setSubmitting(false)
    }
  }

  if (teamsError) {
    return (
      <div className="rounded-lg border border-red-900 bg-red-950/40 p-4 text-sm text-red-300">
        {teamsError}
      </div>
    )
  }

  if (teams === null) {
    return <p className="text-sm text-gray-500">Loading your teams…</p>
  }

  if (teams.length === 0) {
    return (
      <div>
        <h1 className="mb-6 font-display text-2xl font-semibold tracking-tight text-white">
          New Environment
        </h1>
        <div className="rounded-xl border border-dashed border-gray-800 p-12 text-center">
          <p className="mb-4 text-gray-400">
            You need to belong to a team before you can provision an environment.
          </p>
          <Link to="/teams" className="text-cyan-400 hover:underline text-sm">
            Create or join a team →
          </Link>
        </div>
      </div>
    )
  }

  return (
    <div>
      <h1 className="mb-6 font-display text-2xl font-semibold tracking-tight text-white">
        New Environment
      </h1>

      <div className="grid grid-cols-1 gap-8 lg:grid-cols-2">
        {/* Left column — form */}
        <form onSubmit={handleSubmit} className="space-y-6">
          {teams.length > 1 && (
            <div>
              <label className="mb-1 block text-sm text-gray-300">Team</label>
              <select
                value={teamId}
                onChange={(e) => setTeamId(e.target.value)}
                className="w-full rounded-md border border-gray-800 bg-gray-900 px-3 py-2 text-sm text-white focus:border-cyan-600 focus:outline-none"
              >
                {teams.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name} ({t.slug})
                  </option>
                ))}
              </select>
            </div>
          )}

          <div>
            <label className="mb-1 block text-sm text-gray-300">Name</label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="my-feature"
              className="w-full rounded-md border border-gray-800 bg-gray-900 px-3 py-2 font-mono text-sm text-white
                         placeholder-gray-600 focus:border-cyan-600 focus:outline-none"
            />
            {nameTouched && !nameValid && (
              <p className="mt-1 text-xs text-red-400">Lowercase alphanumeric and hyphens only.</p>
            )}
          </div>

          <div>
            <label className="mb-2 block text-sm text-gray-300">Type</label>
            <div className="flex gap-3">
              {(['dev', 'staging'] as const).map((t) => (
                <button
                  type="button"
                  key={t}
                  onClick={() => setEnvType(t)}
                  className={`flex-1 rounded-md border px-4 py-2 text-sm font-medium capitalize transition-colors ${
                    envType === t
                      ? 'border-cyan-600 bg-cyan-950 text-cyan-300'
                      : 'border-gray-800 bg-gray-900 text-gray-400 hover:border-gray-700'
                  }`}
                >
                  {t}
                </button>
              ))}
            </div>
          </div>

          <div>
            <div className="mb-2 flex items-center justify-between">
              <label className="text-sm text-gray-300">TTL</label>
              <span className="font-mono text-sm text-cyan-400">{ttlHours}h</span>
            </div>
            <input
              type="range"
              min={1}
              max={168}
              value={ttlHours}
              onChange={(e) => setTtlHours(Number(e.target.value))}
              className="w-full accent-cyan-500"
            />
            <div className="mt-1 flex justify-between text-xs text-gray-600">
              <span>1h</span>
              <span>168h (7d)</span>
            </div>
          </div>

          {formError && (
            <div className="rounded-md border border-red-900 bg-red-950/40 p-3 text-sm text-red-300">
              {formError}
            </div>
          )}

          <button
            type="submit"
            disabled={submitting || !nameValid || !teamId}
            className="w-full rounded-md bg-cyan-500 px-4 py-2.5 text-sm font-semibold text-gray-950
                       hover:bg-cyan-400 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {submitting ? 'Requesting environment…' : 'Provision Environment'}
          </button>
        </form>

        {/* Right column — cost preview */}
        <div className="rounded-xl border border-gray-800 bg-gray-900 p-6 h-fit">
          <h2 className="mb-4 text-sm font-mono uppercase tracking-wide text-cyan-400">Cost Estimate</h2>
          {previewError && <p className="text-sm text-red-400">{previewError}</p>}
          {preview && (
            <div className="space-y-3">
              <Row label="ECS Fargate" value={preview.ecs_fargate} />
              <Row label="RDS Postgres" value={preview.rds_postgres} />
              <Row label="CloudWatch Logs" value={preview.cloudwatch_logs} />
              <Row label="Secrets Manager" value={preview.secrets_manager} />
              <div className="mt-4 flex items-center justify-between border-t border-gray-800 pt-3">
                <span className="text-sm font-semibold text-white">Total</span>
                <span className="font-mono text-lg font-bold text-cyan-400">
                  ${preview.total_monthly.toFixed(2)}/mo
                </span>
              </div>
              <p className="pt-2 text-xs text-gray-600">{preview.note}</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function Row({ label, value }: { label: string; value: number }) {
  return (
    <div className="flex items-center justify-between text-sm">
      <span className="text-gray-400">{label}</span>
      <span className="font-mono text-gray-300">${value.toFixed(2)}/mo</span>
    </div>
  )
}