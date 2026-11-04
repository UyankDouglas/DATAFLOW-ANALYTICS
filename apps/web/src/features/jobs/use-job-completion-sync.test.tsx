import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import type { JobStatus } from '@/types/api'

import {
  JOB_RESULT_QUERY_KEYS,
  detectFinishedJobs,
  useJobCompletionSync,
} from './use-job-completion-sync'

const job = (id: string, status: JobStatus) => ({ id, status })

describe('detecção de processamentos encerrados', () => {
  it('a primeira leitura só serve de base, mesmo com jobs encerrados', () => {
    const { finished } = detectFinishedJobs(null, [job('a', 'succeeded'), job('b', 'queued')])
    expect(finished).toBe(false)
  })

  it('job em andamento que passa a concluído, falho ou cancelado conta como encerrado', () => {
    const base = detectFinishedJobs(null, [job('a', 'processing')]).seen
    for (const status of ['succeeded', 'failed', 'cancelled'] as const) {
      expect(detectFinishedJobs(base, [job('a', status)]).finished).toBe(true)
    }
  })

  it('job que avança de etapa sem terminar não conta', () => {
    const base = detectFinishedJobs(null, [job('a', 'queued')]).seen
    expect(detectFinishedJobs(base, [job('a', 'saving')]).finished).toBe(false)
  })

  it('job que rodou inteiro entre duas leituras conta; um antigo já encerrado não', () => {
    const base = detectFinishedJobs(null, [job('antigo', 'succeeded')]).seen
    expect(detectFinishedJobs(base, [job('antigo', 'succeeded')]).finished).toBe(false)
    const next = [job('novo', 'succeeded'), job('antigo', 'succeeded')]
    expect(detectFinishedJobs(base, next).finished).toBe(true)
  })

  it('job novo ainda em andamento não conta', () => {
    const base = detectFinishedJobs(null, []).seen
    expect(detectFinishedJobs(base, [job('novo', 'queued')]).finished).toBe(false)
  })
})

describe('useJobCompletionSync', () => {
  interface Props {
    jobs?: { id: string; status: JobStatus }[]
  }

  function setup() {
    const client = new QueryClient()
    const invalidate = vi.spyOn(client, 'invalidateQueries').mockResolvedValue()
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    )
    const hook = renderHook<void, Props>(({ jobs }) => useJobCompletionSync(jobs), {
      wrapper,
      initialProps: {},
    })
    return { invalidate, rerender: hook.rerender }
  }

  it('revalida datasets, análises, dashboards e visão geral quando o job termina', () => {
    const { invalidate, rerender } = setup()
    rerender({ jobs: [job('a', 'queued')] })
    rerender({ jobs: [job('a', 'processing')] })
    expect(invalidate).not.toHaveBeenCalled()

    rerender({ jobs: [job('a', 'succeeded')] })
    expect(invalidate.mock.calls.map(([filters]) => filters?.queryKey)).toEqual(
      JOB_RESULT_QUERY_KEYS,
    )
  })

  it('não revalida na primeira leitura nem quando a lista não muda', () => {
    const { invalidate, rerender } = setup()
    rerender({ jobs: [job('a', 'succeeded')] })
    rerender({ jobs: [job('a', 'succeeded')] })
    expect(invalidate).not.toHaveBeenCalled()
  })
})
