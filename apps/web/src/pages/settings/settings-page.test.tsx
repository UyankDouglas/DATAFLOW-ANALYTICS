import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { bodiesOf, mockApi } from '@/features/dashboards/test-fixtures'
import { jsonResponse, renderWithProviders } from '@/test/render'

import { SettingsPage } from './settings-page'

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
afterEach(() => vi.unstubAllGlobals())

const current = {
  id: 'w',
  name: 'Comercial',
  slug: 'comercial',
  settings: { export_ttl_hours: 24, viewer_exports: false, original_retention_days: null },
}

describe('SettingsPage', () => {
  it('administrador salva validade, exportação por visualizadores e retenção', async () => {
    const fetchMock = mockApi(['workspace:view', 'workspace:manage'], {
      'GET /workspaces/current/settings': () => jsonResponse(current),
      'PATCH /workspaces/current': (body) => jsonResponse({ ...current, ...(body as object) }),
    })
    renderWithProviders(<SettingsPage />)
    const ttl = await screen.findByLabelText('Validade dos arquivos (horas)')
    await waitFor(() => expect(ttl).toBeEnabled()) // permissões vêm da sessão
    await userEvent.clear(ttl)
    await userEvent.type(ttl, '48')
    await userEvent.click(screen.getByRole('checkbox', { name: /Visualizadores podem exportar/ }))
    await userEvent.click(screen.getByRole('checkbox', { name: 'Apagar originais antigos' }))
    const days = screen.getByLabelText('Prazo (dias)')
    await userEvent.clear(days)
    await userEvent.type(days, '3')
    expect(screen.getByRole('button', { name: /Salvar configurações/ })).toBeDisabled() // mínimo 7
    await userEvent.type(days, '0')
    await userEvent.click(screen.getByRole('button', { name: /Salvar configurações/ }))
    await waitFor(() =>
      expect(bodiesOf(fetchMock, 'PATCH /workspaces/current')).toEqual([
        {
          name: 'Comercial',
          settings: { export_ttl_hours: 48, viewer_exports: true, original_retention_days: 30 },
        },
      ]),
    )
  })

  it('quem não é administrador só consulta', async () => {
    mockApi(['workspace:view'], {
      'GET /workspaces/current/settings': () => jsonResponse(current),
    })
    renderWithProviders(<SettingsPage />)
    expect(await screen.findByText(/Somente administradores alteram/)).toBeInTheDocument()
    expect(screen.getByLabelText('Nome')).toBeDisabled()
    expect(screen.queryByRole('button', { name: /Salvar configurações/ })).toBeNull()
  })
})
