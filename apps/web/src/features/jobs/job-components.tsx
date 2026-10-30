import { Link } from 'react-router'

import { StatusBadge } from '@/components/status-badge'
import { Progress } from '@/components/ui/progress'
import { formatInteger } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { Job, JobStatus } from '@/types/api'

import { JOB_STATUS_LABEL, JOB_STATUS_TONE, isActive } from './status'

export function JobStatusBadge({
  status,
  cancelRequested,
}: {
  status: JobStatus
  cancelRequested?: boolean
}) {
  if (cancelRequested && isActive(status)) {
    return (
      <StatusBadge tone="warning" pulse>
        Cancelamento solicitado
      </StatusBadge>
    )
  }
  return (
    <StatusBadge tone={JOB_STATUS_TONE[status]} pulse={isActive(status)}>
      {JOB_STATUS_LABEL[status]}
    </StatusBadge>
  )
}

/**
 * Progresso real: percentual de bytes do arquivo efetivamente lidos pelo worker.
 * Sem medida confiável (fila, validação, salvamento), o indicador é indeterminado.
 */
export function JobProgress({ job, compact = false }: { job: Job; compact?: boolean }) {
  const active = isActive(job.status)
  const determinate = job.status === 'processing' && job.progress_percent !== null
  if (!active) {
    if (job.status !== 'succeeded') return null
    return compact ? null : <Progress value={100} aria-label="Processamento concluído" />
  }
  return (
    <div className={cn('space-y-1', compact && 'min-w-32')}>
      {determinate ? (
        <Progress
          value={job.progress_percent ?? 0}
          aria-label={`Progresso ${job.progress_percent}%`}
        />
      ) : (
        <div
          role="progressbar"
          aria-label="Processando (sem estimativa)"
          aria-busy="true"
          className="relative h-2 w-full overflow-hidden rounded-full bg-primary/15"
        >
          <div className="absolute inset-y-0 w-1/3 animate-[indeterminate_1.4s_ease-in-out_infinite] rounded-full bg-primary" />
        </div>
      )}
      <p className="tabular text-xs text-muted-foreground">
        {determinate ? `${job.progress_percent?.toLocaleString('pt-BR')}% do arquivo · ` : ''}
        {formatInteger(job.rows_processed)} registros processados
      </p>
    </div>
  )
}

export function JobLink({ job }: { job: Job }) {
  return (
    <Link
      to={`/processamentos/${job.id}`}
      className="font-medium transition-colors hover:text-primary"
    >
      {job.dataset_name ?? 'Dataset'}
    </Link>
  )
}
