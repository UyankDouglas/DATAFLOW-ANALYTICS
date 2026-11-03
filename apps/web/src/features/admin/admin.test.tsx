import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { toast } from 'sonner'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { bodiesOf, mockApi } from '@/features/dashboards/test-fixtures'
import { jsonResponse, renderWithProviders } from '@/test/render'
import type { DatasetImpact, ExportJob } from '@/types/api'

import { DeleteDatasetDialog } from './deletion-dialogs'
import { ExportMenu } from './export-menu'
import { auditLabel, describeDetails } from './labels'

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

afterEach(() => {
  vi.unstubAllGlobals()
  vi.clearAllMocks()
})

describe('describeDetails', () => {
  it('resume os detalhes da auditoria com ids curtos', () => {
    expect(
      describeDetails({
        dataset_id: '7dff4b54-f934-47b6-a607-1101c4ff1a89',
        format: 'xlsx',
        rows: 5,
        vazio: null,
      }),
    ).toBe('dataset_id: 7dff4b54 · format: xlsx · rows: 5')
    expect(auditLabel('export.downloaded')).toBe('Exportação baixada')
    expect(auditLabel('acao.nova')).toBe('acao.nova')
  })
})

describe('ExportMenu', () => {
  const job = { id: 'e1', estimated_rows: 4 } as ExportJob

  it('não aparece para quem não pode exportar', async () => {
    mockApi([])
    renderWithProviders(
      <ExportMenu request={(format) => ({ dataset_id: 'd1', kind: 'rows', format })} />,
    )
    await waitFor(() => expect(screen.queryByRole('button', { name: /Exportar/ })).toBeNull())
  })

  it('pede a exportação no formato escolhido', async () => {
    const fetchMock = mockApi(['data:export'], { 'POST /exports': () => jsonResponse(job, 202) })
    renderWithProviders(
      <ExportMenu
        request={(format, style) => ({
          dataset_id: 'd1',
          kind: 'rows',
          format,
          csv_style: style,
          rows: { search: 'Lima' },
        })}
      />,
    )
    await userEvent.click(await screen.findByRole('button', { name: /Exportar/ }))
    await userEvent.click(await screen.findByRole('menuitem', { name: /Planilha XLSX/ }))
    await waitFor(() =>
      expect(bodiesOf(fetchMock, 'POST /exports')).toEqual([
        { dataset_id: 'd1', kind: 'rows', format: 'xlsx', rows: { search: 'Lima' } },
      ]),
    )
    expect(toast.success).toHaveBeenCalledWith(
      'Exportação de 4 registros na fila.',
      expect.objectContaining({ description: 'Ela fica pronta na tela Exportações.' }),
    )
  })
})

describe('DeleteDatasetDialog', () => {
  const impact: DatasetImpact = {
    dataset_id: 'd1',
    dataset_name: 'vendas',
    versions: 2,
    uploads: 1,
    jobs: 2,
    exports: 1,
    stored_bytes: 2048,
    dashboards: [{ id: 'db1', name: 'Comercial' }],
    blocked_reason: null,
  }

  it('só exclui depois de digitar o nome do dataset', async () => {
    const onDeleted = vi.fn()
    const fetchMock = mockApi([], {
      'GET /datasets/d1/deletion-impact': () => jsonResponse(impact),
      'DELETE /datasets/d1': () => new Response(null, { status: 204 }),
    })
    renderWithProviders(
      <DeleteDatasetDialog datasetId="d1" onClose={() => undefined} onDeleted={onDeleted} />,
    )
    expect(await screen.findByText('Dashboards apagados junto: Comercial.')).toBeInTheDocument()
    const button = screen.getByRole('button', { name: 'Excluir definitivamente' })
    expect(button).toBeDisabled()
    await userEvent.type(screen.getByLabelText(/para confirmar/), 'vend')
    expect(button).toBeDisabled()
    await userEvent.type(screen.getByLabelText(/para confirmar/), 'as')
    await userEvent.click(button)
    await waitFor(() => expect(onDeleted).toHaveBeenCalled())
    expect(bodiesOf(fetchMock, 'DELETE /datasets/d1')).toEqual([{ confirm_name: 'vendas' }])
  })

  it('explica o que impede a exclusão', async () => {
    mockApi([], {
      'GET /datasets/d1/deletion-impact': () =>
        jsonResponse({ ...impact, blocked_reason: 'Há um processamento em andamento.' }),
    })
    renderWithProviders(
      <DeleteDatasetDialog datasetId="d1" onClose={() => undefined} onDeleted={() => undefined} />,
    )
    expect(await screen.findByText('Há um processamento em andamento.')).toBeInTheDocument()
    expect(screen.queryByLabelText(/para confirmar/)).toBeNull()
    expect(screen.getByRole('button', { name: 'Excluir definitivamente' })).toBeDisabled()
  })
})
