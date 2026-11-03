import { useMutation } from '@tanstack/react-query'
import { CheckCircle2, Copy, Loader2, Plus } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
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
import { formatInteger } from '@/lib/format'
import { describeError } from '@/services/api-client'
import type { ColumnSpec, DatasetVersion, DuplicateAnalysis } from '@/types/api'

import { transformationsApi } from './api'
import { ColumnPicker } from './rule-editor'

/** Duplicidades na versão inteira, pela chave escolhida, sem alterar dados (DuckDB no servidor). */
export function DuplicatesPanel({
  datasetId,
  version,
  schema,
}: {
  datasetId: string
  version: DatasetVersion
  schema: ColumnSpec[]
}) {
  const [columns, setColumns] = useState<string[]>([])
  const [keep, setKeep] = useState<'first' | 'last'>('first')
  const analysis = useMutation({
    mutationFn: () => transformationsApi.duplicates(datasetId, version.id, { columns, keep }),
    onError: (error) => toast.error(describeError(error)),
  })
  const result: DuplicateAnalysis | undefined = analysis.data
  return (
    <Card aria-label="Duplicidades na versão inteira" role="region">
      <CardHeader>
        <CardTitle>Duplicidades na versão inteira</CardTitle>
        <CardDescription>
          Conta registros repetidos em todos os {formatInteger(version.row_count)} registros da v
          {version.version_number}, sem alterar nada. Valores nulos contam como iguais entre si.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <ColumnPicker
          label="Chave (nenhuma marcada = todas as colunas)"
          columns={schema}
          value={columns}
          onChange={setColumns}
        />
        <div className="flex flex-wrap items-end gap-3">
          <div className="space-y-1.5">
            <Label className="text-xs">Manter</Label>
            <Select value={keep} onValueChange={(value) => setKeep(value as 'first' | 'last')}>
              <SelectTrigger size="sm" className="w-44" aria-label="Registro mantido">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="first">O primeiro registro</SelectItem>
                <SelectItem value="last">O último registro</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <Button variant="outline" onClick={() => analysis.mutate()} disabled={analysis.isPending}>
            {analysis.isPending ? <Loader2 className="animate-spin" /> : <Copy />}
            Analisar duplicidades
          </Button>
        </div>
        {result && (
          <div className="space-y-3">
            <dl className="grid grid-cols-2 gap-2 text-sm">
              <div className="rounded-lg border p-2.5">
                <dt className="text-xs text-muted-foreground">Registros duplicados</dt>
                <dd className="tabular text-lg font-semibold">
                  {formatInteger(result.duplicate_rows)}
                </dd>
              </div>
              <div className="rounded-lg border p-2.5">
                <dt className="text-xs text-muted-foreground">Restariam após remover</dt>
                <dd className="tabular text-lg font-semibold">
                  {formatInteger(result.rows_after)}
                </dd>
              </div>
              <div className="rounded-lg border p-2.5">
                <dt className="text-xs text-muted-foreground">Chaves distintas</dt>
                <dd className="tabular font-semibold">{formatInteger(result.distinct_keys)}</dd>
              </div>
              <div className="rounded-lg border p-2.5">
                <dt className="text-xs text-muted-foreground">Chaves repetidas</dt>
                <dd className="tabular font-semibold">
                  {formatInteger(result.groups_with_duplicates)}
                </dd>
              </div>
            </dl>
            {result.top_groups.length > 0 ? (
              <div className="overflow-x-auto rounded-xl border">
                <Table>
                  <TableHeader className="bg-muted/40">
                    <TableRow className="hover:bg-transparent">
                      <TableHead className="text-xs">Chave ({result.columns.join(', ')})</TableHead>
                      <TableHead className="text-xs">Ocorrências</TableHead>
                      <TableHead className="text-xs">Mantido</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {result.top_groups.map((group) => (
                      <TableRow key={group.sample_rows.join('-')}>
                        <TableCell className="max-w-56 truncate font-mono text-xs">
                          {group.key
                            .map((value) => (value === null ? 'nulo' : String(value)))
                            .join(' · ')}
                        </TableCell>
                        <TableCell className="tabular text-xs">
                          {formatInteger(group.count)}
                        </TableCell>
                        <TableCell className="tabular text-xs">#{group.kept_row}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            ) : (
              <p className="flex items-center gap-1.5 text-sm text-success">
                <CheckCircle2 className="size-4" /> Nenhuma duplicidade por essa chave.
              </p>
            )}
            <p className="text-xs text-muted-foreground">
              Para remover, adicione a regra “Remover duplicidades” com a mesma chave
              <Plus className="mx-1 inline size-3" aria-hidden />e aplique o conjunto.
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
