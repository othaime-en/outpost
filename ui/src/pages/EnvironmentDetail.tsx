import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api, APIError, type AuditLogEntry, type Environment } from '../api/client'
import StatusBadge from '../components/StatusBadge'
import HealthIndicator from '../components/HealthIndicator'
import RunbookViewer from '../components/RunbookViewer'
import TTLCountdown from '../components/TTLCountdown'
import { formatUTC } from '../lib/format'

type Tab = 'outputs' | 'runbook' | 'audit' | 'cost'

const TABS: { id: Tab; label: string }[] = [
  { id: 'outputs', label: 'Outputs' },
  { id: 'runbook', label: 'Runbook' },
  { id: 'audit', label: 'Audit' },
  { id: 'cost', label: 'Cost' },
]

const POLL_INTERVAL_MS = 5_000
const TRANSITIONAL = new Set(['PENDING', 'PROVISIONING', 'DESTROYING'])

export default function EnvironmentDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [env, setEnv] = useState<Environment | null>(null)
  const [notFound, setNotFound] = useState(false)
  const [tab, setTab] = useState<Tab>('outputs')

  const fetchEnv = useCallback(async () => {
    if (!id) return
    try {
      const result = await api.getEnvironment(id)
      setEnv(result)
    } catch (err) {
      if (err instanceof APIError && err.status === 404) setNotFound(true)
    }
  }, [id])

  useEffect(() => {
    fetchEnv()
  }, [fetchEnv])

  // Poll while the environment is mid-transition so the tabs (especially
  // Runbook, which only exists once RUNNING) update without a manual refresh.
  useEffect(() => {
    if (!env || !TRANSITIONAL.has(env.status)) return
    const iv = setInterval(fetchEnv, POLL_INTERVAL_MS)
    return () => clearInterval(iv)
  }, [env, fetchEnv])

  if (notFound) {
    return (
      <div className="text-center py-16">
        <p className="mb-4 text-gray-400">Environment not found.</p>
        <Link to="/" className="text-cyan-400 hover:underline text-sm">
          ← Back to dashboard
        </Link>
      </div>
    )
  }

  if (!env) {
    return <p className="text-sm text-gray-500">Loading…</p>
  }

  return (
    <div>
      <button
        onClick={() => navigate('/')}
        className="mb-4 text-xs text-gray-500 hover:text-gray-300"
      >
        ← Back to dashboard
      </button>

      <div className="mb-6 flex flex-wrap items-center gap-3">
        <HealthIndicator status={env.health_status} />
        <h1 className="font-mono text-2xl font-semibold text-white">{env.name}</h1>
        <StatusBadge status={env.status} />
        <span className="rounded bg-gray-800 px-1.5 py-0.5 text-xs font-mono uppercase text-gray-400">
          {env.env_type}
        </span>
      </div>

      <div className="mb-6 grid grid-cols-2 gap-4 sm:grid-cols-4">
        <Stat label="Region" value={env.aws_region} />
        <Stat
          label="Expires"
          value={env.status === 'DESTROYED' ? '—' : undefined}
          node={env.status === 'DESTROYED' ? undefined : <TTLCountdown expiresAt={env.expires_at} />}
        />
        <Stat label="Created" value={formatUTC(env.created_at)} />
        <Stat label="Env ID" value={env.id} mono small />
      </div>

      <div className="mb-6 flex gap-1 border-b border-gray-800">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`px-4 py-2 text-sm font-medium transition-colors ${
              tab === t.id
                ? 'border-b-2 border-cyan-500 text-cyan-400'
                : 'text-gray-500 hover:text-gray-300'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'outputs' && <OutputsTab env={env} />}
      {tab === 'runbook' && <RunbookTab env={env} />}
      {tab === 'audit' && <AuditTab envId={env.id} />}
      {tab === 'cost' && <CostTab env={env} />}
    </div>
  )
}

function Stat({
  label,
  value,
  node,
  mono,
  small,
}: {
  label: string
  value?: string
  node?: React.ReactNode
  mono?: boolean
  small?: boolean
}) {
  return (
    <div className="rounded-lg border border-gray-800 bg-gray-900 p-3">
      <div className="mb-1 text-xs text-gray-500">{label}</div>
      {node ?? (
        <div
          className={`truncate ${mono ? 'font-mono' : ''} ${small ? 'text-xs' : 'text-sm'} text-gray-200`}
          title={value}
        >
          {value}
        </div>
      )}
    </div>
  )
}

function OutputsTab({ env }: { env: Environment }) {
  if (env.status !== 'RUNNING' && !env.outputs) {
    return (
      <p className="text-sm text-gray-500">
        Outputs are populated once the environment reaches <code className="text-gray-400">RUNNING</code>.
      </p>
    )
  }
  const entries = Object.entries(env.outputs ?? {})
  if (entries.length === 0) {
    return <p className="text-sm text-gray-500">No outputs recorded for this environment.</p>
  }
  return (
    <div className="overflow-hidden rounded-lg border border-gray-800">
      <table className="w-full text-sm">
        <tbody>
          {entries.map(([key, value]) => (
            <OutputRow key={key} label={key} value={String(value)} />
          ))}
        </tbody>
      </table>
    </div>
  )
}

function OutputRow({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false)
  const truncated = value.length > 40 ? `${value.slice(0, 40)}…` : value

  async function copy() {
    await navigator.clipboard.writeText(value)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  return (
    <tr className="border-b border-gray-800 last:border-0 hover:bg-gray-900">
      <td className="w-1/3 px-4 py-2.5 text-xs text-gray-500">{label}</td>
      <td className="px-4 py-2.5">
        <div className="flex items-center gap-2">
          <span className="font-mono text-gray-200" title={value}>
            {truncated}
          </span>
          <button
            onClick={copy}
            className="text-xs text-gray-600 hover:text-cyan-400"
            title="Copy to clipboard"
          >
            {copied ? '✓' : '⧉'}
          </button>
        </div>
      </td>
    </tr>
  )
}

function RunbookTab({ env }: { env: Environment }) {
  const [content, setContent] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    api
      .getRunbook(env.id)
      .then((r) => !cancelled && setContent(r.content_md))
      .catch((err) => {
        if (cancelled) return
        if (err instanceof APIError && err.status === 404) {
          setError('Runbook will be available once the environment is running.')
        } else {
          setError(err instanceof APIError ? err.message : 'Failed to load runbook')
        }
      })
    return () => {
      cancelled = true
    }
  }, [env.id, env.status])

  if (error) return <p className="text-sm text-gray-500">{error}</p>
  if (!content) return <p className="text-sm text-gray-500">Loading runbook…</p>
  return <RunbookViewer envName={env.name} contentMd={content} />
}

const ACTION_COLORS: Record<string, string> = {
  ENV_CREATED: 'text-green-400',
  ENV_RUNNING: 'text-green-400',
  ENV_DESTROY_REQUESTED: 'text-amber-400',
  ENV_DESTROYED: 'text-red-400',
  ENV_FAILED: 'text-red-400',
  TTL_EXTENDED: 'text-amber-400',
}

function AuditTab({ envId }: { envId: string }) {
  const [logs, setLogs] = useState<AuditLogEntry[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api
      .listAuditLogs({ environment_id: envId, page_size: 100 })
      .then((r) => setLogs(r.items))
      .catch((err) => setError(err instanceof APIError ? err.message : 'Failed to load audit log'))
  }, [envId])

  if (error) return <p className="text-sm text-red-400">{error}</p>
  if (!logs) return <p className="text-sm text-gray-500">Loading…</p>
  if (logs.length === 0) return <p className="text-sm text-gray-500">No audit events yet.</p>

  return (
    <div className="space-y-3">
      {logs.map((log) => (
        <div key={log.id} className="flex items-start gap-3 rounded-lg border border-gray-800 bg-gray-900 p-3">
          <span className={`mt-0.5 text-lg ${ACTION_COLORS[log.action] ?? 'text-gray-500'}`}>●</span>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-baseline justify-between gap-x-3">
              <span className="font-mono text-sm font-semibold text-white">{log.action}</span>
              <span className="font-mono text-xs text-gray-600">{formatUTC(log.created_at)}</span>
            </div>
            <div className="text-xs text-gray-500">
              {log.actor_type}
              {log.actor_id && <span className="text-gray-600"> · {log.actor_id.slice(0, 8)}</span>}
            </div>
            {log.metadata && Object.keys(log.metadata).length > 0 && (
              <pre className="mt-1 overflow-x-auto rounded bg-gray-950 p-2 text-xs text-gray-500">
                {JSON.stringify(log.metadata, null, 2)}
              </pre>
            )}
          </div>
        </div>
      ))}
    </div>
  )
}

function CostTab({ env }: { env: Environment }) {
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
      <div className="rounded-lg border border-gray-800 bg-gray-900 p-5">
        <div className="mb-1 text-xs text-gray-500">Estimated monthly cost</div>
        <div className="font-mono text-2xl font-bold text-cyan-400">
          {env.cost_estimate_usd !== null ? `$${env.cost_estimate_usd.toFixed(2)}` : 'n/a'}
        </div>
        <div className="mt-1 text-xs text-gray-600">Computed at creation time, 24/7 runtime assumed.</div>
      </div>
      <div className="rounded-lg border border-gray-800 bg-gray-900 p-5">
        <div className="mb-1 text-xs text-gray-500">Actual cost</div>
        <div className="font-mono text-2xl font-bold text-gray-600">—</div>
        {/*
          The API doesn't currently expose a cost-snapshot read endpoint —
          `cost_snapshots` rows are modeled (Section 6, data model) but there's
          no GET route to fetch them yet. Showing the plan's documented
          fallback message rather than fabricating a number.
        */}
        <div className="mt-1 text-xs text-gray-600">
          Actual cost available after 24h (AWS Cost Explorer lag).
        </div>
      </div>
    </div>
  )
}