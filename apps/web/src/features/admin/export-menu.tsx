import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Download, FileSpreadsheet, FileText } from 'lucide-react'
import { useNavigate } from 'react-router'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { usePermission } from '@/features/auth/use-auth'
import { formatInteger } from '@/lib/format'
import { describeError } from '@/services/api-client'
import type { CsvStyle, ExportFormat, ExportRequest } from '@/types/api'

import { exportsApi } from './api'

const OPTIONS: { format: ExportFormat; style?: CsvStyle; label: string; hint: string }[] = [
  {
    format: 'csv',
    style: 'excel_br',
    label: 'CSV para Excel em português',
    hint: 'ponto e vírgula, vírgula decimal, datas dd/mm/aaaa',
  },
  {
    format: 'csv',
    style: 'padrao',
    label: 'CSV padrão',
    hint: 'vírgula, ponto decimal, datas ISO',
  },
  { format: 'xlsx', label: 'Planilha XLSX', hint: 'números e datas tipados' },
]

/**
 * Pede uma exportação em segundo plano. O arquivo não volta nesta requisição: fica pronto na
 * tela Exportações, com validade, e só é baixado pela API.
 */
export function ExportMenu({
  label = 'Exportar',
  request,
  disabled,
}: {
  label?: string
  request: (format: ExportFormat, style?: CsvStyle) => ExportRequest
  disabled?: boolean
}) {
  const canExport = usePermission('data:export')
  const navigate = useNavigate()
  const client = useQueryClient()
  const mutation = useMutation({
    mutationFn: ({ format, style }: { format: ExportFormat; style?: CsvStyle }) =>
      exportsApi.request(request(format, style)),
    onSuccess: (job) => {
      client.invalidateQueries({ queryKey: ['exports'] })
      toast.success(
        job.estimated_rows !== null
          ? `Exportação de ${formatInteger(job.estimated_rows)} registros na fila.`
          : 'Exportação do relatório na fila.',
        {
          description: 'Ela fica pronta na tela Exportações.',
          action: { label: 'Ver exportações', onClick: () => navigate('/exportacoes') },
        },
      )
    },
    onError: (error) => toast.error(describeError(error)),
  })
  if (!canExport) return null
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" disabled={disabled || mutation.isPending}>
          <Download /> {mutation.isPending ? 'Enviando…' : label}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-72">
        <DropdownMenuLabel>Gerado em segundo plano</DropdownMenuLabel>
        <DropdownMenuSeparator />
        {OPTIONS.map((option) => {
          const Icon = option.format === 'xlsx' ? FileSpreadsheet : FileText
          return (
            <DropdownMenuItem
              key={option.label}
              onSelect={() => mutation.mutate({ format: option.format, style: option.style })}
            >
              <Icon />
              <span className="flex flex-col">
                <span>{option.label}</span>
                <span className="text-xs text-muted-foreground">{option.hint}</span>
              </span>
            </DropdownMenuItem>
          )
        })}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
