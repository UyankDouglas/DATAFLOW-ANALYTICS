import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle,
  Ban,
  CheckCircle2,
  Circle,
  Clock,
  Database,
  Loader2,
  RotateCcw,
  Table2,
  XCircle,
} from 'lucide-react'
import { useState } from 'react'
import { Link, useParams } from 'react-router'
import { toast } from 'sonner'

import { PageHeader } from '@/components/page-header'
import { ErrorState, TableSkeleton } from '@/components/states'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
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
import { jobsApi } from '@/features/jobs/api'
import { JobProgress, JobStatusBadge } from '@/features/jobs/job-components'
import {
  JOB_STAGES,
  JOB_STATUS_LABEL,
  REJECTION_LABEL,
  TIMING_LABEL,
  isActive,
} from '@/features/jobs/status'
import { useElapsed } from '@/features/jobs/use-elapsed'
import { formatBytes, formatDuration, formatInteger, formatTimestamp } from '@/lib/format'
import { cn } from '@/lib/utils'
import { describeError } from '@/services/api-client'
import type { Job } from '@/types/api'

export function JobDetailPage() {
  const { jobId = '' } = useParams()
  const job = useQuery({
    queryKey: ['jobs', jobId],
    queryFn: () => jobsApi.get(jobId),
    // Polling apenas enquanto há trabalho em andamento.
    refetchInterval: (query) =>
      query.state.data && isActive(query.state.data.status) ? 1500 : false,
  })

  if (job.isPending) return <TableSkeleton rows={6} columns={3} />
  if (job.isError) {
    return (
      <>
        <PageHeader
          title="Processamento"
          breadcrumbs={[{ label: 'Histórico', to: '/processamentos' }]}
        />
        <ErrorState error={job.error} onRetry={() => job.refetch()} />
      </>
    )
  }
  return <JobDetail job={job.data} />
}

function JobDetail({ job }: { job: Job }) {
  const elapsed = useElapsed(job.started_at ?? null, job.finished_at)
  const active = isActive(job.status)

  return (
    <>
      <PageHeader
        title={job.dataset_name ?? 'Processamento'}
        description={
          <span className="flex flex-wrap items-center gap-2">
            <JobStatusBadge status={job.status} cancelRequested={job.cancel_requested} />
            <span>
              {job.upload_filename} · iniciado por {job.created_by_name ?? '—'} em{' '}
              {formatTimestamp(job.created_at)}
            </span>
          </span>
        }
        breadcrumbs={[
          { label: 'Histórico', to: '/processamentos' },
          { label: `Job ${job.id.slice(0, 8)}` },
        ]}
        actions={<JobActions job={job} />}
      />

      <Card>
        <CardHeader>
          <CardTitle>Etapas</CardTitle>
          <CardDescription>
            Estado durável registrado no banco a cada etapa e a cada lote processado.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          <Stepper job={job} />
          {active && <JobProgress job={job} />}
          <dl className="grid gap-4 text-sm sm:grid-cols-2 lg:grid-cols-4">
            <Stat label="Tempo decorrido" value={formatDuration(elapsed)} icon={Clock} />
            <Stat
              label="Registros processados"
              value={`${formatInteger(job.rows_processed)}${job.rows_total !== null ? ` de ${formatInteger(job.rows_total)}` : ''}`}
              icon={Database}
            />
            <Stat
              label="Arquivo lido"
              value={`${formatBytes(job.bytes_processed)} de ${formatBytes(job.bytes_total)}`}
              icon={Table2}
            />
            <Stat
              label="Tentativas"
              value={`${job.attempts} de ${job.max_attempts}`}
              icon={RotateCcw}
            />
          </dl>
        </CardContent>
      </Card>

      {job.status === 'failed' && (
        <Alert variant="destructive" className="mt-6">
          <XCircle />
          <AlertTitle>O processamento falhou</AlertTitle>
          <AlertDescription>
            {job.error_message ?? 'Erro não informado.'} Nenhuma versão foi publicada; os dados
            anteriores continuam intactos.
            <Button asChild variant="outline" size="sm" className="mt-3 w-fit">
              <Link to={`/datasets/${job.dataset_id}/preview`}>Revisar configuração</Link>
            </Button>
          </AlertDescription>
        </Alert>
      )}
      {job.status === 'cancelled' && (
        <Alert className="mt-6">
          <Ban />
          <AlertTitle>Processamento cancelado</AlertTitle>
          <AlertDescription>
            A execução parou em um ponto seguro. Nenhuma versão foi publicada.
          </AlertDescription>
        </Alert>
      )}

      {job.warnings.length > 0 && (
        <Card className="mt-6">
          <CardHeader>
            <CardTitle>Avisos</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="space-y-2 text-sm">
              {job.warnings.map((warning) => (
                <li key={warning.at + warning.message} className="flex items-start gap-2">
                  <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" />
                  <span>
                    {warning.message}{' '}
                    <span className="text-xs text-muted-foreground">
                      ({formatTimestamp(warning.at)})
                    </span>
                  </span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}

      {job.status === 'succeeded' && <JobResult job={job} />}
    </>
  )
}

function Stat({ label, value, icon: Icon }: { label: string; value: string; icon: typeof Clock }) {
  return (
    <div className="rounded-lg border bg-muted/30 p-3">
      <dt className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <Icon className="size-3.5" /> {label}
      </dt>
      <dd className="tabular mt-1 font-semibold">{value}</dd>
    </div>
  )
}

function Stepper({ job }: { job: Job }) {
  const terminalFailure = job.status === 'failed' || job.status === 'cancelled'
  const currentIndex = JOB_STAGES.indexOf(job.status)
  return (
    <ol className="grid gap-3 sm:grid-cols-5" aria-label="Etapas do processamento">
      {JOB_STAGES.map((stage, index) => {
        const done = job.status === 'succeeded' || (currentIndex > index && !terminalFailure)
        const current = stage === job.status && !terminalFailure && job.status !== 'succeeded'
        return (
          <li
            key={stage}
            aria-current={current ? 'step' : undefined}
            className={cn(
              'flex items-center gap-2 rounded-lg border px-3 py-2 text-sm',
              done && 'border-success/30 bg-success/5',
              current && 'border-primary/40 bg-primary/5',
            )}
          >
            {done ? (
              <CheckCircle2 className="size-4 text-success" />
            ) : current ? (
              <Loader2 className="size-4 animate-spin text-primary" />
            ) : (
              <Circle className="size-4 text-muted-foreground" />
            )}
            <span className={cn(!done && !current && 'text-muted-foreground')}>
              {JOB_STATUS_LABEL[stage]}
            </span>
          </li>
        )
      })}
    </ol>
  )
}

function JobActions({ job }: { job: Job }) {
  const canCancel = usePermission('jobs:cancel')
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const cancel = useMutation({
    mutationFn: () => jobsApi.cancel(job.id),
    onSuccess: (updated) => {
      queryClient.setQueryData(['jobs', job.id], updated)
      void queryClient.invalidateQueries({ queryKey: ['jobs'] })
      setOpen(false)
      toast.info(
        updated.status === 'cancelled'
          ? 'Processamento cancelado.'
          : 'Cancelamento solicitado. O worker confirmará ao parar.',
      )
    },
    onError: (error) => toast.error(describeError(error)),
  })

  return (
    <>
      {job.status === 'succeeded' && (
        <Button asChild>
          <Link to={`/datasets/${job.dataset_id}/explorar?versao=${job.result_version_id}`}>
            <Table2 /> Ver registros
          </Link>
        </Button>
      )}
      <Button asChild variant="outline">
        <Link to={`/datasets/${job.dataset_id}`}>Abrir dataset</Link>
      </Button>
      {canCancel && isActive(job.status) && !job.cancel_requested && (
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger asChild>
            <Button variant="destructive">
              <Ban /> Cancelar
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Cancelar processamento?</DialogTitle>
              <DialogDescription>
                O cancelamento é cooperativo: o worker para no próximo ponto seguro e nenhuma versão
                parcial é publicada.
              </DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <DialogClose asChild>
                <Button variant="outline">Continuar processando</Button>
              </DialogClose>
              <Button
                variant="destructive"
                onClick={() => cancel.mutate()}
                disabled={cancel.isPending}
              >
                {cancel.isPending && <Loader2 className="animate-spin" />} Cancelar processamento
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}
    </>
  )
}

function JobResult({ job }: { job: Job }) {
  const received = job.rows_total ?? 0
  const valid = job.rows_valid ?? 0
  const rejected = job.rows_rejected ?? 0
  const byReason = Object.entries(job.rejection_summary.by_reason ?? {})
  const byColumn = Object.entries(job.rejection_summary.by_column ?? {})
  const timings = Object.entries(job.metrics.timings_ms ?? {}).filter(
    ([, value]) => value !== null && value !== undefined,
  )

  const rejectedRows = useQuery({
    queryKey: ['datasets', job.dataset_id, 'rejected', job.result_version_id],
    queryFn: () => datasetsApi.rejected(job.dataset_id, job.result_version_id ?? '', 1, 20),
    enabled: Boolean(job.result_version_id) && rejected > 0,
  })

  return (
    <>
      <Card className="mt-6">
        <CardHeader>
          <CardTitle>Reconciliação — versão {job.result_version_number}</CardTitle>
          <CardDescription>
            Recebidos = válidos + rejeitados. Duplicidades ainda não são avaliadas nesta fase
            (deduplicação chega na Fase 2).
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid gap-3 sm:grid-cols-4">
            <Recon label="Recebidos" value={received} tone="text-foreground" />
            <Recon
              label="Válidos (publicados)"
              value={valid}
              tone="text-success"
              ratio={received ? valid / received : 0}
            />
            <Recon
              label="Rejeitados"
              value={rejected}
              tone={rejected ? 'text-warning' : 'text-foreground'}
              ratio={received ? rejected / received : 0}
            />
            <div className="rounded-lg border border-dashed p-4">
              <p className="text-xs text-muted-foreground">Duplicados</p>
              <p className="mt-1 text-sm font-medium">Não avaliado</p>
              <p className="text-xs text-muted-foreground">regra aplicada a partir da Fase 2</p>
            </div>
          </div>
        </CardContent>
      </Card>

      <div className="mt-6 grid gap-6 xl:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Rejeições por motivo</CardTitle>
            <CardDescription>Nenhum registro é descartado em silêncio.</CardDescription>
          </CardHeader>
          <CardContent>
            {byReason.length === 0 ? (
              <p className="flex items-center gap-2 text-sm text-success">
                <CheckCircle2 className="size-4" /> Nenhum registro rejeitado.
              </p>
            ) : (
              <ul className="space-y-2 text-sm">
                {byReason.map(([reason, count]) => (
                  <li key={reason} className="flex items-center justify-between gap-4">
                    <span>{REJECTION_LABEL[reason] ?? reason}</span>
                    <span className="tabular font-semibold">{formatInteger(count)}</span>
                  </li>
                ))}
                {byColumn.length > 0 && (
                  <li className="border-t pt-2 text-xs text-muted-foreground">
                    Falhas de tipo por coluna:{' '}
                    {byColumn
                      .map(([column, count]) => `${column} (${formatInteger(count)})`)
                      .join(', ')}
                  </li>
                )}
              </ul>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Métricas de execução</CardTitle>
            <CardDescription>
              Medidas reais desta execução (regras v{job.rules_version}).
            </CardDescription>
          </CardHeader>
          <CardContent>
            <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
              {timings.map(([key, value]) => (
                <div key={key} className="contents">
                  <dt className="text-muted-foreground">{TIMING_LABEL[key] ?? key}</dt>
                  <dd className="tabular text-right">{formatDuration(value)}</dd>
                </div>
              ))}
              {job.metrics.rows_per_second !== undefined && (
                <>
                  <dt className="text-muted-foreground">Vazão</dt>
                  <dd className="tabular text-right">
                    {formatInteger(Math.round(job.metrics.rows_per_second))} registros/s
                  </dd>
                </>
              )}
              <dt className="text-muted-foreground">Memória máxima</dt>
              <dd className="tabular text-right">
                {job.metrics.peak_memory_mb
                  ? `${job.metrics.peak_memory_mb.toLocaleString('pt-BR')} MB`
                  : 'não mensurável'}
              </dd>
            </dl>
          </CardContent>
        </Card>
      </div>

      {rejected > 0 && (
        <Card className="mt-6">
          <CardHeader>
            <CardTitle>Registros rejeitados</CardTitle>
            <CardDescription>
              Primeiros {formatInteger(Math.min(20, rejected))} de {formatInteger(rejected)}, com
              valor original preservado.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {rejectedRows.isPending ? (
              <TableSkeleton rows={4} columns={5} />
            ) : rejectedRows.isError ? (
              <ErrorState error={rejectedRows.error} onRetry={() => rejectedRows.refetch()} />
            ) : (
              <div className="overflow-x-auto rounded-xl border">
                <Table>
                  <TableHeader className="bg-muted/40">
                    <TableRow className="hover:bg-transparent">
                      <TableHead>Registro</TableHead>
                      <TableHead>Linha</TableHead>
                      <TableHead>Motivo</TableHead>
                      <TableHead>Coluna</TableHead>
                      <TableHead>Valor original</TableHead>
                      <TableHead>Detalhe</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {rejectedRows.data?.rows.map((row) => {
                      const [record, line, reason, column, detail] = row as [
                        number,
                        number,
                        string,
                        string | null,
                        string,
                      ]
                      const columnIndex = column ? rejectedRows.data.columns.indexOf(column) : -1
                      const original = columnIndex >= 0 ? row[columnIndex] : null
                      return (
                        <TableRow key={record}>
                          <TableCell className="tabular">{formatInteger(record)}</TableCell>
                          <TableCell className="tabular">{formatInteger(line)}</TableCell>
                          <TableCell>{REJECTION_LABEL[reason] ?? reason}</TableCell>
                          <TableCell className="font-mono text-xs">{column ?? '—'}</TableCell>
                          <TableCell className="max-w-48 truncate font-mono text-xs">
                            {original === null ? '—' : String(original) || '(vazio)'}
                          </TableCell>
                          <TableCell className="max-w-80 text-xs text-muted-foreground">
                            {detail}
                          </TableCell>
                        </TableRow>
                      )
                    })}
                  </TableBody>
                </Table>
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </>
  )
}

function Recon({
  label,
  value,
  tone,
  ratio,
}: {
  label: string
  value: number
  tone: string
  ratio?: number
}) {
  return (
    <div className="rounded-lg border p-4">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className={cn('tabular mt-1 text-2xl font-semibold', tone)}>{formatInteger(value)}</p>
      {ratio !== undefined && (
        <p className="tabular text-xs text-muted-foreground">
          {(ratio * 100).toLocaleString('pt-BR', { maximumFractionDigits: 2 })}% do total
        </p>
      )}
    </div>
  )
}
