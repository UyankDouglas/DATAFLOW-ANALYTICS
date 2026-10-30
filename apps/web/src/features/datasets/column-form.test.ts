import { describe, expect, it } from 'vitest'

import type { ColumnConfig, Preview } from '@/types/api'

import { ambiguousColumns, importFormSchema, initialColumns } from './column-form'

const column = (overrides: Partial<ColumnConfig>): ColumnConfig => ({
  position: 0,
  source_name: 'a',
  name: 'a',
  data_type: 'text',
  format: null,
  scale: null,
  ...overrides,
})

describe('validação do mapeamento de colunas', () => {
  it('rejeita nomes duplicados sem diferenciar maiúsculas', () => {
    const result = importFormSchema.safeParse({
      columns: [
        column({ name: 'Valor' }),
        column({ position: 1, source_name: 'b', name: ' valor ' }),
      ],
      confirm_ambiguous: false,
    })
    expect(result.success).toBe(false)
    const paths = result.error?.issues.map((issue) => issue.path.join('.'))
    expect(paths).toContain('columns.0.name')
    expect(paths).toContain('columns.1.name')
  })

  it('exige formato para datas e escala para decimais', () => {
    const result = importFormSchema.safeParse({
      columns: [
        column({ data_type: 'date' }),
        column({ position: 1, name: 'v', data_type: 'decimal' }),
      ],
      confirm_ambiguous: false,
    })
    expect(result.error?.issues.map((issue) => issue.message)).toEqual(
      expect.arrayContaining(['Escolha o formato da data.', 'Informe as casas decimais.']),
    )
  })

  it('bloqueia prefixo reservado e caracteres de controle', () => {
    expect(
      importFormSchema.safeParse({
        columns: [column({ name: '__df_row' })],
        confirm_ambiguous: false,
      }).success,
    ).toBe(false)
    expect(
      importFormSchema.safeParse({ columns: [column({ name: 'a"b' })], confirm_ambiguous: false })
        .success,
    ).toBe(false)
  })
})

const preview = {
  header: ['data', 'valor'],
  columns: [
    {
      position: 0,
      inferred_type: 'date',
      format: '%d/%m/%Y',
      scale: null,
      ambiguous_formats: ['%d/%m/%Y', '%m/%d/%Y'],
    },
    { position: 1, inferred_type: 'decimal', format: null, scale: 2, ambiguous_formats: [] },
  ],
  saved_columns: [],
} as unknown as Preview

describe('estado inicial e ambiguidades', () => {
  it('usa a inferência quando não há mapeamento salvo', () => {
    const initial = initialColumns(preview)
    expect(initial.map((c) => [c.name, c.data_type, c.format, c.scale])).toEqual([
      ['data', 'date', '%d/%m/%Y', null],
      ['valor', 'decimal', null, 2],
    ])
  })

  it('reaproveita o mapeamento salvo quando corresponde ao cabeçalho', () => {
    const saved = {
      ...preview,
      saved_columns: [
        {
          position: 0,
          source_name: 'data',
          name: 'data_venda',
          data_type: 'date',
          inferred_type: 'date',
          format: '%m/%d/%Y',
        },
        {
          position: 1,
          source_name: 'valor',
          name: 'valor_total',
          data_type: 'text',
          inferred_type: 'decimal',
          format: null,
        },
      ],
    } as Preview
    expect(initialColumns(saved).map((c) => c.name)).toEqual(['data_venda', 'valor_total'])
  })

  it('detecta colunas com formato de data ambíguo', () => {
    expect(ambiguousColumns(initialColumns(preview), preview)).toEqual(['data'])
  })
})
