import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle,
  BarChart3,
  CheckCircle2,
  ClipboardCheck,
  Copy,
  Database,
  Loader2,
  Percent,
  RefreshCw,
  Rows3,
  ScrollText,
  ShieldAlert,
  XCircle,
} from 'lucide-react'
import { useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { toast } from 'sonner'

import { KpiCard } from '@/components/kpi-card'
import { PageHeader } from '@/components/page-header'
import { Pagination } from '@/components/pagination'
import { EmptyState, ErrorState, TableSkeleton } from '@/components/states'
import { StatusBadge } from '@/components/status-badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { usePermission } from '@/features/auth/use-auth'
import { datasetsApi } from '@/features/datasets/api'
import { CellValue } from '@/features/datasets/cell-value'
import { DATA_TYPE_LABEL } from '@/features/datasets/column-form'
import { REJECTION_LABEL } from '@/features/jobs/status'
import { qualityApi } from '@/features/quality/api'
import {
  CompletenessChart,
  FrequencyChart,
  IssuesChart,
  NullDistributionChart,
  VersionScoreChart,
} from '@/features/quality/charts'
import {
  COMPONENT_HINT,
  COMPONENT_LABEL,
  formatRatio,
  formatScore,
  scoreTone,
} from '@/features/quality/score'
import { DuplicatesPanel } from '@/features/transformations/duplicates-panel'
import { CATEGORY_LABEL, CATEGORY_TONE } from '@/features/transformations/rules'
import { formatInteger, formatTimestamp } from '@/lib/format'
import { ApiError, describeError } from '@/services/api-client'
import type {
  ColumnSpec,
  DatasetVersion,
  ExclusionCategory,
  QualityComponents,
  QualityReport,
  QualityVersionSummary,
} from '@/types/api'

const ALL = 'todos'

export function QualityPage() {
  const [params, setParams] = useSearchParams()
  const datasetId = params.get('dataset') ?? ''
  const datasets = useQuery({
    queryKey: ['datasets', { page: 1, pageSize: 100, status: 'ready' }],
    queryFn: () => datasetsApi.list({ page: 1, pageSize: 100, status: 'ready' }),
  })

  return (
    <>
      <PageHeader
        title="Qualidade dos Dados"
        description="Indicadores calculados sobre os dados reais de cada versão: completude, nulos, duplicidades e cada exclusão com motivo, regra e tratamento."
        breadcrumbs={[{ label: 'Tratamento' }, { label: 'Qualidade' }]}
      />
      {datasets.isPending ? (
        <TableSkeleton rows={4} columns={3} />
      ) : datasets.isError ? (
        <ErrorState error={datasets.error} onRetry={() => datasets.refetch()} />
      ) : datasets.data.items.length === 0 ? (
        <EmptyState
          icon={ClipboardCheck}
          title="Nenhum dataset processado"
          description="A qualidade é medida sobre versões publicadas. Importe e processe um arquivo primeiro."
          action={
            <Button asChild>
              <Link to="/importar">Importar dados</Link>
            </Button>
          }
        />
      ) : (
        <>
          <div className="mb-6 max-w-md space-y-1.5">
            <Label>Dataset</Label>
            <Select
              value={datasetId || undefined}
              onValueChange={(id) => setParams({ dataset: id }, { replace: true })}
            >
              <SelectTrigger className="w-full" aria-label="Dataset">
                <SelectValue placeholder="Escolha um dataset processado" />
              </SelectTrigger>
              <SelectContent>
                {datasets.data.items.map((dataset) => (
                  <SelectItem key={dataset.id} value={dataset.id}>
                    {dataset.name}
                    <span className="text-xs text-muted-foreground">
                      {' '}
                      · v{dataset.current_version_number}
                    </span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          {datasetId ? (
            <DatasetQuality key={datasetId} datasetId={datasetId} />
          ) : (
            <EmptyState
              icon={ClipboardCheck}
              title="Escolha um dataset"
              description="Veja a nota de qualidade de cada versão, o perfil das colunas e as inconsistências encontradas."
            />
          )}
        </>
      )}
    </>
  )
}

function DatasetQuality({ datasetId }: { datasetId: string }) {
  const [params, setParams] = useSearchParams()
  const dataset = useQuery({
    queryKey: ['datasets', datasetId],
    queryFn: () => datasetsApi.get(datasetId),
  })
  const versions = useQuery({
    queryKey: ['datasets', datasetId, 'versions'],
    queryFn: () => datasetsApi.versions(datasetId),
  })
  const comparison = useQuery({
    queryKey: ['datasets', datasetId, 'quality'],
    queryFn: () => qualityApi.compare(datasetId),
  })
  const versionId = params.get('versao') ?? dataset.data?.current_version_id ?? ''
  const version = versions.data?.find((v) => v.id === versionId)

  if (dataset.isPending || versions.isPending) return <TableSkeleton rows={6} columns={4} />
  if (dataset.isError) return <ErrorState error={dataset.error} onRetry={() => dataset.refetch()} />
  if (versions.isError)
    return <ErrorState error={versions.error} onRetry={() => versions.refetch()} />

  return (
    <div className="space-y-6">
      <div className="max-w-md space-y-1.5">
        <Label>Versão</Label>
        <Select
          value={versionId}
          onValueChange={(id) => {
            const next = new URLSearchParams(params)
            next.set('versao', id)
            setParams(next, { replace: true })
          }}
        >
          <SelectTrigger className="w-full" aria-label="Versão">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {versions.data.map((v) => (
              <SelectItem key={v.id} value={v.id}>
                v{v.version_number}
                {v.id === dataset.data.current_version_id ? ' (atual)' : ''} ·{' '}
                {v.parent_version_number !== null ? `de v${v.parent_version_number}` : 'importação'}{' '}
                · nota {formatScore(v.quality_score)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      {version && <VersionQuality key={version.id} datasetId={datasetId} version={version} />}
      {comparison.data && comparison.data.length > 0 && (
        <VersionComparison versions={comparison.data} />
      )}
    </div>
  )
}

function VersionQuality({ datasetId, version }: { datasetId: string; version: DatasetVersion }) {
  const canCompute = usePermission('datasets:process')
  const queryClient = useQueryClient()
  const report = useQuery({
    queryKey: ['datasets', datasetId, 'quality', version.id],
    queryFn: () => qualityApi.report(datasetId, version.id),
    retry: false,
  })
  const compute = useMutation({
    mutationFn: () => qualityApi.compute(datasetId, version.id),
    onSuccess: (data) => {
      queryClient.setQueryData(['datasets', datasetId, 'quality', version.id], data)
      void queryClient.invalidateQueries({ queryKey: ['datasets', datasetId, 'quality'] })
      void queryClient.invalidateQueries({ queryKey: ['datasets', datasetId, 'versions'] })
      toast.success(`Relatório da v${version.version_number} calculado.`)
    },
    onError: (error) => toast.error(describeError(error)),
  })

  if (report.isPending) return <TableSkeleton rows={6} columns={4} />
  if (report.isError) {
    const missing = report.error instanceof ApiError && report.error.code === 'quality_not_computed'
    if (!missing) return <ErrorState error={report.error} onRetry={() => report.refetch()} />
    return (
      <EmptyState
        icon={ClipboardCheck}
        title={`A v${version.version_number} ainda não tem relatório de qualidade`}
        description={
          canCompute
            ? 'Versões publicadas a partir desta fase já saem com o relatório. Para esta, calcule agora: a leitura é feita sobre os dados reais da versão.'
            : 'Peça a um analista para calcular o relatório desta versão.'
        }
        action={
          canCompute && (
            <Button onClick={() => compute.mutate()} disabled={compute.isPending}>
              {compute.isPending ? <Loader2 className="animate-spin" /> : <RefreshCw />}
              Calcular relatório
            </Button>
          )
        }
      />
    )
  }
  return (
    <ReportView
      datasetId={datasetId}
      version={version}
      report={report.data}
      onRecompute={canCompute ? () => compute.mutate() : undefined}
      recomputing={compute.isPending}
    />
  )
}

function ReportView({
  datasetId,
  version,
  report,
  onRecompute,
  recomputing,
}: {
  datasetId: string
  version: DatasetVersion
  report: QualityReport
  onRecompute?: () => void
  recomputing: boolean
}) {
  const { indicators, components, columns, formula } = report.metrics
  const schema: ColumnSpec[] = version.column_schema.map((c) => ({
    name: c.name,
    data_type: c.data_type,
    format: c.format,
    scale: c.scale,
  }))
  const duplicates = (indicators.duplicates_removed ?? 0) + indicators.duplicates_remaining

  return (
    <>
      <Card>
        <CardContent className="grid gap-6 lg:grid-cols-[minmax(0,16rem)_1fr]">
          <div className="space-y-2" aria-label="Nota de qualidade" role="group">
            <p className="text-sm text-muted-foreground">
              Nota de qualidade · v{version.version_number}
            </p>
            <p className="tabular text-5xl font-semibold" data-testid="quality-score">
              {formatScore(report.score)}
            </p>
            <StatusBadge tone={scoreTone(report.score)}>
              {report.score === null ? 'Sem registros para avaliar' : 'de 0 a 100'}
            </StatusBadge>
            <p className="text-xs text-muted-foreground">
              Fórmula v{report.formula_version} ·{' '}
              {report.computed_by_name
                ? `calculada por ${report.computed_by_name}`
                : 'calculada ao publicar a versão'}{' '}
              em {formatTimestamp(report.computed_at)} ({formatInteger(report.duration_ms)} ms)
            </p>
            {onRecompute && (
              <Button variant="outline" size="sm" onClick={onRecompute} disabled={recomputing}>
                {recomputing ? <Loader2 className="animate-spin" /> : <RefreshCw />} Recalcular
              </Button>
            )}
          </div>
          <div className="space-y-3">
            <p className="text-sm">
              Nota = 100 × (
              {(Object.keys(formula.weights) as (keyof QualityComponents)[])
                .map(
                  (key) =>
                    `${formula.weights[key].toLocaleString('pt-BR')} × ${COMPONENT_LABEL[key].toLowerCase()}`,
                )
                .join(' + ')}
              )
            </p>
            <dl className="grid gap-3 sm:grid-cols-3">
              {(Object.keys(COMPONENT_LABEL) as (keyof QualityComponents)[]).map((key) => (
                <div key={key} className="rounded-lg border p-3">
                  <dt className="text-xs text-muted-foreground">
                    {COMPONENT_LABEL[key]} · peso {formula.weights[key].toLocaleString('pt-BR')}
                  </dt>
                  <dd className="tabular mt-1 text-xl font-semibold">
                    {formatRatio(components[key])}
                  </dd>
                  <p className="mt-1 text-xs text-muted-foreground">{COMPONENT_HINT[key]}</p>
                </div>
              ))}
            </dl>
            <p className="text-xs text-muted-foreground">
              Cálculo detalhado e casos-limite em <code>docs/quality.md</code>. Filtrados são
              escolha do usuário e não penalizam a nota.
            </p>
          </div>
        </CardContent>
      </Card>

      <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4" aria-label="Indicadores">
        <KpiCard
          label="Total de registros"
          icon={Database}
          value={formatInteger(indicators.received)}
          hint="recebidos pela versão"
        />
        <KpiCard
          label="Registros válidos"
          icon={CheckCircle2}
          accent="green"
          value={formatInteger(indicators.valid)}
          hint={`${formatInteger(indicators.filtered)} filtrados pelas regras`}
        />
        <KpiCard
          label="Registros rejeitados"
          icon={XCircle}
          accent={indicators.rejected ? 'amber' : 'green'}
          value={formatInteger(indicators.rejected)}
          hint="problemas de dado, com motivo"
        />
        <KpiCard
          label="Registros duplicados"
          icon={Copy}
          accent="violet"
          value={formatInteger(duplicates)}
          hint={`${indicators.duplicates_removed === null ? 'deduplicação não aplicada' : `${formatInteger(indicators.duplicates_removed)} removidos`} · ${formatInteger(indicators.duplicates_remaining)} restantes (todas as colunas)`}
        />
        <KpiCard
          label="Valores nulos"
          icon={Rows3}
          accent="cyan"
          value={formatInteger(indicators.null_cells)}
          hint={`de ${formatInteger(indicators.total_cells)} células publicadas`}
        />
        <KpiCard
          label="Completude"
          icon={Percent}
          accent="green"
          value={formatRatio(indicators.completeness)}
          hint="células com valor"
        />
        <KpiCard
          label="Colunas com inconsistências"
          icon={ShieldAlert}
          accent={indicators.columns_with_issues ? 'amber' : 'green'}
          value={formatInteger(indicators.columns_with_issues)}
          hint={`de ${formatInteger(columns.length)} colunas`}
        />
        <KpiCard
          label="Regras violadas"
          icon={ScrollText}
          accent={indicators.rules_violated ? 'red' : 'green'}
          value={formatInteger(indicators.rules_violated)}
          hint={`${formatInteger(indicators.violations)} violações no total`}
        />
      </section>

      <div className="grid gap-6 xl:grid-cols-2">
        <Card className="min-w-0">
          <CardHeader>
            <CardTitle>Completude por coluna</CardTitle>
            <CardDescription>
              Percentual de células com valor em cada coluna publicada.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <CompletenessChart columns={columns} />
          </CardContent>
        </Card>
        <Card className="min-w-0">
          <CardHeader>
            <CardTitle>Distribuição de nulos</CardTitle>
            <CardDescription>Registros publicados por quantidade de colunas nulas.</CardDescription>
          </CardHeader>
          <CardContent>
            {report.metrics.null_distribution.length > 0 ? (
              <NullDistributionChart data={report.metrics.null_distribution} />
            ) : (
              <p className="text-sm text-muted-foreground">Nenhum registro publicado.</p>
            )}
          </CardContent>
        </Card>
        <Card className="min-w-0">
          <CardHeader>
            <CardTitle>Erros por categoria</CardTitle>
            <CardDescription>
              Exclusões por motivo: rejeitados (problema de dado), filtrados e duplicados.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {report.issues.length > 0 ? (
              <IssuesChart issues={report.issues} />
            ) : (
              <p className="flex items-center gap-2 text-sm text-success">
                <CheckCircle2 className="size-4" /> Nenhum registro excluído nesta versão.
              </p>
            )}
          </CardContent>
        </Card>
        <ValueFrequencyCard datasetId={datasetId} versionId={version.id} schema={schema} />
      </div>

      <ColumnProfileTable report={report} />
      <DuplicatesPanel datasetId={datasetId} version={version} schema={schema} />
      <InconsistencyTable datasetId={datasetId} version={version} report={report} />
    </>
  )
}

function ColumnProfileTable({ report }: { report: QualityReport }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Perfil das colunas</CardTitle>
        <CardDescription>
          Contagens exatas sobre todos os registros publicados da versão.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto rounded-xl border">
          <Table>
            <TableHeader className="bg-muted/40">
              <TableRow className="hover:bg-transparent">
                <TableHead>Coluna</TableHead>
                <TableHead>Tipo</TableHead>
                <TableHead>Completude</TableHead>
                <TableHead>Nulos</TableHead>
                <TableHead>Distintos</TableHead>
                <TableHead>Mínimo</TableHead>
                <TableHead>Máximo</TableHead>
                <TableHead>Exclusões atribuídas</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {report.metrics.columns.map((column) => (
                <TableRow key={column.name}>
                  <TableCell className="font-medium">{column.name}</TableCell>
                  <TableCell className="text-muted-foreground">
                    {DATA_TYPE_LABEL[column.data_type]}
                  </TableCell>
                  <TableCell className="tabular">{formatRatio(column.completeness)}</TableCell>
                  <TableCell className="tabular">{formatInteger(column.nulls)}</TableCell>
                  <TableCell className="tabular">{formatInteger(column.distinct)}</TableCell>
                  <TableCell className="text-xs">
                    {column.min === null ? (
                      '—'
                    ) : (
                      <CellValue value={column.min} type={column.data_type} />
                    )}
                  </TableCell>
                  <TableCell className="text-xs">
                    {column.max === null ? (
                      '—'
                    ) : (
                      <CellValue value={column.max} type={column.data_type} />
                    )}
                  </TableCell>
                  <TableCell className={column.issues ? 'tabular text-warning' : 'tabular'}>
                    {formatInteger(column.issues)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </CardContent>
    </Card>
  )
}

function ValueFrequencyCard({
  datasetId,
  versionId,
  schema,
}: {
  datasetId: string
  versionId: string
  schema: ColumnSpec[]
}) {
  const [column, setColumn] = useState(
    schema.find((c) => c.data_type === 'text')?.name ?? schema[0]?.name ?? '',
  )
  const values = useQuery({
    queryKey: ['datasets', datasetId, 'quality', versionId, 'values', column],
    queryFn: () => qualityApi.values(datasetId, versionId, column),
    enabled: Boolean(column),
  })
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Frequência de valores</CardTitle>
        <CardDescription>
          Os 10 valores mais frequentes, lidos do Parquet da versão.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <Select value={column} onValueChange={setColumn}>
          <SelectTrigger size="sm" className="w-full sm:w-64" aria-label="Coluna da frequência">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {schema.map((c) => (
              <SelectItem key={c.name} value={c.name}>
                {c.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {values.isPending ? (
          <TableSkeleton rows={3} columns={2} />
        ) : values.isError ? (
          <ErrorState error={values.error} onRetry={() => values.refetch()} />
        ) : (
          <>
            <FrequencyChart values={values.data.values} />
            <p className="text-xs text-muted-foreground">
              {formatInteger(values.data.distinct)} valores distintos ·{' '}
              {formatInteger(values.data.nulls)} nulos · {formatInteger(values.data.others)}{' '}
              registros com outros valores
            </p>
          </>
        )}
      </CardContent>
    </Card>
  )
}

function InconsistencyTable({
  datasetId,
  version,
  report,
}: {
  datasetId: string
  version: DatasetVersion
  report: QualityReport
}) {
  const [category, setCategory] = useState<string>(ALL)
  const [reason, setReason] = useState<string>(ALL)
  const [column, setColumn] = useState<string>(ALL)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(25)
  const reasons = [...new Set(report.issues.map((i) => i.reason))]
  const columns = [
    ...new Set(report.issues.map((i) => i.column).filter((c): c is string => Boolean(c))),
  ]
  const filters = {
    category: category === ALL ? undefined : (category as ExclusionCategory),
    reason: reason === ALL ? undefined : reason,
    column: column === ALL ? undefined : column,
  }
  const rows = useQuery({
    queryKey: [
      'datasets',
      datasetId,
      'quality',
      version.id,
      'inconsistencies',
      filters,
      page,
      pageSize,
    ],
    queryFn: () =>
      qualityApi.inconsistencies(datasetId, version.id, { ...filters, page, pageSize }),
    placeholderData: keepPreviousData,
  })
  const filterSelect = (
    label: string,
    value: string,
    onChange: (value: string) => void,
    options: Record<string, string>,
  ) => (
    <div className="space-y-1.5">
      <Label className="text-xs">{label}</Label>
      <Select
        value={value}
        onValueChange={(next) => {
          onChange(next)
          setPage(1)
        }}
      >
        <SelectTrigger size="sm" className="w-full sm:w-52" aria-label={label}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={ALL}>Todos</SelectItem>
          {Object.entries(options).map(([key, text]) => (
            <SelectItem key={key} value={key}>
              {text}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  )

  return (
    <Card aria-label="Inconsistências" role="region">
      <CardHeader>
        <CardTitle>Inconsistências</CardTitle>
        <CardDescription>
          Cada registro excluído da v{version.version_number}: coluna, valor original, tipo do
          problema, regra violada e tratamento aplicado.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {report.issues.length === 0 ? (
          <p className="flex items-center gap-2 text-sm text-success">
            <CheckCircle2 className="size-4" /> Nenhuma inconsistência registrada nesta versão.
          </p>
        ) : (
          <>
            <div className="flex flex-wrap gap-3">
              {filterSelect('Categoria', category, setCategory, CATEGORY_LABEL)}
              {filterSelect(
                'Tipo do problema',
                reason,
                setReason,
                Object.fromEntries(reasons.map((r) => [r, REJECTION_LABEL[r] ?? r])),
              )}
              {filterSelect(
                'Coluna',
                column,
                setColumn,
                Object.fromEntries(columns.map((c) => [c, c])),
              )}
            </div>
            {rows.isPending ? (
              <TableSkeleton rows={5} columns={6} />
            ) : rows.isError ? (
              <ErrorState error={rows.error} onRetry={() => rows.refetch()} />
            ) : (
              <>
                <div
                  className={`overflow-x-auto rounded-xl border ${rows.isFetching ? 'opacity-70' : ''}`}
                >
                  <Table>
                    <TableHeader className="bg-muted/40">
                      <TableRow className="hover:bg-transparent">
                        <TableHead>Registro</TableHead>
                        <TableHead>Coluna</TableHead>
                        <TableHead>Valor original</TableHead>
                        <TableHead>Tipo do problema</TableHead>
                        <TableHead>Regra violada</TableHead>
                        <TableHead>Tratamento aplicado</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {rows.data.items.map((item) => (
                        <TableRow key={`${item.row}-${item.reason}`}>
                          <TableCell className="tabular align-top">
                            #{formatInteger(item.row)}
                            {item.line !== null && (
                              <span className="block text-xs text-muted-foreground">
                                linha {formatInteger(item.line)}
                              </span>
                            )}
                          </TableCell>
                          <TableCell className="align-top font-mono text-xs">
                            {item.column ?? '—'}
                          </TableCell>
                          <TableCell className="max-w-48 align-top font-mono text-xs">
                            {item.column ? (
                              item.original_value === null ? (
                                <span className="text-muted-foreground">(vazio)</span>
                              ) : (
                                item.original_value
                              )
                            ) : (
                              '—'
                            )}
                          </TableCell>
                          <TableCell className="align-top">
                            <StatusBadge tone={CATEGORY_TONE[item.category]}>
                              {CATEGORY_LABEL[item.category]}
                            </StatusBadge>
                            <span className="mt-1 block text-sm">
                              {REJECTION_LABEL[item.reason] ?? item.reason}
                            </span>
                            {item.detail && (
                              <span className="block max-w-72 text-xs text-muted-foreground">
                                {item.detail}
                              </span>
                            )}
                          </TableCell>
                          <TableCell className="align-top text-sm">{item.rule_label}</TableCell>
                          <TableCell className="align-top text-sm">
                            {item.treatment}
                            <details className="mt-1 text-xs text-muted-foreground">
                              <summary className="cursor-pointer">Registro completo</summary>
                              <dl className="mt-1 grid grid-cols-[auto_1fr] gap-x-2">
                                {Object.entries(item.record).map(([key, value]) => (
                                  <div key={key} className="contents">
                                    <dt className="font-mono">{key}</dt>
                                    <dd className="truncate">{value ?? '(vazio)'}</dd>
                                  </div>
                                ))}
                              </dl>
                            </details>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
                <Pagination
                  page={page}
                  pageSize={pageSize}
                  total={rows.data.total}
                  onPageChange={setPage}
                  onPageSizeChange={(size) => {
                    setPageSize(size)
                    setPage(1)
                  }}
                  pageSizes={[25, 50, 100]}
                />
              </>
            )}
          </>
        )}
      </CardContent>
    </Card>
  )
}

function VersionComparison({ versions }: { versions: QualityVersionSummary[] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <BarChart3 className="size-4" /> Comparação entre versões
        </CardTitle>
        <CardDescription>
          Nota e componentes de cada versão do dataset, na ordem em que foram publicadas.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {versions.some((v) => v.computed) && <VersionScoreChart versions={versions} />}
        <div className="overflow-x-auto rounded-xl border">
          <Table>
            <TableHeader className="bg-muted/40">
              <TableRow className="hover:bg-transparent">
                <TableHead>Versão</TableHead>
                <TableHead>Origem</TableHead>
                <TableHead>Nota</TableHead>
                <TableHead>Validade</TableHead>
                <TableHead>Completude</TableHead>
                <TableHead>Unicidade</TableHead>
                <TableHead>Válidos</TableHead>
                <TableHead>Rejeitados</TableHead>
                <TableHead>Duplicados removidos</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {versions.map((v) => (
                <TableRow key={v.version_id}>
                  <TableCell className="font-medium">v{v.version_number}</TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {v.parent_version_number !== null
                      ? `de v${v.parent_version_number}`
                      : 'importação'}
                  </TableCell>
                  {v.computed ? (
                    <>
                      <TableCell>
                        <StatusBadge tone={scoreTone(v.score)}>{formatScore(v.score)}</StatusBadge>
                      </TableCell>
                      <TableCell className="tabular">
                        {formatRatio(v.components.validity)}
                      </TableCell>
                      <TableCell className="tabular">
                        {formatRatio(v.components.completeness)}
                      </TableCell>
                      <TableCell className="tabular">
                        {formatRatio(v.components.uniqueness)}
                      </TableCell>
                      <TableCell className="tabular">{formatInteger(v.indicators.valid)}</TableCell>
                      <TableCell className="tabular">
                        {formatInteger(v.indicators.rejected)}
                      </TableCell>
                      <TableCell className="tabular">
                        {v.indicators.duplicates_removed === null ||
                        v.indicators.duplicates_removed === undefined
                          ? '—'
                          : formatInteger(v.indicators.duplicates_removed)}
                      </TableCell>
                    </>
                  ) : (
                    <TableCell colSpan={7} className="text-xs text-muted-foreground">
                      <AlertTriangle className="mr-1 inline size-3.5" /> Relatório não calculado
                    </TableCell>
                  )}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </CardContent>
    </Card>
  )
}
