import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { Job } from '@/types/api'

import { JobProgress, JobStatusBadge } from './job-components'

const baseJob = {
  id: 'j1',
  status: 'processing',
  progress_percent: 42.5,
  rows_processed: 12500,
  cancel_requested: false,
} as Job

describe('acompanhamento de jobs', () => {
  it('mostra percentual real quando o worker reporta bytes lidos', () => {
    render(<JobProgress job={baseJob} />)
    expect(screen.getByRole('progressbar', { name: /Progresso 42.5%/ })).toBeInTheDocument()
    expect(screen.getByText(/42,5% do arquivo/)).toBeInTheDocument()
    expect(screen.getByText(/12\.500 registros processados/)).toBeInTheDocument()
  })

  it('usa indicador indeterminado quando não há estimativa confiável', () => {
    render(
      <JobProgress
        job={{ ...baseJob, status: 'queued', progress_percent: null, rows_processed: 0 }}
      />,
    )
    expect(
      screen.getByRole('progressbar', { name: 'Processando (sem estimativa)' }),
    ).toBeInTheDocument()
    expect(screen.queryByText(/% do arquivo/)).not.toBeInTheDocument()
  })

  it('exibe rótulos em português a partir dos códigos estáveis', () => {
    const { rerender } = render(<JobStatusBadge status="succeeded" />)
    expect(screen.getByText('Concluído')).toBeInTheDocument()
    rerender(<JobStatusBadge status="processing" cancelRequested />)
    expect(screen.getByText('Cancelamento solicitado')).toBeInTheDocument()
    rerender(<JobStatusBadge status="cancelled" cancelRequested />)
    expect(screen.getByText('Cancelado')).toBeInTheDocument()
  })
})
