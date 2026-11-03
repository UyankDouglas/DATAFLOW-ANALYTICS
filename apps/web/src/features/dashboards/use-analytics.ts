import { keepPreviousData, useQuery } from '@tanstack/react-query'

import type { AnalyticsQuery, FilterSet } from '@/types/api'

import { dashboardsApi } from './api'

/** Consulta analítica avulsa; `body` nulo desliga a consulta (configuração incompleta). */
export function useAnalytics(datasetId: string, body: AnalyticsQuery | null) {
  return useQuery({
    queryKey: ['analytics', datasetId, body],
    queryFn: ({ signal }) => dashboardsApi.analytics(datasetId, body as AnalyticsQuery, signal),
    enabled: Boolean(datasetId && body),
    placeholderData: keepPreviousData,
    retry: false,
    staleTime: 60_000,
  })
}

/** Um widget salvo, recalculado com os filtros da tela. */
export function useWidgetResult(dashboardId: string, widgetId: string, filters: FilterSet[]) {
  return useQuery({
    queryKey: ['dashboards', dashboardId, 'widgets', widgetId, filters],
    queryFn: ({ signal }) => dashboardsApi.query(dashboardId, widgetId, filters, signal),
    placeholderData: keepPreviousData,
    retry: false,
    staleTime: 60_000,
    select: (data) => data.result,
  })
}
