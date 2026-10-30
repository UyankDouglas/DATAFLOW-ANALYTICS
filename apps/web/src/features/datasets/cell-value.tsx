import {
  formatBoolean,
  formatDate,
  formatDecimal,
  formatInteger,
  formatNaiveDateTime,
} from '@/lib/format'
import type { DataType } from '@/types/api'

/** Renderiza um valor conforme o tipo da coluna. Nunca aplica formato monetário. */
export function CellValue({ value, type }: { value: unknown; type: DataType }) {
  if (value === null || value === undefined) {
    return <span className="text-muted-foreground/70 italic">nulo</span>
  }
  switch (type) {
    case 'integer':
      return (
        <span className="tabular block text-right">{formatInteger(value as number | string)}</span>
      )
    case 'decimal':
      return <span className="tabular block text-right">{formatDecimal(value as string)}</span>
    case 'date':
      return <span className="tabular">{formatDate(value as string)}</span>
    case 'datetime':
      return (
        <span className="tabular whitespace-nowrap">{formatNaiveDateTime(value as string)}</span>
      )
    case 'boolean':
      return <span>{formatBoolean(value as boolean)}</span>
    default:
      return (
        <span className="block max-w-80 truncate" title={String(value)}>
          {String(value)}
        </span>
      )
  }
}
