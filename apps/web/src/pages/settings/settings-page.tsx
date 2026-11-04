import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Save } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { PageHeader } from '@/components/page-header'
import { ErrorState } from '@/components/states'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Progress } from '@/components/ui/progress'
import { Skeleton } from '@/components/ui/skeleton'
import { workspaceApi } from '@/features/admin/api'
import { ME_KEY, usePermission } from '@/features/auth/use-auth'
import { formatBytes, formatPercent } from '@/lib/format'
import { describeError } from '@/services/api-client'
import type { WorkspaceSettingsInfo } from '@/types/api'

export function SettingsPage() {
  const settings = useQuery({ queryKey: ['workspace', 'settings'], queryFn: workspaceApi.settings })
  return (
    <>
      <PageHeader
        title="Configurações"
        description="Nome do workspace, validade das exportações, quem pode exportar e por quanto tempo os arquivos originais ficam guardados."
      />
      {settings.isPending ? (
        <Skeleton className="h-64 w-full" />
      ) : settings.isError ? (
        <ErrorState error={settings.error} onRetry={() => settings.refetch()} />
      ) : (
        <SettingsForm key={settings.data.id} initial={settings.data} />
      )}
    </>
  )
}

function StorageUsage({ info }: { info: WorkspaceSettingsInfo }) {
  const quota = info.storage_quota_bytes
  const ratio = quota ? Math.min(info.storage_used_bytes / quota, 1) : null
  return (
    <Card>
      <CardHeader>
        <CardTitle>Armazenamento</CardTitle>
        <CardDescription>
          Arquivos originais, versões publicadas e exportações prontas. Ao atingir a cota, novos
          envios são recusados; exclua datasets ou versões antigos ou ative a retenção.
        </CardDescription>
      </CardHeader>
      <CardContent className="max-w-md space-y-2">
        <p className="text-sm" data-testid="storage-usage">
          <span className="tabular font-medium">{formatBytes(info.storage_used_bytes)}</span>
          {quota ? (
            <span className="text-muted-foreground">
              {' '}
              de {formatBytes(quota)} ({formatPercent(ratio)})
            </span>
          ) : (
            <span className="text-muted-foreground"> usados, sem cota nesta instalação</span>
          )}
        </p>
        {ratio !== null && (
          <Progress value={ratio * 100} aria-label="Uso do armazenamento do workspace" />
        )}
      </CardContent>
    </Card>
  )
}

function SettingsForm({ initial }: { initial: WorkspaceSettingsInfo }) {
  const canManage = usePermission('workspace:manage')
  const client = useQueryClient()
  const [name, setName] = useState(initial.name)
  const [ttl, setTtl] = useState(String(initial.settings.export_ttl_hours))
  const [viewerExports, setViewerExports] = useState(initial.settings.viewer_exports)
  const [retain, setRetain] = useState(initial.settings.original_retention_days !== null)
  const [days, setDays] = useState(String(initial.settings.original_retention_days ?? 90))
  const save = useMutation({
    mutationFn: () =>
      workspaceApi.update({
        name: name.trim(),
        settings: {
          export_ttl_hours: Number(ttl),
          viewer_exports: viewerExports,
          original_retention_days: retain ? Number(days) : null,
        },
      }),
    onSuccess: (saved) => {
      toast.success('Configurações salvas.')
      client.setQueryData(['workspace', 'settings'], saved)
      // O nome aparece na barra superior e a liberação muda as permissões dos visualizadores.
      client.invalidateQueries({ queryKey: ME_KEY })
      client.invalidateQueries({ queryKey: ['workspaces'] })
    },
    onError: (error) => toast.error(describeError(error)),
  })
  const ttlValid = Number.isInteger(Number(ttl)) && Number(ttl) >= 1 && Number(ttl) <= 168
  const daysValid =
    !retain || (Number.isInteger(Number(days)) && Number(days) >= 7 && Number(days) <= 3650)
  const valid = name.trim().length >= 2 && ttlValid && daysValid

  return (
    <form
      className="space-y-6"
      onSubmit={(event) => {
        event.preventDefault()
        if (valid) save.mutate()
      }}
    >
      <StorageUsage info={initial} />
      {!canManage && (
        <Alert>
          <AlertDescription>
            Somente administradores alteram as configurações. Você pode consultá-las.
          </AlertDescription>
        </Alert>
      )}
      <fieldset disabled={!canManage} className="space-y-6">
        <Card>
          <CardHeader>
            <CardTitle>Workspace</CardTitle>
          </CardHeader>
          <CardContent className="max-w-md space-y-1.5">
            <Label htmlFor="config-nome">Nome</Label>
            <Input
              id="config-nome"
              value={name}
              maxLength={120}
              onChange={(e) => setName(e.target.value)}
            />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Exportações</CardTitle>
            <CardDescription>
              Os arquivos ficam no armazenamento privado e são apagados quando vencem; o histórico
              continua na tela Exportações e na auditoria.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="max-w-xs space-y-1.5">
              <Label htmlFor="config-validade">Validade dos arquivos (horas)</Label>
              <Input
                id="config-validade"
                type="number"
                min={1}
                max={168}
                value={ttl}
                aria-invalid={!ttlValid}
                onChange={(e) => setTtl(e.target.value)}
              />
              <p className="text-xs text-muted-foreground">De 1 a 168 horas (7 dias).</p>
            </div>
            <label className="flex items-start gap-2 text-sm">
              <Checkbox
                checked={viewerExports}
                onCheckedChange={(checked) => setViewerExports(checked === true)}
                className="mt-0.5"
              />
              <span>
                Visualizadores podem exportar dados
                <span className="block text-xs text-muted-foreground">
                  Desligado, só Analistas e Administradores exportam.
                </span>
              </span>
            </label>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Retenção dos arquivos originais</CardTitle>
            <CardDescription>
              Apaga os arquivos enviados depois de um prazo. As versões publicadas continuam
              consultáveis, transformáveis e exportáveis; só deixa de ser possível reprocessar o
              arquivo do zero. Datasets sem versão publicada e processamentos em andamento nunca
              perdem o original.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <label className="flex items-center gap-2 text-sm">
              <Checkbox
                checked={retain}
                onCheckedChange={(checked) => setRetain(checked === true)}
              />
              Apagar originais antigos
            </label>
            {retain && (
              <div className="max-w-xs space-y-1.5">
                <Label htmlFor="config-retencao">Prazo (dias)</Label>
                <Input
                  id="config-retencao"
                  type="number"
                  min={7}
                  max={3650}
                  value={days}
                  aria-invalid={!daysValid}
                  onChange={(e) => setDays(e.target.value)}
                />
                <p className="text-xs text-muted-foreground">
                  De 7 a 3.650 dias. A limpeza roda a cada 6 horas.
                </p>
              </div>
            )}
          </CardContent>
        </Card>
      </fieldset>
      {canManage && (
        <Button type="submit" disabled={!valid || save.isPending}>
          <Save /> {save.isPending ? 'Salvando…' : 'Salvar configurações'}
        </Button>
      )}
    </form>
  )
}
