import { describe, expect, it } from 'vitest'

import {
  defaultPeriod,
  describeCondition,
  formatKey,
  formatMetricValue,
  formatVariation,
  variation,
} from './format'

describe('formatMetricValue', () => {
  it('formata pelo tipo do resultado, sem símbolo de moeda', () => {
    expect(formatMetricValue('7082.75', { data_type: 'decimal', scale: 2 })).toBe('7.082,75')
    expect(formatMetricValue('1180.4583', { data_type: 'decimal', scale: 4 })).toBe('1.180,4583')
    expect(formatMetricValue(1234567, { data_type: 'integer' })).toBe('1.234.567')
    // Inteiros acima de 2^53 chegam como texto e não perdem dígitos.
    expect(formatMetricValue('9007199254740993', { data_type: 'integer' })).toBe(
      '9.007.199.254.740.993',
    )
    expect(formatMetricValue('2025-01-05', { data_type: 'date' })).toBe('05/01/2025')
    expect(formatMetricValue(null, { data_type: 'decimal' })).toBe('—')
  })
})

describe('formatKey', () => {
  const temporal = (granularity: 'day' | 'week' | 'month' | 'quarter' | 'year') => ({
    column: 'data_venda',
    data_type: 'date' as const,
    granularity,
  })

  it('rotula datas pela granularidade', () => {
    expect(formatKey('2025-02-01', temporal('month'))).toBe('fev/2025')
    expect(formatKey('2025-04-01', temporal('quarter'))).toBe('2º tri/2025')
    expect(formatKey('2024-12-30', temporal('week'))).toBe('Sem. 30/12/2024')
    expect(formatKey('2025-01-01', temporal('year'))).toBe('2025')
    expect(formatKey('2025-01-13', temporal('day'))).toBe('13/01/2025')
  })

  it('mostra o grupo sem valor e booleanos por extenso', () => {
    const text = { column: 'equipe', data_type: 'text' as const, granularity: null }
    expect(formatKey(null, text)).toBe('(sem valor)')
    expect(formatKey('Norte', text)).toBe('Norte')
    expect(formatKey(true, { column: 'ativo', data_type: 'boolean', granularity: null })).toBe(
      'Sim',
    )
    expect(formatKey(1000, { column: 'loja', data_type: 'integer', granularity: null })).toBe(
      '1.000',
    )
  })
})

describe('variation', () => {
  it('compara o período atual com o anterior', () => {
    expect(variation('1093.95', '5988.80')).toBeCloseTo(-0.8173, 4)
    expect(formatVariation(variation(500230.82, 298038.53))).toBe('+67,8%')
    expect(formatVariation(variation(10, 10))).toBe('0%')
  })

  it('não inventa variação sem base de comparação', () => {
    expect(variation(10, 0)).toBeNull()
    expect(variation(10, null)).toBeNull()
    expect(formatVariation(null)).toBe('—')
  })
})

describe('defaultPeriod', () => {
  it('sugere os 30 dias mais recentes até a última data', () => {
    expect(defaultPeriod('2025-12-31')).toEqual({ start: '2025-12-02', end: '2025-12-31' })
    expect(defaultPeriod('2025-03-15T12:28:24')).toEqual({ start: '2025-02-14', end: '2025-03-15' })
  })
})

describe('describeCondition', () => {
  it('descreve filtros salvos em português', () => {
    expect(
      describeCondition({ column: 'valor', operator: 'between', value: '100', value_to: '500' }),
    ).toBe('valor entre 100 e 500')
    expect(
      describeCondition({ column: 'status', operator: 'in', values: ['pago', 'pendente'] }),
    ).toBe('status está em pago, pendente')
    expect(describeCondition({ column: 'equipe', operator: 'is_null' })).toBe('equipe é nulo')
  })
})
