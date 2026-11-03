import type { Tone } from '@/features/jobs/status'
import type { QualityComponents } from '@/types/api'

/** Componentes da nota, na ordem e com os pesos documentados em docs/quality.md. */
export const COMPONENT_LABEL: Record<keyof QualityComponents, string> = {
  validity: 'Validade',
  completeness: 'Completude',
  uniqueness: 'Unicidade',
}

export const COMPONENT_HINT: Record<keyof QualityComponents, string> = {
  validity: 'Válidos ÷ (válidos + rejeitados). Filtrados e duplicados removidos não entram.',
  completeness: 'Células com valor ÷ células publicadas (registros válidos × colunas).',
  uniqueness: 'Registros publicados que não repetem outro em todas as colunas.',
}

/** Faixas só para leitura visual; não alteram a nota. */
export function scoreTone(score: number | null): Tone {
  if (score === null) return 'neutral'
  if (score >= 90) return 'success'
  if (score >= 70) return 'warning'
  return 'danger'
}

export function formatScore(score: number | null | undefined): string {
  if (score === null || score === undefined) return '—'
  return score.toLocaleString('pt-BR', { minimumFractionDigits: 1, maximumFractionDigits: 1 })
}

export function formatRatio(ratio: number | null | undefined): string {
  if (ratio === null || ratio === undefined) return '—'
  return `${(ratio * 100).toLocaleString('pt-BR', { maximumFractionDigits: 1 })}%`
}

/** Reproduz a nota a partir dos componentes (mesma fórmula do backend). */
export function scoreFromComponents(
  components: QualityComponents,
  weights: Record<keyof QualityComponents, number>,
): number {
  const total = (Object.keys(weights) as (keyof QualityComponents)[]).reduce(
    (sum, key) => sum + weights[key] * (components[key] ?? 0),
    0,
  )
  return Math.round(total * 1000) / 10
}
