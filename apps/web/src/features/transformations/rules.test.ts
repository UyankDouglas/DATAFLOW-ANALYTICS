import { describe, expect, it } from 'vitest'

import type { ColumnSpec, Rule } from '@/types/api'

import { defaultRule, describeRule, insertRule, moveRule, simulateSchema } from './rules'

const input: ColumnSpec[] = [
  { name: 'data', data_type: 'text' },
  { name: 'vendedor', data_type: 'text' },
  { name: 'valor', data_type: 'decimal', scale: 2 },
  { name: 'qtd', data_type: 'integer' },
]

describe('simulação do esquema', () => {
  it('acompanha conversões, renomeações e colunas derivadas na ordem das regras', () => {
    const rules: Rule[] = [
      {
        operation: 'standardize_dates',
        enabled: true,
        column: 'data',
        target: 'date',
        formats: ['%d/%m/%Y'],
      },
      { operation: 'rename_columns', enabled: true, mapping: { vendedor: 'responsavel' } },
      {
        operation: 'derived_column',
        enabled: true,
        name: 'preco_medio',
        expression: {
          kind: 'arithmetic',
          operator: 'divide',
          left: { column: 'valor' },
          right: { column: 'qtd' },
          scale: 4,
        },
      },
      { operation: 'deduplicate', enabled: true, columns: ['responsavel'], keep: 'first' },
    ]
    const { before, output } = simulateSchema(rules, input)
    expect(before[1]?.find((c) => c.name === 'data')?.data_type).toBe('date')
    expect(before[3]?.map((c) => c.name)).toEqual([
      'data',
      'responsavel',
      'valor',
      'qtd',
      'preco_medio',
    ])
    expect(output.at(-1)).toEqual({ name: 'preco_medio', data_type: 'decimal', scale: 4 })
  })

  it('ignora regras desativadas', () => {
    const rules: Rule[] = [
      { operation: 'rename_columns', enabled: false, mapping: { valor: 'total' } },
    ]
    expect(simulateSchema(rules, input).output.map((c) => c.name)).toContain('valor')
  })

  it('tipa colunas derivadas como o servidor', () => {
    const datePart = defaultRule('derived_column', [{ name: 'd', data_type: 'date' }])
    expect(datePart.operation).toBe('derived_column')
    const rules: Rule[] = [
      {
        operation: 'derived_column',
        enabled: true,
        name: 'mes',
        expression: { kind: 'date_part', column: 'd', part: 'year_month' },
      },
      {
        operation: 'derived_column',
        enabled: true,
        name: 'dias',
        expression: { kind: 'date_diff_days', start: 'd', end: 'd' },
      },
    ]
    const output = simulateSchema(rules, [{ name: 'd', data_type: 'date' }]).output
    expect(output.map((c) => c.data_type)).toEqual(['date', 'text', 'integer'])
  })
})

describe('edição da lista de regras', () => {
  const dedup = defaultRule('deduplicate', input)

  it('mantém a deduplicação como última regra ao inserir', () => {
    const rules = insertRule([dedup], defaultRule('trim', input))
    expect(rules.map((r) => r.operation)).toEqual(['trim', 'deduplicate'])
  })

  it('move regras sem sair dos limites', () => {
    const rules = [defaultRule('trim', input), defaultRule('remove_empty_rows', input)]
    expect(moveRule(rules, 0, 1).map((r) => r.operation)).toEqual(['remove_empty_rows', 'trim'])
    expect(moveRule(rules, 0, -1)).toBe(rules)
  })

  it('sugere colunas de texto e operandos numéricos por padrão', () => {
    const trim = defaultRule('trim', input)
    expect(trim.operation === 'trim' && trim.columns).toEqual(['data', 'vendedor'])
    const derived = defaultRule('derived_column', input)
    expect(derived.operation === 'derived_column' && derived.expression).toMatchObject({
      kind: 'arithmetic',
      left: { column: 'valor' },
      right: { column: 'qtd' },
    })
  })
})

describe('resumo das regras', () => {
  it('descreve filtros e deduplicação em português', () => {
    expect(
      describeRule({
        operation: 'filter_rows',
        enabled: true,
        match: 'any',
        conditions: [
          { column: 'equipe', operator: 'in', values: ['Norte', 'Sul'] },
          { column: 'valor', operator: 'between', value: '10', value_to: '20' },
        ],
      }),
    ).toBe('equipe está em (Norte, Sul) ou valor entre 10 e 20')
    expect(describeRule(defaultRule('deduplicate', input))).toBe(
      'chave: todas as colunas · manter o primeiro',
    )
  })
})
