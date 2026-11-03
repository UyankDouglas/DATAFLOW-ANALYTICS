import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { bodiesOf, mockApi } from '@/features/dashboards/test-fixtures'
import { jsonResponse, renderWithProviders } from '@/test/render'
import type { DashboardSummary } from '@/types/api'

import { DashboardsPage } from './dashboards-page'

afterEach(() => vi.unstubAllGlobals())

const summary: DashboardSummary = {
  id: 'db1',
  name: 'Vendas',
  description: 'Acompanhamento mensal',
  dataset_id: 'd1',
  dataset_name: 'vendas',
  version_id: 'v1',
  version_number: 1,
  widget_count: 2,
  chart_types: ['kpi', 'table'],
  updated_by_name: 'Ana',
  updated_at: new Date().toISOString(),
}

describe('DashboardsPage', () => {
  it('lista os dashboards salvos e o acesso ao dashboard geral', async () => {
    mockApi(['dashboards:manage'], { 'GET /dashboards': () => jsonResponse([summary]) })
    renderWithProviders(<DashboardsPage />)
    expect(await screen.findByRole('link', { name: 'Vendas' })).toHaveAttribute(
      'href',
      '/dashboards/db1',
    )
    expect(screen.getByText('Versão 1 (fixa)')).toBeInTheDocument()
    expect(screen.getByText('2 widgets')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Abrir dashboard geral' })).toHaveAttribute(
      'href',
      '/dashboards/geral',
    )
    expect(screen.getByRole('link', { name: /Novo dashboard/ })).toBeInTheDocument()
  })

  it('visualizador abre e filtra, mas não cria, edita nem exclui', async () => {
    mockApi([], { 'GET /dashboards': () => jsonResponse([summary]) })
    renderWithProviders(<DashboardsPage />)
    expect(await screen.findByRole('link', { name: 'Abrir' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /Novo dashboard/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Editar' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Excluir Vendas' })).not.toBeInTheDocument()
  })

  it('exclui só depois da confirmação', async () => {
    let listed = [summary]
    const fetchMock = mockApi(['dashboards:manage'], {
      'GET /dashboards': () => jsonResponse(listed),
      'DELETE /dashboards/db1': () => {
        listed = []
        return new Response(null, { status: 204 })
      },
    })
    renderWithProviders(<DashboardsPage />)
    await userEvent.click(await screen.findByRole('button', { name: 'Excluir Vendas' }))
    expect(bodiesOf(fetchMock, 'DELETE /dashboards/db1')).toHaveLength(0)
    expect(screen.getByText(/não pode ser desfeita/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Excluir dashboard' }))
    await waitFor(() => expect(bodiesOf(fetchMock, 'DELETE /dashboards/db1')).toHaveLength(1))
    expect(await screen.findByText('Nenhum dashboard salvo')).toBeInTheDocument()
  })
})
