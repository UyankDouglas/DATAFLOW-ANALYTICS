import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { ScrollText, X } from 'lucide-react'
import { useState } from 'react'

import { PageHeader } from '@/components/page-header'
import { Pagination } from '@/components/pagination'
import { EmptyState, ErrorState, TableSkeleton } from '@/components/states'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { auditApi } from '@/features/admin/api'
import { AUDIT_CATEGORY, auditLabel, describeDetails } from '@/features/admin/labels'
import { formatTimestamp } from '@/lib/format'

const ALL = '__todas__'

export function AuditPage() {
  const [action, setAction] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(50)
  const actions = useQuery({ queryKey: ['audit', 'actions'], queryFn: auditApi.actions })
  const entries = useQuery({
    queryKey: ['audit', { action, dateFrom, dateTo, page, pageSize }],
    queryFn: () =>
      auditApi.search({
        action: action || undefined,
        dateFrom: dateFrom || undefined,
        dateTo: dateTo || undefined,
        page,
        pageSize,
      }),
    placeholderData: keepPreviousData,
  })
  const categories = [...new Set((actions.data ?? []).map((a) => a.split('.')[0] ?? a))]
  const filtered = Boolean(action || dateFrom || dateTo)

  return (
    <>
      <PageHeader
        title="Auditoria"
        description="Ações relevantes do workspace, da mais recente para a mais antiga: acessos, uploads, processamentos, exportações, membros e exclusões. Os registros não guardam conteúdo de arquivos nem senhas."
      />
      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-end">
        <div className="space-y-1.5">
          <Label className="text-xs">Ação</Label>
          <Select
            value={action || ALL}
            onValueChange={(value) => {
              setAction(value === ALL ? '' : value)
              setPage(1)
            }}
          >
            <SelectTrigger size="sm" className="w-full sm:w-64" aria-label="Ação">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>Todas</SelectItem>
              {categories.map((category) => (
                <SelectItem key={category} value={category}>
                  {AUDIT_CATEGORY[category] ?? category} (todas)
                </SelectItem>
              ))}
              {(actions.data ?? []).map((name) => (
                <SelectItem key={name} value={name}>
                  {auditLabel(name)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="grid grid-cols-2 gap-2">
          <div className="space-y-1.5">
            <Label className="text-xs" htmlFor="auditoria-de">
              De
            </Label>
            <Input
              id="auditoria-de"
              type="date"
              value={dateFrom}
              onChange={(e) => {
                setDateFrom(e.target.value)
                setPage(1)
              }}
            />
          </div>
          <div className="space-y-1.5">
            <Label className="text-xs" htmlFor="auditoria-ate">
              Até
            </Label>
            <Input
              id="auditoria-ate"
              type="date"
              value={dateTo}
              onChange={(e) => {
                setDateTo(e.target.value)
                setPage(1)
              }}
            />
          </div>
        </div>
        {filtered && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setAction('')
              setDateFrom('')
              setDateTo('')
              setPage(1)
            }}
          >
            <X /> Limpar
          </Button>
        )}
      </div>

      {entries.isPending ? (
        <TableSkeleton rows={8} columns={5} />
      ) : entries.isError ? (
        <ErrorState error={entries.error} onRetry={() => entries.refetch()} />
      ) : entries.data.items.length === 0 ? (
        <EmptyState
          icon={ScrollText}
          title="Nenhum registro"
          description={filtered ? 'Ajuste os filtros.' : undefined}
        />
      ) : (
        <div className="space-y-4">
          <div className="overflow-x-auto rounded-xl border">
            <Table>
              <caption className="sr-only">Registros de auditoria</caption>
              <TableHeader className="bg-muted/40">
                <TableRow className="hover:bg-transparent">
                  <TableHead>Quando</TableHead>
                  <TableHead>Quem</TableHead>
                  <TableHead>Ação</TableHead>
                  <TableHead>Detalhes</TableHead>
                  <TableHead>IP</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {entries.data.items.map((entry) => (
                  <TableRow key={entry.id}>
                    <TableCell className="tabular text-xs whitespace-nowrap">
                      {formatTimestamp(entry.created_at)}
                    </TableCell>
                    <TableCell className="text-sm whitespace-nowrap">
                      {entry.actor_name ?? <span className="text-muted-foreground">Sistema</span>}
                    </TableCell>
                    <TableCell>
                      <p className="text-sm font-medium">{auditLabel(entry.action)}</p>
                      <p className="font-mono text-xs text-muted-foreground">{entry.action}</p>
                    </TableCell>
                    <TableCell className="max-w-md min-w-64 text-xs [overflow-wrap:anywhere] whitespace-normal text-muted-foreground">
                      {entry.entity_type && (
                        <span className="text-foreground">
                          {entry.entity_type} {entry.entity_id?.slice(0, 8)}
                        </span>
                      )}
                      {entry.entity_type && Object.keys(entry.details).length > 0 && ' · '}
                      {describeDetails(entry.details)}
                    </TableCell>
                    <TableCell className="font-mono text-xs">{entry.ip_address ?? '—'}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          <Pagination
            page={page}
            pageSize={pageSize}
            total={entries.data.total}
            onPageChange={setPage}
            onPageSizeChange={(size) => {
              setPageSize(size)
              setPage(1)
            }}
            pageSizes={[25, 50, 100]}
          />
        </div>
      )}
    </>
  )
}
