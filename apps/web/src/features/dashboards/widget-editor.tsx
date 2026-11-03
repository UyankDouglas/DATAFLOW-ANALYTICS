import { Plus, X } from 'lucide-react'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { DATA_TYPE_LABEL } from '@/features/datasets/column-form'
import { FilterEditor } from '@/features/transformations/rule-editor'
import { isTemporal } from '@/features/transformations/rules'
import type {
  Aggregation,
  ColumnSpec,
  FilterSet,
  Granularity,
  Metric,
  WidgetConfig,
  WidgetSize,
} from '@/types/api'

import { AGGREGATION_LABEL, CHART_TYPE_LABEL, GRANULARITY_LABEL } from './format'
import {
  CHART_RULES,
  MAX_METRICS,
  PART_OF_WHOLE,
  adaptToChart,
  aggregationsFor,
  dimensionColumns,
  temporalColumns,
  widgetProblem,
} from './rules'
import { useAnalytics } from './use-analytics'
import { WidgetCard } from './widget-card'

const RECORDS = '__registros__'
const SIZE_LABEL: Record<WidgetSize, string> = {
  small: 'Pequeno (¼ da largura)',
  medium: 'Médio (½ da largura)',
  large: 'Grande (largura inteira)',
}

function Choice<T extends string>({
  label,
  value,
  options,
  onChange,
  id,
}: {
  label: string
  value: T
  options: Record<T, string>
  onChange: (value: T) => void
  id?: string
}) {
  return (
    <div className="min-w-0 space-y-1.5">
      <Label className="text-xs" htmlFor={id}>
        {label}
      </Label>
      <Select value={value} onValueChange={(next) => onChange(next as T)}>
        <SelectTrigger id={id} size="sm" className="w-full" aria-label={label}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {(Object.entries(options) as [T, string][]).map(([key, text]) => (
            <SelectItem key={key} value={key}>
              {text}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  )
}

const columnOptions = (columns: ColumnSpec[]) =>
  Object.fromEntries(
    columns.map((c) => [c.name, `${c.name} · ${DATA_TYPE_LABEL[c.data_type]}`]),
  ) as Record<string, string>

export function WidgetEditor({
  open,
  onOpenChange,
  initial,
  schema,
  datasetId,
  versionId,
  dashboardFilters,
  onSave,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  initial: WidgetConfig
  schema: ColumnSpec[]
  datasetId: string
  versionId: string | null
  dashboardFilters: FilterSet
  onSave: (widget: WidgetConfig) => void
}) {
  const [widget, setWidget] = useState(initial)
  const rules = CHART_RULES[widget.chart_type]
  const { query } = widget
  const problem = widgetProblem(widget, schema)
  // A prévia não espera o título: só a consulta precisa estar completa.
  const queryProblem = widgetProblem({ ...widget, title: widget.title || 'prévia' }, schema)
  const typeOf = (name: string | null | undefined) =>
    schema.find((c) => c.name === name)?.data_type ?? null
  const dimensionType = typeOf(query.dimension?.column)
  const temporalDimension = dimensionType !== null && isTemporal(dimensionType)
  const setQuery = (patch: Partial<WidgetConfig['query']>) =>
    setWidget({ ...widget, query: { ...query, ...patch } })
  const setMetric = (index: number, metric: Metric) =>
    setQuery({ metrics: query.metrics.map((m, i) => (i === index ? metric : m)) })

  const preview = useAnalytics(
    datasetId,
    queryProblem
      ? null
      : {
          ...query,
          version_id: versionId,
          extra_filters: dashboardFilters.filters.length > 0 ? [dashboardFilters] : [],
        },
  )
  const dimensions = dimensionColumns(schema).filter(
    (c) => !rules.categoricalOnly || !isTemporal(c.data_type),
  )
  const temporal = temporalColumns(schema)

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[92vh] overflow-y-auto sm:max-w-5xl">
        <DialogHeader>
          <DialogTitle>{initial.title ? `Editar “${initial.title}”` : 'Novo widget'}</DialogTitle>
          <DialogDescription>
            Escolha a medida e a agregação, a dimensão e os filtros. A prévia é calculada pela API
            com os dados reais da versão.
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
          <div className="min-w-0 space-y-4">
            <div className="space-y-1.5">
              <Label className="text-xs" htmlFor="widget-titulo">
                Título
              </Label>
              <Input
                id="widget-titulo"
                value={widget.title}
                maxLength={120}
                onChange={(e) => setWidget({ ...widget, title: e.target.value })}
                placeholder="ex.: Valor por equipe"
              />
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <Choice
                id="widget-tipo"
                label="Tipo de gráfico"
                value={widget.chart_type}
                options={CHART_TYPE_LABEL}
                onChange={(chartType) => setWidget(adaptToChart(widget, chartType, schema))}
              />
              <Choice
                id="widget-tamanho"
                label="Tamanho"
                value={widget.size}
                options={SIZE_LABEL}
                onChange={(size) => setWidget({ ...widget, size })}
              />
            </div>

            <fieldset className="space-y-2">
              <legend className="mb-1 text-xs font-medium">Medidas</legend>
              {query.metrics.map((metric, index) => {
                const type = typeOf(metric.column)
                const allowed = aggregationsFor(metric.column ? type : null).filter(
                  (a) => !rules.partOfWhole || PART_OF_WHOLE.includes(a),
                )
                return (
                  <div key={index} className="flex items-end gap-2">
                    <div className="grid min-w-0 flex-1 gap-2 sm:grid-cols-2">
                      <Choice
                        label={`Coluna da medida ${index + 1}`}
                        value={metric.column ?? RECORDS}
                        options={{
                          [RECORDS]: 'Registros (contagem)',
                          ...columnOptions(schema),
                        }}
                        onChange={(column) => {
                          const next = column === RECORDS ? null : column
                          const options = aggregationsFor(next ? typeOf(next) : null)
                          // Saindo de "Registros", vale a primeira agregação da coluna (soma,
                          // para números); entre colunas, a agregação é mantida se couber.
                          const aggregation =
                            metric.column && options.includes(metric.aggregation)
                              ? metric.aggregation
                              : (options[0] ?? 'count')
                          setMetric(index, { column: next, aggregation })
                        }}
                      />
                      <Choice
                        label={`Agregação da medida ${index + 1}`}
                        value={metric.aggregation}
                        options={
                          Object.fromEntries(
                            allowed.map((a) => [a, AGGREGATION_LABEL[a]]),
                          ) as Record<Aggregation, string>
                        }
                        onChange={(aggregation) => setMetric(index, { ...metric, aggregation })}
                      />
                    </div>
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      aria-label={`Remover medida ${index + 1}`}
                      disabled={query.metrics.length === 1}
                      onClick={() =>
                        setQuery({ metrics: query.metrics.filter((_, i) => i !== index) })
                      }
                    >
                      <X />
                    </Button>
                  </div>
                )
              })}
              {!rules.singleMetric && (
                <Button
                  variant="outline"
                  size="sm"
                  disabled={query.metrics.length >= MAX_METRICS}
                  onClick={() =>
                    setQuery({
                      metrics: [...query.metrics, { aggregation: 'count', column: null }],
                    })
                  }
                >
                  <Plus /> Medida
                </Button>
              )}
              {rules.partOfWhole && (
                <p className="text-xs text-muted-foreground">
                  Pizza e rosca mostram partes de um todo: só contagem ou soma.
                </p>
              )}
            </fieldset>

            {rules.needsDimension && (
              <fieldset className="space-y-2">
                <legend className="mb-1 text-xs font-medium">Dimensão</legend>
                <div className="grid gap-2 sm:grid-cols-2">
                  <Choice
                    label="Agrupar por"
                    value={query.dimension?.column ?? ''}
                    options={columnOptions(dimensions)}
                    onChange={(column) =>
                      setQuery({
                        dimension: {
                          column,
                          granularity: isTemporal(typeOf(column) ?? 'text') ? 'month' : null,
                        },
                        comparison: isTemporal(typeOf(column) ?? 'text') ? null : query.comparison,
                      })
                    }
                  />
                  {temporalDimension && query.dimension && (
                    <Choice
                      label="Granularidade"
                      value={query.dimension.granularity ?? 'month'}
                      options={GRANULARITY_LABEL}
                      onChange={(granularity: Granularity) =>
                        query.dimension &&
                        setQuery({ dimension: { ...query.dimension, granularity } })
                      }
                    />
                  )}
                </div>
                {!temporalDimension && query.dimension && (
                  <div className="grid gap-2 sm:grid-cols-3">
                    <Choice
                      label="Ordenar por"
                      value={query.sort ?? 'metric'}
                      options={{ metric: 'Primeira medida', dimension: 'Dimensão' }}
                      onChange={(sort) => setQuery({ sort })}
                    />
                    <Choice
                      label="Direção"
                      value={query.direction ?? (query.sort === 'dimension' ? 'asc' : 'desc')}
                      options={{ desc: 'Decrescente', asc: 'Crescente' }}
                      onChange={(direction) => setQuery({ direction })}
                    />
                    <div className="space-y-1.5">
                      <Label className="text-xs" htmlFor="widget-limite">
                        Grupos exibidos
                      </Label>
                      <Input
                        id="widget-limite"
                        type="number"
                        min={1}
                        max={100}
                        value={query.limit ?? 10}
                        onChange={(e) =>
                          setQuery({
                            limit: Math.min(100, Math.max(1, Number(e.target.value) || 1)),
                          })
                        }
                      />
                    </div>
                  </div>
                )}
                {temporalDimension && (
                  <p className="text-xs text-muted-foreground">
                    Séries temporais saem em ordem cronológica, sem corte de grupos.
                  </p>
                )}
              </fieldset>
            )}

            {rules.allowComparison && !temporalDimension && temporal.length > 0 && (
              <fieldset className="space-y-2">
                <legend className="sr-only">Comparação entre períodos</legend>
                <label className="flex items-center gap-2 text-sm font-medium">
                  <Checkbox
                    checked={Boolean(query.comparison)}
                    onCheckedChange={(checked) =>
                      setQuery({
                        comparison:
                          checked === true
                            ? {
                                column: temporal[0]?.name ?? '',
                                start: '',
                                end: '',
                                mode: 'previous_period',
                              }
                            : null,
                      })
                    }
                  />
                  Comparar com outro período
                </label>
                {query.comparison && (
                  <div className="grid gap-2 sm:grid-cols-2">
                    <Choice
                      label="Coluna de data"
                      value={query.comparison.column}
                      options={columnOptions(temporal)}
                      onChange={(column) =>
                        query.comparison &&
                        setQuery({ comparison: { ...query.comparison, column } })
                      }
                    />
                    <Choice
                      label="Comparar com"
                      value={query.comparison.mode ?? 'previous_period'}
                      options={{
                        previous_period: 'Período anterior de mesma duração',
                        previous_year: 'Mesmo período do ano anterior',
                      }}
                      onChange={(mode) =>
                        query.comparison && setQuery({ comparison: { ...query.comparison, mode } })
                      }
                    />
                    <div className="space-y-1.5">
                      <Label className="text-xs" htmlFor="comparacao-inicio">
                        Início do período atual
                      </Label>
                      <Input
                        id="comparacao-inicio"
                        type="date"
                        value={query.comparison.start}
                        onChange={(e) =>
                          query.comparison &&
                          setQuery({ comparison: { ...query.comparison, start: e.target.value } })
                        }
                      />
                    </div>
                    <div className="space-y-1.5">
                      <Label className="text-xs" htmlFor="comparacao-fim">
                        Fim do período atual
                      </Label>
                      <Input
                        id="comparacao-fim"
                        type="date"
                        value={query.comparison.end}
                        onChange={(e) =>
                          query.comparison &&
                          setQuery({ comparison: { ...query.comparison, end: e.target.value } })
                        }
                      />
                    </div>
                  </div>
                )}
              </fieldset>
            )}

            <fieldset className="space-y-2">
              <legend className="mb-1 text-xs font-medium">Filtros deste widget</legend>
              {(query.filters ?? []).length > 0 ? (
                <FilterEditor
                  conditions={query.filters ?? []}
                  match={query.match ?? 'all'}
                  schema={schema}
                  onChange={(filters, match) => setQuery({ filters, match })}
                />
              ) : (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() =>
                    setQuery({ filters: [{ column: schema[0]?.name ?? '', operator: 'not_null' }] })
                  }
                >
                  <Plus /> Filtro
                </Button>
              )}
            </fieldset>
          </div>

          <div className="min-w-0 space-y-2">
            <p className="text-xs font-medium text-muted-foreground uppercase">Prévia</p>
            <WidgetCard
              title={widget.title || 'Sem título'}
              chartType={widget.chart_type}
              size="large"
              state={preview}
              problem={queryProblem}
            />
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancelar
          </Button>
          <Button
            disabled={problem !== null}
            onClick={() => onSave({ ...widget, title: widget.title.trim() })}
          >
            Salvar widget
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
