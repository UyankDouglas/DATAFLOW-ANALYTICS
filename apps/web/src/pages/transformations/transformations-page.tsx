import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowDown,
  ArrowUp,
  CheckCircle2,
  Copy,
  Database,
  Eye,
  Loader2,
  Play,
  Plus,
  Save,
  Trash2,
  Wand2,
} from 'lucide-react'
import { useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router'
import { toast } from 'sonner'

import { PageHeader } from '@/components/page-header'
import { EmptyState, ErrorState, TableSkeleton } from '@/components/states'
import { StatusBadge } from '@/components/status-badge'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
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
import { usePermission } from '@/features/auth/use-auth'
import { datasetsApi } from '@/features/datasets/api'
import { CellValue } from '@/features/datasets/cell-value'
import { transformationsApi } from '@/features/transformations/api'
import { ColumnPicker, RuleEditor } from '@/features/transformations/rule-editor'
import {
  CATEGORY_LABEL,
  CATEGORY_TONE,
  OPERATION_HINT,
  OPERATION_LABEL,
  REASON_LABEL,
  defaultRule,
  describeRule,
  insertRule,
  moveRule,
  simulateSchema,
} from '@/features/transformations/rules'
import { formatInteger, formatTimestamp } from '@/lib/format'
import { cn } from '@/lib/utils'
import { ApiError, describeError } from '@/services/api-client'
import type {
  ColumnSpec,
  DatasetVersion,
  DuplicateAnalysis,
  Rule,
  RuleOperation,
  TransformationSet,
  TransformPreview,
} from '@/types/api'

const NEW_SET = 'novo'

export function TransformationsPage() {
  const [params, setParams] = useSearchParams()
  const datasetId = params.get('dataset') ?? ''
  const datasets = useQuery({
    queryKey: ['datasets', { page: 1, pageSize: 100, status: 'ready' }],
    queryFn: () => datasetsApi.list({ page: 1, pageSize: 100, status: 'ready' }),
  })

  const selectDataset = (id: string) => setParams(id ? { dataset: id } : {}, { replace: true })

  return (
    <>
      <PageHeader
        title="Transformações"
        description="Regras configuráveis aplicadas a uma versão publicada. Cada aplicação gera uma nova versão imutável, com linhagem e reconciliação."
        breadcrumbs={[{ label: 'Tratamento' }, { label: 'Transformações' }]}
      />
      {datasets.isPending ? (
        <TableSkeleton rows={4} columns={3} />
      ) : datasets.isError ? (
        <ErrorState error={datasets.error} onRetry={() => datasets.refetch()} />
      ) : datasets.data.items.length === 0 ? (
        <EmptyState
          icon={Database}
          title="Nenhum dataset processado"
          description="Transformações partem de uma versão publicada. Importe e processe um arquivo primeiro."
          action={
            <Button asChild>
              <Link to="/importar">Importar dados</Link>
            </Button>
          }
        />
      ) : (
        <>
          <div className="mb-6 max-w-md space-y-1.5">
            <Label>Dataset</Label>
            <Select value={datasetId || undefined} onValueChange={selectDataset}>
              <SelectTrigger className="w-full" aria-label="Dataset">
                <SelectValue placeholder="Escolha um dataset processado" />
              </SelectTrigger>
              <SelectContent>
                {datasets.data.items.map((dataset) => (
                  <SelectItem key={dataset.id} value={dataset.id}>
                    {dataset.name}
                    <span className="text-xs text-muted-foreground">
                      {' '}
                      · v{dataset.current_version_number} · {formatInteger(dataset.row_count)}{' '}
                      registros
                    </span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          {datasetId ? (
            <Workbench key={datasetId} datasetId={datasetId} />
          ) : (
            <EmptyState
              icon={Wand2}
              title="Escolha um dataset"
              description="Monte as regras, confira a prévia e aplique para gerar a próxima versão."
            />
          )}
        </>
      )}
    </>
  )
}

interface Draft {
  name: string
  description: string
  rules: Rule[]
}

const EMPTY_DRAFT: Draft = { name: '', description: '', rules: [] }

function draftFrom(set: TransformationSet): Draft {
  return { name: set.name, description: set.description ?? '', rules: set.rules }
}

function versionLabel(version: DatasetVersion, currentId: string | null): string {
  const origin =
    version.parent_version_number !== null
      ? `de v${version.parent_version_number}`
      : version.transformations.kind === 'transform'
        ? 'transformada'
        : 'importação'
  return `v${version.version_number}${version.id === currentId ? ' (atual)' : ''} · ${origin} · ${formatInteger(version.row_count)} registros`
}

function Workbench({ datasetId }: { datasetId: string }) {
  const canManage = usePermission('transformations:manage')
  const [params, setParams] = useSearchParams()
  const dataset = useQuery({
    queryKey: ['datasets', datasetId],
    queryFn: () => datasetsApi.get(datasetId),
  })
  const versions = useQuery({
    queryKey: ['datasets', datasetId, 'versions'],
    queryFn: () => datasetsApi.versions(datasetId),
  })
  const sets = useQuery({
    queryKey: ['datasets', datasetId, 'transformation-sets'],
    queryFn: () => transformationsApi.listSets(datasetId),
  })

  const [versionId, setVersionId] = useState<string>('')
  const setId = params.get('conjunto') ?? NEW_SET
  const selectedSet = sets.data?.find((set) => set.id === setId) ?? null
  const sourceVersionId = versionId || dataset.data?.current_version_id || ''
  const sourceVersion = versions.data?.find((version) => version.id === sourceVersionId)

  const selectSet = (id: string) => {
    const next = new URLSearchParams(params)
    if (id === NEW_SET) next.delete('conjunto')
    else next.set('conjunto', id)
    setParams(next, { replace: true })
  }

  if (dataset.isPending || versions.isPending || sets.isPending) {
    return <TableSkeleton rows={6} columns={4} />
  }
  const failed = [dataset, versions, sets].find((query) => query.isError)
  if (failed?.isError) return <ErrorState error={failed.error} onRetry={() => failed.refetch()} />

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Origem e conjunto de regras</CardTitle>
          <CardDescription>
            A versão de origem não muda: o resultado vira a próxima versão do dataset.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4 md:grid-cols-2">
          <div className="space-y-1.5">
            <Label>Versão de origem</Label>
            <Select value={sourceVersionId} onValueChange={setVersionId}>
              <SelectTrigger className="w-full" aria-label="Versão de origem">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {versions.data?.map((version) => (
                  <SelectItem key={version.id} value={version.id}>
                    {versionLabel(version, dataset.data?.current_version_id ?? null)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label>Conjunto de regras</Label>
            <Select value={setId} onValueChange={selectSet}>
              <SelectTrigger className="w-full" aria-label="Conjunto de regras">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {canManage && <SelectItem value={NEW_SET}>Novo conjunto</SelectItem>}
                {sets.data?.map((set) => (
                  <SelectItem key={set.id} value={set.id}>
                    {set.name} · revisão {set.revision}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {selectedSet && (
              <p className="text-xs text-muted-foreground">
                Atualizado por {selectedSet.updated_by_name ?? '—'} em{' '}
                {formatTimestamp(selectedSet.updated_at)}
              </p>
            )}
          </div>
        </CardContent>
      </Card>

      {sourceVersion && (
        <SetEditor
          // Outro conjunto ou nova revisão salva: o editor recomeça a partir do que está salvo.
          key={`${setId}:${selectedSet?.revision ?? 0}`}
          datasetId={datasetId}
          sourceVersion={sourceVersion}
          nextVersionNumber={(versions.data?.[0]?.version_number ?? 0) + 1}
          selectedSet={selectedSet}
          onSelectSet={selectSet}
          canManage={canManage}
        />
      )}
    </div>
  )
}

interface SetEditorProps {
  datasetId: string
  sourceVersion: DatasetVersion
  nextVersionNumber: number
  selectedSet: TransformationSet | null
  onSelectSet: (id: string) => void
  canManage: boolean
}

function SetEditor({
  datasetId,
  sourceVersion,
  nextVersionNumber,
  selectedSet,
  onSelectSet,
  canManage,
}: SetEditorProps) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const sourceVersionId = sourceVersion.id
  const [draft, setDraft] = useState<Draft>(() =>
    selectedSet ? draftFrom(selectedSet) : EMPTY_DRAFT,
  )
  const [dirty, setDirty] = useState(false)
  const [ruleError, setRuleError] = useState<{ index: number; message: string } | null>(null)
  // Prévia e as regras exatas que a geraram (para saber se ficou desatualizada).
  const [lastPreview, setPreview] = useState<{ result: TransformPreview; rules: string } | null>(
    null,
  )
  // Prévia de outra versão de origem não vale para a escolhida agora.
  const preview =
    lastPreview?.result.source_version_id === sourceVersionId ? lastPreview.result : null
  const previewStale = preview !== null && lastPreview?.rules !== JSON.stringify(draft.rules)
  const inputSchema: ColumnSpec[] = useMemo(
    () =>
      sourceVersion.column_schema.map((column) => ({
        name: column.name,
        data_type: column.data_type,
        format: column.format,
        scale: column.scale,
      })),
    [sourceVersion],
  )
  const simulation = useMemo(
    () => simulateSchema(draft.rules, inputSchema),
    [draft.rules, inputSchema],
  )

  const edit = (next: Partial<Draft>) => {
    setDraft((current) => ({ ...current, ...next }))
    setDirty(true)
    setRuleError(null)
  }
  const handleRuleError = (error: unknown) => {
    if (error instanceof ApiError && error.code === 'invalid_rule') {
      const details = error.details as { rule_index?: number; message?: string } | null
      if (typeof details?.rule_index === 'number') {
        setRuleError({ index: details.rule_index, message: details.message ?? error.message })
      }
    }
    toast.error(describeError(error))
  }

  const runPreview = useMutation({
    mutationFn: (rules: Rule[]) => transformationsApi.preview(datasetId, sourceVersionId, rules),
    onSuccess: (data, rules) => {
      setPreview({ result: data, rules: JSON.stringify(rules) })
      setRuleError(null)
    },
    onError: handleRuleError,
  })

  const save = useMutation({
    mutationFn: () => {
      const body = {
        name: draft.name.trim(),
        description: draft.description.trim() || null,
        rules: draft.rules,
      }
      return selectedSet
        ? transformationsApi.updateSet(datasetId, selectedSet.id, body)
        : transformationsApi.createSet(datasetId, body)
    },
    onSuccess: (saved) => {
      queryClient.setQueryData<TransformationSet[]>(
        ['datasets', datasetId, 'transformation-sets'],
        (current) => [saved, ...(current ?? []).filter((set) => set.id !== saved.id)],
      )
      setDirty(false)
      toast.success(`Conjunto "${saved.name}" salvo (revisão ${saved.revision}).`)
      onSelectSet(saved.id)
    },
    onError: handleRuleError,
  })

  const remove = useMutation({
    mutationFn: (id: string) => transformationsApi.deleteSet(datasetId, id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['datasets', datasetId] })
      toast.success('Conjunto excluído. Versões geradas por ele continuam com a cópia das regras.')
      onSelectSet(NEW_SET)
    },
    onError: (error) => toast.error(describeError(error)),
  })

  // Uma chave por combinação versão + conjunto + revisão: clique duplo não cria dois jobs.
  const idempotency = useRef({ scope: '', key: '' })
  const apply = useMutation({
    mutationFn: () => {
      const scope = `${sourceVersionId}:${selectedSet?.id}:${selectedSet?.revision}`
      if (idempotency.current.scope !== scope) {
        idempotency.current = { scope, key: crypto.randomUUID() }
      }
      return transformationsApi.apply(
        datasetId,
        sourceVersionId,
        selectedSet?.id ?? '',
        idempotency.current.key,
      )
    },
    onSuccess: (job) => {
      toast.success('Transformação iniciada.')
      void queryClient.invalidateQueries({ queryKey: ['jobs'] })
      void queryClient.invalidateQueries({ queryKey: ['datasets'] })
      navigate(`/processamentos/${job.id}`)
    },
    onError: handleRuleError,
  })

  const nameMissing = draft.name.trim() === ''
  const canApply = canManage && selectedSet !== null && !dirty && draft.rules.some((r) => r.enabled)

  return (
    <div className="grid gap-6 2xl:grid-cols-5">
      <Card className="min-w-0 2xl:col-span-3">
        <CardHeader>
          <CardTitle>Regras</CardTitle>
          <CardDescription>
            Aplicadas em ordem, só com operações da lista abaixo — nenhuma fórmula ou código livre é
            aceito.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="set-name">Nome do conjunto</Label>
              <Input
                id="set-name"
                value={draft.name}
                maxLength={120}
                placeholder="Ex.: Limpeza de vendas"
                onChange={(event) => edit({ name: event.target.value })}
                disabled={!canManage}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="set-description">Descrição</Label>
              <Input
                id="set-description"
                value={draft.description}
                maxLength={2000}
                placeholder="Opcional"
                onChange={(event) => edit({ description: event.target.value })}
                disabled={!canManage}
              />
            </div>
          </div>

          {draft.rules.length === 0 ? (
            <p className="rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground">
              Nenhuma regra ainda. Adicione a primeira abaixo.
            </p>
          ) : (
            <ol className="space-y-3" aria-label="Regras do conjunto">
              {draft.rules.map((rule, index) => (
                <RuleCard
                  key={index}
                  index={index}
                  total={draft.rules.length}
                  rule={rule}
                  schema={simulation.before[index] ?? inputSchema}
                  error={ruleError?.index === index ? ruleError.message : null}
                  disabled={!canManage}
                  onChange={(next) =>
                    edit({ rules: draft.rules.map((r, i) => (i === index ? next : r)) })
                  }
                  onMove={(delta) => edit({ rules: moveRule(draft.rules, index, delta) })}
                  onRemove={() => edit({ rules: draft.rules.filter((_, i) => i !== index) })}
                />
              ))}
            </ol>
          )}

          {canManage && (
            <div className="flex flex-col gap-3 border-t pt-4 sm:flex-row sm:items-end">
              <div className="flex-1 space-y-1.5">
                <Label>Adicionar regra</Label>
                <Select
                  value=""
                  onValueChange={(operation) =>
                    edit({
                      rules: insertRule(
                        draft.rules,
                        defaultRule(operation as RuleOperation, simulation.output),
                      ),
                    })
                  }
                  disabled={draft.rules.length >= 50}
                >
                  <SelectTrigger className="w-full" aria-label="Adicionar regra">
                    <SelectValue placeholder="Escolha a operação" />
                  </SelectTrigger>
                  <SelectContent>
                    {(Object.keys(OPERATION_LABEL) as RuleOperation[]).map((operation) => (
                      <SelectItem key={operation} value={operation}>
                        {OPERATION_LABEL[operation]}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button
                  variant="outline"
                  onClick={() => runPreview.mutate(draft.rules)}
                  disabled={runPreview.isPending || draft.rules.length === 0}
                >
                  {runPreview.isPending ? <Loader2 className="animate-spin" /> : <Eye />}
                  Gerar prévia
                </Button>
                <Button
                  onClick={() => save.mutate()}
                  disabled={save.isPending || nameMissing || !dirty}
                >
                  {save.isPending ? <Loader2 className="animate-spin" /> : <Save />}
                  {selectedSet ? 'Salvar nova revisão' : 'Salvar conjunto'}
                </Button>
              </div>
            </div>
          )}

          {canManage && (
            <div className="flex flex-col gap-3 rounded-lg border bg-muted/30 p-3 sm:flex-row sm:items-center">
              <p className="flex-1 text-sm">
                {selectedSet ? (
                  dirty ? (
                    'Há alterações não salvas: salve uma nova revisão antes de aplicar.'
                  ) : (
                    <>
                      Aplicar <strong>{selectedSet.name}</strong> (revisão {selectedSet.revision})
                      sobre <strong>v{sourceVersion?.version_number}</strong> gera a versão{' '}
                      <strong>v{nextVersionNumber}</strong>.
                    </>
                  )
                ) : (
                  'Salve o conjunto para poder aplicá-lo.'
                )}
              </p>
              <div className="flex gap-2">
                {selectedSet && (
                  <DeleteSetButton
                    name={selectedSet.name}
                    pending={remove.isPending}
                    onConfirm={() => remove.mutate(selectedSet.id)}
                  />
                )}
                <Button onClick={() => apply.mutate()} disabled={!canApply || apply.isPending}>
                  {apply.isPending ? <Loader2 className="animate-spin" /> : <Play />}
                  Aplicar e gerar nova versão
                </Button>
              </div>
            </div>
          )}
          {!canManage && (
            <p className="text-sm text-muted-foreground">
              Seu perfil permite apenas visualizar os conjuntos. Peça a um analista para editar ou
              aplicar.
            </p>
          )}
        </CardContent>
      </Card>

      <div className="min-w-0 space-y-6 2xl:col-span-2">
        <PreviewPanel preview={preview} stale={previewStale} />
        {canManage && (
          <DuplicatesPanel
            key={sourceVersion.id}
            datasetId={datasetId}
            version={sourceVersion}
            schema={inputSchema}
          />
        )}
      </div>
    </div>
  )
}

function RuleCard({
  index,
  total,
  rule,
  schema,
  error,
  disabled,
  onChange,
  onMove,
  onRemove,
}: {
  index: number
  total: number
  rule: Rule
  schema: ColumnSpec[]
  error: string | null
  disabled: boolean
  onChange: (rule: Rule) => void
  onMove: (delta: -1 | 1) => void
  onRemove: () => void
}) {
  return (
    <li
      className={cn(
        'rounded-xl border p-4',
        !rule.enabled && 'opacity-60',
        error && 'border-destructive/60 bg-destructive/5',
      )}
      aria-label={`Regra ${index + 1}: ${OPERATION_LABEL[rule.operation]}`}
    >
      <div className="mb-3 flex flex-wrap items-start gap-3">
        <span className="tabular flex size-6 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary">
          {index + 1}
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold">{OPERATION_LABEL[rule.operation]}</p>
          <p className="text-xs text-muted-foreground">{OPERATION_HINT[rule.operation]}</p>
        </div>
        <label className="flex items-center gap-1.5 text-xs">
          <Checkbox
            checked={rule.enabled}
            onCheckedChange={(checked) => onChange({ ...rule, enabled: checked === true })}
            disabled={disabled}
            aria-label={`Regra ${index + 1} ativa`}
          />
          Ativa
        </label>
        {!disabled && (
          <div className="flex">
            <Button
              variant="ghost"
              size="icon"
              aria-label={`Mover regra ${index + 1} para cima`}
              onClick={() => onMove(-1)}
              disabled={index === 0}
            >
              <ArrowUp />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              aria-label={`Mover regra ${index + 1} para baixo`}
              onClick={() => onMove(1)}
              disabled={index === total - 1}
            >
              <ArrowDown />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              aria-label={`Remover regra ${index + 1}`}
              onClick={onRemove}
            >
              <Trash2 />
            </Button>
          </div>
        )}
      </div>
      <RuleEditor rule={rule} schema={schema} onChange={onChange} disabled={disabled} />
      <p className="mt-3 text-xs text-muted-foreground">Resumo: {describeRule(rule)}</p>
      {error && (
        <p className="mt-2 text-sm text-destructive" role="alert">
          {error}
        </p>
      )}
    </li>
  )
}

function DeleteSetButton({
  name,
  pending,
  onConfirm,
}: {
  name: string
  pending: boolean
  onConfirm: () => void
}) {
  const [open, setOpen] = useState(false)
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="ghost" aria-label="Excluir conjunto">
          <Trash2 />
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Excluir o conjunto “{name}”?</DialogTitle>
          <DialogDescription>
            As versões já geradas continuam com a cópia das regras que usaram; só o conjunto
            reutilizável deixa de existir.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <DialogClose asChild>
            <Button variant="outline">Manter</Button>
          </DialogClose>
          <Button variant="destructive" onClick={onConfirm} disabled={pending}>
            {pending && <Loader2 className="animate-spin" />} Excluir conjunto
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function PreviewPanel({ preview, stale }: { preview: TransformPreview | null; stale: boolean }) {
  if (!preview) {
    return (
      <Card aria-label="Prévia" role="region">
        <CardHeader>
          <CardTitle>Prévia</CardTitle>
          <CardDescription>
            Aplica as regras aos primeiros registros da versão, sem gravar nada.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            Use “Gerar prévia” para ver o resultado e o que seria excluído.
          </p>
        </CardContent>
      </Card>
    )
  }
  const { counts } = preview
  const accounted = counts.valid + counts.rejected + counts.filtered + (counts.duplicates ?? 0)
  return (
    <Card aria-label="Prévia" role="region">
      <CardHeader>
        <CardTitle>Prévia</CardTitle>
        <CardDescription>
          {preview.sample_is_complete
            ? `Todos os ${formatInteger(preview.sample_size)} registros da v${preview.source_version_number}.`
            : `Primeiros ${formatInteger(preview.sample_size)} de ${formatInteger(preview.source_row_count)} registros da v${preview.source_version_number}. A duplicidade aqui considera só a amostra.`}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {stale && (
          <Alert>
            <AlertTitle>Prévia desatualizada</AlertTitle>
            <AlertDescription>As regras mudaram depois desta prévia.</AlertDescription>
          </Alert>
        )}
        <dl className="grid grid-cols-2 gap-2 sm:grid-cols-5 2xl:grid-cols-3">
          {(
            [
              ['Recebidos', counts.received],
              ['Válidos', counts.valid],
              ['Rejeitados', counts.rejected],
              ['Filtrados', counts.filtered],
              ['Duplicados', counts.duplicates],
            ] as const
          ).map(([label, value]) => (
            <div key={label} className="rounded-lg border p-2.5">
              <dt className="text-xs text-muted-foreground">{label}</dt>
              <dd className="tabular text-lg font-semibold">
                {value === null ? '—' : formatInteger(value)}
              </dd>
            </div>
          ))}
        </dl>
        <p
          className={cn(
            'flex items-center gap-1.5 text-xs',
            accounted === counts.received ? 'text-success' : 'text-destructive',
          )}
        >
          <CheckCircle2 className="size-3.5" /> Recebidos = válidos + rejeitados + filtrados +
          duplicados ({formatInteger(accounted)})
        </p>

        <div className="max-h-80 overflow-auto rounded-xl border">
          <Table>
            <TableHeader className="sticky top-0 bg-muted/60 backdrop-blur">
              <TableRow className="hover:bg-transparent">
                <TableHead className="w-12 text-xs">#</TableHead>
                {preview.output_columns.map((column) => (
                  <TableHead key={column.name} className="text-xs whitespace-nowrap">
                    {column.name}
                  </TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {preview.rows.map((row) => (
                <TableRow key={row.row}>
                  <TableCell className="tabular text-xs text-muted-foreground">{row.row}</TableCell>
                  {row.values.map((value, index) => (
                    <TableCell key={index} className="text-xs">
                      <CellValue
                        value={value}
                        type={preview.output_columns[index]?.data_type ?? 'text'}
                      />
                    </TableCell>
                  ))}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>

        {preview.excluded.length > 0 && (
          <div>
            <p className="mb-2 text-sm font-medium">Excluídos na prévia</p>
            <ul className="max-h-64 space-y-1.5 overflow-auto text-sm">
              {preview.excluded.map((item) => (
                <li
                  key={`${item.row}-${item.reason}`}
                  className="flex flex-wrap items-baseline gap-2"
                >
                  <span className="tabular w-12 text-xs text-muted-foreground">#{item.row}</span>
                  <StatusBadge tone={CATEGORY_TONE[item.category]}>
                    {CATEGORY_LABEL[item.category]}
                  </StatusBadge>
                  <span>{REASON_LABEL[item.reason] ?? item.reason}</span>
                  {item.rule !== null && (
                    <span className="text-xs text-muted-foreground">regra {item.rule}</span>
                  )}
                  {item.detail && (
                    <span className="w-full pl-14 text-xs text-muted-foreground">
                      {item.detail}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function DuplicatesPanel({
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
