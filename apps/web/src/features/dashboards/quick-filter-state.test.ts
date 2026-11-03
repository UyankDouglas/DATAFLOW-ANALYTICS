import { describe, expect, it } from 'vitest'

import type { ColumnSpec } from '@/types/api'

import { EMPTY_QUICK_FILTERS, activeFilterCount, quickFilterSets } from './quick-filter-state'

const schema: ColumnSpec[] = [
  { name: 'data_venda', data_type: 'date' },
  { name: 'atendido_em', data_type: 'datetime' },
  { name: 'status', data_type: 'text' },
  { name: 'vendedor', data_type: 'text' },
  { name: 'valor', data_type: 'decimal', scale: 2 },
]

describe('quickFilterSets', () => {
  it('sem filtros não envia grupos', () => {
    expect(quickFilterSets(EMPTY_QUICK_FILTERS, schema)).toEqual([])
  })

  it('combina período, valores e faixa com E', () => {
    const sets = quickFilterSets(
      {
        ...EMPTY_QUICK_FILTERS,
        period: { column: 'data_venda', start: '2025-02-01', end: '2025-02-28' },
        values: [
          { column: 'status', values: ['pago'] },
          { column: 'vendedor', values: [] }, // sem valores marcados: ignorado
        ],
        range: { column: 'valor', min: '100,50', max: '' },
      },
      schema,
    )
    expect(sets).toEqual([
      {
        match: 'all',
        filters: [
          {
            column: 'data_venda',
            operator: 'between',
            value: '2025-02-01',
            value_to: '2025-02-28',
          },
          { column: 'status', operator: 'in', values: ['pago'] },
          { column: 'valor', operator: 'gte', value: '100.50' },
        ],
      },
    ])
  })

  it('cobre o dia inteiro em colunas de data e hora', () => {
    const [set] = quickFilterSets(
      { ...EMPTY_QUICK_FILTERS, period: { column: 'atendido_em', start: '', end: '2025-06-30' } },
      schema,
    )
    expect(set?.filters).toEqual([
      { column: 'atendido_em', operator: 'lte', value: '2025-06-30 23:59:59' },
    ])
  })

  it('mantém os filtros avançados num grupo próprio, com o E/OU escolhido', () => {
    const state = {
      ...EMPTY_QUICK_FILTERS,
      range: { column: 'valor', min: '', max: '500' },
      advanced: {
        match: 'any' as const,
        filters: [
          { column: 'status', operator: 'eq' as const, value: 'pago' },
          { column: 'vendedor', operator: 'is_null' as const },
        ],
      },
    }
    const sets = quickFilterSets(state, schema)
    expect(sets).toHaveLength(2)
    expect(sets[1]).toEqual(state.advanced)
    expect(activeFilterCount(state, schema)).toBe(3)
  })

  it('ignora colunas que não existem na versão', () => {
    expect(
      quickFilterSets(
        { ...EMPTY_QUICK_FILTERS, values: [{ column: 'removida', values: ['x'] }] },
        schema,
      ),
    ).toEqual([])
  })
})
