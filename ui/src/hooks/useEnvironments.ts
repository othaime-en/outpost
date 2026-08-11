import { useCallback, useEffect, useRef, useState } from 'react'
import { api, APIError, type Environment, type EnvironmentFilters, type EnvStatus } from '../api/client'

const TRANSITIONAL: EnvStatus[] = ['PENDING', 'PROVISIONING', 'DESTROYING']
const POLL_INTERVAL_MS = 5_000

/**
 * Fetches the caller's visible environments, applying server-side filters.
 *
 * Polling is based on the *filtered* result set: if a transitional
 * environment is hidden by the current filters (e.g. "Show destroyed" is
 * off and something just finished destroying), polling will stop even
 * though it's still mid-transition elsewhere. That's an accepted tradeoff —
 * re-fetching every 5s for a status you've deliberately filtered out isn't
 * worth the complexity of tracking it separately.
 *
 * `filters` is compared by value (via JSON.stringify) rather than by
 * reference, since callers will typically construct a new filters object
 * on every render.
 */
export function useEnvironments(filters: EnvironmentFilters = {}) {
  const [environments, setEnvironments] = useState<Environment[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const intervalRef = useRef<ReturnType<typeof setInterval>>()

  const filtersKey = JSON.stringify(filters)
  const filtersRef = useRef(filters)
  filtersRef.current = filters

  const fetchOnce = useCallback(async () => {
    try {
      const envs = await api.listEnvironments(filtersRef.current)
      setEnvironments(envs)
      setError(null)

      const needsPoll = envs.some((e) => TRANSITIONAL.includes(e.status))
      if (needsPoll && intervalRef.current === undefined) {
        intervalRef.current = setInterval(fetchOnceRef.current, POLL_INTERVAL_MS)
      } else if (!needsPoll && intervalRef.current !== undefined) {
        clearInterval(intervalRef.current)
        intervalRef.current = undefined
      }
    } catch (err) {
      setError(err instanceof APIError ? err.message : 'Failed to load environments')
    } finally {
      setLoading(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filtersKey])

  // setInterval needs a stable function reference that always calls the
  // *latest* fetchOnce (which itself starts/stops the interval) — a ref
  // avoids stale closures without re-creating the interval on every render.
  const fetchOnceRef = useRef(fetchOnce)
  fetchOnceRef.current = fetchOnce

  useEffect(() => {
    setLoading(true)
    fetchOnce()
    return () => {
      if (intervalRef.current !== undefined) {
        clearInterval(intervalRef.current)
        intervalRef.current = undefined
      }
    }
    // Re-run whenever the filters actually change value, not just reference.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filtersKey])

  return { environments, loading, error, refresh: fetchOnce }
}