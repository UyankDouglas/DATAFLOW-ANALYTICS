import { useCallback, useSyncExternalStore } from 'react'

export type Theme = 'dark' | 'light'

const STORAGE_KEY = 'df-theme'
const listeners = new Set<() => void>()

export function readStoredTheme(): Theme {
  try {
    return localStorage.getItem(STORAGE_KEY) === 'light' ? 'light' : 'dark'
  } catch {
    return 'dark'
  }
}

export function applyTheme(theme: Theme) {
  const root = document.documentElement
  root.classList.toggle('dark', theme === 'dark')
  root.style.colorScheme = theme
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function useTheme() {
  const theme = useSyncExternalStore(subscribe, readStoredTheme, () => 'dark' as Theme)
  const setTheme = useCallback((next: Theme) => {
    try {
      localStorage.setItem(STORAGE_KEY, next)
    } catch {
      // armazenamento indisponível: aplica só nesta sessão
    }
    applyTheme(next)
    listeners.forEach((listener) => listener())
  }, [])
  const toggle = useCallback(
    () => setTheme(readStoredTheme() === 'dark' ? 'light' : 'dark'),
    [setTheme],
  )
  return { theme, setTheme, toggle }
}
