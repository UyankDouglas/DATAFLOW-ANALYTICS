import { api } from '@/services/api-client'
import type { Job, Overview, Page } from '@/types/api'

export interface JobListParams {
  page: number
  pageSize: number
  status?: string
  datasetId?: string
}

export const jobsApi = {
  list: (p: JobListParams) => {
    const search = new URLSearchParams({ page: String(p.page), page_size: String(p.pageSize) })
    if (p.status) search.set('status', p.status)
    if (p.datasetId) search.set('dataset_id', p.datasetId)
    return api<Page<Job>>(`/jobs?${search.toString()}`)
  },
  get: (id: string) => api<Job>(`/jobs/${id}`),
  cancel: (id: string) => api<Job>(`/jobs/${id}/cancel`, { method: 'POST' }),
  overview: () => api<Overview>('/overview'),
}
