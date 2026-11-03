import { useQuery } from '@tanstack/react-query'
import { Filter, Plus, SlidersHorizontal, X } from 'lucide-react'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
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
import { qualityApi } from '@/features/quality/api'
import { FilterEditor } from '@/features/transformations/rule-editor'
import { formatInteger } from '@/lib/format'
import type { ColumnSpec } from '@/types/api'

import { formatKey } from './format'
import { EMPTY_QUICK_FILTERS, activeFilterCount, type QuickFilterState } from './quick-filter-state'
import { numericColumns, temporalColumns, textColumns } from './rules'

const MAX_VALUE_FILTERS = 3
const NONE = '__none__'

function ColumnChoice({
  label,
  columns,
  value,
  onChange,
}: {
  label: string
  columns: ColumnSpec[]
  value: string
  onChange: (value: string) => void
}) {
  return (
    <div className="min-w-0 space-y-1.5">
      <Label className="text-xs">{label}</Label>
      <Select value={value || NONE} onValueChange={(next) => onChange(next === NONE ? '' : next)}>
        <SelectTrigger size="sm" className="w-full" aria-label={label}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={NONE}>Nenhuma</SelectItem>
          {columns.map((c) => (
            <SelectItem key={c.name} value={c.name}>
              {c.name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  )
}

/** Valores mais frequentes da coluna (lidos da versão), para marcar quais manter. */
function ValueChoices({
  datasetId,
  versionId,
  column,
  value,
  onChange,
}: {
  datasetId: string
  versionId: string
  column: string
  value: string[]
  onChange: (values: string[]) => void
}) {
  const frequency = useQuery({
    queryKey: ['quality', datasetId, versionId, 'values', column, 50],
    queryFn: () => qualityApi.values(datasetId, versionId, column, 50),
    enabled: Boolean(column),
    staleTime: Infinity, // versões são imutáveis
  })
  if (!column) return null
  if (frequency.isPending)
    return <p className="text-xs text-muted-foreground">Carregando valores…</p>
  if (frequency.isError)
    return <p className="text-xs text-destructive">Não foi possível listar os valores.</p>
  const options = frequency.data.values.map((v) => String(v.value))
  return (
    <fieldset className="space-y-1">
      <legend className="sr-only">Valores de {column}</legend>
      <div className="max-h-36 space-y-1 overflow-y-auto rounded-md border p-2">
        {frequency.data.values.map((v) => {
          const text = String(v.value)
          return (
            <label key={text} className="flex items-center gap-2 text-sm">
              <Checkbox
                checked={value.includes(text)}
                aria-label={text}
                onCheckedChange={(checked) =>
                  onChange(checked === true ? [...value, text] : value.filter((x) => x !== text))
                }
              />
              <span className="min-w-0 flex-1 truncate">
                {formatKey(v.value, { column, data_type: 'text', granularity: null })}
              </span>
              <span className="tabular text-xs text-muted-foreground">
                {formatInteger(v.count)}
              </span>
            </label>
          )
        })}
      </div>
      {frequency.data.distinct > options.length && (
        <p className="text-xs text-muted-foreground">
          Mostrando os {options.length} valores mais frequentes de{' '}
          {formatInteger(frequency.data.distinct)}. Use os filtros avançados para outros.
        </p>
      )}
    </fieldset>
  )
}

export function QuickFilters({
  datasetId,
  versionId,
  schema,
  value,
  onApply,
}: {
  datasetId: string
  versionId: string
  schema: ColumnSpec[]
  value: QuickFilterState
  onApply: (next: QuickFilterState) => void
}) {
  const [draft, setDraft] = useState(value)
  const [advancedOpen, setAdvancedOpen] = useState(value.advanced.filters.length > 0)
  const temporal = temporalColumns(schema)
  const numeric = numericColumns(schema)
  const text = textColumns(schema)
  const applied = activeFilterCount(value, schema)
  const set = (patch: Partial<QuickFilterState>) => setDraft({ ...draft, ...patch })

  return (
    <Card>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="flex items-center gap-2 text-sm font-semibold">
            <Filter className="size-4" aria-hidden /> Filtros
            {applied > 0 && (
              <span className="rounded bg-primary/15 px-1.5 text-xs text-primary">
                {applied} aplicado{applied === 1 ? '' : 's'}
              </span>
            )}
          </h2>
          <p className="text-xs text-muted-foreground">
            Aplicados no servidor sobre os dados da versão, respeitando o tipo de cada coluna.
          </p>
        </div>

        <div className="grid gap-4 lg:grid-cols-3">
          <fieldset className="min-w-0 space-y-2">
            <legend className="mb-1 text-xs font-medium text-muted-foreground uppercase">
              Período
            </legend>
            <ColumnChoice
              label="Coluna de data"
              columns={temporal}
              value={draft.period.column}
              onChange={(column) => set({ period: { ...draft.period, column } })}
            />
            <div className="grid grid-cols-2 gap-2">
              <div className="space-y-1.5">
                <Label className="text-xs" htmlFor="periodo-inicio">
                  De
                </Label>
                <Input
                  id="periodo-inicio"
                  type="date"
                  value={draft.period.start}
                  disabled={!draft.period.column}
                  onChange={(e) => set({ period: { ...draft.period, start: e.target.value } })}
                />
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs" htmlFor="periodo-fim">
                  Até
                </Label>
                <Input
                  id="periodo-fim"
                  type="date"
                  value={draft.period.end}
                  disabled={!draft.period.column}
                  onChange={(e) => set({ period: { ...draft.period, end: e.target.value } })}
                />
              </div>
            </div>
          </fieldset>

          <fieldset className="min-w-0 space-y-2">
            <legend className="mb-1 text-xs font-medium text-muted-foreground uppercase">
              Categoria, status ou responsável
            </legend>
            {draft.values.map((entry, index) => (
              <div key={index} className="space-y-1.5 rounded-lg border p-2">
                <div className="flex items-end gap-1">
                  <div className="min-w-0 flex-1">
                    <ColumnChoice
                      label={`Coluna ${index + 1}`}
                      columns={text}
                      value={entry.column}
                      onChange={(column) =>
                        set({
                          values: draft.values.map((v, i) =>
                            i === index ? { column, values: [] } : v,
                          ),
                        })
                      }
                    />
                  </div>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label={`Remover filtro de valores ${index + 1}`}
                    onClick={() => set({ values: draft.values.filter((_, i) => i !== index) })}
                  >
                    <X />
                  </Button>
                </div>
                <ValueChoices
                  datasetId={datasetId}
                  versionId={versionId}
                  column={entry.column}
                  value={entry.values}
                  onChange={(values) =>
                    set({
                      values: draft.values.map((v, i) => (i === index ? { ...v, values } : v)),
                    })
                  }
                />
              </div>
            ))}
            <Button
              variant="outline"
              size="sm"
              disabled={text.length === 0 || draft.values.length >= MAX_VALUE_FILTERS}
              onClick={() =>
                set({ values: [...draft.values, { column: text[0]?.name ?? '', values: [] }] })
              }
            >
              <Plus /> Filtrar por valores
            </Button>
          </fieldset>

          <fieldset className="min-w-0 space-y-2">
            <legend className="mb-1 text-xs font-medium text-muted-foreground uppercase">
              Faixa de valores
            </legend>
            <ColumnChoice
              label="Coluna numérica"
              columns={numeric}
              value={draft.range.column}
              onChange={(column) => set({ range: { ...draft.range, column } })}
            />
            <div className="grid grid-cols-2 gap-2">
              <div className="space-y-1.5">
                <Label className="text-xs" htmlFor="faixa-min">
                  Mínimo
                </Label>
                <Input
                  id="faixa-min"
                  inputMode="decimal"
                  placeholder="ex.: 100"
                  value={draft.range.min}
                  disabled={!draft.range.column}
                  onChange={(e) => set({ range: { ...draft.range, min: e.target.value } })}
                />
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs" htmlFor="faixa-max">
                  Máximo
                </Label>
                <Input
                  id="faixa-max"
                  inputMode="decimal"
                  placeholder="ex.: 5000"
                  value={draft.range.max}
                  disabled={!draft.range.column}
                  onChange={(e) => set({ range: { ...draft.range, max: e.target.value } })}
                />
              </div>
            </div>
          </fieldset>
        </div>

        <div className="space-y-2">
          <Button
            variant="ghost"
            size="sm"
            aria-expanded={advancedOpen}
            onClick={() => {
              if (!advancedOpen && draft.advanced.filters.length === 0)
                set({
                  advanced: {
                    ...draft.advanced,
                    filters: [{ column: schema[0]?.name ?? '', operator: 'not_null' }],
                  },
                })
              setAdvancedOpen(!advancedOpen)
            }}
          >
            <SlidersHorizontal /> Filtros avançados (colunas personalizadas)
          </Button>
          {advancedOpen && draft.advanced.filters.length > 0 && (
            <FilterEditor
              conditions={draft.advanced.filters}
              match={draft.advanced.match}
              schema={schema}
              onChange={(filters, match) => set({ advanced: { filters, match } })}
            />
          )}
        </div>

        <div className="flex flex-wrap gap-2">
          <Button
            size="sm"
            onClick={() =>
              onApply(advancedOpen ? draft : { ...draft, advanced: EMPTY_QUICK_FILTERS.advanced })
            }
          >
            <Filter /> Aplicar filtros
          </Button>
          {(applied > 0 || draft !== value) && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                setDraft(EMPTY_QUICK_FILTERS)
                setAdvancedOpen(false)
                onApply(EMPTY_QUICK_FILTERS)
              }}
            >
              <X /> Limpar
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  )
}
