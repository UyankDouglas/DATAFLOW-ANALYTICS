import { formatInteger } from '@/lib/format'
import type { AggregateResult, MetricInfo } from '@/types/api'

import { formatKey, toNumber } from './format'

export const COLORS = [
  'var(--chart-1)',
  'var(--chart-2)',
  'var(--chart-3)',
  'var(--chart-4)',
  'var(--chart-5)',
  'var(--primary)',
]

export interface Series {
  key: string
  label: string
  metric: MetricInfo
  color: string
  previous: boolean
}

export interface Point {
  label: string
  others?: boolean
  [key: string]: unknown
}

/** Pontos do gráfico: cada medida vira uma série; com comparação, também a anterior. */
export function chartData(
  result: AggregateResult,
  includeOthers: boolean,
): { points: Point[]; series: Series[] } {
  const series: Series[] = result.metrics.flatMap((metric, index) => {
    const color = COLORS[index % COLORS.length] ?? 'var(--chart-1)'
    const current = { key: `s${index}`, label: metric.label, metric, color, previous: false }
    if (!result.comparison) return [current]
    return [
      { ...current, label: `${metric.label} (atual)` },
      {
        key: `p${index}`,
        label: `${metric.label} (anterior)`,
        metric,
        color,
        previous: true,
      },
    ]
  })
  const toPoint = (
    label: string,
    values: unknown[],
    previous: unknown[] | null,
    others = false,
  ): Point => {
    const point: Point = { label, others }
    result.metrics.forEach((_, index) => {
      point[`s${index}`] = toNumber(values[index])
      point[`raw_s${index}`] = values[index]
      if (previous) {
        point[`p${index}`] = toNumber(previous[index])
        point[`raw_p${index}`] = previous[index]
      }
    })
    return point
  }
  const points = result.rows.map((row) =>
    toPoint(formatKey(row.key, result.dimension), row.values, row.previous),
  )
  if (includeOthers && result.others) {
    points.push(
      toPoint(
        `Outros (${formatInteger(result.others.groups)})`,
        result.others.values,
        result.others.previous,
        true,
      ),
    )
  }
  return { points, series }
}
