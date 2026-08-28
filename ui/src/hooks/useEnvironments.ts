import { useCallback, useEffect, useRef, useState } from 'react'
import { api, APIError, type Environment, type EnvironmentFilters, type EnvStatus } from '../api/client'

// PENDING/PROVISIONING/DESTROYING are the original set; PAUSING/RESUMING
// added alongside the grace-period/pause safety net (see api/app/routers/
// environments.py's module docstring) — both resolve in seconds-to-minutes,
// same timescale as a Terraform apply/destroy. EXPIRING is deliberately
// EXCLUDED even though it's also "mid-transition": it can last up to 24h
// (the grace period), and polling the whole dashboard every 5s for 24h
// would be wasteful for no real benefit — see EnvironmentDetail.tsx's
// identical reasoning on its own TRANSITIONAL set.
const TRANSITIONAL: EnvStatus[] = ['PENDING', 'PROVISIONING', 'DESTROYING', 'PAUSING', 'RESUMING']
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