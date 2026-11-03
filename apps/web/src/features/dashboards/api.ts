import { api } from '@/services/api-client'
import type {
  AggregateResult,
  AnalyticsQuery,
  Dashboard,
  DashboardInput,
  DashboardSummary,
  FilterSet,
  WidgetResult,
} from '@/types/api'

export const dashboardsApi = {
  /** Consulta avulsa sobre uma versão (Dashboard geral e prévia do construtor). */
  analytics: (datasetId: string, body: AnalyticsQuery, signal?: AbortSignal) =>
    api<AggregateResult>(`/datasets/${datasetId}/analytics`, { method: 'POST', body, signal }),
  list: () => api<DashboardSummary[]>('/dashboards'),
  get: (id: string) => api<Dashboard>(`/dashboards/${id}`),
  create: (body: DashboardInput) => api<Dashboard>('/dashboards', { method: 'POST', body }),
  update: (id: string, body: Partial<DashboardInput>) =>
    api<Dashboard>(`/dashboards/${id}`, { method: 'PATCH', body }),
  remove: (id: string) => api<void>(`/dashboards/${id}`, { method: 'DELETE' }),
  /** Um widget salvo, com os grupos de filtros da tela somados aos filtros salvos. */
  query: (id: string, widgetId: string, extraFilters: FilterSet[], signal?: AbortSignal) =>
    api<WidgetResult>(`/dashboards/${id}/query`, {
      method: 'POST',
      body: { widget_id: widgetId, extra_filters: extraFilters },
      signal,
    }),
}
