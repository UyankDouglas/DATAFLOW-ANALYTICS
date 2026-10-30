import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
  type SortingState,
} from '@tanstack/react-table'
import { ArrowDown, ArrowUp, ArrowUpDown } from 'lucide-react'

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { cn } from '@/lib/utils'

interface DataTableProps<T> {
  columns: ColumnDef<T, unknown>[]
  data: T[]
  /** Ordenação controlada pelo servidor (manualSorting). */
  sorting?: SortingState
  onSortingChange?: (sorting: SortingState) => void
  getRowId?: (row: T, index: number) => string
  caption?: string
  className?: string
  dense?: boolean
}

/** Tabela baseada em TanStack Table; paginação e ordenação acontecem no servidor. */
export function DataTable<T>({
  columns,
  data,
  sorting,
  onSortingChange,
  getRowId,
  caption,
  className,
  dense,
}: DataTableProps<T>) {
  // O projeto não usa o React Compiler; a regra apenas avisa que a tabela não será memoizada.
  // eslint-disable-next-line react-hooks/incompatible-library
  const table = useReactTable({
    data,
    columns,
    getCoreRowModel: getCoreRowModel(),
    manualSorting: true,
    manualPagination: true,
    enableSortingRemoval: true,
    state: { sorting: sorting ?? [] },
    onSortingChange: (updater) => {
      if (!onSortingChange) return
      onSortingChange(typeof updater === 'function' ? updater(sorting ?? []) : updater)
    },
    getRowId,
  })

  return (
    <div className={cn('overflow-x-auto rounded-xl border', className)}>
      <Table>
        {caption && <caption className="sr-only">{caption}</caption>}
        <TableHeader className="bg-muted/40">
          {table.getHeaderGroups().map((group) => (
            <TableRow key={group.id} className="hover:bg-transparent">
              {group.headers.map((header) => {
                const sortable = header.column.getCanSort() && Boolean(onSortingChange)
                const direction = header.column.getIsSorted()
                return (
                  <TableHead
                    key={header.id}
                    className="h-10 text-xs font-semibold tracking-wide whitespace-nowrap text-muted-foreground uppercase"
                    aria-sort={
                      direction === 'asc'
                        ? 'ascending'
                        : direction === 'desc'
                          ? 'descending'
                          : undefined
                    }
                  >
                    {header.isPlaceholder ? null : sortable ? (
                      <button
                        type="button"
                        onClick={header.column.getToggleSortingHandler()}
                        className="inline-flex items-center gap-1 rounded outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
                      >
                        {flexRender(header.column.columnDef.header, header.getContext())}
                        {direction === 'asc' ? (
                          <ArrowUp className="size-3.5" />
                        ) : direction === 'desc' ? (
                          <ArrowDown className="size-3.5" />
                        ) : (
                          <ArrowUpDown className="size-3.5 opacity-40" />
                        )}
                      </button>
                    ) : (
                      flexRender(header.column.columnDef.header, header.getContext())
                    )}
                  </TableHead>
                )
              })}
            </TableRow>
          ))}
        </TableHeader>
        <TableBody>
          {table.getRowModel().rows.map((row) => (
            <TableRow key={row.id}>
              {row.getVisibleCells().map((cell) => (
                <TableCell key={cell.id} className={cn('align-middle', dense && 'py-1.5')}>
                  {flexRender(cell.column.columnDef.cell, cell.getContext())}
                </TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}
