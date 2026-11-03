import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { jsonResponse, renderWithProviders } from '@/test/render'
import type { QualityReport } from '@/types/api'

import { QualityPage } from './quality-page'

afterEach(() => vi.unstubAllGlobals())

const version = {
  id: 'v1',
  version_number: 1,
  parent_version_number: null,
  parent_version_id: null,
  row_count: 938,
  quality_score: null,
  column_schema: [
    { name: 'vendedor', data_type: 'text', format: null, scale: null, position: 0 },
    { name: 'valor', data_type: 'decimal', format: null, scale: 2, position: 1 },
  ],
  transformations: { kind: 'import' },
}

const report: QualityReport = {
  id: 'r1',
  dataset_id: 'd1',
  version_id: 'v1',
  version_number: 1,
  formula_version: '1.0',
  score: 96.4,
  metrics: {
    formula: { version: '1.0', weights: { validity: 0.4, completeness: 0.4, uniqueness: 0.2 } },
    components: { validity: 0.938, completeness: 0.9957, uniqueness: 0.951 },
    indicators: {
      received: 1000,
      valid: 938,
      rejected: 62,
      filtered: 0,
      duplicates_removed: null,
      duplicates_remaining: 46,
      null_cells: 36,
      total_cells: 8442,
      completeness: 0.9957,
      columns_with_issues: 3,
      rules_violated: 5,
      violations: 62,
    },
    columns: [
      {
        name: 'vendedor',
        data_type: 'text',
        non_null: 938,
        nulls: 0,
        completeness: 1,
        distinct: 55,
        min: null,
        max: null,
        issues: 0,
      },
      {
        name: 'valor',
        data_type: 'decimal',
        non_null: 938,
        nulls: 0,
        completeness: 1,
        distinct: 891,
        min: '47.38',
        max: '103188.00',
        issues: 7,
      },
    ],
    null_distribution: [{ nulls: 0, rows: 938 }],
    issue_groups_total: 1,
  },
  issues: [
    {
      category: 'rejeitado',
      reason: 'tipo_invalido',
      column: 'valor',
      rule: null,
      rule_label: 'Leitura e mapeamento do arquivo',
      count: 7,
      example_row: 67,
    },
  ],
  computed_by_name: 'Ana',
  computed_at: '2026-11-03T10:00:00Z',
  duration_ms: 272,
}

function mockApi(permissions: string[]) {
  document.cookie = 'df_csrf=tk; path=/'
  let computed = false
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input).replace('/api/v1', '').split('?')[0]
    const key = `${init?.method ?? 'GET'} ${url}`
    switch (key) {
      case 'GET /auth/me':
        return jsonResponse({
          user: { id: 'u', email: 'a@example.com', full_name: 'Ana', created_at: '' },
          workspace: { id: 'w', name: 'W', slug: 'w', role: 'analyst' },
          permissions,
          csrf_token: 'tk',
        })
      case 'GET /datasets':
        return jsonResponse({
          items: [{ id: 'd1', name: 'Qualidade', current_version_number: 1 }],
          total: 1,
          page: 1,
          page_size: 100,
        })
      case 'GET /datasets/d1':
        return jsonResponse({ id: 'd1', name: 'Qualidade', current_version_id: 'v1' })
      case 'GET /datasets/d1/versions':
        return jsonResponse([version])
      case 'GET /datasets/d1/quality':
        return jsonResponse([
          {
            version_id: 'v1',
            version_number: 1,
            parent_version_number: null,
            kind: 'import',
            created_at: '',
            computed,
            score: computed ? 96.4 : null,
            indicators: computed ? report.metrics.indicators : {},
            components: computed ? report.metrics.components : {},
          },
        ])
      case 'GET /datasets/d1/versions/v1/quality':
        return computed
          ? jsonResponse(report)
          : jsonResponse(
              {
                error: { code: 'quality_not_computed', message: 'Não calculado.', details: null },
                request_id: null,
              },
              404,
            )
      case 'POST /datasets/d1/versions/v1/quality':
        computed = true
        return jsonResponse(report)
      case 'GET /datasets/d1/versions/v1/quality/values':
        return jsonResponse({
          column: 'vendedor',
          data_type: 'text',
          total: 938,
          nulls: 0,
          distinct: 55,
          values: [{ value: 'Ana', count: 40 }],
          others: 898,
        })
      case 'GET /datasets/d1/versions/v1/quality/inconsistencies':
        return jsonResponse({
          version_id: 'v1',
          items: [
            {
              row: 67,
              line: 68,
              category: 'rejeitado',
              reason: 'tipo_invalido',
              column: 'valor',
              original_value: 'R$ 99,90',
              rule: null,
              rule_label: 'Leitura e mapeamento do arquivo',
              treatment: 'Excluído da versão; valor original preservado',
              detail: 'Valor não converte para Decimal.',
              duplicate_of: null,
              record: { vendedor: 'Ana', valor: 'R$ 99,90' },
            },
          ],
          total: 1,
          page: 1,
          page_size: 25,
        })
      default:
        return jsonResponse({ error: { code: 'not_found', message: key, details: null } }, 404)
    }
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

describe('QualityPage', () => {
  it('calcula o relatório ausente e mostra nota, indicadores e inconsistências', async () => {
    const fetchMock = mockApi(['datasets:process'])
    renderWithProviders(<QualityPage />, { route: '/qualidade?dataset=d1' })

    await userEvent.click(await screen.findByRole('button', { name: 'Calcular relatório' }))
    expect(await screen.findByTestId('quality-score')).toHaveTextContent('96,4')
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/datasets/d1/versions/v1/quality',
      expect.objectContaining({ method: 'POST' }),
    )

    const indicators = screen.getByRole('region', { name: 'Indicadores' })
    expect(within(indicators).getByText('1.000')).toBeInTheDocument()
    expect(within(indicators).getByText('Regras violadas')).toBeInTheDocument()
    expect(within(indicators).getByText('5')).toBeInTheDocument()

    const table = screen.getByRole('region', { name: 'Inconsistências' })
    expect(await within(table).findByText('R$ 99,90', { selector: 'td' })).toBeInTheDocument()
    expect(within(table).getAllByText('Leitura e mapeamento do arquivo').length).toBeGreaterThan(0)
  })

  it('perfil sem permissão de processar não vê o botão de cálculo', async () => {
    mockApi([])
    renderWithProviders(<QualityPage />, { route: '/qualidade?dataset=d1' })
    expect(await screen.findByText(/Peça a um analista/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Calcular relatório' })).not.toBeInTheDocument()
  })
})
