import { AlertTriangle, RefreshCw } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { formatDuration, formatInteger } from '@/lib/format'
import { cn } from '@/lib/utils'
import { describeError } from '@/services/api-client'
import type { AggregateResult, ChartType, WidgetSize } from '@/types/api'

import { CHART_TYPE_LABEL } from './format'
import { SIZE_CLASS } from './layout'
import { WidgetChart } from './widget-chart'

export interface WidgetState {
  data?: AggregateResult
  isPending: boolean
  isError: boolean
  isFetching?: boolean
  error: unknown
  refetch: () => unknown
}

export function WidgetCard({
  title,
  chartType,
  size,
  state,
  actions,
  problem,
  className,
}: {
  title: string
  chartType: ChartType
  size: WidgetSize
  state: WidgetState
  actions?: React.ReactNode
  /** Configuração incompleta: mostra o motivo no lugar do gráfico. */
  problem?: string | null
  className?: string
}) {
  const result = state.data
  return (
    <Card
      className={cn('min-w-0 animate-fade-in gap-3 p-4', SIZE_CLASS[size], className)}
      aria-label={title}
      role="region"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="line-clamp-2 text-sm font-semibold break-words">{title}</h3>
          <p className="text-xs text-muted-foreground">{CHART_TYPE_LABEL[chartType]}</p>
        </div>
        {actions && <div className="flex shrink-0 items-center gap-0.5">{actions}</div>}
      </div>
      <div className={cn('min-w-0', state.isFetching && result && 'opacity-70 transition-opacity')}>
        {problem ? (
          <p className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">
            {problem}
          </p>
        ) : state.isError ? (
          <div
            role="alert"
            className="flex flex-col items-start gap-2 rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm"
          >
            <p className="flex items-start gap-1.5">
              <AlertTriangle className="mt-0.5 size-4 shrink-0 text-destructive" aria-hidden />
              {describeError(state.error)}
            </p>
            <Button variant="outline" size="xs" onClick={() => state.refetch()}>
              <RefreshCw /> Tentar novamente
            </Button>
          </div>
        ) : !result ? (
          <Skeleton
            className={chartType === 'kpi' ? 'h-16 w-full' : 'h-52 w-full'}
            aria-label="Carregando"
          />
        ) : (
          <WidgetChart chartType={chartType} result={result} title={title} />
        )}
      </div>
      {result && !problem && !state.isError && (
        <p className="text-xs text-muted-foreground">
          {chartType !== 'kpi' && <>{formatInteger(result.matched_rows)} registros · </>}
          versão {result.version_number}
          {result.others && (
            <>
              {' '}
              · {formatInteger(result.rows.length)} de {formatInteger(result.total_groups)} grupos,
              os demais em “Outros”
            </>
          )}{' '}
          · {formatDuration(result.duration_ms)}
        </p>
      )}
    </Card>
  )
}
