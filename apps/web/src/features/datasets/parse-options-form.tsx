import { RefreshCw } from 'lucide-react'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import type { ParseOptions } from '@/types/api'

const ENCODINGS: Record<ParseOptions['encoding'], string> = {
  'utf-8': 'UTF-8',
  'windows-1252': 'Windows-1252 (ANSI)',
  'iso-8859-1': 'ISO-8859-1 (Latin-1)',
}
const DELIMITERS: Record<string, string> = {
  ',': 'Vírgula ( , )',
  ';': 'Ponto e vírgula ( ; )',
  '\t': 'Tabulação',
  '|': 'Barra vertical ( | )',
}
const DECIMALS: Record<string, string> = { '.': 'Ponto ( 1234.56 )', ',': 'Vírgula ( 1234,56 )' }
const THOUSANDS: Record<string, string> = {
  none: 'Nenhum',
  '.': 'Ponto ( 1.234 )',
  ',': 'Vírgula ( 1,234 )',
  ' ': 'Espaço ( 1 234 )',
}

interface ParseOptionsFormProps {
  value: ParseOptions
  onApply: (options: ParseOptions) => void
  pending?: boolean
  disabled?: boolean
}

export function ParseOptionsForm({ value, onApply, pending, disabled }: ParseOptionsFormProps) {
  const [draft, setDraft] = useState(value)
  const [nullText, setNullText] = useState(value.null_values.filter(Boolean).join(', '))
  const [emptyIsNull, setEmptyIsNull] = useState(value.null_values.includes(''))
  const set = <K extends keyof ParseOptions>(key: K, next: ParseOptions[K]) =>
    setDraft((current) => ({ ...current, [key]: next }))

  const apply = () => {
    const tokens = nullText
      .split(',')
      .map((token) => token.trim())
      .filter(Boolean)
    onApply({ ...draft, null_values: [...(emptyIsNull ? [''] : []), ...tokens] })
  }

  return (
    <div className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <OptionSelect
          label="Encoding"
          value={draft.encoding}
          options={ENCODINGS}
          onChange={(v) => set('encoding', v as ParseOptions['encoding'])}
          disabled={disabled}
        />
        <OptionSelect
          label="Delimitador"
          value={draft.delimiter}
          options={DELIMITERS}
          onChange={(v) => set('delimiter', v as ParseOptions['delimiter'])}
          disabled={disabled}
        />
        <OptionSelect
          label="Separador decimal"
          value={draft.decimal_separator}
          options={DECIMALS}
          onChange={(v) => set('decimal_separator', v as ParseOptions['decimal_separator'])}
          disabled={disabled}
        />
        <OptionSelect
          label="Separador de milhar"
          value={draft.thousands_separator === '' ? 'none' : draft.thousands_separator}
          options={THOUSANDS}
          onChange={(v) =>
            set(
              'thousands_separator',
              (v === 'none' ? '' : v) as ParseOptions['thousands_separator'],
            )
          }
          disabled={disabled}
        />
        <div className="space-y-1.5 sm:col-span-2">
          <Label htmlFor="null-values">Valores tratados como nulos</Label>
          <Input
            id="null-values"
            value={nullText}
            onChange={(event) => setNullText(event.target.value)}
            placeholder="NULL, null, N/A"
            disabled={disabled}
            aria-describedby="null-values-hint"
          />
          <p id="null-values-hint" className="text-xs text-muted-foreground">
            Separe por vírgula. Esses valores viram nulo em todas as colunas.
          </p>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
        <label className="flex items-center gap-2 text-sm">
          <Checkbox
            checked={draft.has_header}
            onCheckedChange={(checked) => set('has_header', checked === true)}
            disabled={disabled}
          />
          Primeira linha é o cabeçalho
        </label>
        <label className="flex items-center gap-2 text-sm">
          <Checkbox
            checked={emptyIsNull}
            onCheckedChange={(checked) => setEmptyIsNull(checked === true)}
            disabled={disabled}
          />
          Célula vazia é nulo
        </label>
        <div className="flex-1" />
        <Button variant="outline" onClick={apply} disabled={pending || disabled}>
          <RefreshCw className={pending ? 'animate-spin' : undefined} /> Aplicar e recarregar prévia
        </Button>
      </div>
    </div>
  )
}

function OptionSelect({
  label,
  value,
  options,
  onChange,
  disabled,
}: {
  label: string
  value: string
  options: Record<string, string>
  onChange: (value: string) => void
  disabled?: boolean
}) {
  return (
    <div className="space-y-1.5">
      <Label>{label}</Label>
      <Select value={value} onValueChange={onChange} disabled={disabled}>
        <SelectTrigger className="w-full" aria-label={label}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {Object.entries(options).map(([key, text]) => (
            <SelectItem key={key} value={key}>
              {text}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  )
}
