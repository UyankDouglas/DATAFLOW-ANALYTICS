import { z } from 'zod'

import type { ColumnConfig, ColumnPreview, DataType, DatasetColumn, Preview } from '@/types/api'

export const DATA_TYPE_LABEL: Record<DataType, string> = {
  text: 'Texto',
  integer: 'Inteiro',
  decimal: 'Decimal',
  date: 'Data',
  datetime: 'Data e hora',
  boolean: 'Booleano',
}

export const DATE_FORMATS: Record<string, string> = {
  '%d/%m/%Y': 'dd/mm/aaaa',
  '%Y-%m-%d': 'aaaa-mm-dd',
  '%d-%m-%Y': 'dd-mm-aaaa',
  '%d.%m.%Y': 'dd.mm.aaaa',
  '%m/%d/%Y': 'mm/dd/aaaa',
  '%Y/%m/%d': 'aaaa/mm/dd',
}

export const DATETIME_FORMATS: Record<string, string> = {
  '%d/%m/%Y %H:%M:%S': 'dd/mm/aaaa hh:mm:ss',
  '%d/%m/%Y %H:%M': 'dd/mm/aaaa hh:mm',
  '%Y-%m-%d %H:%M:%S': 'aaaa-mm-dd hh:mm:ss',
  '%Y-%m-%dT%H:%M:%S': 'aaaa-mm-ddThh:mm:ss',
  '%Y-%m-%d %H:%M': 'aaaa-mm-dd hh:mm',
  '%m/%d/%Y %H:%M:%S': 'mm/dd/aaaa hh:mm:ss',
}

export const WARNING_LABEL: Record<string, string> = {
  coluna_vazia_na_amostra: 'Coluna vazia na amostra',
  formato_de_data_ambiguo: 'Formato de data ambíguo',
  zeros_a_esquerda_preservados_como_texto: 'Zeros à esquerda: mantida como texto',
}

const RESERVED_PREFIX = '__df_'

const columnSchema = z
  .object({
    position: z.number().int(),
    source_name: z.string(),
    name: z
      .string()
      .trim()
      .min(1, 'Informe o nome da coluna.')
      .max(63, 'Máximo de 63 caracteres.')
      .refine(
        (value) => !value.toLowerCase().startsWith(RESERVED_PREFIX),
        `Prefixo "${RESERVED_PREFIX}" é reservado.`,
      )
      .refine(
        (value) => ![...value].some((char) => char === '"' || char.charCodeAt(0) < 32),
        'Contém caracteres não permitidos.',
      ),
    data_type: z.enum(['text', 'integer', 'decimal', 'date', 'datetime', 'boolean']),
    format: z.string().nullable(),
    scale: z.number().int().min(0, 'Mínimo 0.').max(18, 'Máximo 18.').nullable(),
  })
  .superRefine((column, ctx) => {
    if (column.data_type === 'date' && !(column.format && column.format in DATE_FORMATS)) {
      ctx.addIssue({ code: 'custom', path: ['format'], message: 'Escolha o formato da data.' })
    }
    if (column.data_type === 'datetime' && !(column.format && column.format in DATETIME_FORMATS)) {
      ctx.addIssue({
        code: 'custom',
        path: ['format'],
        message: 'Escolha o formato de data e hora.',
      })
    }
    if (column.data_type === 'decimal' && column.scale === null) {
      ctx.addIssue({ code: 'custom', path: ['scale'], message: 'Informe as casas decimais.' })
    }
  })

export const importFormSchema = z
  .object({ columns: z.array(columnSchema).min(1), confirm_ambiguous: z.boolean() })
  .superRefine((form, ctx) => {
    const seen = new Map<string, number>()
    form.columns.forEach((column, index) => {
      const key = column.name.trim().normalize('NFC').toLocaleLowerCase('pt-BR')
      const first = seen.get(key)
      if (first !== undefined) {
        ctx.addIssue({
          code: 'custom',
          path: ['columns', index, 'name'],
          message: 'Nome duplicado.',
        })
        ctx.addIssue({
          code: 'custom',
          path: ['columns', first, 'name'],
          message: 'Nome duplicado.',
        })
      } else {
        seen.set(key, index)
      }
    })
  })

export type ImportFormValues = z.infer<typeof importFormSchema>

function fromInference(column: ColumnPreview, header: string): ColumnConfig {
  return {
    position: column.position,
    source_name: header,
    name: header,
    data_type: column.inferred_type,
    format: column.format,
    scale: column.scale,
  }
}

/** Reaproveita o mapeamento salvo quando ele corresponde ao cabeçalho atual. */
export function initialColumns(preview: Preview): ColumnConfig[] {
  const saved = preview.saved_columns
  const matchesSaved =
    saved.length === preview.header.length &&
    saved.every((column, index) => column.source_name === preview.header[index])
  if (matchesSaved) {
    return saved.map((column: DatasetColumn) => {
      const inferred = preview.columns[column.position]
      return {
        position: column.position,
        source_name: column.source_name,
        name: column.name,
        data_type: column.data_type,
        format: column.format,
        scale: column.data_type === 'decimal' ? (inferred?.scale ?? 2) : null,
      }
    })
  }
  return preview.columns.map((column, index) =>
    fromInference(column, preview.header[index] ?? `coluna_${index + 1}`),
  )
}

/** Colunas cujo formato escolhido está entre os formatos ambíguos detectados. */
export function ambiguousColumns(values: ColumnConfig[], preview: Preview): string[] {
  return values
    .filter((column) => {
      if (column.data_type !== 'date' && column.data_type !== 'datetime') return false
      const inferred = preview.columns[column.position]
      return Boolean(column.format && inferred?.ambiguous_formats.includes(column.format))
    })
    .map((column) => column.name)
}
