import { screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { bodiesOf, mockApi, teamResult } from '@/features/dashboards/test-fixtures'
import { jsonResponse, renderWithProviders } from '@/test/render'
import type { AggregateResult, AnalyticsQuery } from '@/types/api'

import { GeneralDashboardPage } from './general-dashboard-page'

afterEach(() => vi.unstubAllGlobals())

const kpis: AggregateResult = {
  ...teamResult,
  dimension: null,
  others: null,
  total_groups: null,
  metrics: [
    ['count', null, 'Registros', 'integer', null],
    ['sum', 'valor', 'Soma de valor', 'decimal', 2],
    ['avg', 'valor', 'Média de valor', 'decimal', 4],
    ['max', 'valor', 'Máximo de valor', 'decimal', 2],
    ['min', 'valor', 'Mínimo de valor', 'decimal', 2],
    ['count_distinct', 'equipe', 'Distintos de equipe', 'integer', null],
  ].map(([aggregation, column, label, data_type, scale], index) => ({
    key: `m${index}`,
    aggregation: aggregation as AggregateResult['metrics'][number]['aggregation'],
    column: column as string | null,
    label: label as string,
    data_type: data_type as AggregateResult['metrics'][number]['data_type'],
    scale: scale as number | null,
  })),
  rows: [{ key: null, values: [6, '7082.75', '1180.4583', '4599.90', '44.95', 3], previous: null }],
}

function analytics(body: unknown): Response {
  const query = body as AnalyticsQuery
  if (query.dimension) return jsonResponse(teamResult)
  if (query.metrics[0]?.aggregation === 'min')
    return jsonResponse({
      ...kpis,
      metrics: kpis.metrics.slice(0, 2),
      rows: [{ key: null, values: ['2025-01-05', '2025-02-28'], previous: null }],
    })
  return jsonResponse(kpis)
}

describe('GeneralDashboardPage', () => {
  it('calcula os KPIs com a medida e a categoria escolhidas', async () => {
    const fetchMock = mockApi([], { 'POST /datasets/d1/analytics': analytics })
    renderWithProviders(<GeneralDashboardPage />, {
      route: '/dashboards/geral?dataset=d1&medida=valor&categoria=equipe',
      path: '/dashboards/geral',
    })
    const indicators = await screen.findByRole('region', { name: 'Indicadores' })
    expect(await within(indicators).findByText('7.082,75')).toBeInTheDocument()
    expect(within(indicators).getByText('Soma de valor')).toBeInTheDocument()
    expect(within(indicators).getByText('1.180,4583')).toBeInTheDocument()
    expect(within(indicators).getByText('equipe distintos')).toBeInTheDocument()
    await waitFor(() => {
      const kpiBody = (bodiesOf(fetchMock, 'POST /datasets/d1/analytics') as AnalyticsQuery[]).find(
        (b) => b.metrics.length === 6,
      )
      expect(kpiBody?.metrics.map((m) => `${m.aggregation}:${m.column ?? ''}`)).toEqual([
        'count:',
        'sum:valor',
        'avg:valor',
        'max:valor',
        'min:valor',
        'count_distinct:equipe',
      ])
    })
    // O período sugerido para a comparação termina na data mais recente dos dados.
    expect(await screen.findByLabelText('Fim')).toHaveValue('2025-02-28')
  })

  it('sem medida escolhida, mostra só contagens e não presume receita', async () => {
    const fetchMock = mockApi([], { 'POST /datasets/d1/analytics': analytics })
    renderWithProviders(<GeneralDashboardPage />, {
      route: '/dashboards/geral?dataset=d1',
      path: '/dashboards/geral',
    })
    expect(await screen.findByText(/Escolha uma medida numérica/)).toBeInTheDocument()
    await waitFor(() => {
      const bodies = bodiesOf(fetchMock, 'POST /datasets/d1/analytics') as AnalyticsQuery[]
      expect(bodies.length).toBeGreaterThan(0)
      expect(bodies.flatMap((b) => b.metrics).some((m) => m.aggregation === 'sum')).toBe(false)
    })
  })
})
