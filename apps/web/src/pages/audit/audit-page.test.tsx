import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { mockApi } from '@/features/dashboards/test-fixtures'
import { jsonResponse, renderWithProviders } from '@/test/render'

import { AuditPage } from './audit-page'

afterEach(() => vi.unstubAllGlobals())

const entry = {
  id: 'a1',
  action: 'export.downloaded',
  entity_type: 'export',
  entity_id: '04ce32d2-0000-4000-8000-000000000000',
  details: { format: 'xlsx', rows: 5 },
  actor_id: 'u',
  actor_name: 'Ana',
  ip_address: '127.0.0.1',
  created_at: '2026-11-03T12:00:00Z',
}

describe('AuditPage', () => {
  it('lista as ações com rótulos e filtra por data no servidor', async () => {
    const fetchMock = mockApi(['audit:view'], {
      'GET /audit': () => jsonResponse({ items: [entry], total: 1, page: 1, page_size: 50 }),
      'GET /audit/actions': () => jsonResponse(['export.downloaded']),
    })
    renderWithProviders(<AuditPage />)
    expect(await screen.findByText('Exportação baixada')).toBeInTheDocument()
    expect(screen.getByText(/export 04ce32d2/)).toBeInTheDocument()
    expect(screen.getByText(/format: xlsx · rows: 5/)).toBeInTheDocument()
    expect(screen.getByText('127.0.0.1')).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText('De'), '2026-11-01')
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([url]) => String(url).includes('date_from=2026-11-01')),
      ).toBe(true),
    )
  })
})
