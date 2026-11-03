import type { ColumnSpec, Condition, FilterSet } from '@/types/api'

export interface QuickFilterState {
  period: { column: string; start: string; end: string }
  values: { column: string; values: string[] }[]
  range: { column: string; min: string; max: string }
  advanced: FilterSet
}

export const EMPTY_QUICK_FILTERS: QuickFilterState = {
  period: { column: '', start: '', end: '' },
  values: [],
  range: { column: '', min: '', max: '' },
  advanced: { filters: [], match: 'all' },
}

/**
 * Filtros da tela em grupos para a API: os rápidos (período, valores, faixa) combinados com E,
 * e os avançados com o E/OU escolhido. Datas viram o dia inteiro em colunas de data e hora.
 */
export function quickFilterSets(state: QuickFilterState, schema: ColumnSpec[]): FilterSet[] {
  const quick: Condition[] = []
  const typeOf = (name: string) => schema.find((c) => c.name === name)?.data_type
  const { period, range } = state
  if (period.column && typeOf(period.column)) {
    const datetime = typeOf(period.column) === 'datetime'
    const start = period.start && (datetime ? `${period.start} 00:00:00` : period.start)
    const end = period.end && (datetime ? `${period.end} 23:59:59` : period.end)
    if (start && end)
      quick.push({ column: period.column, operator: 'between', value: start, value_to: end })
    else if (start) quick.push({ column: period.column, operator: 'gte', value: start })
    else if (end) quick.push({ column: period.column, operator: 'lte', value: end })
  }
  for (const entry of state.values) {
    if (entry.column && typeOf(entry.column) && entry.values.length > 0)
      quick.push({ column: entry.column, operator: 'in', values: entry.values })
  }
  if (range.column && typeOf(range.column)) {
    const min = range.min.trim().replace(',', '.')
    const max = range.max.trim().replace(',', '.')
    if (min && max)
      quick.push({ column: range.column, operator: 'between', value: min, value_to: max })
    else if (min) quick.push({ column: range.column, operator: 'gte', value: min })
    else if (max) quick.push({ column: range.column, operator: 'lte', value: max })
  }
  const sets: FilterSet[] = []
  if (quick.length > 0) sets.push({ filters: quick, match: 'all' })
  if (state.advanced.filters.length > 0) sets.push(state.advanced)
  return sets
}

export function activeFilterCount(state: QuickFilterState, schema: ColumnSpec[]): number {
  return quickFilterSets(state, schema).reduce((sum, set) => sum + set.filters.length, 0)
}
