import { useEffect, useState } from 'react'
import { api, APIError, type AuditLogEntry } from '../api/client'
import { formatUTC } from '../lib/format'

const ACTIONS = [
  'ENV_CREATED',
  'ENV_RUNNING',
  'ENV_DESTROY_REQUESTED',
  'ENV_DESTROYED',
  'ENV_FAILED',
  'TTL_EXTENDED',
  'USER_ADDED',
  'USER_ROLE_CHANGED',
  'TEAM_CREATED',
  'API_KEY_GENERATED',
]

const ACTOR_TYPES = ['user', 'system', 'cron']
const PAGE_SIZE = 25

export default function AuditLog() {
  const [items, setItems] = useState<AuditLogEntry[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [action, setAction] = useState('')
  const [actorType, setActorType] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setLoading(true)
    api
      .listAuditLogs({
        page,
        page_size: PAGE_SIZE,
        action: action || undefined,
        actor_type: actorType || undefined,
      })
      .then((r) => {
        setItems(r.items)
        setTotal(r.total)
        setError(null)
      })
      .catch((err) => setError(err instanceof APIError ? err.message : 'Failed to load audit log'))
      .finally(() => setLoading(false))
  }, [page, action, actorType])

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  return (
    <div>
      <h1 className="mb-6 font-display text-2xl font-semibold tracking-tight text-gray-900 dark:text-white">
        Audit Log
      </h1>

      <div className="mb-4 flex flex-wrap gap-3">
        <select
          value={action}
          onChange={(e) => {
            setPage(1)
            setAction(e.target.value)
          }}
          className="rounded-md border border-gray-200 bg-white dark:border-gray-800 dark:bg-gray-900 px-3 py-1.5 text-sm text-gray-700 dark:text-gray-300 focus:border-cyan-600 focus:outline-none"
        >
          <option value="">All actions</option>
          {ACTIONS.map((a) => (
            <option key={a} value={a}>
              {a}
            </option>
          ))}
        </select>
        <select
          value={actorType}
          onChange={(e) => {
            setPage(1)
            setActorType(e.target.value)
          }}
          className="rounded-md border border-gray-200 bg-white dark:border-gray-800 dark:bg-gray-900 px-3 py-1.5 text-sm text-gray-700 dark:text-gray-300 focus:border-cyan-600 focus:outline-none"
        >
          <option value="">All actor types</option>
          {ACTOR_TYPES.map((a) => (
            <option key={a} value={a}>
              {a}
            </option>
          ))}
        </select>
        {(action || actorType) && (
          <button
            onClick={() => {
              setAction('')
              setActorType('')
              setPage(1)
            }}
            className="text-sm text-gray-500 hover:text-gray-700 dark:hover:text-gray-300"
          >
            Clear filters
          </button>
        )}
      </div>

      {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}
      {loading && <p className="text-sm text-gray-500 dark:text-gray-500">Loading…</p>}

      {!loading && !error && (
        <>
          <div className="overflow-hidden rounded-lg border border-gray-200 dark:border-gray-800">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 dark:bg-gray-900 text-xs uppercase tracking-wide text-gray-500 dark:text-gray-500">
                <tr>
                  <th className="px-4 py-2 text-left font-mono">Action</th>
                  <th className="px-4 py-2 text-left font-mono">Actor</th>
                  <th className="px-4 py-2 text-left font-mono">Environment</th>
                  <th className="px-4 py-2 text-left font-mono">When</th>
                </tr>
              </thead>
              <tbody>
                {items.map((log) => (
                  <tr key={log.id} className="border-t border-gray-200 dark:border-gray-800 hover:bg-gray-50 dark:hover:bg-gray-900">
                    <td className="px-4 py-2.5 font-mono text-gray-800 dark:text-gray-200">{log.action}</td>
                    <td className="px-4 py-2.5 text-gray-600 dark:text-gray-400">
                      {log.actor_type}
                      {log.actor_id && (
                        <span className="text-gray-400 dark:text-gray-600"> · {log.actor_id.slice(0, 8)}</span>
                      )}
                    </td>
                    <td className="px-4 py-2.5 font-mono text-xs text-gray-500 dark:text-gray-500">
                      {log.environment_id ? log.environment_id.slice(0, 8) : '—'}
                    </td>
                    <td className="px-4 py-2.5 font-mono text-xs text-gray-500 dark:text-gray-500">
                      {formatUTC(log.created_at)}
                    </td>
                  </tr>
                ))}
                {items.length === 0 && (
                  <tr>
                    <td colSpan={4} className="px-4 py-8 text-center text-gray-400 dark:text-gray-600">
                      No matching audit events.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          <div className="mt-4 flex items-center justify-between text-sm text-gray-500 dark:text-gray-500">
            <span>
              Page {page} of {totalPages} · {total} total
            </span>
            <div className="flex gap-2">
              <button
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page <= 1}
                className="rounded-md border border-gray-200 dark:border-gray-800 px-3 py-1 hover:bg-gray-100 dark:hover:bg-gray-900 disabled:opacity-40"
              >
                Previous
              </button>
              <button
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={page >= totalPages}
                className="rounded-md border border-gray-200 dark:border-gray-800 px-3 py-1 hover:bg-gray-100 dark:hover:bg-gray-900 disabled:opacity-40"
              >
                Next
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  )
}