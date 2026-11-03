import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  bodiesOf,
  dashboard,
  kpiResult,
  mockApi,
  teamResult,
} from '@/features/dashboards/test-fixtures'
import { jsonResponse, renderWithProviders } from '@/test/render'
import type { AnalyticsQuery } from '@/types/api'

import { DashboardBuilderPage } from './dashboard-builder-page'

afterEach(() => vi.unstubAllGlobals())

const analytics = (body: unknown) =>
  jsonResponse((body as AnalyticsQuery).dimension ? teamResult : kpiResult)

describe('DashboardBuilderPage', () => {
  it('reorganiza os widgets e salva a nova ordem com os ids mantidos', async () => {
    const fetchMock = mockApi(['dashboards:manage'], {
      'GET /dashboards/db1': () => jsonResponse(dashboard),
      'POST /datasets/d1/analytics': analytics,
      'PATCH /dashboards/db1': () => jsonResponse(dashboard),
    })
    renderWithProviders(<DashboardBuilderPage />, {
      route: '/dashboards/construtor/db1',
      path: '/dashboards/construtor/:dashboardId',
    })
    await userEvent.click(
      await screen.findByRole('button', { name: 'Mover Registros por equipe para antes' }),
    )
    // As prévias usam a versão escolhida e os filtros do dashboard como grupo extra.
    const previews = bodiesOf(fetchMock, 'POST /datasets/d1/analytics') as AnalyticsQuery[]
    expect(previews[0]?.extra_filters).toEqual([dashboard.filters])
    expect(previews[0]?.version_id).toBeNull()

    await userEvent.click(screen.getByRole('button', { name: /Salvar dashboard/ }))
    await waitFor(() => expect(bodiesOf(fetchMock, 'PATCH /dashboards/db1')).toHaveLength(1))
    const [body] = bodiesOf(fetchMock, 'PATCH /dashboards/db1') as {
      widgets: Record<string, unknown>[]
    }[]
    expect(body?.widgets.map((w) => w.id)).toEqual(['w2', 'w1'])
    // Só os campos do contrato: a posição vem da ordem da lista.
    expect(Object.keys(body?.widgets[0] ?? {}).sort()).toEqual([
      'chart_type',
      'id',
      'query',
      'size',
      'title',
    ])
  })

  it('destaca o widget recusado pelo servidor', async () => {
    mockApi(['dashboards:manage'], {
      'GET /dashboards/db1': () => jsonResponse(dashboard),
      'POST /datasets/d1/analytics': analytics,
      'PATCH /dashboards/db1': () =>
        jsonResponse(
          {
            error: {
              code: 'invalid_widget',
              message: 'Widget 2 (Registros por equipe): Dimensão: coluna desconhecida.',
              details: { widget_index: 1 },
            },
          },
          422,
        ),
    })
    renderWithProviders(<DashboardBuilderPage />, {
      route: '/dashboards/construtor/db1',
      path: '/dashboards/construtor/:dashboardId',
    })
    await userEvent.click(await screen.findByRole('button', { name: /Salvar dashboard/ }))
    await waitFor(() =>
      expect(screen.getByRole('region', { name: 'Registros por equipe' })).toHaveClass(
        'ring-destructive',
      ),
    )
  })

  it('sem permissão, explica e não mostra o construtor', async () => {
    mockApi([])
    renderWithProviders(<DashboardBuilderPage />, {
      route: '/dashboards/construtor',
      path: '/dashboards/construtor',
    })
    expect(await screen.findByText('Sem permissão para montar dashboards')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Salvar dashboard/ })).not.toBeInTheDocument()
  })
})
