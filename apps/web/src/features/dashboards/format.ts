/**
 * Formatação dos resultados analíticos pelo tipo de cada medida e dimensão. Nenhuma medida
 * recebe símbolo de moeda: a API só informa tipo e escala, nunca o significado da coluna.
 */

import {
  AreaChart,
  BarChart3,
  BarChartHorizontal,
  Gauge,
  LineChart,
  PieChart,
  Table2,
  type LucideIcon,
} from 'lucide-react'

import { OPERATOR_LABEL } from '@/features/transformations/rules'
import {
  formatBoolean,
  formatDate,
  formatDecimal,
  formatInteger,
  formatNaiveDateTime,
} from '@/lib/format'
import type {
  AggregateResult,
  Aggregation,
  ChartType,
  Condition,
  DataType,
  Granularity,
} from '@/types/api'

export const AGGREGATION_LABEL: Record<Aggregation, string> = {
  count: 'Contagem',
  count_distinct: 'Contagem distinta',
  sum: 'Soma',
  avg: 'Média',
  min: 'Mínimo',
  max: 'Máximo',
}

export const GRANULARITY_LABEL: Record<Granularity, string> = {
  day: 'Dia',
  week: 'Semana',
  month: 'Mês',
  quarter: 'Trimestre',
  year: 'Ano',
}

export const CHART_TYPE_LABEL: Record<ChartType, string> = {
  kpi: 'Card KPI',
  line: 'Linha',
  area: 'Área',
  bar: 'Barras',
  bar_horizontal: 'Barras horizontais',
  pie: 'Pizza',
  donut: 'Rosca',
  table: 'Tabela analítica',
}

export const CHART_ICON: Record<ChartType, LucideIcon> = {
  kpi: Gauge,
  line: LineChart,
  area: AreaChart,
  bar: BarChart3,
  bar_horizontal: BarChartHorizontal,
  pie: PieChart,
  donut: PieChart,
  table: Table2,
}

/** "status igual a pago", "valor entre 100 e 500" — para listar filtros salvos. */
export function describeCondition(condition: Condition): string {
  const value =
    condition.values?.join(', ') ??
    [condition.value, condition.value_to].filter((v) => v !== null && v !== undefined).join(' e ')
  return `${condition.column} ${OPERATOR_LABEL[condition.operator]}${value ? ` ${value}` : ''}`
}

const MONTHS = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez']
const compact = new Intl.NumberFormat('pt-BR', { notation: 'compact', maximumFractionDigits: 1 })
const percent = new Intl.NumberFormat('pt-BR', {
  style: 'percent',
  maximumFractionDigits: 1,
  signDisplay: 'exceptZero',
})

export const EMPTY_KEY_LABEL = '(sem valor)'

interface Typed {
  data_type: DataType
  scale?: number | null
}

/** Valor exato de uma medida, no formato do seu tipo (decimais chegam como texto). */
export function formatMetricValue(value: unknown, metric: Typed): string {
  if (value === null || value === undefined) return '—'
  switch (metric.data_type) {
    case 'integer':
      return formatInteger(value as number | string)
    case 'decimal':
      return formatDecimal(value as string | number)
    case 'date':
      return formatDate(String(value))
    case 'datetime':
      return formatNaiveDateTime(String(value))
    case 'boolean':
      return formatBoolean(value as boolean)
    default:
      return String(value)
  }
}

/** Posição no gráfico. Pode perder precisão em números enormes; o rótulo usa o texto exato. */
export function toNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === '') return null
  const number = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(number) ? number : null
}

export function formatAxis(value: number): string {
  return compact.format(value)
}

/** Rótulo de um grupo: datas pela granularidade, booleanos por extenso, nulo explícito. */
export function formatKey(key: unknown, dimension: AggregateResult['dimension']): string {
  if (key === null || key === undefined) return EMPTY_KEY_LABEL
  if (!dimension) return ''
  const text = String(key)
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(text)
  if (dimension.granularity && match) {
    const [, year, month = '01'] = match
    const monthIndex = Number(month) - 1
    switch (dimension.granularity) {
      case 'day':
        return formatDate(text)
      case 'week':
        return `Sem. ${formatDate(text)}`
      case 'month':
        return `${MONTHS[monthIndex]}/${year}`
      case 'quarter':
        return `${Math.floor(monthIndex / 3) + 1}º tri/${year}`
      case 'year':
        return String(year)
    }
  }
  if (dimension.data_type === 'boolean') return formatBoolean(key as boolean)
  if (dimension.data_type === 'integer') return formatInteger(key as number | string)
  return text
}

/** Variação relativa entre o período atual e o anterior; nula sem base de comparação. */
export function variation(current: unknown, previous: unknown): number | null {
  const now = toNumber(current)
  const before = toNumber(previous)
  if (now === null || before === null || before === 0) return null
  return (now - before) / Math.abs(before)
}

export function formatVariation(ratio: number | null): string {
  return ratio === null ? '—' : percent.format(ratio)
}

/** Período no formato dd/mm/aaaa a dd/mm/aaaa. */
export function formatPeriod(start: string, end: string): string {
  return start === end ? formatDate(start) : `${formatDate(start)} a ${formatDate(end)}`
}

/** Últimos 30 dias até a data mais recente da coluna (no formato aaaa-mm-dd). */
export function defaultPeriod(max: string): { start: string; end: string } {
  const end = max.slice(0, 10)
  const date = new Date(`${end}T00:00:00Z`)
  date.setUTCDate(date.getUTCDate() - 29)
  return { start: date.toISOString().slice(0, 10), end }
}
