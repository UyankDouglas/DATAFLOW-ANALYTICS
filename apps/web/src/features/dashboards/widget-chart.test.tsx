import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { chartData } from './chart-data'
import { kpiResult, teamResult } from './test-fixtures'
import { WidgetChart } from './widget-chart'

describe('WidgetChart', () => {
  it('mostra o KPI com o valor exato e a variação entre os períodos', () => {
    render(<WidgetChart chartType="kpi" result={kpiResult} title="Faturamento" />)
    expect(screen.getByTestId('kpi-value')).toHaveTextContent('1.093,95')
    expect(screen.getByTestId('kpi-variation')).toHaveTextContent('-81,7%')
    expect(screen.getByText(/vs\. 5\.988,80/)).toBeInTheDocument()
    expect(
      screen.getByText('01/02/2025 a 28/02/2025 vs. 04/01/2025 a 31/01/2025'),
    ).toBeInTheDocument()
  })

  it('monta a tabela analítica com o grupo "Outros"', () => {
    render(<WidgetChart chartType="table" result={teamResult} title="Por equipe" />)
    const table = screen.getByRole('table', { name: 'Por equipe' })
    const rows = within(table).getAllByRole('row')
    expect(rows.map((r) => r.textContent)).toEqual([
      'equipeRegistros',
      'Norte3',
      'Leste1',
      'Outros (2 grupos)2',
    ])
  })

  it('avisa quando nenhum registro atende aos filtros', () => {
    render(
      <WidgetChart
        chartType="bar"
        result={{ ...teamResult, rows: [], others: null, matched_rows: 0, total_groups: 0 }}
        title="Vazio"
      />,
    )
    expect(screen.getByText('Nenhum registro atende aos filtros.')).toBeInTheDocument()
  })
})

describe('chartData', () => {
  it('converte para números só a posição e guarda o valor exato para o rótulo', () => {
    const { points, series } = chartData(
      {
        ...kpiResult,
        dimension: teamResult.dimension,
        rows: [{ key: 'Norte', values: ['1093.95'], previous: ['5988.80'] }],
      },
      true,
    )
    expect(series.map((s) => s.label)).toEqual([
      'Soma de valor (atual)',
      'Soma de valor (anterior)',
    ])
    expect(points[0]).toMatchObject({ label: 'Norte', s0: 1093.95, raw_s0: '1093.95', p0: 5988.8 })
  })
})
