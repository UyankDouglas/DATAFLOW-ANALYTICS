import { keepPreviousData, useQuery } from '@tanstack/react-query'
import type { ColumnDef } from '@tanstack/react-table'
import { History } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link } from 'react-router'

import { DataTable } from '@/components/data-table'
import { PageHeader } from '@/components/page-header'
import { Pagination } from '@/components/pagination'
import { EmptyState, ErrorState, TableSkeleton } from '@/components/states'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { jobsApi } from '@/features/jobs/api'
import { JobProgress, JobStatusBadge } from '@/features/jobs/job-components'
import { JOB_STATUS_LABEL, isActive } from '@/features/jobs/status'
import { formatDuration, formatInteger, formatTimestamp } from '@/lib/format'
import type { Job, JobStatus } from '@/types/api'

const ALL = 'all'

export function JobsPage() {
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [status, setStatus] = useState(ALL)

  const jobs = useQuery({
    queryKey: ['jobs', { page, pageSize, status }],
    queryFn: () => jobsApi.list({ page, pageSize, status: status === ALL ? undefined : status }),
    placeholderData: keepPreviousData,
    refetchInterval: (query) =>
      query.state.data?.items.some((job) => isActive(job.status)) ? 2000 : false,
  })

  const columns = useMemo<ColumnDef<Job, unknown>[]>(
    () => [
      {
        header: 'Dataset',
        id: 'dataset',
        cell: ({ row }) => (
          <div className="min-w-44">
            <Link
              to={`/processamentos/${row.original.id}`}
              className="font-medium hover:text-primary"
            >
              {row.original.dataset_name}
            </Link>
            <p className="truncate text-xs text-muted-foreground">{row.original.upload_filename}</p>
          </div>
        ),
      },
      {
        header: 'Status',
        id: 'status',
        cell: ({ row }) => (
          <div className="space-y-1.5">
            <JobStatusBadge
              status={row.original.status}
              cancelRequested={row.original.cancel_requested}
            />
            {isActive(row.original.status) && <JobProgress job={row.original} compact />}
          </div>
        ),
      },
      {
        header: 'Válidos / rejeitados',
        id: 'rows',
        cell: ({ row }) =>
          row.original.rows_valid !== null ? (
            <span className="tabular whitespace-nowrap">
              <span className="text-success">{formatInteger(row.original.rows_valid)}</span>
              {' / '}
              <span
                className={row.original.rows_rejected ? 'text-warning' : 'text-muted-foreground'}
              >
                {formatInteger(row.original.rows_rejected)}
              </span>
            </span>
          ) : (
            <span className="text-muted-foreground">—</span>
          ),
      },
      {
        header: 'Versão',
        id: 'version',
        cell: ({ row }) =>
          row.original.result_version_number ? (
            `v${row.original.result_version_number}`
          ) : (
            <span className="text-muted-foreground">—</span>
          ),
      },
      {
        header: 'Iniciado por',
        id: 'user',
        cell: ({ row }) => row.original.created_by_name ?? '—',
      },
      {
        header: 'Criado em',
        id: 'created',
        cell: ({ row }) => (
          <span className="tabular whitespace-nowrap">
            {formatTimestamp(row.original.created_at)}
          </span>
        ),
      },
      {
        header: 'Duração',
        id: 'duration',
        cell: ({ row }) => {
          const { started_at: start, finished_at: end } = row.original
          return (
            <span className="tabular">
              {start && end
                ? formatDuration(new Date(end).getTime() - new Date(start).getTime())
                : '—'}
            </span>
          )
        },
      },
    ],
    [],
  )

  return (
    <>
      <PageHeader
        title="Histórico de processamento"
        description="Cada execução registra configuração, versão das regras, contagens, erros e métricas."
      />
      <div className="mb-4 flex justify-end">
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
            <SelectItem value="active">Em andamento</SelectItem>
            {(Object.keys(JOB_STATUS_LABEL) as JobStatus[]).map((key) => (
              <SelectItem key={key} value={key}>
                {JOB_STATUS_LABEL[key]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      {jobs.isPending ? (
        <TableSkeleton />
      ) : jobs.isError ? (
        <ErrorState error={jobs.error} onRetry={() => jobs.refetch()} />
      ) : jobs.data.total === 0 ? (
        <EmptyState
          icon={History}
          title="Nenhum processamento encontrado"
          description="Inicie um processamento a partir da pré-visualização de um dataset."
        />
      ) : (
        <div className="space-y-4">
          <DataTable
            columns={columns}
            data={jobs.data.items}
            getRowId={(job) => job.id}
            caption="Histórico de processamentos"
          />
          <Pagination
            page={page}
            pageSize={pageSize}
            total={jobs.data.total}
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
