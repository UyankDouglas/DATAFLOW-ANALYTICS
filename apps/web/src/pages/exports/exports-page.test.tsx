import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { mockApi } from '@/features/dashboards/test-fixtures'
import { jsonResponse, renderWithProviders } from '@/test/render'
import type { ExportJob } from '@/types/api'

import { ExportsPage } from './exports-page'

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
afterEach(() => vi.unstubAllGlobals())

const base: ExportJob = {
  id: 'e1',
  dataset_id: 'd1',
  dataset_name: 'vendas',
  version_id: 'v1',
  version_number: 1,
  kind: 'rows',
  format: 'csv',
  status: 'succeeded',
  file_name: 'vendas_v1_registros_20261103-1200.csv',
  params: {
    rows: { filters: [{ column: 'status', operator: 'eq', value: 'pago' }], search: 'Lima' },
  },
  estimated_rows: 4,
  row_count: 4,
  size_bytes: 2048,
  error_code: null,
  error_message: null,
  created_by_name: 'Ana',
  created_at: '2026-11-03T12:00:00Z',
  started_at: '2026-11-03T12:00:01Z',
  finished_at: '2026-11-03T12:00:02Z',
  expires_at: new Date(Date.now() + 3600_000).toISOString(),
  duration_ms: 900,
  download_count: 0,
}

const page = (items: ExportJob[]) =>
  jsonResponse({ items, total: items.length, page: 1, page_size: 20 })

describe('ExportsPage', () => {
  it('mostra o status, a validade e o download pela API', async () => {
    mockApi(['data:export'], {
      'GET /exports': () =>
        page([
          base,
          {
            ...base,
            id: 'e2',
            status: 'failed',
            file_name: 'falhou.xlsx',
            error_message: 'O armazenamento ficou indisponível.',
          },
          { ...base, id: 'e3', status: 'running', file_name: 'gerando.csv' },
          { ...base, id: 'e4', status: 'expired', file_name: 'antiga.csv' },
        ]),
    })
    renderWithProviders(<ExportsPage />)
    const table = await screen.findByRole('table', { name: 'Histórico de exportações' })
    const rows = within(table).getAllByRole('row').slice(1)
    expect(within(rows[0]!).getByText('Pronta')).toBeInTheDocument()
    expect(
      within(rows[0]!).getByText(/Registros · 1 filtro\(s\) · busca “Lima”/),
    ).toBeInTheDocument()
    expect(within(rows[0]!).getByRole('link', { name: /Baixar/ })).toHaveAttribute(
      'href',
      '/api/v1/exports/e1/download',
    )
    expect(within(rows[1]!).getByText('O armazenamento ficou indisponível.')).toBeInTheDocument()
    expect(within(rows[2]!).getByText('Gerando')).toBeInTheDocument()
    expect(within(rows[2]!).queryByRole('button', { name: /Excluir/ })).toBeNull()
    expect(within(rows[3]!).getByText('Arquivo apagado')).toBeInTheDocument()
    expect(within(rows[3]!).queryByRole('link', { name: /Baixar/ })).toBeNull()
  })

  it('filtra as minhas e exclui', async () => {
    const fetchMock = mockApi(['data:export'], {
      'GET /exports': () => page([base]),
      'DELETE /exports/e1': () => new Response(null, { status: 204 }),
    })
    renderWithProviders(<ExportsPage />)
    await screen.findByText(base.file_name)
    await userEvent.click(screen.getByRole('checkbox', { name: 'Somente as minhas' }))
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([url]) => String(url).includes('mine=true'))).toBe(true),
    )
    await userEvent.click(screen.getByRole('button', { name: `Excluir ${base.file_name}` }))
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(
          ([url, init]) => String(url).endsWith('/exports/e1') && init?.method === 'DELETE',
        ),
      ).toBe(true),
    )
  })
})
