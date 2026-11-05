import { CircleCheck } from 'lucide-react'
import { useCallback, useMemo, useRef, useState, type ReactNode } from 'react'
import { ToastContext } from './toastContext'

export function ToastProvider({ children }: { children: ReactNode }) {
  const [messages, setMessages] = useState<{ id: number; text: string }[]>([])
  const seq = useRef(0)

  const success = useCallback((text: string) => {
    const id = ++seq.current
    setMessages((m) => [...m, { id, text }])
    window.setTimeout(() => setMessages((m) => m.filter((x) => x.id !== id)), 4000)
  }, [])
  const api = useMemo(() => ({ success }), [success])

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div aria-live="polite" className="pointer-events-none fixed right-4 bottom-4 z-[60] flex flex-col gap-2">
        {messages.map((m) => (
          <div key={m.id} role="status"
            className="flex items-center gap-2 rounded-xl border border-emerald-200 bg-white px-4 py-3 text-sm font-medium text-ink shadow-lg">
            <CircleCheck className="size-5 text-emerald-600" aria-hidden />
            {m.text}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}
