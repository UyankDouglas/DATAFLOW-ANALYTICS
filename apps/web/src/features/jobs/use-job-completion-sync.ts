import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef } from 'react'

import type { Job } from '@/types/api'

import { isActive } from './status'

/** Consultas que mudam quando um processamento termina e publica (ou não) uma versão. */
export const JOB_RESULT_QUERY_KEYS = [['datasets'], ['analytics'], ['dashboards'], ['overview']]

export interface SeenJobs {
  active: Set<string>
  listed: Set<string>
}

/**
 * Compara a lista de jobs com a leitura anterior e diz se algum processamento terminou: um que
 * estava em andamento e não está mais, ou um que apareceu já encerrado (rodou inteiro entre duas
 * leituras). A primeira leitura só serve de base.
 */
export function detectFinishedJobs(
  previous: SeenJobs | null,
  jobs: Pick<Job, 'id' | 'status'>[],
): { seen: SeenJobs; finished: boolean } {
  const seen = {
    active: new Set(jobs.filter((job) => isActive(job.status)).map((job) => job.id)),
    listed: new Set(jobs.map((job) => job.id)),
  }
  if (!previous) return { seen, finished: false }
  const stopped = [...previous.active].some((id) => !seen.active.has(id))
  const ranBetweenReads = jobs.some((job) => !isActive(job.status) && !previous.listed.has(job.id))
  return { seen, finished: stopped || ranBetweenReads }
}

/**
 * Revalida as telas quando um processamento termina.
 *
 * Datasets, versões e análises ficam em cache sem polling. Sem isto, uma tela aberta com o
 * dataset ainda em processamento continuava em "Nenhum dataset processado" (Relatórios,
 * Dashboard geral) ou "Ainda não há versão processada" (Data Explorer) até ser aberta de novo.
 * Recebe a lista de jobs que as notificações da barra superior já acompanham em todas as telas.
 */
export function useJobCompletionSync(jobs: Pick<Job, 'id' | 'status'>[] | undefined): void {
  const client = useQueryClient()
  const seen = useRef<SeenJobs | null>(null)
  useEffect(() => {
    if (!jobs) return
    const result = detectFinishedJobs(seen.current, jobs)
    seen.current = result.seen
    if (result.finished) {
      for (const queryKey of JOB_RESULT_QUERY_KEYS) void client.invalidateQueries({ queryKey })
    }
  }, [jobs, client])
}
