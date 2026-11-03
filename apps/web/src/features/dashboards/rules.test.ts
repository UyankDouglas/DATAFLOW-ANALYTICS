import { describe, expect, it } from 'vitest'

import type { ColumnSpec, WidgetConfig } from '@/types/api'

import { adaptToChart, aggregationsFor, defaultWidget, widgetProblem } from './rules'

const schema: ColumnSpec[] = [
  { name: 'data_venda', data_type: 'date' },
  { name: 'equipe', data_type: 'text' },
  { name: 'quantidade', data_type: 'integer' },
  { name: 'valor', data_type: 'decimal', scale: 2 },
]

const widget = (overrides: Partial<WidgetConfig>): WidgetConfig => ({
  title: 'Widget',
  chart_type: 'bar',
  size: 'medium',
  query: { metrics: [{ aggregation: 'count' }], dimension: { column: 'equipe' } },
  ...overrides,
})

describe('aggregationsFor', () => {
  it('oferece só agregações que fazem sentido para o tipo', () => {
    expect(aggregationsFor(null)).toEqual(['count'])
    expect(aggregationsFor('text')).toEqual(['count', 'count_distinct'])
    expect(aggregationsFor('date')).not.toContain('sum')
    expect(aggregationsFor('decimal')).toContain('avg')
  })
})

describe('widgetProblem', () => {
  it('aceita uma configuração completa', () => {
    expect(widgetProblem(widget({}), schema)).toBeNull()
  })

  it.each([
    [
      'pizza com média',
      widget({
        chart_type: 'pie',
        query: {
          metrics: [{ aggregation: 'avg', column: 'valor' }],
          dimension: { column: 'equipe' },
        },
      }),
      'partes de um todo',
    ],
    [
      'KPI com dimensão',
      widget({
        chart_type: 'kpi',
        query: { metrics: [{ aggregation: 'count' }], dimension: { column: 'equipe' } },
      }),
      'não tem dimensão',
    ],
    [
      'decimal como dimensão',
      widget({ query: { metrics: [{ aggregation: 'count' }], dimension: { column: 'valor' } } }),
      'faixa',
    ],
    [
      'gráfico sem dimensão',
      widget({ query: { metrics: [{ aggregation: 'count' }] } }),
      'dimensão',
    ],
    [
      'soma de texto',
      widget({
        query: {
          metrics: [{ aggregation: 'sum', column: 'equipe' }],
          dimension: { column: 'equipe' },
        },
      }),
      'agregação incompatível',
    ],
    [
      'linha comparando períodos',
      widget({
        chart_type: 'line',
        query: {
          metrics: [{ aggregation: 'count' }],
          dimension: { column: 'data_venda', granularity: 'month' },
          comparison: { column: 'data_venda', start: '2025-01-01', end: '2025-01-31' },
        },
      }),
      'não compara',
    ],
    [
      'coluna que sumiu',
      widget({
        query: {
          metrics: [{ aggregation: 'max', column: 'preco' }],
          dimension: { column: 'equipe' },
        },
      }),
      'indisponível',
    ],
  ])('recusa %s', (_case, config, message) => {
    expect(widgetProblem(config, schema)).toContain(message)
  })
})

describe('defaultWidget', () => {
  it('começa contando registros: a medida numérica é escolha do usuário', () => {
    for (const type of ['kpi', 'bar', 'line', 'table'] as const) {
      expect(defaultWidget(type, schema).query.metrics).toEqual([
        { aggregation: 'count', column: null },
      ])
    }
    expect(defaultWidget('line', schema).query.dimension).toEqual({
      column: 'data_venda',
      granularity: 'month',
    })
    expect(defaultWidget('bar', schema).query.dimension).toEqual({ column: 'equipe' })
    expect(defaultWidget('kpi', schema).query.dimension).toBeUndefined()
  })
})

describe('adaptToChart', () => {
  it('ajusta a consulta ao trocar o tipo de gráfico', () => {
    const table = widget({
      chart_type: 'table',
      query: {
        metrics: [{ aggregation: 'avg', column: 'valor' }, { aggregation: 'count' }],
        dimension: { column: 'equipe' },
      },
    })
    const pie = adaptToChart(table, 'donut', schema)
    expect(pie.query.metrics).toEqual([{ aggregation: 'sum', column: 'valor' }])
    expect(widgetProblem(pie, schema)).toBeNull()
    const kpi = adaptToChart(table, 'kpi', schema)
    expect(kpi.query.dimension).toBeNull()
    expect(kpi.query.metrics).toHaveLength(1)
  })
})
