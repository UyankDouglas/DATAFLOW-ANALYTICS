import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle,
  FileText,
  Info,
  Loader2,
  Play,
  Rows3,
  TableProperties,
  Type,
} from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Controller, useFieldArray, useForm, useWatch } from 'react-hook-form'
import { Link, useNavigate, useParams } from 'react-router'
import { toast } from 'sonner'

import { KpiCard } from '@/components/kpi-card'
import { PageHeader } from '@/components/page-header'
import { ErrorState, TableSkeleton } from '@/components/states'
import { StatusBadge } from '@/components/status-badge'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
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
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { usePermission } from '@/features/auth/use-auth'
import { datasetsApi } from '@/features/datasets/api'
import {
  DATA_TYPE_LABEL,
  DATE_FORMATS,
  DATETIME_FORMATS,
  WARNING_LABEL,
  ambiguousColumns,
  importFormSchema,
  initialColumns,
  type ImportFormValues,
} from '@/features/datasets/column-form'
import { ParseOptionsForm } from '@/features/datasets/parse-options-form'
import { formatBytes, formatInteger, formatPercent, formatTimestamp } from '@/lib/format'
import { ApiError, describeError } from '@/services/api-client'
import type { DataType, ParseOptions, Preview } from '@/types/api'

export function PreviewPage() {
  const { datasetId = '' } = useParams()
  const queryClient = useQueryClient()
  const [options, setOptions] = useState<ParseOptions | null>(null)

  const saved = useQuery({
    queryKey: ['datasets', datasetId, 'preview'],
    queryFn: () => datasetsApi.preview(datasetId),
  })
  const trial = useMutation({
    mutationFn: (next: ParseOptions) => datasetsApi.tryPreview(datasetId, next),
    onSuccess: (data, next) => {
      setOptions(next)
      queryClient.setQueryData(['datasets', datasetId, 'preview', 'trial'], data)
    },
    onError: (error) => toast.error(describeError(error)),
  })
  const preview = trial.data ?? saved.data

  if (saved.isPending) {
    return (
      <>
        <PageHeader title="Pré-visualização" />
        <TableSkeleton rows={8} columns={6} />
      </>
    )
  }
  if (saved.isError || !preview) {
    return (
      <>
        <PageHeader
          title="Pré-visualização"
          breadcrumbs={[{ label: 'Datasets', to: '/datasets' }]}
        />
        <ErrorState error={saved.error} onRetry={() => saved.refetch()} />
      </>
    )
  }

  const effectiveOptions = options ?? preview.parse_options
  return (
    <PreviewContent
      key={`${preview.header.join('|')}-${JSON.stringify(effectiveOptions)}`}
      preview={preview}
      options={effectiveOptions}
      onApplyOptions={(next) => trial.mutate(next)}
      applying={trial.isPending}
    />
  )
}

interface PreviewContentProps {
  preview: Preview
  options: ParseOptions
  onApplyOptions: (options: ParseOptions) => void
  applying: boolean
}

function PreviewContent({ preview, options, onApplyOptions, applying }: PreviewContentProps) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const canProcess = usePermission('datasets:process')
  const idempotencyKey = useRef(crypto.randomUUID())
  const form = useForm<ImportFormValues>({
    resolver: zodResolver(importFormSchema),
    defaultValues: { columns: initialColumns(preview), confirm_ambiguous: false },
    mode: 'onChange',
  })
  const { fields } = useFieldArray({ control: form.control, name: 'columns' })
  const columns = useWatch({ control: form.control, name: 'columns' })
  const ambiguous = useMemo(() => ambiguousColumns(columns, preview), [columns, preview])
  const confirm = useWatch({ control: form.control, name: 'confirm_ambiguous' })

  const start = useMutation({
    mutationFn: (values: ImportFormValues) =>
      datasetsApi.startImport(
        preview.dataset_id,
        {
          parse_options: options,
          columns: values.columns.map((column) => ({ ...column, name: column.name.trim() })),
          confirm_ambiguous_formats: values.confirm_ambiguous,
        },
        idempotencyKey.current,
      ),
    onSuccess: (job) => {
      toast.success('Processamento iniciado.')
      void queryClient.invalidateQueries({ queryKey: ['datasets'] })
      void queryClient.invalidateQueries({ queryKey: ['jobs'] })
      navigate(`/processamentos/${job.id}`)
    },
    onError: (error) => {
      if (error instanceof ApiError && error.code === 'job_in_progress') {
        toast.warning(error.message)
      }
    },
  })

  useEffect(() => {
    void form.trigger()
  }, [form])

  const onSubmit = form.handleSubmit((values) => {
    if (ambiguous.length > 0 && !values.confirm_ambiguous) {
      form.setError('confirm_ambiguous', { message: 'Confirme os formatos de data ambíguos.' })
      return
    }
    start.mutate(values)
  })

  const errorCount = Object.keys(form.formState.errors.columns ?? {}).length
  const upload = preview.upload

  return (
    <>
      <PageHeader
        title={preview.dataset_name}
        description="Confira a amostra, ajuste a leitura e o mapeamento de colunas antes de processar."
        breadcrumbs={[
          { label: 'Datasets', to: '/datasets' },
          { label: preview.dataset_name, to: `/datasets/${preview.dataset_id}` },
          { label: 'Pré-visualização' },
        ]}
        actions={
          canProcess && (
            <Button onClick={onSubmit} disabled={start.isPending || applying}>
              {start.isPending ? <Loader2 className="animate-spin" /> : <Play />}
              Iniciar processamento
            </Button>
          )
        }
      />

      <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <KpiCard
          label="Arquivo"
          icon={FileText}
          value={formatBytes(upload.size_bytes)}
          hint={`${upload.original_filename} · ${formatTimestamp(upload.created_at)}`}
        />
        <KpiCard
          label={preview.row_count.exact ? 'Registros (exato)' : 'Registros (estimado)'}
          icon={Rows3}
          accent="cyan"
          value={`${preview.row_count.exact ? '' : '≈ '}${formatInteger(preview.row_count.value)}`}
          hint={preview.row_count.method}
        />
        <KpiCard
          label="Colunas"
          icon={TableProperties}
          accent="violet"
          value={formatInteger(preview.column_count)}
          hint={`${formatInteger(preview.sample_rows_analyzed)} registros analisados na amostra`}
        />
        <KpiCard
          label="Encoding detectado"
          icon={Type}
          accent={upload.detection.utf8_valid === false ? 'amber' : 'green'}
          value={upload.detection.utf8_valid === false ? 'Não UTF-8' : 'UTF-8'}
          hint={
            upload.detection.utf8_valid === false
              ? 'Confirme o encoding na leitura'
              : 'Conteúdo válido em UTF-8'
          }
        />
      </section>

      {preview.warnings.length > 0 && (
        <Alert className="mt-6 border-warning/40 bg-warning/5">
          <AlertTriangle className="text-warning" />
          <AlertTitle>Atenção</AlertTitle>
          <AlertDescription>
            <ul className="list-disc space-y-1 pl-4">
              {preview.warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          </AlertDescription>
        </Alert>
      )}

      <Card className="mt-6">
        <CardHeader>
          <CardTitle>Leitura do arquivo</CardTitle>
          <CardDescription>
            Valores detectados automaticamente. Ajuste se a prévia não estiver correta.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <ParseOptionsForm
            value={options}
            onApply={onApplyOptions}
            pending={applying}
            disabled={!canProcess}
          />
        </CardContent>
      </Card>

      <form onSubmit={onSubmit} noValidate>
        <Card className="mt-6">
          <CardHeader>
            <CardTitle>Mapeamento de colunas</CardTitle>
            <CardDescription>
              Tipos inferidos sobre a amostra. Valores que não converterem para o tipo escolhido
              rejeitam o registro, com motivo registrado.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto rounded-xl border">
              <Table>
                <TableHeader className="bg-muted/40">
                  <TableRow className="hover:bg-transparent">
                    {[
                      'Coluna original',
                      'Nome no dataset',
                      'Tipo',
                      'Formato / casas',
                      'Inferido',
                      'Nulos (amostra)',
                      'Distintos',
                      'Avisos',
                    ].map((label) => (
                      <TableHead
                        key={label}
                        className="text-xs font-semibold whitespace-nowrap text-muted-foreground uppercase"
                      >
                        {label}
                      </TableHead>
                    ))}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {fields.map((field, index) => {
                    const stats = preview.columns[field.position]
                    const current = columns[index]
                    const errors = form.formState.errors.columns?.[index]
                    return (
                      <TableRow key={field.id}>
                        <TableCell className="font-mono text-xs whitespace-nowrap">
                          {field.source_name}
                        </TableCell>
                        <TableCell className="min-w-44">
                          <Input
                            {...form.register(`columns.${index}.name`)}
                            aria-label={`Nome da coluna ${field.source_name}`}
                            aria-invalid={Boolean(errors?.name)}
                            className="h-8"
                            disabled={!canProcess}
                          />
                          {errors?.name && (
                            <p className="mt-1 text-xs text-destructive">{errors.name.message}</p>
                          )}
                        </TableCell>
                        <TableCell className="min-w-36">
                          <Controller
                            control={form.control}
                            name={`columns.${index}.data_type`}
                            render={({ field: typeField }) => (
                              <Select
                                value={typeField.value}
                                disabled={!canProcess}
                                onValueChange={(value) => {
                                  const dataType = value as DataType
                                  typeField.onChange(dataType)
                                  const formatDefault =
                                    dataType === 'date'
                                      ? stats?.inferred_type === 'date'
                                        ? stats.format
                                        : '%d/%m/%Y'
                                      : dataType === 'datetime'
                                        ? stats?.inferred_type === 'datetime'
                                          ? stats.format
                                          : '%d/%m/%Y %H:%M:%S'
                                        : null
                                  form.setValue(`columns.${index}.format`, formatDefault, {
                                    shouldValidate: true,
                                  })
                                  form.setValue(
                                    `columns.${index}.scale`,
                                    dataType === 'decimal' ? (stats?.scale ?? 2) : null,
                                    { shouldValidate: true },
                                  )
                                }}
                              >
                                <SelectTrigger
                                  size="sm"
                                  className="w-full"
                                  aria-label={`Tipo da coluna ${field.source_name}`}
                                >
                                  <SelectValue />
                                </SelectTrigger>
                                <SelectContent>
                                  {(Object.keys(DATA_TYPE_LABEL) as DataType[]).map((type) => (
                                    <SelectItem key={type} value={type}>
                                      {DATA_TYPE_LABEL[type]}
                                    </SelectItem>
                                  ))}
                                </SelectContent>
                              </Select>
                            )}
                          />
                        </TableCell>
                        <TableCell className="min-w-44">
                          {current?.data_type === 'date' || current?.data_type === 'datetime' ? (
                            <Controller
                              control={form.control}
                              name={`columns.${index}.format`}
                              render={({ field: formatField }) => (
                                <Select
                                  value={formatField.value ?? undefined}
                                  onValueChange={formatField.onChange}
                                  disabled={!canProcess}
                                >
                                  <SelectTrigger
                                    size="sm"
                                    className="w-full"
                                    aria-label={`Formato da coluna ${field.source_name}`}
                                    aria-invalid={Boolean(errors?.format)}
                                  >
                                    <SelectValue placeholder="Escolha o formato" />
                                  </SelectTrigger>
                                  <SelectContent>
                                    {Object.entries(
                                      current.data_type === 'date'
                                        ? DATE_FORMATS
                                        : DATETIME_FORMATS,
                                    ).map(([key, label]) => (
                                      <SelectItem key={key} value={key}>
                                        {label}
                                        {stats?.ambiguous_formats.includes(key)
                                          ? ' (possível)'
                                          : ''}
                                      </SelectItem>
                                    ))}
                                  </SelectContent>
                                </Select>
                              )}
                            />
                          ) : current?.data_type === 'decimal' ? (
                            <Input
                              type="number"
                              min={0}
                              max={18}
                              className="h-8 w-24"
                              aria-label={`Casas decimais da coluna ${field.source_name}`}
                              disabled={!canProcess}
                              {...form.register(`columns.${index}.scale`, { valueAsNumber: true })}
                            />
                          ) : (
                            <span className="text-xs text-muted-foreground">—</span>
                          )}
                          {(errors?.format || errors?.scale) && (
                            <p className="mt-1 text-xs text-destructive">
                              {errors.format?.message ?? errors.scale?.message}
                            </p>
                          )}
                        </TableCell>
                        <TableCell>
                          <StatusBadge tone="neutral">
                            {stats ? DATA_TYPE_LABEL[stats.inferred_type] : '—'}
                          </StatusBadge>
                        </TableCell>
                        <TableCell className="tabular text-sm whitespace-nowrap">
                          {stats
                            ? `${formatPercent(stats.null_ratio)} (${formatInteger(stats.null_count)})`
                            : '—'}
                        </TableCell>
                        <TableCell className="tabular text-sm">
                          {formatInteger(stats?.distinct_count)}
                        </TableCell>
                        <TableCell>
                          <div className="flex flex-wrap gap-1">
                            {stats?.warnings.map((warning) => (
                              <StatusBadge key={warning} tone="warning">
                                {WARNING_LABEL[warning] ?? warning}
                              </StatusBadge>
                            ))}
                            {preview.duplicate_header_names.includes(field.source_name) && (
                              <StatusBadge tone="danger">Cabeçalho repetido</StatusBadge>
                            )}
                          </div>
                        </TableCell>
                      </TableRow>
                    )
                  })}
                </TableBody>
              </Table>
            </div>

            {ambiguous.length > 0 && (
              <div className="mt-4 rounded-lg border border-warning/40 bg-warning/5 p-3">
                <label className="flex items-start gap-2 text-sm">
                  <Controller
                    control={form.control}
                    name="confirm_ambiguous"
                    render={({ field }) => (
                      <Checkbox
                        checked={field.value}
                        onCheckedChange={(checked) => field.onChange(checked === true)}
                        className="mt-0.5"
                        aria-describedby="ambiguous-help"
                      />
                    )}
                  />
                  <span>
                    Confirmo o formato escolhido para <strong>{ambiguous.join(', ')}</strong>.
                    <span id="ambiguous-help" className="block text-xs text-muted-foreground">
                      Na amostra, os valores servem tanto para dia/mês quanto para mês/dia.
                    </span>
                  </span>
                </label>
                {form.formState.errors.confirm_ambiguous && !confirm && (
                  <p className="mt-2 text-xs text-destructive">
                    {form.formState.errors.confirm_ambiguous.message}
                  </p>
                )}
              </div>
            )}

            {start.isError && (
              <Alert variant="destructive" className="mt-4">
                <AlertTriangle />
                <AlertTitle>Não foi possível iniciar o processamento</AlertTitle>
                <AlertDescription>{describeError(start.error)}</AlertDescription>
              </Alert>
            )}

            {canProcess ? (
              <div className="mt-4 flex flex-col-reverse items-stretch justify-between gap-3 sm:flex-row sm:items-center">
                <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  <Info className="size-3.5" /> O mapeamento fica salvo no dataset e é reutilizado
                  em reprocessamentos.
                </p>
                <Button type="submit" disabled={start.isPending || applying}>
                  {start.isPending ? <Loader2 className="animate-spin" /> : <Play />}
                  Iniciar processamento
                  {errorCount > 0 && (
                    <span className="rounded bg-destructive/20 px-1.5 text-xs">
                      {errorCount} pendência(s)
                    </span>
                  )}
                </Button>
              </div>
            ) : (
              <p className="mt-4 text-sm text-muted-foreground">
                Seu perfil permite apenas visualizar. Peça a um analista para processar.
              </p>
            )}
          </CardContent>
        </Card>
      </form>

      <Card className="mt-6">
        <CardHeader>
          <CardTitle>Primeiras {formatInteger(preview.rows.length)} linhas</CardTitle>
          <CardDescription>
            Valores exatamente como estão no arquivo, antes da conversão de tipos.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="max-h-[480px] overflow-auto rounded-xl border">
            <Table>
              <TableHeader className="sticky top-0 z-10 bg-muted/60 backdrop-blur">
                <TableRow className="hover:bg-transparent">
                  <TableHead className="w-12 text-xs text-muted-foreground">#</TableHead>
                  {preview.header.map((name, index) => (
                    <TableHead key={`${name}-${index}`} className="whitespace-nowrap">
                      <span className="block text-xs font-semibold">
                        {columns[index]?.name || name}
                      </span>
                      <span className="block text-[11px] font-normal text-muted-foreground">
                        {columns[index] ? DATA_TYPE_LABEL[columns[index].data_type] : ''}
                      </span>
                    </TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {preview.rows.map((row, rowIndex) => (
                  <TableRow key={rowIndex}>
                    <TableCell className="tabular text-xs text-muted-foreground">
                      {rowIndex + 1}
                    </TableCell>
                    {preview.header.map((_, colIndex) => {
                      const value = row[colIndex]
                      return (
                        <TableCell key={colIndex} className="max-w-64 truncate font-mono text-xs">
                          {value === undefined ? (
                            <Tooltip>
                              <TooltipTrigger asChild>
                                <span className="text-destructive">ausente</span>
                              </TooltipTrigger>
                              <TooltipContent>
                                Este registro tem menos campos que o cabeçalho.
                              </TooltipContent>
                            </Tooltip>
                          ) : value === '' ? (
                            <span className="text-muted-foreground">vazio</span>
                          ) : (
                            value
                          )}
                        </TableCell>
                      )
                    })}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          <p className="mt-3 text-xs text-muted-foreground">
            Prefere outro arquivo?{' '}
            <Link to="/importar" className="text-primary hover:underline">
              Importar novamente
            </Link>
          </p>
        </CardContent>
      </Card>
    </>
  )
}
