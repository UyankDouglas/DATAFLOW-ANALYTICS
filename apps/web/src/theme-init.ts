// Aplica o tema salvo antes da renderização para evitar flash de tema incorreto.
import { applyTheme, readStoredTheme } from './hooks/use-theme'

applyTheme(readStoredTheme())
