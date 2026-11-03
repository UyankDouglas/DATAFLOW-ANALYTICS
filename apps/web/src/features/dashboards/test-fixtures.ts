/** Dados de teste dos dashboards (só usados nos testes do Vitest). */

import { vi } from 'vitest'

import { jsonResponse } from '@/test/render'
import type { AggregateResult, Dashboard, DatasetVersion } from '@/types/api'

export const version: DatasetVersion = {
  id: 'v1',
  version_number: 1,
  status: 'published',
  job_id: 'j1',
  upload_id: 'u1',
  created_by_id: null,
  created_by_name: 'Ana',
  parent_version_id: null,
  parent_version_number: null,
  transformation_set_id: null,
  row_count: 6,
  rejected_count: 0,
  filtered_count: 0,
  duplicate_count: null,
  size_bytes: 1024,
  column_schema: [
    ['data_venda', 'date', null],
    ['equipe', 'text', null],
    ['status', 'text', null],
    ['quantidade', 'integer', null],
    ['valor', 'decimal', 2],
  ].map(([name, data_type, scale], position) => ({
    name: name as string,
    source_name: name as string,
    position,
    data_type: data_type as DatasetVersion['column_schema'][number]['data_type'],
    format: data_type === 'date' ? '%d/%m/%Y' : null,
    scale: scale as number | null,
    null_count: 0,
  })),
  transformations: { kind: 'import', source_format: 'csv' },
  reconciliation: {
    received: 6,
    valid: 6,
    rejected: 0,
    duplicates: null,
    duplicates_policy: 'nao_aplicada',
    consistent: true,
  },
  rules_version: '2.0.0',
  created_at: '2026-11-03T10:00:00Z',
  quality_score: null,
}

export const kpiResult: AggregateResult = {
  version_id: 'v1',
  version_number: 1,
  metrics: [
    {
      key: 'm0',
      aggregation: 'sum',
      column: 'valor',
      label: 'Soma de valor',
      data_type: 'decimal',
      scale: 2,
    },
  ],
  dimension: null,
  rows: [{ key: null, values: ['1093.95'], previous: ['5988.80'] }],
  matched_rows: 3,
  total_groups: null,
  others: null,
  comparison: {
    column: 'data_venda',
    mode: 'previous_period',
    current_start: '2025-02-01',
    current_end: '2025-02-28',
    previous_start: '2025-01-04',
    previous_end: '2025-01-31',
    previous_rows: 3,
  },
  duration_ms: 12,
}

export const teamResult: AggregateResult = {
  version_id: 'v1',
  version_number: 1,
  metrics: [
    {
      key: 'm0',
      aggregation: 'count',
      column: null,
      label: 'Registros',
      data_type: 'integer',
      scale: null,
    },
  ],
  dimension: { column: 'equipe', data_type: 'text', granularity: null },
  rows: [
    { key: 'Norte', values: [3], previous: null },
    { key: 'Leste', values: [1], previous: null },
  ],
  matched_rows: 6,
  total_groups: 4,
  others: { groups: 2, values: [2], previous: null },
  comparison: null,
  duration_ms: 8,
}

export const dashboard: Dashboard = {
  id: 'db1',
  name: 'Vendas',
  description: 'Acompanhamento mensal',
  dataset_id: 'd1',
  dataset_name: 'vendas',
  version_id: null,
  version_number: null,
  resolved_version_id: 'v1',
  resolved_version_number: 1,
  filters: { filters: [{ column: 'status', operator: 'eq', value: 'pago' }], match: 'all' },
  widgets: [
    {
      id: 'w1',
      position: 0,
      title: 'Faturamento registrado',
      chart_type: 'kpi',
      size: 'small',
      query: { metrics: [{ aggregation: 'sum', column: 'valor' }] },
    },
    {
      id: 'w2',
      position: 1,
      title: 'Registros por equipe',
      chart_type: 'table',
      size: 'medium',
      query: { metrics: [{ aggregation: 'count', column: null }], dimension: { column: 'equipe' } },
    },
  ],
  created_by_name: 'Ana',
  updated_by_name: 'Ana',
  created_at: '2026-11-03T10:00:00Z',
  updated_at: '2026-11-03T10:00:00Z',
}

type Handler = (body: unknown) => Response

/** fetch simulado: sessão com as permissões dadas, dataset d1 e rotas extras por chave. */
export function mockApi(permissions: string[], routes: Record<string, Handler> = {}) {
  document.cookie = 'df_csrf=tk; path=/'
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    const key = `${method} ${url.replace('/api/v1', '').split('?')[0]}`
    const body = init?.body ? JSON.parse(String(init.body)) : undefined
    const route = routes[key]
    if (route) return route(body)
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
          items: [{ id: 'd1', name: 'vendas', current_version_number: 1, row_count: 6 }],
          total: 1,
          page: 1,
          page_size: 100,
        })
      case 'GET /datasets/d1':
        return jsonResponse({
          id: 'd1',
          name: 'vendas',
          current_version_id: 'v1',
          current_version: version,
          columns: [],
        })
      case 'GET /datasets/d1/versions':
        return jsonResponse([version])
      default:
        return jsonResponse({ error: { code: 'not_found', message: key, details: null } }, 404)
    }
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

/** Corpos enviados para uma rota (método e caminho), na ordem. */
export function bodiesOf(fetchMock: ReturnType<typeof mockApi>, key: string): unknown[] {
  return fetchMock.mock.calls
    .filter(([input, init]) => {
      const method = init?.method ?? 'GET'
      return `${method} ${String(input).replace('/api/v1', '').split('?')[0]}` === key
    })
    .map(([, init]) => (init?.body ? JSON.parse(String(init.body)) : undefined))
}
