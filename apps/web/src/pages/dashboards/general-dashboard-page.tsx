import { useQuery } from '@tanstack/react-query'
import {
  ArrowDownToLine,
  ArrowUpToLine,
  BarChart3,
  Database,
  Hash,
  Sigma,
  Tags,
  TrendingUp,
} from 'lucide-react'
import { useMemo, useState } from 'react'
import { useSearchParams } from 'react-router'

import { KpiCard } from '@/components/kpi-card'
import { PageHeader } from '@/components/page-header'
import { EmptyState, ErrorState } from '@/components/states'
import { Card, CardContent } from '@/components/ui/card'
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
import { GRANULARITY_LABEL, defaultPeriod, formatMetricValue } from '@/features/dashboards/format'
import {
  EMPTY_QUICK_FILTERS,
  quickFilterSets,
  type QuickFilterState,
} from '@/features/dashboards/quick-filter-state'
import { QuickFilters } from '@/features/dashboards/quick-filters'
import { numericColumns, temporalColumns } from '@/features/dashboards/rules'
import { useAnalytics } from '@/features/dashboards/use-analytics'
import { GRID_CLASS } from '@/features/dashboards/layout'
import { WidgetCard } from '@/features/dashboards/widget-card'
import { datasetsApi } from '@/features/datasets/api'
import { isTemporal } from '@/features/transformations/rules'
import { formatInteger } from '@/lib/format'
import type {
  AggregateSpec,
  AnalyticsQuery,
  ChartType,
  ColumnSpec,
  FilterSet,
  Granularity,
  Metric,
  WidgetSize,
} from '@/types/api'

const NONE = '__none__'

function Picker({
  label,
  value,
  onChange,
  options,
  none,
  disabled,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  options: { value: string; label: string }[]
  none?: string
  disabled?: boolean
}) {
  return (
    <div className="min-w-0 space-y-1.5">
      <Label className="text-xs">{label}</Label>
      <Select
        value={value || (none ? NONE : undefined)}
        onValueChange={(next) => onChange(next === NONE ? '' : next)}
        disabled={disabled}
      >
        <SelectTrigger className="w-full" aria-label={label}>
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

export function GeneralDashboardPage() {
  const [params, setParams] = useSearchParams()
  const datasetId = params.get('dataset') ?? ''
  const update = (patch: Record<string, string>) => {
    const next = new URLSearchParams(params)
    for (const [key, value] of Object.entries(patch)) {
      if (value) next.set(key, value)
      else next.delete(key)
    }
    setParams(next, { replace: true })
  }
  const datasets = useQuery({
    queryKey: ['datasets', { status: 'ready', page: 1 }],
    queryFn: () => datasetsApi.list({ page: 1, pageSize: 100, status: 'ready' }),
  })

  return (
    <>
      <PageHeader
        title="Dashboard geral"
        description="Indicadores calculados no servidor sobre a versão escolhida. Você escolhe a medida, a categoria e a data: nenhuma coluna numérica é tratada como receita automaticamente."
        breadcrumbs={[{ label: 'Dashboards', to: '/dashboards' }, { label: 'Dashboard geral' }]}
      />
      {datasets.isPending ? (
        <Skeleton className="h-24 w-full" />
      ) : datasets.isError ? (
        <ErrorState error={datasets.error} onRetry={() => datasets.refetch()} />
      ) : datasets.data.items.length === 0 ? (
        <EmptyState
          icon={Database}
          title="Nenhum dataset processado"
          description="Importe e processe um arquivo para analisar os dados aqui."
        />
      ) : (
        <div className="space-y-4">
          <Card>
            <CardContent className="max-w-md">
              <Picker
                label="Dataset"
                value={datasetId}
                onChange={(value) =>
                  setParams(new URLSearchParams(value ? { dataset: value } : {}), {
                    replace: true,
                  })
                }
                options={datasets.data.items.map((d) => ({ value: d.id, label: d.name }))}
              />
            </CardContent>
          </Card>
          {datasetId ? (
            <DatasetAnalysis
              key={datasetId}
              datasetId={datasetId}
              params={params}
              update={update}
            />
          ) : (
            <EmptyState
              icon={BarChart3}
              title="Escolha um dataset"
              description="Depois, escolha a medida numérica, a categoria e a coluna de data para montar os indicadores."
            />
          )}
        </div>
      )}
    </>
  )
}

function DatasetAnalysis({
  datasetId,
  params,
  update,
}: {
  datasetId: string
  params: URLSearchParams
  update: (patch: Record<string, string>) => void
}) {
  const dataset = useQuery({
    queryKey: ['datasets', datasetId],
    queryFn: () => datasetsApi.get(datasetId),
  })
  const versions = useQuery({
    queryKey: ['datasets', datasetId, 'versions'],
    queryFn: () => datasetsApi.versions(datasetId),
  })
  const versionId = params.get('versao') || dataset.data?.current_version_id || ''
  const version = versions.data?.find((v) => v.id === versionId)
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
  const has = (name: string | null, ok: (c: ColumnSpec) => boolean) =>
    Boolean(name && schema.some((c) => c.name === name && ok(c)))
  const measureParam = params.get('medida')
  const measure = has(measureParam, (c) => c.data_type === 'integer' || c.data_type === 'decimal')
    ? (measureParam ?? '')
    : ''
  const categoryParam = params.get('categoria')
  const category = has(categoryParam, (c) => c.data_type !== 'decimal' && !isTemporal(c.data_type))
    ? (categoryParam ?? '')
    : ''
  const dateParam = params.get('data')
  const temporal = temporalColumns(schema)
  // A data é uma escolha inofensiva: sem parâmetro, usa a primeira coluna de data.
  const dateColumn =
    dateParam === NONE
      ? ''
      : has(dateParam, (c) => isTemporal(c.data_type))
        ? (dateParam ?? '')
        : (temporal[0]?.name ?? '')
  const granularity = (params.get('granularidade') as Granularity | null) ?? 'month'
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
        description="Configure e processe o arquivo para analisar os dados."
      />
    )
  }

  const categories = schema.filter((c) => c.data_type !== 'decimal' && !isTemporal(c.data_type))
  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
          <Picker
            label="Versão"
            value={versionId}
            onChange={(value) =>
              update({ versao: value === dataset.data.current_version_id ? '' : value })
            }
            options={versions.data.map((v) => ({
              value: v.id,
              label: `Versão ${v.version_number}${v.id === dataset.data.current_version_id ? ' (atual)' : ''} · ${formatInteger(v.row_count)} reg.`,
            }))}
          />
          <Picker
            label="Medida numérica"
            value={measure}
            onChange={(value) => update({ medida: value })}
            none="Nenhuma (só contagens)"
            options={numericColumns(schema).map((c) => ({ value: c.name, label: c.name }))}
          />
          <Picker
            label="Categoria"
            value={category}
            onChange={(value) => update({ categoria: value })}
            none="Nenhuma"
            options={categories.map((c) => ({ value: c.name, label: c.name }))}
          />
          <Picker
            label="Coluna de data"
            value={dateColumn}
            onChange={(value) => update({ data: value || NONE })}
            none="Nenhuma"
            options={temporal.map((c) => ({ value: c.name, label: c.name }))}
          />
          <Picker
            label="Granularidade"
            value={granularity}
            onChange={(value) => update({ granularidade: value === 'month' ? '' : value })}
            disabled={!dateColumn}
            options={Object.entries(GRANULARITY_LABEL).map(([value, label]) => ({
              value,
              label,
            }))}
          />
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

      <Analysis
        datasetId={datasetId}
        versionId={params.get('versao') || null}
        measure={measure}
        category={category}
        dateColumn={dateColumn}
        granularity={granularity}
        filters={sets}
      />
    </div>
  )
}

function Analysis({
  datasetId,
  versionId,
  measure,
  category,
  dateColumn,
  granularity,
  filters,
}: {
  datasetId: string
  versionId: string | null
  measure: string
  category: string
  dateColumn: string
  granularity: Granularity
  filters: FilterSet[]
}) {
  const base = { version_id: versionId, extra_filters: filters }
  const value: Metric = measure
    ? { aggregation: 'sum', column: measure }
    : { aggregation: 'count', column: null }
  const kpiMetrics: Metric[] = [
    { aggregation: 'count', column: null },
    ...(measure
      ? (['sum', 'avg', 'max', 'min'] as const).map((aggregation) => ({
          aggregation,
          column: measure,
        }))
      : []),
    ...(category ? [{ aggregation: 'count_distinct' as const, column: category }] : []),
  ]
  const kpis = useAnalytics(datasetId, { ...base, metrics: kpiMetrics })
  // O intervalo de datas sugere o período da comparação: os 30 dias mais recentes dos dados.
  const range = useAnalytics(
    datasetId,
    dateColumn
      ? {
          version_id: versionId,
          metrics: [
            { aggregation: 'min', column: dateColumn },
            { aggregation: 'max', column: dateColumn },
          ],
        }
      : null,
  )
  const [period, setPeriod] = useState<{
    start: string
    end: string
    mode: 'previous_period' | 'previous_year'
  } | null>(null)
  const max = range.data?.rows[0]?.values[1]
  const suggested = typeof max === 'string' ? defaultPeriod(max) : null
  const effective =
    period ?? (suggested ? { ...suggested, mode: 'previous_period' as const } : null)

  const icons = [Hash, Sigma, TrendingUp, ArrowUpToLine, ArrowDownToLine, Tags]
  const accents = ['blue', 'green', 'cyan', 'violet', 'amber', 'red'] as const
  const kpiLabels = ['Total de registros', 'Soma', 'Média', 'Máximo', 'Mínimo', 'Valores distintos']
  const kpiData = kpis.data
  const labelFor = (index: number) => {
    const metric = kpiData?.metrics[index] ?? null
    if (index === 0) return kpiLabels[0]
    if (metric?.aggregation === 'count_distinct') return `${metric.column} distintos`
    return `${kpiLabels[index]} de ${measure}`
  }

  return (
    <div className="space-y-4">
      <section aria-label="Indicadores" className="grid gap-4 sm:grid-cols-2 xl:grid-cols-6">
        {kpiMetrics.map((metric, index) => {
          const info = kpiData?.metrics[index]
          return (
            <KpiCard
              key={`${metric.aggregation}-${metric.column ?? ''}`}
              label={labelFor(index) ?? ''}
              value={info ? formatMetricValue(kpiData?.rows[0]?.values[index], info) : '—'}
              icon={icons[metric.aggregation === 'count_distinct' ? 5 : index] ?? Hash}
              accent={accents[metric.aggregation === 'count_distinct' ? 5 : index] ?? 'blue'}
              loading={!kpiData && !kpis.isError}
              hint={index === 0 && kpiData ? `versão ${kpiData.version_number}` : undefined}
            />
          )
        })}
      </section>
      {kpis.isError && <ErrorState error={kpis.error} onRetry={() => kpis.refetch()} />}
      {!measure && (
        <p className="text-sm text-muted-foreground">
          Escolha uma medida numérica para ver soma, média, máximo e mínimo. O DataFlow não presume
          que uma coluna numérica representa dinheiro.
        </p>
      )}

      <div className={GRID_CLASS}>
        {dateColumn && (
          <AnalysisWidget
            datasetId={datasetId}
            title={`Evolução temporal · ${measure ? `soma de ${measure}` : 'registros'} por ${GRANULARITY_LABEL[granularity].toLowerCase()}`}
            chartType="line"
            size={category ? 'medium' : 'large'}
            body={{ ...base, metrics: [value], dimension: { column: dateColumn, granularity } }}
          />
        )}
        {category && (
          <AnalysisWidget
            datasetId={datasetId}
            title={`${measure ? `Soma de ${measure}` : 'Registros'} por ${category}`}
            chartType="bar_horizontal"
            size={dateColumn ? 'medium' : 'large'}
            body={{ ...base, metrics: [value], dimension: { column: category }, limit: 10 }}
          />
        )}
        {category && (
          <AnalysisWidget
            datasetId={datasetId}
            title={`Participação por ${category}`}
            chartType="donut"
            size="medium"
            body={{ ...base, metrics: [value], dimension: { column: category }, limit: 6 }}
          />
        )}
        {category && (
          <AnalysisWidget
            datasetId={datasetId}
            title={`Tabela analítica por ${category}`}
            chartType="table"
            size="medium"
            body={{
              ...base,
              metrics: measure
                ? [
                    { aggregation: 'count', column: null },
                    { aggregation: 'sum', column: measure },
                    { aggregation: 'avg', column: measure },
                    { aggregation: 'min', column: measure },
                    { aggregation: 'max', column: measure },
                  ]
                : [{ aggregation: 'count', column: null }],
              dimension: { column: category },
              limit: 20,
            }}
          />
        )}
      </div>

      {dateColumn && effective && (
        <section aria-labelledby="comparacao-titulo" className="space-y-3">
          <Card>
            <CardContent className="flex flex-col gap-3 lg:flex-row lg:items-end">
              <div className="min-w-0 flex-1">
                <h2 id="comparacao-titulo" className="text-sm font-semibold">
                  Comparação entre períodos
                </h2>
                <p className="text-xs text-muted-foreground">
                  Período atual em {dateColumn} comparado ao anterior. Sugestão: os 30 dias mais
                  recentes dos dados.
                </p>
              </div>
              <div className="grid gap-2 sm:grid-cols-3">
                <div className="space-y-1.5">
                  <Label className="text-xs" htmlFor="comparar-inicio">
                    Início
                  </Label>
                  <Input
                    id="comparar-inicio"
                    type="date"
                    value={effective.start}
                    onChange={(e) => setPeriod({ ...effective, start: e.target.value })}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label className="text-xs" htmlFor="comparar-fim">
                    Fim
                  </Label>
                  <Input
                    id="comparar-fim"
                    type="date"
                    value={effective.end}
                    onChange={(e) => setPeriod({ ...effective, end: e.target.value })}
                  />
                </div>
                <Picker
                  label="Comparar com"
                  value={effective.mode}
                  onChange={(mode) =>
                    setPeriod({ ...effective, mode: mode as 'previous_period' | 'previous_year' })
                  }
                  options={[
                    { value: 'previous_period', label: 'Período anterior' },
                    { value: 'previous_year', label: 'Ano anterior' },
                  ]}
                />
              </div>
            </CardContent>
          </Card>
          {effective.start && effective.end && effective.start <= effective.end && (
            <div className={GRID_CLASS}>
              <AnalysisWidget
                datasetId={datasetId}
                title={measure ? `Soma de ${measure} no período` : 'Registros no período'}
                chartType="kpi"
                size="small"
                body={{
                  ...base,
                  metrics: [value],
                  comparison: { column: dateColumn, ...effective },
                }}
              />
              {category && (
                <AnalysisWidget
                  datasetId={datasetId}
                  title={`Período atual e anterior por ${category}`}
                  chartType="bar"
                  size="large"
                  className="xl:col-span-3"
                  body={{
                    ...base,
                    metrics: [value],
                    dimension: { column: category },
                    limit: 8,
                    comparison: { column: dateColumn, ...effective },
                  }}
                />
              )}
            </div>
          )}
        </section>
      )}
    </div>
  )
}

function AnalysisWidget({
  datasetId,
  title,
  chartType,
  size,
  body,
  className,
}: {
  datasetId: string
  title: string
  chartType: ChartType
  size: WidgetSize
  body: AnalyticsQuery & AggregateSpec
  className?: string
}) {
  const result = useAnalytics(datasetId, body)
  return (
    <WidgetCard
      title={title}
      chartType={chartType}
      size={size}
      state={result}
      className={className}
    />
  )
}
