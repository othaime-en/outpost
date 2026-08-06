import { useCallback, useEffect, useRef, useState } from 'react'
import { api, APIError, type Environment, type EnvStatus } from '../api/client'

const TRANSITIONAL: EnvStatus[] = ['PENDING', 'PROVISIONING', 'DESTROYING']
const POLL_INTERVAL_MS = 5_000

export function useEnvironments() {
  const [environments, setEnvironments] = useState<Environment[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const intervalRef = useRef<ReturnType<typeof setInterval>>()

  const fetchOnce = useCallback(async () => {
    try {
      const envs = await api.listEnvironments()
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
  }, [])

  // setInterval needs a stable function reference that always calls the
  // *latest* fetchOnce (which itself starts/stops the interval) — a ref
  // avoids stale closures without re-creating the interval on every render.
  const fetchOnceRef = useRef(fetchOnce)
  fetchOnceRef.current = fetchOnce

  useEffect(() => {
    fetchOnce()
    return () => {
      if (intervalRef.current !== undefined) clearInterval(intervalRef.current)
    }
  }, [fetchOnce])

  return { environments, loading, error, refresh: fetchOnce }
}