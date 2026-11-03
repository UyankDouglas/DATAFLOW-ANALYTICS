import { useQuery } from '@tanstack/react-query'
import { Database, FileSpreadsheet, Plus, X } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useSearchParams } from 'react-router'

import { PageHeader } from '@/components/page-header'
import { EmptyState, ErrorState } from '@/components/states'
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
import { Skeleton } from '@/components/ui/skeleton'
import { ExportMenu } from '@/features/admin/export-menu'
import {
  AGGREGATION_LABEL,
  GRANULARITY_LABEL,
  formatMetricValue,
  formatVariation,
  variation,
} from '@/features/dashboards/format'
import {
  EMPTY_QUICK_FILTERS,
  quickFilterSets,
  type QuickFilterState,
} from '@/features/dashboards/quick-filter-state'
import { QuickFilters } from '@/features/dashboards/quick-filters'
import {
  MAX_METRICS,
  aggregationsFor,
  dimensionColumns,
  temporalColumns,
} from '@/features/dashboards/rules'
import { useAnalytics } from '@/features/dashboards/use-analytics'
import { WidgetCard } from '@/features/dashboards/widget-card'
import { datasetsApi } from '@/features/datasets/api'
import { isTemporal } from '@/features/transformations/rules'
import { formatInteger } from '@/lib/format'
import type {
  AggregateResult,
  AggregateSpec,
  ColumnSpec,
  Granularity,
  Metric,
  PeriodComparison,
} from '@/types/api'

const NONE = '__none__'
const RECORDS = '__registros__'

function Pick({
  label,
  value,
  options,
  onChange,
  none,
}: {
  label: string
  value: string
  options: { value: string; label: string }[]
  onChange: (value: string) => void
  none?: string
}) {
  return (
    <div className="min-w-0 space-y-1.5">
      <Label className="text-xs">{label}</Label>
      <Select
        value={value || (none ? NONE : undefined)}
        onValueChange={(next) => onChange(next === NONE ? '' : next)}
      >
        <SelectTrigger size="sm" className="w-full" aria-label={label}>
          <SelectValue placeholder="Escolha" />
        </SelectTrigger>
        <SelectContent>
          {none && <SelectItem value={NONE}>{none}</SelectItem>}
          {options.map((o) => (
            <SelectItem key={o.value} value={o.value}>
              {o.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  )
}

export function ReportsPage() {
  const [params, setParams] = useSearchParams()
  const datasetId = params.get('dataset') ?? ''
  const datasets = useQuery({
    queryKey: ['datasets', { status: 'ready', page: 1 }],
    queryFn: () => datasetsApi.list({ page: 1, pageSize: 100, status: 'ready' }),
  })
  return (
    <>
      <PageHeader
        title="Relatórios"
        description="Indicadores agregados de uma versão, com filtros e comparação entre períodos. A tabela é calculada no servidor; o relatório completo e os registros filtrados podem ser exportados em CSV ou XLSX."
      />
      {datasets.isPending ? (
        <Skeleton className="h-24 w-full" />
      ) : datasets.isError ? (
        <ErrorState error={datasets.error} onRetry={() => datasets.refetch()} />
      ) : datasets.data.items.length === 0 ? (
        <EmptyState
          icon={Database}
          title="Nenhum dataset processado"
          description="Importe e processe um arquivo para montar relatórios."
        />
      ) : (
        <div className="space-y-4">
          <Card>
            <CardContent className="max-w-md">
              <Pick
                label="Dataset"
                value={datasetId}
                options={datasets.data.items.map((d) => ({ value: d.id, label: d.name }))}
                onChange={(value) => setParams(value ? { dataset: value } : {}, { replace: true })}
              />
            </CardContent>
          </Card>
          {datasetId ? (
            <DatasetReport key={datasetId} datasetId={datasetId} />
          ) : (
            <EmptyState
              icon={FileSpreadsheet}
              title="Escolha um dataset"
              description="Depois, escolha como agrupar, quais medidas calcular e os filtros."
            />
          )}
        </div>
      )}
    </>
  )
}

function DatasetReport({ datasetId }: { datasetId: string }) {
  const dataset = useQuery({
    queryKey: ['datasets', datasetId],
    queryFn: () => datasetsApi.get(datasetId),
  })
  const versions = useQuery({
    queryKey: ['datasets', datasetId, 'versions'],
    queryFn: () => datasetsApi.versions(datasetId),
  })
  const [versionId, setVersionId] = useState<string | null>(null)
  const resolvedId = versionId ?? dataset.data?.current_version_id ?? null
  const version = versions.data?.find((v) => v.id === resolvedId)
  const schema: ColumnSpec[] = useMemo(
    () =>
      (version?.column_schema ?? []).map((c) => ({
        name: c.name,
        data_type: c.data_type,
        format: c.format,
        scale: c.scale,
      })),
    [version],
  )
  const [dimension, setDimension] = useState('')
  const [granularity, setGranularity] = useState<Granularity>('month')
  const [metrics, setMetrics] = useState<Metric[]>([{ aggregation: 'count', column: null }])
  const [limit, setLimit] = useState(50)
  const [comparison, setComparison] = useState<PeriodComparison | null>(null)
  const [filters, setFilters] = useState<QuickFilterState>(EMPTY_QUICK_FILTERS)
  const sets = useMemo(() => quickFilterSets(filters, schema), [filters, schema])

  if (dataset.isPending || versions.isPending) return <Skeleton className="h-64 w-full" />
  if (dataset.isError) return <ErrorState error={dataset.error} />
  if (versions.isError) return <ErrorState error={versions.error} />
  if (!version) {
    return (
      <EmptyState
        icon={Database}
        title="Este dataset ainda não tem versão processada"
        description="Configure e processe o arquivo para montar relatórios."
      />
    )
  }

  const typeOf = (name: string | null | undefined) =>
    schema.find((c) => c.name === name)?.data_type ?? null
  const dimensionType = typeOf(dimension)
  const temporalDimension = dimensionType !== null && isTemporal(dimensionType)
  const spec: AggregateSpec = {
    metrics,
    dimension: dimension
      ? { column: dimension, granularity: temporalDimension ? granularity : null }
      : null,
    limit,
    comparison:
      comparison && !temporalDimension && comparison.start && comparison.end ? comparison : null,
  }
  const versionParam = versionId
  const temporal = temporalColumns(schema)

  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <Pick
              label="Versão"
              value={resolvedId ?? ''}
              options={versions.data.map((v) => ({
                value: v.id,
                label: `Versão ${v.version_number}${v.id === dataset.data.current_version_id ? ' (atual)' : ''} · ${formatInteger(v.row_count)} reg.`,
              }))}
              onChange={(value) =>
                setVersionId(value === dataset.data.current_version_id ? null : value)
              }
            />
            <Pick
              label="Agrupar por"
              value={dimension}
              none="Sem agrupamento (totais)"
              options={dimensionColumns(schema).map((c) => ({ value: c.name, label: c.name }))}
              onChange={setDimension}
            />
            {temporalDimension && (
              <Pick
                label="Granularidade"
                value={granularity}
                options={Object.entries(GRANULARITY_LABEL).map(([value, label]) => ({
                  value,
                  label,
                }))}
                onChange={(value) => setGranularity(value as Granularity)}
              />
            )}
            {dimension && !temporalDimension && (
              <div className="space-y-1.5">
                <Label className="text-xs" htmlFor="relatorio-grupos">
                  Grupos na tela
                </Label>
                <Input
                  id="relatorio-grupos"
                  type="number"
                  min={1}
                  max={100}
                  value={limit}
                  onChange={(e) =>
                    setLimit(Math.min(100, Math.max(1, Number(e.target.value) || 1)))
                  }
                />
              </div>
            )}
          </div>

          <fieldset className="space-y-2">
            <legend className="mb-1 text-xs font-medium">Medidas</legend>
            {metrics.map((metric, index) => {
              const allowed = aggregationsFor(metric.column ? typeOf(metric.column) : null)
              return (
                <div key={index} className="flex items-end gap-2">
                  <div className="grid min-w-0 flex-1 gap-2 sm:grid-cols-2">
                    <Pick
                      label={`Coluna da medida ${index + 1}`}
                      value={metric.column ?? RECORDS}
                      options={[
                        { value: RECORDS, label: 'Registros (contagem)' },
                        ...schema.map((c) => ({ value: c.name, label: c.name })),
                      ]}
                      onChange={(value) => {
                        const column = value === RECORDS ? null : value
                        const options = aggregationsFor(column ? typeOf(column) : null)
                        const aggregation =
                          metric.column && options.includes(metric.aggregation)
                            ? metric.aggregation
                            : (options[0] ?? 'count')
                        setMetrics(
                          metrics.map((m, i) => (i === index ? { column, aggregation } : m)),
                        )
                      }}
                    />
                    <Pick
                      label={`Agregação da medida ${index + 1}`}
                      value={metric.aggregation}
                      options={allowed.map((a) => ({ value: a, label: AGGREGATION_LABEL[a] }))}
                      onChange={(value) =>
                        setMetrics(
                          metrics.map((m, i) =>
                            i === index ? { ...m, aggregation: value as Metric['aggregation'] } : m,
                          ),
                        )
                      }
                    />
                  </div>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label={`Remover medida ${index + 1}`}
                    disabled={metrics.length === 1}
                    onClick={() => setMetrics(metrics.filter((_, i) => i !== index))}
                  >
                    <X />
                  </Button>
                </div>
              )
            })}
            <Button
              variant="outline"
              size="sm"
              disabled={metrics.length >= MAX_METRICS}
              onClick={() => setMetrics([...metrics, { aggregation: 'count', column: null }])}
            >
              <Plus /> Medida
            </Button>
          </fieldset>

          {temporal.length > 0 && !temporalDimension && (
            <fieldset className="space-y-2">
              <legend className="sr-only">Comparação entre períodos</legend>
              <label className="flex items-center gap-2 text-sm font-medium">
                <Checkbox
                  checked={comparison !== null}
                  onCheckedChange={(checked) =>
                    setComparison(
                      checked === true
                        ? {
                            column: temporal[0]?.name ?? '',
                            start: '',
                            end: '',
                            mode: 'previous_period',
                          }
                        : null,
                    )
                  }
                />
                Comparar com outro período
              </label>
              {comparison && (
                <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
                  <Pick
                    label="Coluna de data"
                    value={comparison.column}
                    options={temporal.map((c) => ({ value: c.name, label: c.name }))}
                    onChange={(column) => setComparison({ ...comparison, column })}
                  />
                  <div className="space-y-1.5">
                    <Label className="text-xs" htmlFor="relatorio-inicio">
                      Início do período atual
                    </Label>
                    <Input
                      id="relatorio-inicio"
                      type="date"
                      value={comparison.start}
                      onChange={(e) => setComparison({ ...comparison, start: e.target.value })}
                    />
                  </div>
                  <div className="space-y-1.5">
                    <Label className="text-xs" htmlFor="relatorio-fim">
                      Fim do período atual
                    </Label>
                    <Input
                      id="relatorio-fim"
                      type="date"
                      value={comparison.end}
                      onChange={(e) => setComparison({ ...comparison, end: e.target.value })}
                    />
                  </div>
                  <Pick
                    label="Comparar com"
                    value={comparison.mode ?? 'previous_period'}
                    options={[
                      { value: 'previous_period', label: 'Período anterior' },
                      { value: 'previous_year', label: 'Ano anterior' },
                    ]}
                    onChange={(mode) =>
                      setComparison({
                        ...comparison,
                        mode: mode as 'previous_period' | 'previous_year',
                      })
                    }
                  />
                </div>
              )}
            </fieldset>
          )}
        </CardContent>
      </Card>

      <QuickFilters
        key={version.id}
        datasetId={datasetId}
        versionId={version.id}
        schema={schema}
        value={filters}
        onApply={setFilters}
      />

      <ReportResult
        datasetId={datasetId}
        versionId={versionParam}
        spec={spec}
        sets={sets}
        exportReport={(format, style) => ({
          dataset_id: datasetId,
          version_id: version.id,
          kind: 'report',
          format,
          csv_style: style,
          // O arquivo leva até 10 mil grupos; a tela mostra só os primeiros.
          report: { ...spec, limit: 10_000, extra_filters: sets },
        })}
        exportRows={(format, style) => ({
          dataset_id: datasetId,
          version_id: version.id,
          kind: 'rows',
          format,
          csv_style: style,
          rows: { extra_filters: sets },
        })}
      />
    </div>
  )
}

function ReportResult({
  datasetId,
  versionId,
  spec,
  sets,
  exportReport,
  exportRows,
}: {
  datasetId: string
  versionId: string | null
  spec: AggregateSpec
  sets: ReturnType<typeof quickFilterSets>
  exportReport: React.ComponentProps<typeof ExportMenu>['request']
  exportRows: React.ComponentProps<typeof ExportMenu>['request']
}) {
  const result = useAnalytics(datasetId, { ...spec, version_id: versionId, extra_filters: sets })
  return (
    <section aria-labelledby="relatorio-resultado" className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="relatorio-resultado" className="text-sm font-semibold">
          Resultado
          {result.data && (
            <span className="ml-2 font-normal text-muted-foreground">
              {formatInteger(result.data.matched_rows)} registros considerados
            </span>
          )}
        </h2>
        <div className="flex flex-wrap gap-2">
          <ExportMenu label="Exportar relatório" request={exportReport} disabled={!result.data} />
          <ExportMenu label="Exportar registros" request={exportRows} />
        </div>
      </div>
      {spec.dimension ? (
        <WidgetCard title="Relatório" chartType="table" size="large" state={result} />
      ) : (
        <Totals result={result.data} error={result.isError ? result.error : null} />
      )}
    </section>
  )
}

function Totals({ result, error }: { result?: AggregateResult; error: unknown }) {
  if (error) return <ErrorState error={error} />
  if (!result) return <Skeleton className="h-28 w-full" />
  const row = result.rows[0]
  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3" aria-label="Totais">
      {result.metrics.map((metric, index) => (
        <Card key={metric.key} className="gap-1 p-4">
          <p className="text-sm text-muted-foreground">{metric.label}</p>
          <p className="tabular text-2xl font-semibold">
            {formatMetricValue(row?.values[index], metric)}
          </p>
          {result.comparison && (
            <p className="text-xs text-muted-foreground">
              Anterior: {formatMetricValue(row?.previous?.[index], metric)} ·{' '}
              {formatVariation(variation(row?.values[index], row?.previous?.[index]))}
            </p>
          )}
        </Card>
      ))}
    </div>
  )
}
