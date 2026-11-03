import { CopyPlus, EyeOff, Loader2, RefreshCw } from 'lucide-react'
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
import type { ParseOptions, SheetInfo } from '@/types/api'

interface XlsxOptionsFormProps {
  value: ParseOptions
  sheets: SheetInfo[]
  dataRange: string | null
  onApply: (options: ParseOptions) => void
  onImportSheet?: (sheet: string) => void
  importingSheet?: string | null
  pending?: boolean
  disabled?: boolean
}

/** Leitura de planilha: aba, linha do cabeçalho e nulos. Fórmulas nunca são executadas. */
export function XlsxOptionsForm({
  value,
  sheets,
  dataRange,
  onApply,
  onImportSheet,
  importingSheet,
  pending,
  disabled,
}: XlsxOptionsFormProps) {
  const [draft, setDraft] = useState(value)
  const [headerRow, setHeaderRow] = useState(value.header_row ? String(value.header_row) : '')
  const [nullText, setNullText] = useState(value.null_values.filter(Boolean).join(', '))
  const [emptyIsNull, setEmptyIsNull] = useState(value.null_values.includes(''))
  const current = value.sheet ?? sheets[0]?.name
  const others = sheets.filter((sheet) => sheet.name !== current)
  const parsedRow = Number.parseInt(headerRow, 10)
  const rowInvalid = headerRow !== '' && !(parsedRow >= 1 && parsedRow <= 1000)

  const apply = () => {
    const tokens = nullText
      .split(',')
      .map((token) => token.trim())
      .filter(Boolean)
    onApply({
      ...draft,
      header_row: headerRow === '' ? null : parsedRow,
      null_values: [...(emptyIsNull ? [''] : []), ...tokens],
    })
  }

  return (
    <div className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <div className="space-y-1.5">
          <Label>Aba</Label>
          <Select
            value={draft.sheet ?? current ?? ''}
            onValueChange={(sheet) => {
              setDraft((state) => ({ ...state, sheet }))
              // Outra aba, outro layout: a linha do cabeçalho volta a ser detectada.
              if (sheet !== current) setHeaderRow('')
            }}
            disabled={disabled}
          >
            <SelectTrigger className="w-full" aria-label="Aba">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {sheets.map((sheet) => (
                <SelectItem key={sheet.name} value={sheet.name}>
                  {sheet.name}
                  {sheet.hidden ? ' (oculta)' : ''}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="header-row">Linha do cabeçalho</Label>
          <Input
            id="header-row"
            inputMode="numeric"
            value={headerRow}
            onChange={(event) => setHeaderRow(event.target.value.replace(/\D/g, ''))}
            placeholder="Detectar automaticamente"
            aria-invalid={rowInvalid}
            aria-describedby="header-row-hint"
            disabled={disabled}
          />
          <p
            id="header-row-hint"
            className={rowInvalid ? 'text-xs text-destructive' : 'text-xs text-muted-foreground'}
          >
            {rowInvalid
              ? 'Informe uma linha entre 1 e 1000.'
              : `Intervalo de dados detectado: ${dataRange ?? '—'}`}
          </p>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="xlsx-null-values">Valores tratados como nulos</Label>
          <Input
            id="xlsx-null-values"
            value={nullText}
            onChange={(event) => setNullText(event.target.value)}
            placeholder="NULL, N/A, -"
            disabled={disabled}
          />
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
        <label className="flex items-center gap-2 text-sm">
          <Checkbox
            checked={draft.has_header}
            onCheckedChange={(checked) =>
              setDraft((state) => ({ ...state, has_header: checked === true }))
            }
            disabled={disabled}
          />
          A linha indicada é o cabeçalho
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
        <Button variant="outline" onClick={apply} disabled={pending || disabled || rowInvalid}>
          <RefreshCw className={pending ? 'animate-spin' : undefined} /> Aplicar e recarregar prévia
        </Button>
      </div>

      {others.length > 0 && onImportSheet && (
        <div className="rounded-lg border bg-muted/30 p-3">
          <p className="text-sm font-medium">Outras abas desta planilha</p>
          <p className="text-xs text-muted-foreground">
            Cada aba pode virar um dataset independente, com mapeamento e versões próprios.
          </p>
          <ul className="mt-2 flex flex-wrap gap-2">
            {others.map((sheet) => (
              <li key={sheet.name}>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => onImportSheet(sheet.name)}
                  disabled={disabled || Boolean(importingSheet)}
                  aria-label={`Importar a aba ${sheet.name} como novo dataset`}
                >
                  {importingSheet === sheet.name ? (
                    <Loader2 className="animate-spin" />
                  ) : sheet.hidden ? (
                    <EyeOff />
                  ) : (
                    <CopyPlus />
                  )}
                  {sheet.name}
                </Button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
