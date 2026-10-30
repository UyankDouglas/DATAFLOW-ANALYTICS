import { keepPreviousData, useQuery } from '@tanstack/react-query'
import type { ColumnDef } from '@tanstack/react-table'
import { Database, Search, Upload } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link } from 'react-router'

import { DataTable } from '@/components/data-table'
import { PageHeader } from '@/components/page-header'
import { Pagination } from '@/components/pagination'
import { EmptyState, ErrorState, TableSkeleton } from '@/components/states'
import { StatusBadge } from '@/components/status-badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { usePermission } from '@/features/auth/use-auth'
import { datasetsApi } from '@/features/datasets/api'
import { DATASET_STATUS_LABEL, DATASET_STATUS_TONE } from '@/features/jobs/status'
import { useDebouncedValue } from '@/hooks/use-debounced-value'
import { formatBytes, formatInteger, formatTimestamp } from '@/lib/format'
import type { DatasetListItem, DatasetStatus } from '@/types/api'

const ALL = 'all'

export function DatasetsPage() {
  const canUpload = usePermission('datasets:upload')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState<string>(ALL)
  const debouncedSearch = useDebouncedValue(search.trim())

  const datasets = useQuery({
    queryKey: ['datasets', { page, pageSize, search: debouncedSearch, status }],
    queryFn: () =>
      datasetsApi.list({
        page,
        pageSize,
        search: debouncedSearch,
        status: status === ALL ? undefined : status,
      }),
    placeholderData: keepPreviousData,
    refetchInterval: (query) =>
      query.state.data?.items.some((d) => d.status === 'processing') ? 4000 : false,
  })

  const columns = useMemo<ColumnDef<DatasetListItem, unknown>[]>(
    () => [
      {
        header: 'Nome',
        accessorKey: 'name',
        cell: ({ row }) => (
          <div className="min-w-48">
            <Link to={`/datasets/${row.original.id}`} className="font-medium hover:text-primary">
              {row.original.name}
            </Link>
            <p className="truncate text-xs text-muted-foreground">
              {row.original.latest_upload?.original_filename}
            </p>
          </div>
        ),
      },
      {
        header: 'Status',
        accessorKey: 'status',
        cell: ({ row }) => (
          <StatusBadge
            tone={DATASET_STATUS_TONE[row.original.status]}
            pulse={row.original.status === 'processing'}
          >
            {DATASET_STATUS_LABEL[row.original.status]}
          </StatusBadge>
        ),
      },
      {
        header: 'Versão atual',
        accessorKey: 'current_version_number',
        cell: ({ getValue }) => {
          const value = getValue() as number | null
          return value ? `v${value}` : <span className="text-muted-foreground">—</span>
        },
      },
      {
        header: 'Registros',
        accessorKey: 'row_count',
        cell: ({ getValue }) => (
          <span className="tabular">{formatInteger(getValue() as number | null)}</span>
        ),
      },
      {
        header: 'Tamanho',
        id: 'size',
        cell: ({ row }) => (
          <span className="tabular">{formatBytes(row.original.latest_upload?.size_bytes)}</span>
        ),
      },
      {
        header: 'Criado em',
        accessorKey: 'created_at',
        cell: ({ getValue }) => (
          <span className="tabular whitespace-nowrap">{formatTimestamp(getValue() as string)}</span>
        ),
      },
      {
        id: 'actions',
        header: () => <span className="sr-only">Ações</span>,
        cell: ({ row }) =>
          row.original.status === 'ready' ? (
            <Button asChild variant="ghost" size="sm">
              <Link to={`/datasets/${row.original.id}/explorar`}>Explorar</Link>
            </Button>
          ) : row.original.status === 'draft' || row.original.status === 'failed' ? (
            <Button asChild variant="ghost" size="sm">
              <Link to={`/datasets/${row.original.id}/preview`}>Configurar</Link>
            </Button>
          ) : null,
      },
    ],
    [],
  )

  const data = datasets.data
  const filtering = debouncedSearch !== '' || status !== ALL

  return (
    <>
      <PageHeader
        title="Datasets"
        description="Arquivos importados e suas versões processadas."
        actions={
          canUpload && (
            <Button asChild>
              <Link to="/importar">
                <Upload /> Importar dados
              </Link>
            </Button>
          )
        }
      />
      <div className="mb-4 flex flex-col gap-3 sm:flex-row">
        <div className="relative flex-1">
          <Search
            className="absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground"
            aria-hidden
          />
          <Input
            value={search}
            onChange={(event) => {
              setSearch(event.target.value)
              setPage(1)
            }}
            placeholder="Buscar por nome"
            aria-label="Buscar datasets por nome"
            className="pl-9"
          />
        </div>
        <Select
          value={status}
          onValueChange={(value) => {
            setStatus(value)
            setPage(1)
          }}
        >
          <SelectTrigger className="w-full sm:w-56" aria-label="Filtrar por status">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>Todos os status</SelectItem>
            {(Object.keys(DATASET_STATUS_LABEL) as DatasetStatus[]).map((key) => (
              <SelectItem key={key} value={key}>
                {DATASET_STATUS_LABEL[key]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {datasets.isPending ? (
        <TableSkeleton />
      ) : datasets.isError ? (
        <ErrorState error={datasets.error} onRetry={() => datasets.refetch()} />
      ) : data && data.total === 0 ? (
        <EmptyState
          icon={Database}
          title={filtering ? 'Nenhum dataset encontrado' : 'Nenhum dataset importado'}
          description={
            filtering
              ? 'Ajuste a busca ou o filtro de status.'
              : 'Importe um arquivo CSV para começar.'
          }
          action={
            !filtering &&
            canUpload && (
              <Button asChild>
                <Link to="/importar">
                  <Upload /> Importar dados
                </Link>
              </Button>
            )
          }
        />
      ) : (
        <div className="space-y-4">
          <DataTable
            columns={columns}
            data={data?.items ?? []}
            getRowId={(row) => row.id}
            caption="Lista de datasets"
          />
          <Pagination
            page={page}
            pageSize={pageSize}
            total={data?.total ?? 0}
            onPageChange={setPage}
            onPageSizeChange={(size) => {
              setPageSize(size)
              setPage(1)
            }}
          />
        </div>
      )}
    </>
  )
}
