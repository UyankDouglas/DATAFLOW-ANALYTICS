import { useQuery } from '@tanstack/react-query'
import { FileText, GitBranch, Play, Rows3, Settings2, Table2, TableProperties } from 'lucide-react'
import { Link, useParams } from 'react-router'

import { KpiCard } from '@/components/kpi-card'
import { PageHeader } from '@/components/page-header'
import { ErrorState, TableSkeleton } from '@/components/states'
import { StatusBadge } from '@/components/status-badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
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
import { DATA_TYPE_LABEL, DATE_FORMATS, DATETIME_FORMATS } from '@/features/datasets/column-form'
import { jobsApi } from '@/features/jobs/api'
import { JobStatusBadge } from '@/features/jobs/job-components'
import { DATASET_STATUS_LABEL, DATASET_STATUS_TONE, isActive } from '@/features/jobs/status'
import { formatBytes, formatInteger, formatTimestamp } from '@/lib/format'

export function DatasetDetailPage() {
  const { datasetId = '' } = useParams()
  const canProcess = usePermission('datasets:process')
  const dataset = useQuery({
    queryKey: ['datasets', datasetId],
    queryFn: () => datasetsApi.get(datasetId),
    refetchInterval: (query) => (query.state.data?.status === 'processing' ? 3000 : false),
  })
  const versions = useQuery({
    queryKey: ['datasets', datasetId, 'versions'],
    queryFn: () => datasetsApi.versions(datasetId),
  })
  const jobs = useQuery({
    queryKey: ['jobs', { datasetId }],
    queryFn: () => jobsApi.list({ page: 1, pageSize: 10, datasetId }),
    refetchInterval: (query) =>
      query.state.data?.items.some((job) => isActive(job.status)) ? 2000 : false,
  })

  if (dataset.isPending) return <TableSkeleton rows={6} columns={4} />
  if (dataset.isError) {
    return (
      <>
        <PageHeader title="Dataset" breadcrumbs={[{ label: 'Datasets', to: '/datasets' }]} />
        <ErrorState error={dataset.error} onRetry={() => dataset.refetch()} />
      </>
    )
  }
  const data = dataset.data
  const current = data.current_version
  const formatLabel = (format: string | null) =>
    format ? (DATE_FORMATS[format] ?? DATETIME_FORMATS[format] ?? format) : '—'

  return (
    <>
      <PageHeader
        title={data.name}
        description={
          <span className="flex flex-wrap items-center gap-2">
            <StatusBadge
              tone={DATASET_STATUS_TONE[data.status]}
              pulse={data.status === 'processing'}
            >
              {DATASET_STATUS_LABEL[data.status]}
            </StatusBadge>
            <span>Criado em {formatTimestamp(data.created_at)}</span>
          </span>
        }
        breadcrumbs={[{ label: 'Datasets', to: '/datasets' }, { label: data.name }]}
        actions={
          <>
            {current && (
              <Button asChild>
                <Link to={`/datasets/${data.id}/explorar`}>
                  <Table2 /> Explorar registros
                </Link>
              </Button>
            )}
            {canProcess && (
              <Button asChild variant="outline">
                <Link to={`/datasets/${data.id}/preview`}>
                  {current ? <Settings2 /> : <Play />}{' '}
                  {current ? 'Reprocessar' : 'Configurar e processar'}
                </Link>
              </Button>
            )}
          </>
        }
      />

      <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <KpiCard
          label="Versão atual"
          icon={GitBranch}
          value={current ? `v${current.version_number}` : '—'}
          hint={current ? `regras v${current.rules_version}` : 'Nenhuma versão publicada'}
        />
        <KpiCard
          label="Registros válidos"
          icon={Rows3}
          accent="green"
          value={formatInteger(current?.row_count)}
          hint={current ? `${formatInteger(current.rejected_count)} rejeitados` : undefined}
        />
        <KpiCard
          label="Colunas"
          icon={TableProperties}
          accent="violet"
          value={formatInteger(data.columns.length || null)}
          hint="Mapeamento salvo"
        />
        <KpiCard
          label="Arquivo de origem"
          icon={FileText}
          accent="cyan"
          value={formatBytes(data.latest_upload?.size_bytes)}
          hint={data.latest_upload?.original_filename}
        />
      </section>

      <div className="mt-6 grid gap-6 xl:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Versões</CardTitle>
            <CardDescription>
              Versões publicadas são imutáveis; cada uma registra origem, regras e responsável.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {versions.data && versions.data.length > 0 ? (
              <div className="overflow-x-auto rounded-xl border">
                <Table>
                  <TableHeader className="bg-muted/40">
                    <TableRow className="hover:bg-transparent">
                      <TableHead>Versão</TableHead>
                      <TableHead>Válidos</TableHead>
                      <TableHead>Rejeitados</TableHead>
                      <TableHead>Responsável</TableHead>
                      <TableHead>Publicada em</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {versions.data.map((version) => (
                      <TableRow key={version.id}>
                        <TableCell>
                          <Link
                            to={`/datasets/${data.id}/explorar?versao=${version.id}`}
                            className="font-medium hover:text-primary"
                          >
                            v{version.version_number}
                          </Link>
                          {version.id === data.current_version_id && (
                            <span className="ml-2 text-xs text-success">atual</span>
                          )}
                        </TableCell>
                        <TableCell className="tabular">
                          {formatInteger(version.row_count)}
                        </TableCell>
                        <TableCell className="tabular">
                          {formatInteger(version.rejected_count)}
                        </TableCell>
                        <TableCell>{version.created_by_name ?? '—'}</TableCell>
                        <TableCell className="tabular whitespace-nowrap">
                          {formatTimestamp(version.created_at)}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">Nenhuma versão publicada ainda.</p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Processamentos</CardTitle>
            <CardDescription>
              Execuções deste dataset, da mais recente para a mais antiga.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {jobs.data && jobs.data.items.length > 0 ? (
              <ul className="divide-y">
                {jobs.data.items.map((job) => (
                  <li
                    key={job.id}
                    className="flex items-center justify-between gap-3 py-2.5 first:pt-0 last:pb-0"
                  >
                    <div className="min-w-0">
                      <Link
                        to={`/processamentos/${job.id}`}
                        className="text-sm font-medium hover:text-primary"
                      >
                        {formatTimestamp(job.created_at)}
                      </Link>
                      <p className="text-xs text-muted-foreground">
                        {job.created_by_name ?? '—'}
                        {job.result_version_number ? ` · gerou v${job.result_version_number}` : ''}
                      </p>
                    </div>
                    <JobStatusBadge status={job.status} cancelRequested={job.cancel_requested} />
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-muted-foreground">Nenhum processamento ainda.</p>
            )}
          </CardContent>
        </Card>
      </div>

      {data.columns.length > 0 && (
        <Card className="mt-6">
          <CardHeader>
            <CardTitle>Mapeamento de colunas</CardTitle>
            <CardDescription>
              Configuração salva e reutilizada nos reprocessamentos.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto rounded-xl border">
              <Table>
                <TableHeader className="bg-muted/40">
                  <TableRow className="hover:bg-transparent">
                    <TableHead>#</TableHead>
                    <TableHead>Coluna original</TableHead>
                    <TableHead>Nome</TableHead>
                    <TableHead>Tipo</TableHead>
                    <TableHead>Formato</TableHead>
                    <TableHead>Inferido</TableHead>
                    <TableHead>Nulos (versão atual)</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.columns.map((column) => {
                    const stats = current?.column_schema.find((item) => item.name === column.name)
                    return (
                      <TableRow key={column.position}>
                        <TableCell className="tabular text-muted-foreground">
                          {column.position + 1}
                        </TableCell>
                        <TableCell className="font-mono text-xs">{column.source_name}</TableCell>
                        <TableCell className="font-medium">{column.name}</TableCell>
                        <TableCell>{DATA_TYPE_LABEL[column.data_type]}</TableCell>
                        <TableCell className="text-xs text-muted-foreground">
                          {column.data_type === 'decimal' &&
                          stats?.scale !== null &&
                          stats?.scale !== undefined
                            ? `${stats.scale} casas`
                            : formatLabel(column.format)}
                        </TableCell>
                        <TableCell className="text-muted-foreground">
                          {column.inferred_type ? DATA_TYPE_LABEL[column.inferred_type] : '—'}
                        </TableCell>
                        <TableCell className="tabular">
                          {stats ? formatInteger(stats.null_count) : '—'}
                        </TableCell>
                      </TableRow>
                    )
                  })}
                </TableBody>
              </Table>
            </div>
          </CardContent>
        </Card>
      )}
    </>
  )
}
