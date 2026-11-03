import { useQuery } from '@tanstack/react-query'
import { LayoutTemplate, Pencil } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link, useParams } from 'react-router'

import { PageHeader } from '@/components/page-header'
import { EmptyState, ErrorState } from '@/components/states'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { usePermission } from '@/features/auth/use-auth'
import { dashboardsApi } from '@/features/dashboards/api'
import { describeCondition } from '@/features/dashboards/format'
import {
  EMPTY_QUICK_FILTERS,
  quickFilterSets,
  type QuickFilterState,
} from '@/features/dashboards/quick-filter-state'
import { QuickFilters } from '@/features/dashboards/quick-filters'
import { useWidgetResult } from '@/features/dashboards/use-analytics'
import { GRID_CLASS } from '@/features/dashboards/layout'
import { WidgetCard } from '@/features/dashboards/widget-card'
import { datasetsApi } from '@/features/datasets/api'
import { formatTimestamp } from '@/lib/format'
import type { ColumnSpec, DashboardWidget, FilterSet } from '@/types/api'

export function DashboardViewPage() {
  const { dashboardId = '' } = useParams()
  const canManage = usePermission('dashboards:manage')
  const [filters, setFilters] = useState<QuickFilterState>(EMPTY_QUICK_FILTERS)
  const dashboard = useQuery({
    queryKey: ['dashboards', dashboardId],
    queryFn: () => dashboardsApi.get(dashboardId),
  })
  const datasetId = dashboard.data?.dataset_id ?? ''
  const versions = useQuery({
    queryKey: ['datasets', datasetId, 'versions'],
    queryFn: () => datasetsApi.versions(datasetId),
    enabled: Boolean(datasetId),
  })
  const version = versions.data?.find((v) => v.id === dashboard.data?.resolved_version_id)
  const schema: ColumnSpec[] = useMemo(
    () =>
      (version?.column_schema ?? []).map((c) => ({
        name: c.name,
        data_type: c.data_type,
        format: c.format,
        scale: c.scale,
      })),
    [version],
  )
  const sets = useMemo(() => quickFilterSets(filters, schema), [filters, schema])

  if (dashboard.isPending) {
    return (
      <div className="space-y-4" aria-busy="true">
        <Skeleton className="h-10 w-64" />
        <Skeleton className="h-40 w-full" />
      </div>
    )
  }
  if (dashboard.isError) return <ErrorState error={dashboard.error} />
  const data = dashboard.data
  const saved = data.filters.filters

  return (
    <>
      <PageHeader
        title={data.name}
        description={data.description ?? undefined}
        breadcrumbs={[{ label: 'Dashboards', to: '/dashboards' }, { label: data.name }]}
        actions={
          canManage && (
            <Button asChild variant="outline">
              <Link to={`/dashboards/construtor/${data.id}`}>
                <Pencil /> Editar
              </Link>
            </Button>
          )
        }
      />
      <div className="mb-4 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <Badge variant="secondary">
          <Link to={`/datasets/${data.dataset_id}`} className="hover:underline">
            {data.dataset_name}
          </Link>
        </Badge>
        <Badge variant="outline">
          {data.version_id
            ? `Versão ${data.version_number} (fixa)`
            : `Versão ${data.resolved_version_number ?? '—'} (atual)`}
        </Badge>
        <span>
          Atualizado em {formatTimestamp(data.updated_at)}
          {data.updated_by_name ? ` por ${data.updated_by_name}` : ''}
        </span>
      </div>
      {saved.length > 0 && (
        <p className="mb-4 text-xs text-muted-foreground">
          Filtros salvos ({data.filters.match === 'all' ? 'todos' : 'qualquer um'}):{' '}
          {saved.map(describeCondition).join('; ')}
        </p>
      )}

      {data.widgets.length === 0 ? (
        <EmptyState
          icon={LayoutTemplate}
          title="Este dashboard ainda não tem widgets"
          action={
            canManage && (
              <Button asChild>
                <Link to={`/dashboards/construtor/${data.id}`}>Adicionar widgets</Link>
              </Button>
            )
          }
        />
      ) : (
        <div className="space-y-4">
          {data.resolved_version_id && schema.length > 0 && (
            <QuickFilters
              key={data.resolved_version_id}
              datasetId={data.dataset_id}
              versionId={data.resolved_version_id}
              schema={schema}
              value={filters}
              onApply={setFilters}
            />
          )}
          <div className={GRID_CLASS}>
            {data.widgets.map((widget) => (
              <SavedWidget key={widget.id} dashboardId={data.id} widget={widget} filters={sets} />
            ))}
          </div>
        </div>
      )}
    </>
  )
}

function SavedWidget({
  dashboardId,
  widget,
  filters,
}: {
  dashboardId: string
  widget: DashboardWidget
  filters: FilterSet[]
}) {
  const result = useWidgetResult(dashboardId, widget.id, filters)
  return (
    <WidgetCard
      title={widget.title}
      chartType={widget.chart_type}
      size={widget.size}
      state={result}
    />
  )
}
