import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { jsonResponse, renderWithProviders } from '@/test/render'
import type { DatasetVersion, TransformationSet } from '@/types/api'

import { TransformationsPage } from './transformations-page'

afterEach(() => vi.unstubAllGlobals())

const version: DatasetVersion = {
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
    {
      name: 'vendedor',
      source_name: 'vendedor',
      position: 0,
      data_type: 'text',
      format: null,
      scale: null,
      null_count: 0,
    },
    {
      name: 'valor',
      source_name: 'valor',
      position: 1,
      data_type: 'decimal',
      format: null,
      scale: 2,
      null_count: 0,
    },
  ],
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

const savedSet: TransformationSet = {
  id: 's1',
  dataset_id: 'd1',
  name: 'Limpeza',
  description: null,
  revision: 3,
  rules: [
    { operation: 'trim', enabled: true, columns: ['vendedor'], collapse_internal: true },
    { operation: 'deduplicate', enabled: true, columns: ['vendedor'], keep: 'first' },
  ],
  created_by_name: 'Ana',
  updated_by_name: 'Ana',
  created_at: '2026-11-03T10:00:00Z',
  updated_at: '2026-11-03T10:00:00Z',
}

function mockApi(permissions: string[], overrides: Record<string, () => Response> = {}) {
  document.cookie = 'df_csrf=tk; path=/'
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    const key = `${method} ${url.replace('/api/v1', '').split('?')[0]}`
    if (overrides[key]) return overrides[key]()
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
          items: [{ id: 'd1', name: 'Vendas', current_version_number: 1, row_count: 6 }],
          total: 1,
          page: 1,
          page_size: 100,
        })
      case 'GET /datasets/d1':
        return jsonResponse({ id: 'd1', name: 'Vendas', current_version_id: 'v1', columns: [] })
      case 'GET /datasets/d1/versions':
        return jsonResponse([version])
      case 'GET /datasets/d1/transformation-sets':
        return jsonResponse([savedSet])
      default:
        return jsonResponse({ error: { code: 'not_found', message: key, details: null } }, 404)
    }
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

describe('TransformationsPage', () => {
  it('carrega o conjunto salvo e destaca a regra recusada pelo servidor', async () => {
    const fetchMock = mockApi(['transformations:manage'], {
      'POST /datasets/d1/transformations/preview': () =>
        jsonResponse(
          {
            error: {
              code: 'invalid_rule',
              message: "Regra 1: a coluna 'vendedor' não é de texto",
              details: { rule_index: 0, message: "a coluna 'vendedor' não é de texto" },
            },
            request_id: null,
          },
          422,
        ),
    })
    renderWithProviders(<TransformationsPage />, {
      route: '/transformacoes?dataset=d1&conjunto=s1',
    })

    const rules = await screen.findByRole('list', { name: 'Regras do conjunto' })
    expect(within(rules).getAllByRole('listitem')).toHaveLength(2)
    expect(screen.getByLabelText('Nome do conjunto')).toHaveValue('Limpeza')
    expect(screen.getByText(/gera a versão/)).toHaveTextContent('v2')

    await userEvent.click(screen.getByRole('button', { name: 'Gerar prévia' }))
    const first = screen.getByRole('listitem', { name: /Regra 1: Remover espaços/ })
    expect(await within(first).findByRole('alert')).toHaveTextContent('não é de texto')

    const body = JSON.parse(
      String(fetchMock.mock.calls.find(([url]) => String(url).includes('preview'))?.[1]?.body),
    ) as { source_version_id: string; rules: { operation: string }[] }
    expect(body.source_version_id).toBe('v1')
    expect(body.rules.map((rule) => rule.operation)).toEqual(['trim', 'deduplicate'])
  })

  it('exige salvar antes de aplicar e envia chave de idempotência', async () => {
    const fetchMock = mockApi(['transformations:manage'], {
      'POST /datasets/d1/transform-jobs': () => jsonResponse({ id: 'job-1' }, 202),
    })
    renderWithProviders(<TransformationsPage />, {
      route: '/transformacoes?dataset=d1&conjunto=s1',
    })
    const apply = await screen.findByRole('button', { name: 'Aplicar e gerar nova versão' })
    expect(apply).toBeEnabled()

    await userEvent.type(screen.getByLabelText('Nome do conjunto'), ' v2')
    expect(apply).toBeDisabled()
    expect(screen.getByText(/alterações não salvas/)).toBeInTheDocument()
    expect(fetchMock).not.toHaveBeenCalledWith(
      expect.stringContaining('transform-jobs'),
      expect.anything(),
    )
  })

  it('perfil de leitura vê as regras sem poder editar ou aplicar', async () => {
    mockApi([])
    renderWithProviders(<TransformationsPage />, {
      route: '/transformacoes?dataset=d1&conjunto=s1',
    })
    await screen.findByRole('list', { name: 'Regras do conjunto' })
    expect(screen.getByLabelText('Nome do conjunto')).toBeDisabled()
    expect(screen.queryByRole('button', { name: 'Gerar prévia' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Aplicar/ })).not.toBeInTheDocument()
    await waitFor(() => expect(screen.getByText(/permite apenas visualizar/)).toBeInTheDocument())
  })
})
