import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { jsonResponse, renderWithProviders } from '@/test/render'
import type { RowsQuery } from '@/types/api'

import { ExplorerPage } from './explorer-page'

afterEach(() => vi.unstubAllGlobals())

const schema = [
  { name: 'vendedor', data_type: 'text', format: null, scale: null, position: 0 },
  { name: 'valor', data_type: 'decimal', format: null, scale: 2, position: 1 },
]

function mockApi() {
  document.cookie = 'df_csrf=tk; path=/'
  const bodies: RowsQuery[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input).replace('/api/v1', '').split('?')[0]
      if (url === '/datasets/d1') {
        return jsonResponse({ id: 'd1', name: 'Vendas', current_version_id: 'v1' })
      }
      if (url === '/datasets/d1/versions') {
        return jsonResponse([{ id: 'v1', version_number: 1, row_count: 6, column_schema: schema }])
      }
      if (url === '/datasets/d1/rows/query') {
        const body = JSON.parse(String(init?.body)) as RowsQuery
        bodies.push(body)
        const filtered = body.filters.length > 0 || Boolean(body.search)
        const names = body.columns ?? ['vendedor', 'valor']
        return jsonResponse({
          version_id: 'v1',
          version_number: 1,
          columns: names.map((name) => schema.find((c) => c.name === name)),
          rows: [names.map((name) => (name === 'valor' ? '89.90' : 'Bruno Lima'))],
          total: filtered ? 2 : 6,
          total_unfiltered: 6,
          page: body.page,
          page_size: body.page_size,
        })
      }
      return jsonResponse({ error: { code: 'not_found', message: url, details: null } }, 404)
    }),
  )
  return bodies
}

describe('ExplorerPage', () => {
  it('envia busca, filtros e colunas ao servidor e mostra a contagem filtrada', async () => {
    const bodies = mockApi()
    renderWithProviders(<ExplorerPage />, {
      route: '/datasets/d1/explorar',
      path: '/datasets/:datasetId/explorar',
    })
    expect(await screen.findByText('registros na versão')).toBeInTheDocument()

    await userEvent.type(screen.getByLabelText('Buscar nas colunas de texto'), 'lima')
    await waitFor(() => expect(bodies.at(-1)?.search).toBe('lima'))
    expect(await screen.findByText(/de 6 registros atendem/)).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: /Filtros/ }))
    await userEvent.click(screen.getByRole('button', { name: 'Adicionar filtro' }))
    await userEvent.click(screen.getByRole('button', { name: 'Aplicar filtros' }))
    await waitFor(() =>
      expect(bodies.at(-1)?.filters).toEqual([{ column: 'vendedor', operator: 'not_null' }]),
    )
    expect(bodies.at(-1)?.match).toBe('all')

    await userEvent.click(screen.getByRole('button', { name: /Colunas/ }))
    await userEvent.click(screen.getByRole('checkbox', { name: 'Mostrar vendedor' }))
    await waitFor(() => expect(bodies.at(-1)?.columns).toEqual(['valor']))
    expect(bodies.every((body) => body.page_size === 50)).toBe(true)
  })
})
