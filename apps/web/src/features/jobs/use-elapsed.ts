import { useEffect, useState } from 'react'

/** Tempo decorrido real entre início e fim (ou agora, enquanto ativo). */
export function useElapsed(start: string | null, end: string | null): number | null {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!start || end) return
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [start, end])
  if (!start) return null
  const finish = end ? new Date(end).getTime() : now
  return Math.max(0, finish - new Date(start).getTime())
}
