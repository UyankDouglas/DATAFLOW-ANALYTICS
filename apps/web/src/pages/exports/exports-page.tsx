import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Download, FileDown, Info, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'
import { toast } from 'sonner'

import { PageHeader } from '@/components/page-header'
import { Pagination } from '@/components/pagination'
import { EmptyState, ErrorState, TableSkeleton } from '@/components/states'
import { StatusBadge } from '@/components/status-badge'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { exportsApi } from '@/features/admin/api'
import { EXPORT_STATUS, isExportActive } from '@/features/admin/labels'
import { formatBytes, formatInteger, formatRelative, formatTimestamp } from '@/lib/format'
import { describeError } from '@/services/api-client'
import type { ExportJob } from '@/types/api'

function describeQuery(job: ExportJob): string {
  if (job.kind === 'report') {
    const report = job.params.report
    const metrics = report?.metrics.length ?? 0
    return `Relatório · ${metrics} medida${metrics === 1 ? '' : 's'}${
      report?.dimension ? ` por ${report.dimension.column}` : ''
    }`
  }
  const rows = job.params.rows
  const parts = ['Registros']
  if (rows?.filters?.length) parts.push(`${rows.filters.length} filtro(s)`)
  if (rows?.search) parts.push(`busca “${rows.search}”`)
  if (rows?.columns?.length) parts.push(`${rows.columns.length} coluna(s)`)
  return parts.join(' · ')
}

export function ExportsPage() {
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [mine, setMine] = useState(false)
  const client = useQueryClient()
  const exports = useQuery({
    queryKey: ['exports', { page, pageSize, mine }],
    queryFn: () => exportsApi.list(page, pageSize, mine),
    placeholderData: keepPreviousData,
    // Enquanto houver arquivo sendo gerado, a lista se atualiza sozinha.
    refetchInterval: (query) =>
      query.state.data?.items.some((job) => isExportActive(job.status)) ? 2000 : false,
  })
  const remove = useMutation({
    mutationFn: (id: string) => exportsApi.remove(id),
    onSuccess: () => {
      toast.success('Exportação excluída e arquivo apagado.')
      client.invalidateQueries({ queryKey: ['exports'] })
    },
    onError: (error) => toast.error(describeError(error)),
  })

  return (
    <>
      <PageHeader
        title="Exportações"
        description="Arquivos CSV e XLSX gerados em segundo plano. Cada arquivo fica disponível por tempo limitado e só é baixado pela API, por quem tem permissão de exportar."
      />
      <Alert className="mb-4">
        <Info />
        <AlertDescription>
          <p>
            Para exportar, use o botão <strong>Exportar</strong> no Data Explorer (registros
            tratados, com filtros e colunas) ou na tela{' '}
            <Link to="/relatorios" className="underline">
              Relatórios
            </Link>
            . Textos que começam com =, +, - ou @ saem com um apóstrofo na frente, para não virarem
            fórmula na planilha.
          </p>
        </AlertDescription>
      </Alert>
      <label className="mb-4 flex w-fit items-center gap-2 text-sm">
        <Checkbox
          checked={mine}
          onCheckedChange={(checked) => {
            setMine(checked === true)
            setPage(1)
          }}
        />
        Somente as minhas
      </label>

      {exports.isPending ? (
        <TableSkeleton rows={4} columns={6} />
      ) : exports.isError ? (
        <ErrorState error={exports.error} onRetry={() => exports.refetch()} />
      ) : exports.data.items.length === 0 ? (
        <EmptyState
          icon={FileDown}
          title="Nenhuma exportação"
          description="As exportações pedidas no Data Explorer e em Relatórios aparecem aqui, com o status e a validade de cada arquivo."
        />
      ) : (
        <div className="space-y-4">
          <div className="overflow-x-auto rounded-xl border">
            <Table>
              <caption className="sr-only">Histórico de exportações</caption>
              <TableHeader className="bg-muted/40">
                <TableRow className="hover:bg-transparent">
                  <TableHead>Arquivo</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Registros</TableHead>
                  <TableHead className="text-right">Tamanho</TableHead>
                  <TableHead>Pedido</TableHead>
                  <TableHead>Validade</TableHead>
                  <TableHead className="text-right">Ações</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {exports.data.items.map((job) => {
                  const status = EXPORT_STATUS[job.status]
                  const expired =
                    job.status === 'expired' ||
                    (job.expires_at !== null && new Date(job.expires_at) <= new Date())
                  const ready = job.status === 'succeeded' && !expired
                  return (
                    <TableRow key={job.id}>
                      <TableCell className="max-w-72">
                        <p className="truncate font-medium" title={job.file_name}>
                          {job.file_name}
                        </p>
                        <p className="text-xs text-muted-foreground">
                          <Link to={`/datasets/${job.dataset_id}`} className="hover:underline">
                            {job.dataset_name}
                          </Link>{' '}
                          · v{job.version_number} · {job.format.toUpperCase()} ·{' '}
                          {describeQuery(job)}
                        </p>
                      </TableCell>
                      <TableCell>
                        <StatusBadge
                          tone={expired && job.status === 'succeeded' ? 'warning' : status.tone}
                          pulse={isExportActive(job.status)}
                        >
                          {expired && job.status === 'succeeded' ? 'Expirada' : status.label}
                        </StatusBadge>
                        {job.error_message && (
                          <p className="mt-1 max-w-56 text-xs text-destructive">
                            {job.error_message}
                          </p>
                        )}
                      </TableCell>
                      <TableCell className="tabular text-right">
                        {formatInteger(job.row_count ?? job.estimated_rows)}
                      </TableCell>
                      <TableCell className="tabular text-right">
                        {formatBytes(job.size_bytes)}
                      </TableCell>
                      <TableCell className="text-xs whitespace-nowrap">
                        {job.created_by_name ?? '—'}
                        <br />
                        <span className="text-muted-foreground">
                          {formatTimestamp(job.created_at)}
                        </span>
                      </TableCell>
                      <TableCell className="text-xs whitespace-nowrap">
                        {job.status === 'succeeded' && job.expires_at
                          ? expired
                            ? 'Arquivo apagado'
                            : `Expira ${formatRelative(job.expires_at)}`
                          : job.status === 'expired'
                            ? 'Arquivo apagado'
                            : '—'}
                        {job.download_count > 0 && (
                          <span className="block text-muted-foreground">
                            {job.download_count} download{job.download_count === 1 ? '' : 's'}
                          </span>
                        )}
                      </TableCell>
                      <TableCell>
                        <div className="flex justify-end gap-1">
                          {ready && (
                            <Button asChild size="sm" variant="outline">
                              <a href={exportsApi.downloadUrl(job.id)} download={job.file_name}>
                                <Download /> Baixar
                              </a>
                            </Button>
                          )}
                          {!isExportActive(job.status) && (
                            <Button
                              size="icon-sm"
                              variant="ghost"
                              aria-label={`Excluir ${job.file_name}`}
                              disabled={remove.isPending}
                              onClick={() => remove.mutate(job.id)}
                            >
                              <Trash2 />
                            </Button>
                          )}
                        </div>
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          </div>
          <Pagination
            page={page}
            pageSize={pageSize}
            total={exports.data.total}
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
