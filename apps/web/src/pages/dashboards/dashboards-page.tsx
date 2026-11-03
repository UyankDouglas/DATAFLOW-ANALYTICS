import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { BarChart3, LayoutTemplate, Plus, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'
import { toast } from 'sonner'

import { PageHeader } from '@/components/page-header'
import { EmptyState, ErrorState } from '@/components/states'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Skeleton } from '@/components/ui/skeleton'
import { usePermission } from '@/features/auth/use-auth'
import { dashboardsApi } from '@/features/dashboards/api'
import { CHART_ICON, CHART_TYPE_LABEL } from '@/features/dashboards/format'
import { formatRelative } from '@/lib/format'
import { describeError } from '@/services/api-client'
import type { DashboardSummary } from '@/types/api'

export function DashboardsPage() {
  const canManage = usePermission('dashboards:manage')
  const dashboards = useQuery({ queryKey: ['dashboards'], queryFn: dashboardsApi.list })
  const [removing, setRemoving] = useState<DashboardSummary | null>(null)

  return (
    <>
      <PageHeader
        title="Dashboards"
        description="Indicadores e gráficos calculados pela API sobre as versões publicadas. Nenhum número é guardado: cada widget é recalculado ao abrir."
        actions={
          canManage && (
            <Button asChild>
              <Link to="/dashboards/construtor">
                <Plus /> Novo dashboard
              </Link>
            </Button>
          )
        }
      />

      <Card className="mb-6 overflow-hidden">
        <CardContent className="flex flex-col gap-4 sm:flex-row sm:items-center">
          <div className="self-start rounded-xl bg-primary/10 p-3 text-primary ring-1 ring-primary/20 sm:self-center">
            <BarChart3 className="size-6" aria-hidden />
          </div>
          <div className="min-w-0 flex-1">
            <h2 className="font-semibold">Dashboard geral</h2>
            <p className="text-sm text-muted-foreground">
              Escolha um dataset, a medida e as dimensões: KPIs, evolução temporal, comparação entre
              períodos e tabela analítica, com filtros interativos.
            </p>
          </div>
          <Button asChild variant="outline">
            <Link to="/dashboards/geral">Abrir dashboard geral</Link>
          </Button>
        </CardContent>
      </Card>

      <h2 className="mb-3 text-sm font-semibold">Dashboards salvos</h2>
      {dashboards.isPending ? (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3" aria-busy="true">
          {Array.from({ length: 3 }, (_, i) => (
            <Skeleton key={i} className="h-40" />
          ))}
        </div>
      ) : dashboards.isError ? (
        <ErrorState error={dashboards.error} onRetry={() => dashboards.refetch()} />
      ) : dashboards.data.length === 0 ? (
        <EmptyState
          icon={LayoutTemplate}
          title="Nenhum dashboard salvo"
          description={
            canManage
              ? 'Monte um dashboard no construtor: escolha o dataset e a versão, adicione widgets e salve para reabrir depois.'
              : 'Quem tem perfil de Analista ou Administrador pode montar dashboards para este workspace.'
          }
          action={
            canManage && (
              <Button asChild>
                <Link to="/dashboards/construtor">
                  <Plus /> Criar no construtor
                </Link>
              </Button>
            )
          }
        />
      ) : (
        <ul className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {dashboards.data.map((dashboard) => (
            <li key={dashboard.id}>
              <DashboardCard
                dashboard={dashboard}
                canManage={canManage}
                onRemove={() => setRemoving(dashboard)}
              />
            </li>
          ))}
        </ul>
      )}

      {removing && <RemoveDialog dashboard={removing} onClose={() => setRemoving(null)} />}
    </>
  )
}

function DashboardCard({
  dashboard,
  canManage,
  onRemove,
}: {
  dashboard: DashboardSummary
  canManage: boolean
  onRemove: () => void
}) {
  const types = [...new Set(dashboard.chart_types)]
  return (
    <Card className="h-full gap-3 p-5">
      <div className="min-w-0 space-y-1">
        <Link
          to={`/dashboards/${dashboard.id}`}
          className="block truncate font-semibold hover:underline"
        >
          {dashboard.name}
        </Link>
        {dashboard.description && (
          <p className="line-clamp-2 text-sm text-muted-foreground">{dashboard.description}</p>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-1.5 text-xs">
        <Badge variant="secondary">{dashboard.dataset_name}</Badge>
        <Badge variant="outline">
          {dashboard.version_number ? `Versão ${dashboard.version_number} (fixa)` : 'Versão atual'}
        </Badge>
      </div>
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <span>
          {dashboard.widget_count} widget{dashboard.widget_count === 1 ? '' : 's'}
        </span>
        <span className="flex gap-1" aria-label="Tipos de gráfico">
          {types.map((type) => {
            const Icon = CHART_ICON[type]
            return (
              <Icon
                key={type}
                className="size-3.5"
                aria-label={CHART_TYPE_LABEL[type]}
                role="img"
              />
            )
          })}
        </span>
      </div>
      <p className="text-xs text-muted-foreground">
        Atualizado {formatRelative(dashboard.updated_at)}
        {dashboard.updated_by_name ? ` por ${dashboard.updated_by_name}` : ''}
      </p>
      <div className="mt-auto flex flex-wrap gap-2 pt-1">
        <Button asChild size="sm">
          <Link to={`/dashboards/${dashboard.id}`}>Abrir</Link>
        </Button>
        {canManage && (
          <>
            <Button asChild size="sm" variant="outline">
              <Link to={`/dashboards/construtor/${dashboard.id}`}>Editar</Link>
            </Button>
            <Button
              size="sm"
              variant="ghost"
              aria-label={`Excluir ${dashboard.name}`}
              onClick={onRemove}
            >
              <Trash2 />
            </Button>
          </>
        )}
      </div>
    </Card>
  )
}

function RemoveDialog({
  dashboard,
  onClose,
}: {
  dashboard: DashboardSummary
  onClose: () => void
}) {
  const client = useQueryClient()
  const remove = useMutation({
    mutationFn: () => dashboardsApi.remove(dashboard.id),
    onSuccess: () => {
      toast.success(`Dashboard “${dashboard.name}” excluído.`)
      client.invalidateQueries({ queryKey: ['dashboards'] })
      onClose()
    },
    onError: (error) => toast.error(describeError(error)),
  })
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Excluir o dashboard “{dashboard.name}”?</DialogTitle>
          <DialogDescription>
            A configuração e os {dashboard.widget_count} widgets serão removidos. Os datasets e as
            versões não são alterados. Esta ação não pode ser desfeita.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancelar
          </Button>
          <Button variant="destructive" disabled={remove.isPending} onClick={() => remove.mutate()}>
            Excluir dashboard
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
