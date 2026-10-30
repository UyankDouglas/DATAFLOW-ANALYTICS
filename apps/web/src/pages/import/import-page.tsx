import { useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertCircle, ArrowRight, CheckCircle2, FileText, Loader2, X } from 'lucide-react'
import { useRef, useState } from 'react'
import { Link, Navigate } from 'react-router'
import { toast } from 'sonner'

import { PageHeader } from '@/components/page-header'
import { StatusBadge } from '@/components/status-badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Progress } from '@/components/ui/progress'
import { usePermission } from '@/features/auth/use-auth'
import { datasetsApi } from '@/features/datasets/api'
import { UploadDropzone } from '@/features/datasets/upload-dropzone'
import type { RejectedFile } from '@/features/datasets/upload-validation'
import { DATASET_STATUS_LABEL, DATASET_STATUS_TONE } from '@/features/jobs/status'
import { formatBytes, formatRelative, formatTimestamp } from '@/lib/format'
import { describeError } from '@/services/api-client'
import { uploadDataset } from '@/services/upload'

type UploadState = 'uploading' | 'stored' | 'error'

interface QueueItem {
  key: string
  name: string
  size: number
  type: string
  startedAt: string
  state: UploadState
  loaded: number
  error?: string
  datasetId?: string
}

export function ImportPage() {
  const canUpload = usePermission('datasets:upload')
  const queryClient = useQueryClient()
  const [queue, setQueue] = useState<QueueItem[]>([])
  const aborters = useRef(new Map<string, () => void>())

  const pending = useQuery({
    queryKey: ['datasets', { page: 1, pageSize: 10, status: 'draft' }],
    queryFn: () => datasetsApi.list({ page: 1, pageSize: 10, status: 'draft' }),
  })

  if (!canUpload) return <Navigate to="/datasets" replace />

  const update = (key: string, patch: Partial<QueueItem>) =>
    setQueue((items) => items.map((item) => (item.key === key ? { ...item, ...patch } : item)))

  const start = (files: File[]) => {
    for (const file of files) {
      const key = `${file.name}-${file.size}-${crypto.randomUUID()}`
      setQueue((items) => [
        {
          key,
          name: file.name,
          size: file.size,
          type: 'CSV',
          startedAt: new Date().toISOString(),
          state: 'uploading',
          loaded: 0,
        },
        ...items,
      ])
      const handle = uploadDataset(file, (loaded) => update(key, { loaded }))
      aborters.current.set(key, handle.abort)
      handle.promise
        .then((result) => {
          update(key, { state: 'stored', loaded: file.size, datasetId: result.dataset.id })
          toast.success(`"${file.name}" armazenado com segurança.`)
          void queryClient.invalidateQueries({ queryKey: ['datasets'] })
          void queryClient.invalidateQueries({ queryKey: ['overview'] })
        })
        .catch((error: unknown) => update(key, { state: 'error', error: describeError(error) }))
        .finally(() => aborters.current.delete(key))
    }
  }

  const reject = (rejected: RejectedFile[]) => {
    setQueue((items) => [
      ...rejected.map(({ file, reason }) => ({
        key: `${file.name}-${crypto.randomUUID()}`,
        name: file.name,
        size: file.size,
        type: file.name.split('.').pop()?.toUpperCase() ?? '—',
        startedAt: new Date().toISOString(),
        state: 'error' as const,
        loaded: 0,
        error: reason,
      })),
      ...items,
    ])
  }

  return (
    <>
      <PageHeader
        title="Importar dados"
        description="Envie arquivos CSV. Depois do envio, você confere a pré-visualização, ajusta tipos e inicia o processamento."
        breadcrumbs={[{ label: 'Datasets', to: '/datasets' }, { label: 'Importar' }]}
      />
      <div className="grid gap-6 xl:grid-cols-5">
        <div className="space-y-6 xl:col-span-3">
          <UploadDropzone onFiles={start} onReject={reject} />
          {queue.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle>Arquivos enviados nesta sessão</CardTitle>
                <CardDescription>
                  O progresso reflete os bytes realmente transmitidos ao servidor.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <ul className="divide-y" aria-live="polite">
                  {queue.map((item) => (
                    <li
                      key={item.key}
                      className="flex flex-col gap-2 py-3 first:pt-0 last:pb-0 sm:flex-row sm:items-center"
                    >
                      <div className="flex min-w-0 flex-1 items-start gap-3">
                        <FileText
                          className="mt-0.5 size-5 shrink-0 text-muted-foreground"
                          aria-hidden
                        />
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-sm font-medium">{item.name}</p>
                          <p className="tabular text-xs text-muted-foreground">
                            {item.type} · {formatBytes(item.size)} · enviado{' '}
                            {formatTimestamp(item.startedAt)}
                          </p>
                          {item.state === 'uploading' && (
                            <div className="mt-2 flex items-center gap-2">
                              <Progress
                                value={item.size ? (item.loaded / item.size) * 100 : 0}
                                className="h-1.5"
                                aria-label={`Envio de ${item.name}`}
                              />
                              <span className="tabular w-10 text-right text-xs text-muted-foreground">
                                {item.size ? Math.floor((item.loaded / item.size) * 100) : 0}%
                              </span>
                            </div>
                          )}
                          {item.state === 'error' && (
                            <p
                              className="mt-1 flex items-start gap-1 text-xs text-destructive"
                              role="alert"
                            >
                              <AlertCircle className="mt-px size-3.5 shrink-0" /> {item.error}
                            </p>
                          )}
                        </div>
                      </div>
                      <div className="flex items-center gap-2 sm:justify-end">
                        {item.state === 'uploading' && (
                          <>
                            <StatusBadge tone="primary" pulse>
                              Enviando
                            </StatusBadge>
                            <Button
                              variant="ghost"
                              size="icon"
                              className="size-8"
                              onClick={() => aborters.current.get(item.key)?.()}
                              aria-label={`Cancelar envio de ${item.name}`}
                            >
                              <X />
                            </Button>
                          </>
                        )}
                        {item.state === 'error' && <StatusBadge tone="danger">Erro</StatusBadge>}
                        {item.state === 'stored' && item.datasetId && (
                          <Button asChild size="sm">
                            <Link to={`/datasets/${item.datasetId}/preview`}>
                              <CheckCircle2 /> Configurar e processar
                            </Link>
                          </Button>
                        )}
                      </div>
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          )}
        </div>
        <Card className="xl:col-span-2">
          <CardHeader>
            <CardTitle>Aguardando configuração</CardTitle>
            <CardDescription>Arquivos armazenados que ainda não foram processados.</CardDescription>
          </CardHeader>
          <CardContent>
            {pending.isPending ? (
              <Loader2 className="mx-auto size-5 animate-spin text-muted-foreground" />
            ) : pending.data && pending.data.items.length > 0 ? (
              <ul className="divide-y">
                {pending.data.items.map((dataset) => (
                  <li
                    key={dataset.id}
                    className="flex items-center justify-between gap-3 py-3 first:pt-0 last:pb-0"
                  >
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium">{dataset.name}</p>
                      <p className="text-xs text-muted-foreground">
                        {formatBytes(dataset.latest_upload?.size_bytes)} ·{' '}
                        {formatRelative(dataset.created_at)}
                      </p>
                    </div>
                    <div className="flex items-center gap-2">
                      <StatusBadge tone={DATASET_STATUS_TONE[dataset.status]}>
                        {DATASET_STATUS_LABEL[dataset.status]}
                      </StatusBadge>
                      <Button
                        asChild
                        variant="ghost"
                        size="icon"
                        className="size-8"
                        aria-label={`Configurar ${dataset.name}`}
                      >
                        <Link to={`/datasets/${dataset.id}/preview`}>
                          <ArrowRight />
                        </Link>
                      </Button>
                    </div>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="py-6 text-center text-sm text-muted-foreground">
                Nenhum arquivo aguardando.
              </p>
            )}
          </CardContent>
        </Card>
      </div>
    </>
  )
}
