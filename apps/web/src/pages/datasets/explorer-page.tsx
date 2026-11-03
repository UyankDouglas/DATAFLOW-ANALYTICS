import { keepPreviousData, useQuery } from '@tanstack/react-query'
import type { ColumnDef, SortingState } from '@tanstack/react-table'
import { Columns3, Database, Filter, Info, Plus, Search, Table2, X } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router'

import { DataTable } from '@/components/data-table'
import { PageHeader } from '@/components/page-header'
import { Pagination } from '@/components/pagination'
import { EmptyState, ErrorState, TableSkeleton } from '@/components/states'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { ColumnChooser } from '@/features/datasets/column-chooser'
import { DATA_TYPE_LABEL } from '@/features/datasets/column-form'
import { CellValue } from '@/features/datasets/cell-value'
import { datasetsApi } from '@/features/datasets/api'
import { FilterEditor } from '@/features/transformations/rule-editor'
import { useDebouncedValue } from '@/hooks/use-debounced-value'
import { formatInteger, formatTimestamp } from '@/lib/format'
import type { ColumnSpec, Condition, RowsQuery, RowsResponse } from '@/types/api'

type Row = unknown[]

/** Lista datasets prontos para escolher qual explorar. */
export function ExplorerIndexPage() {
  const datasets = useQuery({
    queryKey: ['datasets', { page: 1, pageSize: 50, status: 'ready' }],
    queryFn: () => datasetsApi.list({ page: 1, pageSize: 50, status: 'ready' }),
  })
  return (
    <>
      <PageHeader
        title="Data Explorer"
        description="Escolha um dataset processado para consultar seus registros com paginação no servidor."
      />
      {datasets.isPending ? (
        <TableSkeleton rows={4} columns={3} />
      ) : datasets.isError ? (
        <ErrorState error={datasets.error} onRetry={() => datasets.refetch()} />
      ) : datasets.data.items.length === 0 ? (
        <EmptyState
          icon={Table2}
          title="Nenhum dataset processado"
          description="Processe um arquivo para explorar seus registros."
        />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {datasets.data.items.map((dataset) => (
            <Card
              key={dataset.id}
              className="animate-fade-in transition-colors hover:border-primary/40"
            >
              <CardContent className="space-y-3">
                <div className="flex items-start gap-3">
                  <span className="rounded-lg bg-primary/10 p-2 text-primary">
                    <Database className="size-4" />
                  </span>
                  <div className="min-w-0">
                    <p className="truncate font-medium">{dataset.name}</p>
                    <p className="text-xs text-muted-foreground">
                      v{dataset.current_version_number} · {formatInteger(dataset.row_count)}{' '}
                      registros · {formatTimestamp(dataset.updated_at)}
                    </p>
                  </div>
                </div>
                <Button asChild variant="outline" size="sm" className="w-full">
                  <Link to={`/datasets/${dataset.id}/explorar`}>Explorar registros</Link>
                </Button>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </>
  )
}

export function ExplorerPage() {
  const { datasetId = '' } = useParams()
  const [params, setParams] = useSearchParams()
  const versionId = params.get('versao') ?? undefined
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(50)
  const [sorting, setSorting] = useState<SortingState>([])
  const [searchText, setSearchText] = useState('')
  const search = useDebouncedValue(searchText.trim(), 400)
  // Rascunho editado no painel; só a versão aplicada vai para a consulta.
  const [draft, setDraft] = useState<{ filters: Condition[]; match: 'all' | 'any' }>({
    filters: [],
    match: 'all',
  })
  const [applied, setApplied] = useState(draft)
  const [chosenColumns, setChosenColumns] = useState<string[] | null>(null)
  const [panel, setPanel] = useState<'filters' | 'columns' | null>(null)

  const dataset = useQuery({
    queryKey: ['datasets', datasetId],
    queryFn: () => datasetsApi.get(datasetId),
  })
  const versions = useQuery({
    queryKey: ['datasets', datasetId, 'versions'],
    queryFn: () => datasetsApi.versions(datasetId),
  })
  const selectedVersion =
    versions.data?.find((v) => v.id === (versionId ?? dataset.data?.current_version_id)) ?? null
  const schema: ColumnSpec[] = useMemo(
    () =>
      (selectedVersion?.column_schema ?? []).map((c) => ({
        name: c.name,
        data_type: c.data_type,
        format: c.format,
        scale: c.scale,
      })),
    [selectedVersion],
  )
  const visibleColumns = chosenColumns ?? schema.map((c) => c.name)
  const sort = sorting[0]
  const body: RowsQuery = {
    version_id: versionId,
    page,
    page_size: pageSize,
    sort: sort?.id,
    direction: sort?.desc ? 'desc' : 'asc',
    columns: chosenColumns ?? undefined,
    filters: applied.filters,
    match: applied.match,
    search: search || undefined,
  }
  const rows = useQuery({
    queryKey: ['datasets', datasetId, 'rows', body],
    queryFn: () => datasetsApi.queryRows(datasetId, body),
    placeholderData: keepPreviousData,
    enabled: Boolean(dataset.data?.current_version_id),
    retry: false,
  })

  const columns = useMemo<ColumnDef<Row, unknown>[]>(() => buildColumns(rows.data), [rows.data])
  const name = dataset.data?.name ?? 'Dataset'
  const filtered = applied.filters.length > 0 || Boolean(search)
  const resetVersionState = () => {
    setPage(1)
    setChosenColumns(null)
    setSorting([])
    setDraft({ filters: [], match: 'all' })
    setApplied({ filters: [], match: 'all' })
  }

  return (
    <>
      <PageHeader
        title={`Explorar · ${name}`}
        description="Consulta no servidor via DuckDB sobre o Parquet da versão: filtros, busca e ordenação são aplicados antes da paginação, e só a página atual trafega até o navegador."
        breadcrumbs={[
          { label: 'Datasets', to: '/datasets' },
          { label: name, to: `/datasets/${datasetId}` },
          { label: 'Explorar' },
        ]}
        actions={
          versions.data &&
          versions.data.length > 0 && (
            <Select
              value={versionId ?? versions.data[0]?.id}
              onValueChange={(value) => {
                setParams(value === dataset.data?.current_version_id ? {} : { versao: value })
                resetVersionState()
              }}
            >
              <SelectTrigger className="w-56" aria-label="Versão do dataset">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {versions.data.map((version) => (
                  <SelectItem key={version.id} value={version.id}>
                    Versão {version.version_number}
                    {version.id === dataset.data?.current_version_id ? ' (atual)' : ''} ·{' '}
                    {formatInteger(version.row_count)} reg.
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )
        }
      />

      {dataset.isSuccess && !dataset.data.current_version_id ? (
        <EmptyState
          icon={Table2}
          title="Ainda não há versão processada"
          description="Configure e processe o arquivo para consultar os registros."
          action={
            <Button asChild>
              <Link to={`/datasets/${datasetId}/preview`}>Configurar processamento</Link>
            </Button>
          }
        />
      ) : dataset.isPending || versions.isPending || (rows.isPending && !rows.isError) ? (
        <TableSkeleton rows={10} columns={6} />
      ) : dataset.isError ? (
        <ErrorState error={dataset.error} />
      ) : (
        <div className="space-y-4">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
            <div className="relative flex-1 sm:max-w-sm">
              <Search className="absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={searchText}
                onChange={(event) => {
                  setSearchText(event.target.value)
                  setPage(1)
                }}
                placeholder="Buscar nas colunas de texto"
                aria-label="Buscar nas colunas de texto"
                maxLength={100}
                className="pl-8"
              />
            </div>
            <div className="flex flex-wrap gap-2">
              <Button
                variant={panel === 'filters' ? 'secondary' : 'outline'}
                onClick={() => setPanel(panel === 'filters' ? null : 'filters')}
                aria-expanded={panel === 'filters'}
              >
                <Filter /> Filtros
                {applied.filters.length > 0 && (
                  <span className="rounded bg-primary/15 px-1.5 text-xs text-primary">
                    {applied.filters.length}
                  </span>
                )}
              </Button>
              <Button
                variant={panel === 'columns' ? 'secondary' : 'outline'}
                onClick={() => setPanel(panel === 'columns' ? null : 'columns')}
                aria-expanded={panel === 'columns'}
              >
                <Columns3 /> Colunas ({visibleColumns.length}/{schema.length})
              </Button>
              {(filtered || chosenColumns) && (
                <Button
                  variant="ghost"
                  onClick={() => {
                    setSearchText('')
                    resetVersionState()
                  }}
                >
                  <X /> Limpar
                </Button>
              )}
            </div>
          </div>

          {panel === 'filters' && (
            <Card>
              <CardContent className="space-y-3">
                {draft.filters.length === 0 ? (
                  <p className="text-sm text-muted-foreground">
                    Nenhum filtro. Os operadores disponíveis dependem do tipo de cada coluna.
                  </p>
                ) : (
                  <FilterEditor
                    conditions={draft.filters}
                    match={draft.match}
                    schema={schema}
                    onChange={(filters, match) => setDraft({ filters, match })}
                  />
                )}
                <div className="flex flex-wrap gap-2">
                  {draft.filters.length === 0 && (
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() =>
                        setDraft({
                          ...draft,
                          filters: [{ column: schema[0]?.name ?? '', operator: 'not_null' }],
                        })
                      }
                      disabled={schema.length === 0}
                    >
                      <Plus /> Adicionar filtro
                    </Button>
                  )}
                  <Button
                    size="sm"
                    onClick={() => {
                      setApplied(draft)
                      setPage(1)
                    }}
                  >
                    <Filter /> Aplicar filtros
                  </Button>
                  {draft.filters.length > 0 && (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        setDraft({ filters: [], match: 'all' })
                        setApplied({ filters: [], match: 'all' })
                        setPage(1)
                      }}
                    >
                      Remover filtros
                    </Button>
                  )}
                </div>
              </CardContent>
            </Card>
          )}

          {panel === 'columns' && (
            <Card>
              <CardContent>
                <ColumnChooser
                  columns={schema}
                  value={visibleColumns}
                  onChange={(next) => {
                    setChosenColumns(next)
                    if (sort && !next.includes(sort.id)) setSorting([])
                  }}
                />
              </CardContent>
            </Card>
          )}

          {rows.isError ? (
            <ErrorState error={rows.error} onRetry={() => rows.refetch()} />
          ) : rows.data ? (
            <>
              <p className="flex flex-wrap items-center gap-1.5 text-sm" aria-live="polite">
                <strong className="tabular">{formatInteger(rows.data.total)}</strong>
                {filtered ? (
                  <span className="text-muted-foreground">
                    de {formatInteger(rows.data.total_unfiltered)} registros atendem aos filtros e à
                    busca
                  </span>
                ) : (
                  <span className="text-muted-foreground">registros na versão</span>
                )}
                <span className="flex items-center gap-1 text-xs text-muted-foreground">
                  <Info className="size-3.5" /> Clique no cabeçalho para ordenar. O download do
                  resultado chega com as exportações protegidas (Fase 5).
                </span>
              </p>
              {rows.data.total === 0 ? (
                <EmptyState
                  icon={Table2}
                  title="Nenhum registro encontrado"
                  description="Ajuste a busca ou os filtros."
                />
              ) : (
                <>
                  <DataTable
                    columns={columns}
                    data={rows.data.rows}
                    sorting={sorting}
                    onSortingChange={(next) => {
                      setSorting(next)
                      setPage(1)
                    }}
                    caption={`Registros de ${name}`}
                    dense
                    className={rows.isFetching ? 'opacity-70 transition-opacity' : undefined}
                  />
                  <Pagination
                    page={page}
                    pageSize={pageSize}
                    total={rows.data.total}
                    onPageChange={setPage}
                    onPageSizeChange={(size) => {
                      setPageSize(size)
                      setPage(1)
                    }}
                    pageSizes={[25, 50, 100, 200]}
                  />
                </>
              )}
            </>
          ) : null}
        </div>
      )}
    </>
  )
}

function buildColumns(data: RowsResponse | undefined): ColumnDef<Row, unknown>[] {
  if (!data) return []
  return data.columns.map((column, index) => ({
    id: column.name,
    accessorFn: (row: Row) => row[index],
    enableSorting: true,
    header: () => (
      <span className="flex flex-col items-start normal-case">
        <span className="text-xs font-semibold text-foreground">{column.name}</span>
        <span className="text-[10px] font-normal tracking-normal text-muted-foreground">
          {DATA_TYPE_LABEL[column.data_type]}
        </span>
      </span>
    ),
    cell: ({ getValue }) => <CellValue value={getValue()} type={column.data_type} />,
  }))
}
