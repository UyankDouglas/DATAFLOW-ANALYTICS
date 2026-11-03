import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft,
  ArrowRight,
  Copy,
  Database,
  LayoutTemplate,
  Pencil,
  Plus,
  Save,
  Trash2,
} from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { toast } from 'sonner'

import { PageHeader } from '@/components/page-header'
import { EmptyState, ErrorState } from '@/components/states'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { usePermission } from '@/features/auth/use-auth'
import { dashboardsApi } from '@/features/dashboards/api'
import { CHART_TYPE_LABEL } from '@/features/dashboards/format'
import { MAX_WIDGETS, defaultWidget, widgetProblem } from '@/features/dashboards/rules'
import { useAnalytics } from '@/features/dashboards/use-analytics'
import { GRID_CLASS } from '@/features/dashboards/layout'
import { WidgetCard } from '@/features/dashboards/widget-card'
import { WidgetEditor } from '@/features/dashboards/widget-editor'
import { datasetsApi } from '@/features/datasets/api'
import { FilterEditor } from '@/features/transformations/rule-editor'
import { formatInteger } from '@/lib/format'
import { cn } from '@/lib/utils'
import { ApiError, describeError } from '@/services/api-client'
import type {
  ChartType,
  ColumnSpec,
  Dashboard,
  DashboardInput,
  FilterSet,
  WidgetConfig,
} from '@/types/api'

const CURRENT = '__atual__'

interface Draft extends WidgetConfig {
  key: string
}

let nextKey = 0
const withKey = (widget: WidgetConfig): Draft => ({ ...widget, key: `w${(nextKey += 1)}` })

export function DashboardBuilderPage() {
  const { dashboardId } = useParams()
  const canManage = usePermission('dashboards:manage')
  const existing = useQuery({
    queryKey: ['dashboards', dashboardId],
    queryFn: () => dashboardsApi.get(dashboardId ?? ''),
    enabled: Boolean(dashboardId),
  })
  if (!canManage) {
    return (
      <EmptyState
        icon={LayoutTemplate}
        title="Sem permissão para montar dashboards"
        description="O construtor está disponível para os perfis Analista e Administrador. Você pode abrir e filtrar os dashboards salvos."
        action={
          <Button asChild variant="outline">
            <Link to="/dashboards">Ver dashboards</Link>
          </Button>
        }
      />
    )
  }
  if (dashboardId && existing.isPending) {
    return (
      <div className="space-y-4" aria-busy="true">
        <Skeleton className="h-10 w-64" />
        <Skeleton className="h-48 w-full" />
      </div>
    )
  }
  if (dashboardId && existing.isError) return <ErrorState error={existing.error} />
  return <Builder key={dashboardId ?? 'novo'} initial={existing.data ?? null} />
}

function Builder({ initial }: { initial: Dashboard | null }) {
  const navigate = useNavigate()
  const client = useQueryClient()
  const [name, setName] = useState(initial?.name ?? '')
  const [description, setDescription] = useState(initial?.description ?? '')
  const [datasetId, setDatasetId] = useState(initial?.dataset_id ?? '')
  const [versionId, setVersionId] = useState<string | null>(initial?.version_id ?? null)
  const [filters, setFilters] = useState<FilterSet>(
    initial?.filters ?? { filters: [], match: 'all' },
  )
  const [widgets, setWidgets] = useState<Draft[]>(() => (initial?.widgets ?? []).map(withKey))
  const [editing, setEditing] = useState<{ index: number | null; widget: WidgetConfig } | null>(
    null,
  )
  const [invalidIndex, setInvalidIndex] = useState<number | null>(null)

  const datasets = useQuery({
    queryKey: ['datasets', { status: 'ready', page: 1 }],
    queryFn: () => datasetsApi.list({ page: 1, pageSize: 100, status: 'ready' }),
  })
  const dataset = useQuery({
    queryKey: ['datasets', datasetId],
    queryFn: () => datasetsApi.get(datasetId),
    enabled: Boolean(datasetId),
  })
  const versions = useQuery({
    queryKey: ['datasets', datasetId, 'versions'],
    queryFn: () => datasetsApi.versions(datasetId),
    enabled: Boolean(datasetId),
  })
  const resolvedId = versionId ?? dataset.data?.current_version_id ?? null
  const version = versions.data?.find((v) => v.id === resolvedId)
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
  const ready = Boolean(datasetId && version)
  const problems = widgets.map((w) => widgetProblem(w, schema))
  const canSave =
    ready && name.trim().length > 0 && problems.every((p) => p === null) && widgets.length > 0

  const save = useMutation({
    mutationFn: () => {
      const body: DashboardInput = {
        name: name.trim(),
        description: description.trim() || null,
        dataset_id: datasetId,
        version_id: versionId,
        filters,
        // Só os campos do contrato: a posição sai da ordem da lista.
        widgets: widgets.map(({ id, title, chart_type, size, query }) => ({
          id: id ?? null,
          title,
          chart_type,
          size,
          query,
        })),
      }
      return initial ? dashboardsApi.update(initial.id, body) : dashboardsApi.create(body)
    },
    onSuccess: (saved) => {
      client.invalidateQueries({ queryKey: ['dashboards'] })
      toast.success(initial ? 'Dashboard salvo.' : 'Dashboard criado.')
      navigate(`/dashboards/${saved.id}`)
    },
    onError: (error) => {
      const details =
        error instanceof ApiError ? (error.details as { widget_index?: number }) : null
      setInvalidIndex(details?.widget_index ?? null)
      toast.error(describeError(error))
    },
  })

  const move = (from: number, to: number) => {
    if (to < 0 || to >= widgets.length) return
    const next = [...widgets]
    const [item] = next.splice(from, 1)
    if (item) next.splice(to, 0, item)
    setWidgets(next)
    setInvalidIndex(null)
  }
  const openNew = (chartType: ChartType) =>
    setEditing({ index: null, widget: defaultWidget(chartType, schema) })

  return (
    <>
      <PageHeader
        title={initial ? `Editar · ${initial.name}` : 'Construtor de Dashboards'}
        description="Escolha o dataset e a versão, adicione widgets com medidas, dimensões e filtros, reorganize e salve. Os números são recalculados pela API sempre que o dashboard é aberto."
        breadcrumbs={[
          { label: 'Dashboards', to: '/dashboards' },
          ...(initial ? [{ label: initial.name, to: `/dashboards/${initial.id}` }] : []),
          { label: initial ? 'Editar' : 'Construtor' },
        ]}
        actions={
          <Button disabled={!canSave || save.isPending} onClick={() => save.mutate()}>
            <Save /> {save.isPending ? 'Salvando…' : 'Salvar dashboard'}
          </Button>
        }
      />

      <div className="space-y-6">
        <Card>
          <CardContent className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            <div className="space-y-1.5 xl:col-span-2">
              <Label htmlFor="dashboard-nome">Nome</Label>
              <Input
                id="dashboard-nome"
                value={name}
                maxLength={120}
                placeholder="ex.: Vendas por equipe"
                onChange={(e) => setName(e.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="dashboard-dataset">Dataset</Label>
              <Select
                value={datasetId || undefined}
                onValueChange={(value) => {
                  setDatasetId(value)
                  setVersionId(null)
                  setFilters({ filters: [], match: 'all' })
                }}
              >
                <SelectTrigger id="dashboard-dataset" className="w-full" aria-label="Dataset">
                  <SelectValue placeholder="Escolha um dataset processado" />
                </SelectTrigger>
                <SelectContent>
                  {datasets.data?.items.map((d) => (
                    <SelectItem key={d.id} value={d.id}>
                      {d.name}
                    </SelectItem>
                  ))}
                  {initial && !datasets.data?.items.some((d) => d.id === initial.dataset_id) && (
                    <SelectItem value={initial.dataset_id}>{initial.dataset_name}</SelectItem>
                  )}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="dashboard-versao">Versão</Label>
              <Select
                value={versionId ?? CURRENT}
                onValueChange={(value) => setVersionId(value === CURRENT ? null : value)}
                disabled={!datasetId || !versions.data}
              >
                <SelectTrigger id="dashboard-versao" className="w-full" aria-label="Versão">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={CURRENT}>
                    Atual
                    {dataset.data?.current_version?.version_number
                      ? ` (versão ${dataset.data.current_version.version_number})`
                      : ''}
                  </SelectItem>
                  {versions.data?.map((v) => (
                    <SelectItem key={v.id} value={v.id}>
                      Versão {v.version_number} (fixa) · {formatInteger(v.row_count)} reg.
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <p className="text-xs text-muted-foreground">
                {versionId
                  ? 'Versão fixa: os números não mudam com novas publicações.'
                  : 'Acompanha a versão atual: novas publicações aparecem no dashboard.'}
              </p>
            </div>
            <div className="space-y-1.5 md:col-span-2 xl:col-span-4">
              <Label htmlFor="dashboard-descricao">Descrição (opcional)</Label>
              <Input
                id="dashboard-descricao"
                value={description}
                maxLength={1000}
                placeholder="Para que serve este dashboard"
                onChange={(e) => setDescription(e.target.value)}
              />
            </div>
          </CardContent>
        </Card>

        {!datasetId ? (
          <EmptyState
            icon={Database}
            title="Escolha o dataset"
            description="Os widgets usam as colunas e os tipos da versão escolhida. Só datasets processados aparecem na lista."
          />
        ) : !ready ? (
          <Skeleton className="h-48 w-full" />
        ) : (
          <>
            <Card>
              <CardContent className="space-y-3">
                <div>
                  <h2 className="text-sm font-semibold">Filtros do dashboard</h2>
                  <p className="text-xs text-muted-foreground">
                    Aplicados a todos os widgets, antes dos filtros escolhidos na tela por quem
                    abrir o dashboard.
                  </p>
                </div>
                {filters.filters.length > 0 ? (
                  <FilterEditor
                    conditions={filters.filters}
                    match={filters.match}
                    schema={schema}
                    onChange={(conditions, match) => setFilters({ filters: conditions, match })}
                  />
                ) : (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() =>
                      setFilters({
                        ...filters,
                        filters: [{ column: schema[0]?.name ?? '', operator: 'not_null' }],
                      })
                    }
                  >
                    <Plus /> Filtro do dashboard
                  </Button>
                )}
              </CardContent>
            </Card>

            <section aria-labelledby="widgets-titulo" className="space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h2 id="widgets-titulo" className="text-sm font-semibold">
                  Widgets ({widgets.length}/{MAX_WIDGETS})
                </h2>
                <div className="flex flex-wrap gap-2">
                  {(['kpi', 'bar', 'line', 'table'] as ChartType[]).map((type) => (
                    <Button
                      key={type}
                      variant="outline"
                      size="sm"
                      disabled={widgets.length >= MAX_WIDGETS}
                      onClick={() => openNew(type)}
                    >
                      <Plus /> {CHART_TYPE_LABEL[type]}
                    </Button>
                  ))}
                </div>
              </div>
              {widgets.length === 0 ? (
                <EmptyState
                  icon={LayoutTemplate}
                  title="Nenhum widget ainda"
                  description="Adicione um card KPI, um gráfico ou uma tabela analítica. Outros tipos (área, barras horizontais, pizza e rosca) ficam no editor do widget."
                />
              ) : (
                <div className={GRID_CLASS}>
                  {widgets.map((widget, index) => (
                    <DraftWidget
                      key={widget.key}
                      widget={widget}
                      problem={problems[index] ?? null}
                      highlighted={invalidIndex === index}
                      datasetId={datasetId}
                      versionId={versionId}
                      filters={filters}
                      actions={
                        <>
                          <Button
                            variant="ghost"
                            size="icon-xs"
                            aria-label={`Editar ${widget.title}`}
                            onClick={() => setEditing({ index, widget })}
                          >
                            <Pencil />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon-xs"
                            aria-label={`Mover ${widget.title} para antes`}
                            disabled={index === 0}
                            onClick={() => move(index, index - 1)}
                          >
                            <ArrowLeft />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon-xs"
                            aria-label={`Mover ${widget.title} para depois`}
                            disabled={index === widgets.length - 1}
                            onClick={() => move(index, index + 1)}
                          >
                            <ArrowRight />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon-xs"
                            aria-label={`Duplicar ${widget.title}`}
                            disabled={widgets.length >= MAX_WIDGETS}
                            onClick={() => {
                              const copy = withKey({
                                ...widget,
                                id: null,
                                title: `${widget.title} (cópia)`.slice(0, 120),
                              })
                              setWidgets([
                                ...widgets.slice(0, index + 1),
                                copy,
                                ...widgets.slice(index + 1),
                              ])
                            }}
                          >
                            <Copy />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon-xs"
                            aria-label={`Remover ${widget.title}`}
                            onClick={() => {
                              setWidgets(widgets.filter((_, i) => i !== index))
                              setInvalidIndex(null)
                            }}
                          >
                            <Trash2 />
                          </Button>
                        </>
                      }
                    />
                  ))}
                </div>
              )}
              {!canSave && widgets.length > 0 && (
                <p className="text-xs text-muted-foreground">
                  {!name.trim()
                    ? 'Dê um nome ao dashboard para salvar.'
                    : problems.some((p) => p !== null)
                      ? 'Corrija os widgets marcados para salvar.'
                      : null}
                </p>
              )}
            </section>
          </>
        )}
      </div>

      {editing && version && (
        <WidgetEditor
          open
          onOpenChange={(open) => !open && setEditing(null)}
          initial={editing.widget}
          schema={schema}
          datasetId={datasetId}
          versionId={versionId}
          dashboardFilters={filters}
          onSave={(widget) => {
            if (editing.index === null) setWidgets([...widgets, withKey(widget)])
            else
              setWidgets(
                widgets.map((w, i) => (i === editing.index ? { ...widget, key: w.key } : w)),
              )
            setEditing(null)
            setInvalidIndex(null)
          }}
        />
      )}
    </>
  )
}

function DraftWidget({
  widget,
  problem,
  highlighted,
  datasetId,
  versionId,
  filters,
  actions,
}: {
  widget: Draft
  problem: string | null
  highlighted: boolean
  datasetId: string
  versionId: string | null
  filters: FilterSet
  actions: React.ReactNode
}) {
  const preview = useAnalytics(
    datasetId,
    problem
      ? null
      : {
          ...widget.query,
          version_id: versionId,
          extra_filters: filters.filters.length > 0 ? [filters] : [],
        },
  )
  return (
    <WidgetCard
      title={widget.title}
      chartType={widget.chart_type}
      size={widget.size}
      state={preview}
      problem={problem}
      actions={actions}
      className={cn(highlighted && 'ring-2 ring-destructive')}
    />
  )
}
