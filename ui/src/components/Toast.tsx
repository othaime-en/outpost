import { useEffect } from 'react'

export interface ToastState {
  message: string
  kind: 'success' | 'error'
}

const KIND_STYLES: Record<ToastState['kind'], string> = {
  success: 'border-green-800 bg-green-950 text-green-300',
  error: 'border-red-800 bg-red-950 text-red-300',
}

export default function Toast({
  toast,
  onDismiss,
}: {
  toast: ToastState | null
  onDismiss: () => void
}) {
  useEffect(() => {
    if (!toast) return
    const id = setTimeout(onDismiss, 4000)
    return () => clearTimeout(id)
  }, [toast, onDismiss])

  if (!toast) return null

  return (
    <div
      className={`fixed bottom-6 right-6 z-30 rounded-lg border px-4 py-3 text-sm shadow-lg ${KIND_STYLES[toast.kind]}`}
    >
      {toast.message}
    </div>
  )
}