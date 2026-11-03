import { api } from '@/services/api-client'
import type {
  ExclusionCategory,
  InconsistencyPage,
  QualityReport,
  QualityVersionSummary,
  ValueFrequency,
} from '@/types/api'

export interface InconsistencyFilters {
  category?: ExclusionCategory
  reason?: string
  column?: string
  page: number
  pageSize: number
}

function query(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== '') search.set(key, String(value))
  }
  const text = search.toString()
  return text ? `?${text}` : ''
}

export const qualityApi = {
  compare: (datasetId: string) => api<QualityVersionSummary[]>(`/datasets/${datasetId}/quality`),
  report: (datasetId: string, versionId: string) =>
    api<QualityReport>(`/datasets/${datasetId}/versions/${versionId}/quality`),
  compute: (datasetId: string, versionId: string) =>
    api<QualityReport>(`/datasets/${datasetId}/versions/${versionId}/quality`, { method: 'POST' }),
  inconsistencies: (datasetId: string, versionId: string, f: InconsistencyFilters) =>
    api<InconsistencyPage>(
      `/datasets/${datasetId}/versions/${versionId}/quality/inconsistencies${query({
        category: f.category,
        reason: f.reason,
        column: f.column,
        page: f.page,
        page_size: f.pageSize,
      })}`,
    ),
  values: (datasetId: string, versionId: string, column: string, limit = 10) =>
    api<ValueFrequency>(
      `/datasets/${datasetId}/versions/${versionId}/quality/values${query({ column, limit })}`,
    ),
}
