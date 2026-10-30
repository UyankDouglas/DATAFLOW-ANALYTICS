import { api } from '@/services/api-client'
import type {
  DatasetDetail,
  DatasetListItem,
  DatasetVersion,
  ImportRequest,
  Job,
  Page,
  ParseOptions,
  Preview,
  RejectedRowsResponse,
  RowsResponse,
} from '@/types/api'

export interface DatasetListParams {
  page: number
  pageSize: number
  search?: string
  status?: string
}

export interface RowsParams {
  versionId?: string
  page: number
  pageSize: number
  sort?: string
  direction?: 'asc' | 'desc'
}

function query(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== '') search.set(key, String(value))
  }
  const text = search.toString()
  return text ? `?${text}` : ''
}

export const datasetsApi = {
  list: (p: DatasetListParams) =>
    api<Page<DatasetListItem>>(
      `/datasets${query({ page: p.page, page_size: p.pageSize, search: p.search, status: p.status })}`,
    ),
  get: (id: string) => api<DatasetDetail>(`/datasets/${id}`),
  preview: (id: string) => api<Preview>(`/datasets/${id}/preview`),
  tryPreview: (id: string, options: ParseOptions) =>
    api<Preview>(`/datasets/${id}/preview`, { method: 'POST', body: options }),
  versions: (id: string) => api<DatasetVersion[]>(`/datasets/${id}/versions`),
  startImport: (id: string, body: ImportRequest, idempotencyKey: string) =>
    api<Job>(`/datasets/${id}/imports`, {
      method: 'POST',
      body,
      headers: { 'Idempotency-Key': idempotencyKey },
    }),
  rows: (id: string, p: RowsParams) =>
    api<RowsResponse>(
      `/datasets/${id}/rows${query({
        version_id: p.versionId,
        page: p.page,
        page_size: p.pageSize,
        sort: p.sort,
        direction: p.direction,
      })}`,
    ),
  rejected: (id: string, versionId: string, page: number, pageSize: number) =>
    api<RejectedRowsResponse>(
      `/datasets/${id}/versions/${versionId}/rejected${query({ page, page_size: pageSize })}`,
    ),
}
