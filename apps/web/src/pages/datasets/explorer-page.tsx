import { keepPreviousData, useQuery } from '@tanstack/react-query'
import type { ColumnDef, SortingState } from '@tanstack/react-table'
import { Database, Info, Table2 } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router'

import { DataTable } from '@/components/data-table'
import { PageHeader } from '@/components/page-header'
import { Pagination } from '@/components/pagination'
import { EmptyState, ErrorState, TableSkeleton } from '@/components/states'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { DATA_TYPE_LABEL } from '@/features/datasets/column-form'
import { CellValue } from '@/features/datasets/cell-value'
import { datasetsApi } from '@/features/datasets/api'
import { formatInteger, formatTimestamp } from '@/lib/format'
import type { RowsResponse } from '@/types/api'

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

  const dataset = useQuery({
    queryKey: ['datasets', datasetId],
    queryFn: () => datasetsApi.get(datasetId),
  })
  const versions = useQuery({
    queryKey: ['datasets', datasetId, 'versions'],
    queryFn: () => datasetsApi.versions(datasetId),
  })
  const sort = sorting[0]
  const rows = useQuery({
    queryKey: ['datasets', datasetId, 'rows', { versionId, page, pageSize, sort }],
    queryFn: () =>
      datasetsApi.rows(datasetId, {
        versionId,
        page,
        pageSize,
        sort: sort?.id,
        direction: sort?.desc ? 'desc' : 'asc',
      }),
    placeholderData: keepPreviousData,
    enabled: Boolean(dataset.data?.current_version_id),
  })

  const columns = useMemo<ColumnDef<Row, unknown>[]>(() => buildColumns(rows.data), [rows.data])
  const name = dataset.data?.name ?? 'Dataset'

  return (
    <>
      <PageHeader
        title={`Explorar · ${name}`}
        description="Consulta paginada no servidor via DuckDB sobre o Parquet da versão. Apenas a página atual trafega até o navegador."
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
                setPage(1)
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
      ) : rows.isPending || dataset.isPending ? (
        <TableSkeleton rows={10} columns={6} />
      ) : rows.isError ? (
        <ErrorState error={rows.error} onRetry={() => rows.refetch()} />
      ) : dataset.isError ? (
        <ErrorState error={dataset.error} />
      ) : (
        <div className="space-y-4">
          <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <Info className="size-3.5" /> Clique no cabeçalho para ordenar. Filtros, busca e seleção
            de colunas chegam na Fase 3.
          </p>
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
