import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { formatBytes, formatInteger } from '@/lib/format'
import { describeError } from '@/services/api-client'

import { deletionApi } from './api'

function Count({ value, label }: { value: number; label: string }) {
  return (
    <li className="flex justify-between gap-4">
      <span className="text-muted-foreground">{label}</span>
      <span className="tabular font-medium">{formatInteger(value)}</span>
    </li>
  )
}

export function DeleteDatasetDialog({
  datasetId,
  onClose,
  onDeleted,
}: {
  datasetId: string
  onClose: () => void
  onDeleted: () => void
}) {
  const client = useQueryClient()
  const [typed, setTyped] = useState('')
  const impact = useQuery({
    queryKey: ['datasets', datasetId, 'deletion-impact'],
    queryFn: () => deletionApi.datasetImpact(datasetId),
  })
  const remove = useMutation({
    mutationFn: () => deletionApi.deleteDataset(datasetId, typed),
    onSuccess: () => {
      toast.success('Dataset excluído, com versões, arquivos, dashboards e exportações.')
      client.invalidateQueries({ queryKey: ['datasets'] })
      client.invalidateQueries({ queryKey: ['dashboards'] })
      client.invalidateQueries({ queryKey: ['exports'] })
      onDeleted()
    },
  })
  const data = impact.data
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Excluir o dataset{data ? ` “${data.dataset_name}”` : ''}?</DialogTitle>
          <DialogDescription>
            Apaga de vez as versões, os arquivos no armazenamento, os processamentos, os conjuntos
            de regras, os dashboards e as exportações deste dataset. A ação fica na auditoria e não
            pode ser desfeita.
          </DialogDescription>
        </DialogHeader>
        {impact.isPending ? (
          <Skeleton className="h-32 w-full" />
        ) : impact.isError ? (
          <Alert variant="destructive">
            <AlertDescription>{describeError(impact.error)}</AlertDescription>
          </Alert>
        ) : data ? (
          <div className="space-y-4">
            <ul className="space-y-1 rounded-lg border p-3 text-sm" aria-label="O que será apagado">
              <Count value={data.versions} label="Versões" />
              <Count value={data.uploads} label="Arquivos enviados" />
              <Count value={data.jobs} label="Processamentos" />
              <Count value={data.exports} label="Exportações" />
              <Count value={data.dashboards.length} label="Dashboards" />
              <li className="flex justify-between gap-4">
                <span className="text-muted-foreground">Espaço liberado</span>
                <span className="tabular font-medium">{formatBytes(data.stored_bytes)}</span>
              </li>
            </ul>
            {data.dashboards.length > 0 && (
              <p className="text-xs text-muted-foreground">
                Dashboards apagados junto: {data.dashboards.map((d) => d.name).join(', ')}.
              </p>
            )}
            {data.blocked_reason ? (
              <Alert variant="destructive">
                <AlertTriangle />
                <AlertDescription>{data.blocked_reason}</AlertDescription>
              </Alert>
            ) : (
              <div className="space-y-1.5">
                <Label htmlFor="confirmar-nome">
                  Digite <strong>{data.dataset_name}</strong> para confirmar
                </Label>
                <Input
                  id="confirmar-nome"
                  value={typed}
                  autoComplete="off"
                  onChange={(e) => setTyped(e.target.value)}
                />
              </div>
            )}
            {remove.isError && (
              <Alert variant="destructive">
                <AlertDescription>{describeError(remove.error)}</AlertDescription>
              </Alert>
            )}
          </div>
        ) : null}
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancelar
          </Button>
          <Button
            variant="destructive"
            disabled={
              !data ||
              Boolean(data.blocked_reason) ||
              typed.trim() !== data.dataset_name ||
              remove.isPending
            }
            onClick={() => remove.mutate()}
          >
            Excluir definitivamente
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export function DeleteVersionDialog({
  datasetId,
  versionId,
  onClose,
}: {
  datasetId: string
  versionId: string
  onClose: () => void
}) {
  const client = useQueryClient()
  const impact = useQuery({
    queryKey: ['datasets', datasetId, 'versions', versionId, 'deletion-impact'],
    queryFn: () => deletionApi.versionImpact(datasetId, versionId),
  })
  const remove = useMutation({
    mutationFn: () => deletionApi.deleteVersion(datasetId, versionId),
    onSuccess: () => {
      toast.success('Versão excluída.')
      client.invalidateQueries({ queryKey: ['datasets'] })
      client.invalidateQueries({ queryKey: ['exports'] })
      onClose()
    },
  })
  const data = impact.data
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Excluir a versão{data ? ` ${data.version_number}` : ''}?</DialogTitle>
          <DialogDescription>
            Apaga o Parquet da versão, o relatório de qualidade e as exportações feitas a partir
            dela. O histórico de processamentos continua, e a ação fica na auditoria.
          </DialogDescription>
        </DialogHeader>
        {impact.isPending ? (
          <Skeleton className="h-24 w-full" />
        ) : impact.isError ? (
          <Alert variant="destructive">
            <AlertDescription>{describeError(impact.error)}</AlertDescription>
          </Alert>
        ) : data ? (
          <div className="space-y-3 text-sm">
            <ul className="space-y-1 rounded-lg border p-3">
              <Count value={data.exports} label="Exportações apagadas" />
              <Count value={data.derived_versions} label="Versões derivadas (perdem a origem)" />
              <li className="flex justify-between gap-4">
                <span className="text-muted-foreground">Espaço liberado</span>
                <span className="tabular font-medium">{formatBytes(data.stored_bytes)}</span>
              </li>
            </ul>
            {data.is_current && data.next_current_number && !data.blocked_reason && (
              <p>
                É a versão atual: a versão <strong>{data.next_current_number}</strong> passa a ser a
                atual, e os dashboards que acompanham a atual mudam junto.
              </p>
            )}
            {data.blocked_reason && (
              <Alert variant="destructive">
                <AlertTriangle />
                <AlertDescription>{data.blocked_reason}</AlertDescription>
              </Alert>
            )}
            {remove.isError && (
              <Alert variant="destructive">
                <AlertDescription>{describeError(remove.error)}</AlertDescription>
              </Alert>
            )}
          </div>
        ) : null}
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancelar
          </Button>
          <Button
            variant="destructive"
            disabled={!data || Boolean(data.blocked_reason) || remove.isPending}
            onClick={() => remove.mutate()}
          >
            Excluir versão
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
