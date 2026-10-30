import { useQuery } from '@tanstack/react-query'
import {
  Activity,
  AlertOctagon,
  ArrowRight,
  Database,
  FileWarning,
  Layers,
  Rows3,
  Upload,
} from 'lucide-react'
import { Link } from 'react-router'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { KpiCard } from '@/components/kpi-card'
import { PageHeader } from '@/components/page-header'
import { EmptyState, ErrorState } from '@/components/states'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { usePermission, useSession } from '@/features/auth/use-auth'
import { jobsApi } from '@/features/jobs/api'
import { JobLink, JobProgress, JobStatusBadge } from '@/features/jobs/job-components'
import { isActive } from '@/features/jobs/status'
import { formatDate, formatInteger, formatRelative } from '@/lib/format'

export function OverviewPage() {
  const { data: session } = useSession()
  const canUpload = usePermission('datasets:upload')
  const overview = useQuery({
    queryKey: ['overview'],
    queryFn: jobsApi.overview,
    refetchInterval: (query) => (query.state.data?.jobs_running ? 3000 : 30_000),
  })
  const data = overview.data
  const firstName = session?.user.full_name.split(' ')[0]

  return (
    <>
      <PageHeader
        title={`Olá, ${firstName ?? ''}`}
        description={`Resumo do workspace ${session?.workspace?.name ?? ''} com base nos dados processados.`}
        actions={
          canUpload && (
            <Button asChild>
              <Link to="/importar">
                <Upload /> Importar dados
              </Link>
            </Button>
          )
        }
      />

      {overview.isError ? (
        <ErrorState error={overview.error} onRetry={() => overview.refetch()} />
      ) : (
        <>
          <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4" aria-label="Indicadores">
            <KpiCard
              label="Datasets"
              icon={Database}
              accent="blue"
              loading={overview.isPending}
              value={formatInteger(data?.datasets_total)}
              hint={data ? `${formatInteger(data.datasets_ready)} prontos para análise` : undefined}
            />
            <KpiCard
              label="Registros publicados"
              icon={Rows3}
              accent="cyan"
              loading={overview.isPending}
              value={formatInteger(data?.rows_published)}
              hint={
                data
                  ? `Versões atuais · ${formatInteger(data.versions_total)} versões no total`
                  : undefined
              }
            />
            <KpiCard
              label="Processamentos ativos"
              icon={Activity}
              accent="violet"
              loading={overview.isPending}
              value={formatInteger(data?.jobs_running)}
              hint={
                data ? `${formatInteger(data.jobs_succeeded_7d)} concluídos em 7 dias` : undefined
              }
            />
            <KpiCard
              label="Registros rejeitados (7 dias)"
              icon={FileWarning}
              accent={data && data.rows_rejected_7d > 0 ? 'amber' : 'green'}
              loading={overview.isPending}
              value={formatInteger(data?.rows_rejected_7d)}
              hint={
                data
                  ? `${formatInteger(data.jobs_failed_7d)} processamento(s) com falha`
                  : undefined
              }
            />
          </section>

          {data && data.datasets_total === 0 ? (
            <EmptyState
              className="mt-6"
              icon={Layers}
              title="Nenhum dataset ainda"
              description="Importe um CSV para ver indicadores reais aqui. O repositório inclui arquivos fictícios de vendas e atendimentos em samples/."
              action={
                canUpload && (
                  <Button asChild>
                    <Link to="/importar">
                      <Upload /> Importar primeiro arquivo
                    </Link>
                  </Button>
                )
              }
            />
          ) : (
            <section className="mt-6 grid gap-4 xl:grid-cols-5">
              <Card className="xl:col-span-3">
                <CardHeader>
                  <CardTitle>Processamentos por dia</CardTitle>
                  <CardDescription>Últimos 14 dias (UTC), por resultado</CardDescription>
                </CardHeader>
                <CardContent className="h-72">
                  {overview.isPending ? (
                    <Skeleton className="h-full w-full" />
                  ) : (
                    <JobsChart data={data?.jobs_by_day ?? []} />
                  )}
                </CardContent>
              </Card>
              <Card className="xl:col-span-2">
                <CardHeader className="flex flex-row items-center justify-between">
                  <div>
                    <CardTitle>Atividade recente</CardTitle>
                    <CardDescription>Últimos processamentos</CardDescription>
                  </div>
                  <Button asChild variant="ghost" size="sm">
                    <Link to="/processamentos">
                      Ver todos <ArrowRight />
                    </Link>
                  </Button>
                </CardHeader>
                <CardContent>
                  {overview.isPending ? (
                    <div className="space-y-3">
                      {Array.from({ length: 4 }, (_, i) => (
                        <Skeleton key={i} className="h-12" />
                      ))}
                    </div>
                  ) : data?.recent_jobs.length ? (
                    <ul className="divide-y">
                      {data.recent_jobs.map((job) => (
                        <li key={job.id} className="space-y-2 py-3 first:pt-0 last:pb-0">
                          <div className="flex items-center justify-between gap-3">
                            <div className="min-w-0">
                              <JobLink job={job} />
                              <p className="truncate text-xs text-muted-foreground">
                                {job.upload_filename} · {formatRelative(job.created_at)}
                              </p>
                            </div>
                            <JobStatusBadge
                              status={job.status}
                              cancelRequested={job.cancel_requested}
                            />
                          </div>
                          {isActive(job.status) && <JobProgress job={job} compact />}
                          {job.status === 'failed' && job.error_message && (
                            <p className="flex items-start gap-1.5 text-xs text-destructive">
                              <AlertOctagon className="mt-px size-3.5 shrink-0" />{' '}
                              {job.error_message}
                            </p>
                          )}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="py-6 text-center text-sm text-muted-foreground">
                      Nenhum processamento ainda.
                    </p>
                  )}
                </CardContent>
              </Card>
            </section>
          )}
        </>
      )}
    </>
  )
}

function JobsChart({
  data,
}: {
  data: { date: string; succeeded: number; failed: number; other: number }[]
}) {
  const rows = data.map((day) => ({ ...day, label: formatDate(day.date).slice(0, 5) }))
  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={rows} margin={{ top: 4, right: 8, bottom: 0, left: -20 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
        <XAxis
          dataKey="label"
          tick={{ fill: 'var(--muted-foreground)', fontSize: 12 }}
          tickLine={false}
          axisLine={false}
        />
        <YAxis
          allowDecimals={false}
          tick={{ fill: 'var(--muted-foreground)', fontSize: 12 }}
          tickLine={false}
          axisLine={false}
        />
        <Tooltip
          cursor={{ fill: 'var(--accent)', opacity: 0.4 }}
          contentStyle={{
            background: 'var(--popover)',
            border: '1px solid var(--border)',
            borderRadius: 8,
            color: 'var(--popover-foreground)',
          }}
          formatter={(value, name) => [formatInteger(Number(value)), String(name)]}
        />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        <Bar
          dataKey="succeeded"
          name="Concluídos"
          stackId="a"
          fill="var(--success)"
          radius={[0, 0, 0, 0]}
        />
        <Bar dataKey="failed" name="Falhas" stackId="a" fill="var(--destructive)" />
        <Bar
          dataKey="other"
          name="Outros"
          stackId="a"
          fill="var(--chart-1)"
          radius={[4, 4, 0, 0]}
        />
      </BarChart>
    </ResponsiveContainer>
  )
}
