import { useState } from 'react'
import { api, APIError, type Environment } from '../api/client'
import Modal from '../components/Modal'
import Toast, { type ToastState } from '../components/Toast'


const DESTROYABLE = new Set(['RUNNING', 'FAILED', 'PENDING'])

/**
 * True for a PENDING environment specifically — the one case where
 * "Destroy" is actually "Cancel" (nothing was ever confirmed provisioned,
 * so there's nothing confirmed to tear down). Used to swap in different
 * modal copy/button label/toast wording without duplicating the
 * `status === 'PENDING'` check at each call site.
 */
export function isPendingCancel(env: Environment) {
  return env.status === 'PENDING'
}

/**
 * Encapsulates the destroy/extend confirmation flow so Dashboard.tsx and
 * EnvironmentDetail.tsx share one implementation instead of two copies that
 * can quietly drift apart. Renders its own modals/toast — the caller just
 * drops <actions.modals /> somewhere in its tree and wires the returned
 * handlers to buttons.
 */
export function useEnvironmentActions(onChanged: () => void) {
  const [destroyTarget, setDestroyTarget] = useState<Environment | null>(null)
  const [extendTarget, setExtendTarget] = useState<Environment | null>(null)
  const [extendHours, setExtendHours] = useState(24)
  const [busy, setBusy] = useState(false)
  const [toast, setToast] = useState<ToastState | null>(null)

  function canDestroy(env: Environment) {
    return DESTROYABLE.has(env.status)
  }
  function canExtend(env: Environment) {
    return env.status === 'RUNNING'
  }

  function promptDestroy(env: Environment) {
    setDestroyTarget(env)
  }
  function promptExtend(env: Environment) {
    setExtendHours(24)
    setExtendTarget(env)
  }

  async function confirmDestroy() {
    if (!destroyTarget) return
    setBusy(true)
    try {
      const result = await api.destroyEnvironment(destroyTarget.id)
      // Read the response back rather than assuming based on
      // destroyTarget.status — the backend is the actual authority on
      // whether this was an immediate cancel (status now DESTROYED) or a
      // real async destroy (status now DESTROYING), and by the time this
      // resolves the environment's true state could in principle have
      // moved on regardless of what the UI last saw.
      setToast({
        kind: 'success',
        message:
          result.status === 'DESTROYED'
            ? `Cancelled ${destroyTarget.name}`
            : `Destroying ${destroyTarget.name}…`,
      })
      setDestroyTarget(null)
      onChanged()
    } catch (err) {
      setToast({ kind: 'error', message: err instanceof APIError ? err.message : 'Destroy failed' })
    } finally {
      setBusy(false)
    }
  }

  async function confirmExtend() {
    if (!extendTarget) return
    setBusy(true)
    try {
      await api.extendTTL(extendTarget.id, extendHours)
      setToast({ kind: 'success', message: `Extended ${extendTarget.name} by ${extendHours}h` })
      setExtendTarget(null)
      onChanged()
    } catch (err) {
      setToast({ kind: 'error', message: err instanceof APIError ? err.message : 'Extend failed' })
    } finally {
      setBusy(false)
    }
  }

  function modals() {
    return (
      <>
        {destroyTarget && (
          <Modal
            title={isPendingCancel(destroyTarget) ? `Cancel ${destroyTarget.name}?` : `Destroy ${destroyTarget.name}?`}
            onClose={() => setDestroyTarget(null)}
          >
            <p className="mb-5 text-sm text-gray-400">
              {isPendingCancel(destroyTarget) ? (
                <>
                  This environment never received confirmation that any AWS resources were
                  provisioned, so there's almost certainly nothing to tear down. It'll be marked
                  cancelled immediately — a best-effort teardown request is still sent in the rare
                  case provisioning had silently started. This cannot be undone.
                </>
              ) : (
                <>
                  This tears down all AWS resources for this environment. The environment record
                  and its audit trail are kept — this cannot be undone.
                </>
              )}
            </p>
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setDestroyTarget(null)}
                className="rounded-md px-3 py-1.5 text-sm text-gray-400 hover:text-white"
              >
                Cancel
              </button>
              <button
                onClick={confirmDestroy}
                disabled={busy}
                className="rounded-md bg-red-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-red-500 disabled:opacity-50"
              >
                {busy
                  ? isPendingCancel(destroyTarget)
                    ? 'Cancelling…'
                    : 'Destroying…'
                  : isPendingCancel(destroyTarget)
                    ? 'Cancel Environment'
                    : 'Destroy'}
              </button>
            </div>
          </Modal>
        )}

        {extendTarget && (
          <Modal title={`Extend TTL — ${extendTarget.name}`} onClose={() => setExtendTarget(null)}>
            <label className="mb-1 block text-xs text-gray-500">Extend by (hours)</label>
            <input
              type="number"
              min={1}
              max={168}
              value={extendHours}
              onChange={(e) => setExtendHours(Number(e.target.value))}
              className="mb-5 w-full rounded-md border border-gray-800 bg-gray-950 px-3 py-2 text-sm text-white
                         focus:border-cyan-600 focus:outline-none"
            />
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setExtendTarget(null)}
                className="rounded-md px-3 py-1.5 text-sm text-gray-400 hover:text-white"
              >
                Cancel
              </button>
              <button
                onClick={confirmExtend}
                disabled={busy || extendHours < 1}
                className="rounded-md bg-amber-500 px-3 py-1.5 text-sm font-semibold text-gray-950 hover:bg-amber-400 disabled:opacity-50"
              >
                {busy ? 'Extending…' : 'Extend'}
              </button>
            </div>
          </Modal>
        )}

        <Toast toast={toast} onDismiss={() => setToast(null)} />
      </>
    )
  }

  return { canDestroy, canExtend, promptDestroy, promptExtend, modals }
}