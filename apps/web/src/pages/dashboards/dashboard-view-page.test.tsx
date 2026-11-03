import { screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  bodiesOf,
  dashboard,
  kpiResult,
  mockApi,
  teamResult,
} from '@/features/dashboards/test-fixtures'
import { jsonResponse, renderWithProviders } from '@/test/render'

import { DashboardViewPage } from './dashboard-view-page'

afterEach(() => vi.unstubAllGlobals())

const routes = (queryWidget: (body: { widget_id: string }) => Response) => ({
  'GET /dashboards/db1': () => jsonResponse(dashboard),
  'POST /dashboards/db1/query': (body: unknown) => queryWidget(body as { widget_id: string }),
})

describe('DashboardViewPage', () => {
  it('calcula cada widget pela API e mostra os filtros salvos', async () => {
    const fetchMock = mockApi(
      ['dashboards:manage'],
      routes(({ widget_id }) =>
        jsonResponse({ widget_id, result: widget_id === 'w1' ? kpiResult : teamResult }),
      ),
    )
    renderWithProviders(<DashboardViewPage />, {
      route: '/dashboards/db1',
      path: '/dashboards/:dashboardId',
    })
    expect(await screen.findByRole('heading', { name: 'Vendas' })).toBeInTheDocument()
    expect(screen.getByText('Versão 1 (atual)')).toBeInTheDocument()
    expect(screen.getByText(/status igual a pago/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Editar/ })).toHaveAttribute(
      'href',
      '/dashboards/construtor/db1',
    )
    const kpi = screen.getByRole('region', { name: 'Faturamento registrado' })
    expect(await within(kpi).findByTestId('kpi-value')).toHaveTextContent('1.093,95')
    const table = screen.getByRole('region', { name: 'Registros por equipe' })
    expect(await within(table).findByText('Outros (2 grupos)')).toBeInTheDocument()
    // Sem filtros escolhidos na tela, cada widget vai sem grupos extras.
    await waitFor(() =>
      expect(bodiesOf(fetchMock, 'POST /dashboards/db1/query')).toEqual(
        expect.arrayContaining([
          { widget_id: 'w1', extra_filters: [] },
          { widget_id: 'w2', extra_filters: [] },
        ]),
      ),
    )
  })

  it('um widget incompatível mostra o motivo sem derrubar os outros', async () => {
    mockApi(
      [],
      routes(({ widget_id }) =>
        widget_id === 'w2'
          ? jsonResponse(
              {
                error: {
                  code: 'widget_incompatible',
                  message:
                    'Este widget não é compatível com a versão 2: Dimensão: coluna desconhecida. Edite o widget ou fixe a versão do dashboard.',
                  details: null,
                },
              },
              422,
            )
          : jsonResponse({ widget_id, result: kpiResult }),
      ),
    )
    renderWithProviders(<DashboardViewPage />, {
      route: '/dashboards/db1',
      path: '/dashboards/:dashboardId',
    })
    const broken = await screen.findByRole('region', { name: 'Registros por equipe' })
    expect(await within(broken).findByRole('alert')).toHaveTextContent('compatível com a versão 2')
    const kpi = screen.getByRole('region', { name: 'Faturamento registrado' })
    expect(await within(kpi).findByTestId('kpi-value')).toHaveTextContent('1.093,95')
    expect(screen.queryByRole('link', { name: /Editar/ })).not.toBeInTheDocument()
  })
})
