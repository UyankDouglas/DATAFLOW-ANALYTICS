import { Plus, X } from 'lucide-react'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { DATA_TYPE_LABEL, DATE_FORMATS, DATETIME_FORMATS } from '@/features/datasets/column-form'
import type {
  ColumnSpec,
  Condition,
  DataType,
  Expression,
  FilterOperator,
  Operand,
  Rule,
} from '@/types/api'

import {
  ARITHMETIC_LABEL,
  DATE_PART_LABEL,
  LIST_OPERATORS,
  NO_VALUE_OPERATORS,
  OPERATORS_BY_TYPE,
  OPERATOR_LABEL,
  isNumeric,
  isTemporal,
} from './rules'

interface RuleEditorProps {
  rule: Rule
  /** Esquema visto pela regra (depois das regras anteriores). */
  schema: ColumnSpec[]
  onChange: (rule: Rule) => void
  disabled?: boolean
}

const SEPARATORS = { '.': 'Ponto ( . )', ',': 'Vírgula ( , )' } as const
const THOUSANDS = { none: 'Nenhum', '.': 'Ponto ( . )', ',': 'Vírgula ( , )', ' ': 'Espaço' }

export function RuleEditor({ rule, schema, onChange, disabled }: RuleEditorProps) {
  const text = schema.filter((column) => column.data_type === 'text')
  switch (rule.operation) {
    case 'trim':
      return (
        <div className="space-y-3">
          <ColumnPicker
            label="Colunas de texto"
            columns={text}
            value={rule.columns}
            onChange={(columns) => onChange({ ...rule, columns })}
            disabled={disabled}
          />
          <CheckField
            label="Também reduzir espaços repetidos no meio do texto"
            checked={rule.collapse_internal ?? true}
            onChange={(collapse_internal) => onChange({ ...rule, collapse_internal })}
            disabled={disabled}
          />
        </div>
      )
    case 'normalize_text':
      return (
        <div className="space-y-3">
          <ColumnPicker
            label="Colunas de texto"
            columns={text}
            value={rule.columns}
            onChange={(columns) => onChange({ ...rule, columns })}
            disabled={disabled}
          />
          <CheckField
            label="Remover acentos (São Paulo → Sao Paulo)"
            checked={rule.remove_accents ?? true}
            onChange={(remove_accents) => onChange({ ...rule, remove_accents })}
            disabled={disabled}
          />
        </div>
      )
    case 'change_case':
      return (
        <div className="grid gap-3 sm:grid-cols-2">
          <ColumnPicker
            label="Colunas de texto"
            columns={text}
            value={rule.columns}
            onChange={(columns) => onChange({ ...rule, columns })}
            disabled={disabled}
          />
          <OptionSelect
            label="Padrão"
            value={rule.mode}
            options={{ upper: 'MAIÚSCULAS', lower: 'minúsculas', title: 'Iniciais Maiúsculas' }}
            onChange={(mode) => onChange({ ...rule, mode: mode as typeof rule.mode })}
            disabled={disabled}
          />
        </div>
      )
    case 'convert_type': {
      const source = schema.find((column) => column.name === rule.column)
      const fromText = source?.data_type === 'text'
      return (
        <div className="grid gap-3 sm:grid-cols-2">
          <ColumnSelect
            label="Coluna"
            columns={schema}
            value={rule.column}
            onChange={(column) => onChange({ ...rule, column })}
            disabled={disabled}
          />
          <OptionSelect
            label="Converter para"
            value={rule.target}
            options={DATA_TYPE_LABEL}
            onChange={(value) => {
              const target = value as DataType
              onChange({
                ...rule,
                target,
                format:
                  target === 'date'
                    ? '%d/%m/%Y'
                    : target === 'datetime'
                      ? '%d/%m/%Y %H:%M:%S'
                      : null,
                scale: target === 'decimal' ? (rule.scale ?? 2) : null,
              })
            }}
            disabled={disabled}
          />
          {fromText && isTemporal(rule.target) && (
            <OptionSelect
              label="Formato de origem"
              value={rule.format ?? ''}
              options={rule.target === 'date' ? DATE_FORMATS : DATETIME_FORMATS}
              onChange={(format) => onChange({ ...rule, format })}
              disabled={disabled}
            />
          )}
          {rule.target === 'decimal' && (
            <NumberField
              label="Casas decimais"
              value={rule.scale ?? null}
              onChange={(scale) => onChange({ ...rule, scale })}
              disabled={disabled}
            />
          )}
          {fromText && isNumeric(rule.target) && (
            <SeparatorFields
              decimal={rule.decimal_separator ?? '.'}
              thousands={rule.thousands_separator ?? ''}
              onChange={(decimal_separator, thousands_separator) =>
                onChange({ ...rule, decimal_separator, thousands_separator })
              }
              disabled={disabled}
            />
          )}
        </div>
      )
    }
    case 'standardize_dates': {
      const formats =
        rule.target === 'date' ? DATE_FORMATS : { ...DATETIME_FORMATS, ...DATE_FORMATS }
      return (
        <div className="grid gap-3 sm:grid-cols-2">
          <ColumnSelect
            label="Coluna de texto"
            columns={text}
            value={rule.column}
            onChange={(column) => onChange({ ...rule, column })}
            disabled={disabled}
          />
          <OptionSelect
            label="Resultado"
            value={rule.target}
            options={{ date: 'Data', datetime: 'Data e hora' }}
            onChange={(target) =>
              onChange({ ...rule, target: target as typeof rule.target, formats: rule.formats })
            }
            disabled={disabled}
          />
          <div className="sm:col-span-2">
            <ChoiceList
              label="Formatos aceitos (testados nesta ordem)"
              options={formats}
              value={rule.formats}
              onChange={(next) => onChange({ ...rule, formats: next })}
              disabled={disabled}
            />
          </div>
        </div>
      )
    }
    case 'fix_numbers':
      return (
        <div className="grid gap-3 sm:grid-cols-2">
          <ColumnSelect
            label="Coluna de texto"
            columns={text}
            value={rule.column}
            onChange={(column) => onChange({ ...rule, column })}
            disabled={disabled}
          />
          <OptionSelect
            label="Resultado"
            value={rule.target}
            options={{ decimal: 'Decimal', integer: 'Inteiro' }}
            onChange={(target) =>
              onChange({
                ...rule,
                target: target as typeof rule.target,
                scale: target === 'decimal' ? (rule.scale ?? 2) : null,
              })
            }
            disabled={disabled}
          />
          {rule.target === 'decimal' && (
            <NumberField
              label="Casas decimais"
              value={rule.scale ?? null}
              onChange={(scale) => onChange({ ...rule, scale })}
              disabled={disabled}
            />
          )}
          <SeparatorFields
            decimal={rule.decimal_separator}
            thousands={rule.thousands_separator}
            onChange={(decimal_separator, thousands_separator) =>
              onChange({ ...rule, decimal_separator, thousands_separator })
            }
            disabled={disabled}
          />
          <CheckField
            label="Remover símbolo de moeda (R$, US$, €)"
            checked={rule.strip_currency ?? true}
            onChange={(strip_currency) => onChange({ ...rule, strip_currency })}
            disabled={disabled}
          />
          <CheckField
            label="Parênteses indicam negativo: (10,50) → −10,50"
            checked={rule.parentheses_negative ?? false}
            onChange={(parentheses_negative) => onChange({ ...rule, parentheses_negative })}
            disabled={disabled}
          />
        </div>
      )
    case 'handle_nulls':
      return (
        <div className="grid gap-3 sm:grid-cols-2">
          <ColumnPicker
            label="Colunas"
            columns={schema}
            value={rule.columns}
            onChange={(columns) => onChange({ ...rule, columns })}
            disabled={disabled}
          />
          <div className="space-y-3">
            <OptionSelect
              label="Quando o valor for nulo"
              value={rule.strategy}
              options={{ reject: 'Rejeitar o registro', fill: 'Preencher com valor fixo' }}
              onChange={(strategy) =>
                onChange({
                  ...rule,
                  strategy: strategy as typeof rule.strategy,
                  fill_value: strategy === 'fill' ? (rule.fill_value ?? '') : null,
                })
              }
              disabled={disabled}
            />
            {rule.strategy === 'fill' && (
              <TextField
                label="Valor (formato canônico: 2025-01-31, 10.5, true)"
                value={rule.fill_value ?? ''}
                onChange={(fill_value) => onChange({ ...rule, fill_value })}
                disabled={disabled}
              />
            )}
          </div>
        </div>
      )
    case 'remove_empty_rows':
      return (
        <p className="text-sm text-muted-foreground">
          Registros sem nenhum valor em todas as colunas saem da versão e ficam registrados como
          rejeitados (linha vazia).
        </p>
      )
    case 'filter_rows':
      return (
        <FilterEditor
          conditions={rule.conditions}
          match={rule.match}
          schema={schema}
          onChange={(conditions, match) => onChange({ ...rule, conditions, match })}
          disabled={disabled}
        />
      )
    case 'rename_columns':
      return (
        <div className="grid gap-2 sm:grid-cols-2">
          {schema.map((column) => (
            <label key={column.name} className="flex items-center gap-2 text-sm">
              <span className="w-32 shrink-0 truncate font-mono text-xs" title={column.name}>
                {column.name}
              </span>
              <span className="text-muted-foreground">→</span>
              <Input
                className="h-8"
                value={rule.mapping[column.name] ?? ''}
                placeholder="manter"
                aria-label={`Novo nome para ${column.name}`}
                disabled={disabled}
                onChange={(event) => {
                  const mapping = { ...rule.mapping }
                  if (event.target.value) mapping[column.name] = event.target.value
                  else delete mapping[column.name]
                  onChange({ ...rule, mapping })
                }}
              />
            </label>
          ))}
        </div>
      )
    case 'derived_column':
      return (
        <DerivedEditor
          name={rule.name}
          expression={rule.expression}
          schema={schema}
          onChange={(name, expression) => onChange({ ...rule, name, expression })}
          disabled={disabled}
        />
      )
    case 'deduplicate':
      return (
        <div className="grid gap-3 sm:grid-cols-2">
          <ColumnPicker
            label="Chave (nenhuma marcada = todas as colunas)"
            columns={schema}
            value={rule.columns}
            onChange={(columns) => onChange({ ...rule, columns })}
            disabled={disabled}
          />
          <OptionSelect
            label="Manter"
            value={rule.keep}
            options={{ first: 'O primeiro registro', last: 'O último registro' }}
            onChange={(keep) => onChange({ ...rule, keep: keep as typeof rule.keep })}
            disabled={disabled}
          />
        </div>
      )
  }
}

function FilterEditor({
  conditions,
  match,
  schema,
  onChange,
  disabled,
}: {
  conditions: Condition[]
  match: 'all' | 'any'
  schema: ColumnSpec[]
  onChange: (conditions: Condition[], match: 'all' | 'any') => void
  disabled?: boolean
}) {
  const update = (index: number, next: Condition) =>
    onChange(
      conditions.map((condition, i) => (i === index ? next : condition)),
      match,
    )
  return (
    <div className="space-y-3">
      <OptionSelect
        label="Manter registros que atendem a"
        value={match}
        options={{ all: 'todas as condições (E)', any: 'qualquer condição (OU)' }}
        onChange={(value) => onChange(conditions, value as 'all' | 'any')}
        disabled={disabled}
      />
      {conditions.map((condition, index) => {
        const type = schema.find((column) => column.name === condition.column)?.data_type ?? 'text'
        const operators = OPERATORS_BY_TYPE[type]
        return (
          <div key={index} className="space-y-2 rounded-lg border p-2">
            <div className="grid items-end gap-2 sm:grid-cols-[1fr_1fr_auto]">
              <ColumnSelect
                label="Coluna"
                columns={schema}
                value={condition.column}
                onChange={(column) => {
                  const nextType = schema.find((c) => c.name === column)?.data_type ?? 'text'
                  const operator = OPERATORS_BY_TYPE[nextType].includes(condition.operator)
                    ? condition.operator
                    : 'not_null'
                  update(index, { ...condition, column, operator })
                }}
                disabled={disabled}
              />
              <OptionSelect
                label="Condição"
                value={condition.operator}
                options={Object.fromEntries(operators.map((op) => [op, OPERATOR_LABEL[op]]))}
                onChange={(value) =>
                  update(index, { ...condition, operator: value as FilterOperator })
                }
                disabled={disabled}
              />
              <Button
                variant="ghost"
                size="icon"
                aria-label={`Remover condição ${index + 1}`}
                onClick={() =>
                  onChange(
                    conditions.filter((_, i) => i !== index),
                    match,
                  )
                }
                disabled={disabled || conditions.length === 1}
              >
                <X />
              </Button>
            </div>
            <ConditionValue
              condition={condition}
              type={type}
              onChange={(next) => update(index, next)}
              disabled={disabled}
            />
          </div>
        )
      })}
      <Button
        variant="outline"
        size="sm"
        onClick={() =>
          onChange([...conditions, { column: schema[0]?.name ?? '', operator: 'not_null' }], match)
        }
        disabled={disabled || conditions.length >= 10}
      >
        <Plus /> Condição
      </Button>
    </div>
  )
}

function ConditionValue({
  condition,
  type,
  onChange,
  disabled,
}: {
  condition: Condition
  type: DataType
  onChange: (condition: Condition) => void
  disabled?: boolean
}) {
  if (NO_VALUE_OPERATORS.includes(condition.operator)) {
    return <p className="text-xs text-muted-foreground">Esta condição não usa valor.</p>
  }
  const placeholder = isTemporal(type) ? 'aaaa-mm-dd' : isNumeric(type) ? '10.5' : 'texto'
  if (LIST_OPERATORS.includes(condition.operator)) {
    return (
      <ListValueField
        values={condition.values ?? []}
        placeholder={`${placeholder}; ...`}
        onChange={(values) => onChange({ ...condition, value: null, values })}
        disabled={disabled}
      />
    )
  }
  return (
    <div className="flex flex-wrap items-end gap-2">
      <TextField
        label={condition.operator === 'between' ? 'De' : 'Valor'}
        value={condition.value ?? ''}
        placeholder={placeholder}
        onChange={(value) => onChange({ ...condition, value, values: null })}
        disabled={disabled}
      />
      {condition.operator === 'between' && (
        <TextField
          label="Até"
          value={condition.value_to ?? ''}
          placeholder={placeholder}
          onChange={(value_to) => onChange({ ...condition, value_to })}
          disabled={disabled}
        />
      )}
      {type === 'text' && (
        <label className="flex items-center gap-1.5 pb-2 text-xs whitespace-nowrap">
          <Checkbox
            checked={condition.case_insensitive ?? false}
            onCheckedChange={(checked) =>
              onChange({ ...condition, case_insensitive: checked === true })
            }
            disabled={disabled}
          />
          Ignorar maiúsculas
        </label>
      )}
    </div>
  )
}

/** Lista "a; b; c": o texto digitado fica local para que o separador não suma ao digitar. */
function ListValueField({
  values,
  placeholder,
  onChange,
  disabled,
}: {
  values: string[]
  placeholder: string
  onChange: (values: string[]) => void
  disabled?: boolean
}) {
  const [text, setText] = useState(values.join('; '))
  return (
    <TextField
      label="Valores (separados por ;)"
      value={text}
      placeholder={placeholder}
      onChange={(value) => {
        setText(value)
        onChange(
          value
            .split(';')
            .map((item) => item.trim())
            .filter(Boolean),
        )
      }}
      disabled={disabled}
    />
  )
}

function DerivedEditor({
  name,
  expression,
  schema,
  onChange,
  disabled,
}: {
  name: string
  expression: Expression
  schema: ColumnSpec[]
  onChange: (name: string, expression: Expression) => void
  disabled?: boolean
}) {
  const numeric = schema.filter((column) => isNumeric(column.data_type))
  const temporal = schema.filter((column) => isTemporal(column.data_type))
  const first = schema[0]?.name ?? ''
  const switchKind = (kind: Expression['kind']) => {
    const templates: Record<Expression['kind'], Expression> = {
      arithmetic: {
        kind: 'arithmetic',
        operator: 'multiply',
        left: { column: numeric[0]?.name ?? first },
        right: { value: '1' },
        scale: 2,
      },
      concat: { kind: 'concat', parts: [{ column: first }, { value: '-' }], separator: '' },
      date_part: { kind: 'date_part', column: temporal[0]?.name ?? first, part: 'year_month' },
      date_diff_days: {
        kind: 'date_diff_days',
        start: temporal[0]?.name ?? first,
        end: temporal[1]?.name ?? temporal[0]?.name ?? first,
      },
    }
    onChange(name, templates[kind])
  }
  return (
    <div className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-2">
        <TextField
          label="Nome da nova coluna"
          value={name}
          onChange={(value) => onChange(value, expression)}
          disabled={disabled}
        />
        <OptionSelect
          label="Cálculo"
          value={expression.kind}
          options={{
            arithmetic: 'Operação entre números',
            concat: 'Concatenar textos',
            date_part: 'Parte de uma data',
            date_diff_days: 'Dias entre duas datas',
          }}
          onChange={(kind) => switchKind(kind as Expression['kind'])}
          disabled={disabled}
        />
      </div>
      {expression.kind === 'arithmetic' && (
        <div className="space-y-3">
          <OperandField
            label="Primeiro valor"
            operand={expression.left}
            columns={numeric}
            onChange={(left) => onChange(name, { ...expression, left })}
            disabled={disabled}
          />
          <div className="grid grid-cols-[1fr_auto] items-end gap-3">
            <OptionSelect
              label="Operação"
              value={expression.operator}
              options={ARITHMETIC_LABEL}
              onChange={(operator) =>
                onChange(name, { ...expression, operator: operator as typeof expression.operator })
              }
              disabled={disabled}
            />
            <NumberField
              label="Casas"
              value={expression.scale}
              onChange={(scale) => onChange(name, { ...expression, scale: scale ?? 2 })}
              disabled={disabled}
            />
          </div>
          <OperandField
            label="Segundo valor"
            operand={expression.right}
            columns={numeric}
            onChange={(right) => onChange(name, { ...expression, right })}
            disabled={disabled}
          />
        </div>
      )}
      {expression.kind === 'concat' && (
        <div className="space-y-2">
          {expression.parts.map((part, index) => (
            <div key={index} className="flex items-end gap-2">
              <OperandField
                label={`Parte ${index + 1}`}
                operand={part}
                columns={schema}
                onChange={(next) =>
                  onChange(name, {
                    ...expression,
                    parts: expression.parts.map((p, i) => (i === index ? next : p)),
                  })
                }
                disabled={disabled}
              />
              <Button
                variant="ghost"
                size="icon"
                aria-label={`Remover parte ${index + 1}`}
                disabled={disabled || expression.parts.length <= 2}
                onClick={() =>
                  onChange(name, {
                    ...expression,
                    parts: expression.parts.filter((_, i) => i !== index),
                  })
                }
              >
                <X />
              </Button>
            </div>
          ))}
          <div className="flex flex-wrap items-end gap-3">
            <Button
              variant="outline"
              size="sm"
              disabled={disabled || expression.parts.length >= 10}
              onClick={() =>
                onChange(name, { ...expression, parts: [...expression.parts, { column: first }] })
              }
            >
              <Plus /> Parte
            </Button>
            <TextField
              label="Separador"
              value={expression.separator}
              onChange={(separator) => onChange(name, { ...expression, separator })}
              disabled={disabled}
            />
          </div>
        </div>
      )}
      {expression.kind === 'date_part' && (
        <div className="grid gap-3 sm:grid-cols-2">
          <ColumnSelect
            label="Coluna de data"
            columns={temporal}
            value={expression.column}
            onChange={(column) => onChange(name, { ...expression, column })}
            disabled={disabled}
          />
          <OptionSelect
            label="Parte"
            value={expression.part}
            options={DATE_PART_LABEL}
            onChange={(part) =>
              onChange(name, { ...expression, part: part as typeof expression.part })
            }
            disabled={disabled}
          />
        </div>
      )}
      {expression.kind === 'date_diff_days' && (
        <div className="grid gap-3 sm:grid-cols-2">
          <ColumnSelect
            label="Data inicial"
            columns={temporal}
            value={expression.start}
            onChange={(start) => onChange(name, { ...expression, start })}
            disabled={disabled}
          />
          <ColumnSelect
            label="Data final"
            columns={temporal}
            value={expression.end}
            onChange={(end) => onChange(name, { ...expression, end })}
            disabled={disabled}
          />
        </div>
      )}
    </div>
  )
}

function OperandField({
  label,
  operand,
  columns,
  onChange,
  disabled,
}: {
  label: string
  operand: Operand
  columns: ColumnSpec[]
  onChange: (operand: Operand) => void
  disabled?: boolean
}) {
  const isColumn = operand.column !== undefined && operand.column !== null
  return (
    <div className="grid min-w-0 flex-1 grid-cols-[minmax(0,9rem)_minmax(0,1fr)] items-end gap-2">
      <OptionSelect
        label={label}
        value={isColumn ? 'column' : 'value'}
        options={{ column: 'Coluna', value: 'Valor fixo' }}
        onChange={(kind) =>
          onChange(kind === 'column' ? { column: columns[0]?.name ?? '' } : { value: '' })
        }
        disabled={disabled}
      />
      {isColumn ? (
        <ColumnSelect
          label={`${label}: coluna`}
          hideLabel
          columns={columns}
          value={operand.column ?? ''}
          onChange={(column) => onChange({ column })}
          disabled={disabled}
        />
      ) : (
        <TextField
          label={`${label}: valor`}
          hideLabel
          value={operand.value ?? ''}
          onChange={(value) => onChange({ value })}
          disabled={disabled}
        />
      )}
    </div>
  )
}

// ---------------------------------------------------------------- campos básicos

function OptionSelect({
  label,
  value,
  options,
  onChange,
  disabled,
}: {
  label: string
  value: string
  options: Record<string, string>
  onChange: (value: string) => void
  disabled?: boolean
}) {
  return (
    <div className="min-w-0 space-y-1.5">
      <Label className="text-xs">{label}</Label>
      <Select value={value} onValueChange={onChange} disabled={disabled}>
        <SelectTrigger size="sm" className="w-full" aria-label={label}>
          <SelectValue placeholder="Escolha" />
        </SelectTrigger>
        <SelectContent>
          {Object.entries(options).map(([key, text]) => (
            <SelectItem key={key} value={key}>
              {text}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  )
}

function ColumnSelect({
  label,
  columns,
  value,
  onChange,
  disabled,
  hideLabel,
}: {
  label: string
  columns: ColumnSpec[]
  value: string
  onChange: (value: string) => void
  disabled?: boolean
  hideLabel?: boolean
}) {
  const known = columns.some((column) => column.name === value)
  return (
    <div className="min-w-0 flex-1 space-y-1.5">
      {!hideLabel && <Label className="text-xs">{label}</Label>}
      <Select value={known ? value : undefined} onValueChange={onChange} disabled={disabled}>
        <SelectTrigger size="sm" className="w-full" aria-label={label} aria-invalid={!known}>
          <SelectValue placeholder={value ? `${value} (indisponível)` : 'Escolha a coluna'} />
        </SelectTrigger>
        <SelectContent>
          {columns.map((column) => (
            <SelectItem key={column.name} value={column.name}>
              {column.name}
              <span className="text-xs text-muted-foreground">
                {' '}
                · {DATA_TYPE_LABEL[column.data_type]}
              </span>
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  )
}

export function ColumnPicker({
  label,
  columns,
  value,
  onChange,
  disabled,
}: {
  label: string
  columns: ColumnSpec[]
  value: string[]
  onChange: (value: string[]) => void
  disabled?: boolean
}) {
  const missing = value.filter((name) => !columns.some((column) => column.name === name))
  return (
    <fieldset className="min-w-0 space-y-1.5">
      <legend className="mb-1.5 text-xs font-medium">{label}</legend>
      {columns.length === 0 ? (
        <p className="text-xs text-muted-foreground">Nenhuma coluna compatível nesta etapa.</p>
      ) : (
        <div className="max-h-40 space-y-1 overflow-y-auto rounded-md border p-2">
          {columns.map((column) => (
            <label key={column.name} className="flex items-center gap-2 text-sm">
              <Checkbox
                checked={value.includes(column.name)}
                aria-label={column.name}
                disabled={disabled}
                onCheckedChange={(checked) =>
                  onChange(
                    checked === true
                      ? [...value, column.name]
                      : value.filter((name) => name !== column.name),
                  )
                }
              />
              <span className="truncate">{column.name}</span>
              <span className="text-xs text-muted-foreground">
                {DATA_TYPE_LABEL[column.data_type]}
              </span>
            </label>
          ))}
        </div>
      )}
      {missing.length > 0 && (
        <p className="text-xs text-destructive">Indisponível nesta etapa: {missing.join(', ')}</p>
      )}
    </fieldset>
  )
}

function ChoiceList({
  label,
  options,
  value,
  onChange,
  disabled,
}: {
  label: string
  options: Record<string, string>
  value: string[]
  onChange: (value: string[]) => void
  disabled?: boolean
}) {
  return (
    <fieldset className="space-y-1.5">
      <legend className="mb-1.5 text-xs font-medium">{label}</legend>
      <div className="flex flex-wrap gap-x-4 gap-y-1.5">
        {Object.entries(options).map(([key, text]) => (
          <label key={key} className="flex items-center gap-2 text-sm">
            <Checkbox
              checked={value.includes(key)}
              disabled={disabled}
              onCheckedChange={(checked) =>
                onChange(checked === true ? [...value, key] : value.filter((item) => item !== key))
              }
            />
            {text}
          </label>
        ))}
      </div>
    </fieldset>
  )
}

function SeparatorFields({
  decimal,
  thousands,
  onChange,
  disabled,
}: {
  decimal: '.' | ','
  thousands: '' | '.' | ',' | ' '
  onChange: (decimal: '.' | ',', thousands: '' | '.' | ',' | ' ') => void
  disabled?: boolean
}) {
  return (
    <>
      <OptionSelect
        label="Separador decimal"
        value={decimal}
        options={SEPARATORS}
        onChange={(value) => onChange(value as '.' | ',', thousands)}
        disabled={disabled}
      />
      <OptionSelect
        label="Separador de milhar"
        value={thousands === '' ? 'none' : thousands}
        options={THOUSANDS}
        onChange={(value) =>
          onChange(decimal, (value === 'none' ? '' : value) as '' | '.' | ',' | ' ')
        }
        disabled={disabled}
      />
    </>
  )
}

function TextField({
  label,
  value,
  onChange,
  placeholder,
  disabled,
  hideLabel,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  placeholder?: string
  disabled?: boolean
  hideLabel?: boolean
}) {
  return (
    <div className="min-w-0 flex-1 space-y-1.5">
      {!hideLabel && <Label className="text-xs">{label}</Label>}
      <Input
        className="h-8"
        value={value}
        placeholder={placeholder}
        aria-label={label}
        maxLength={200}
        onChange={(event) => onChange(event.target.value)}
        disabled={disabled}
      />
    </div>
  )
}

function NumberField({
  label,
  value,
  onChange,
  disabled,
}: {
  label: string
  value: number | null
  onChange: (value: number | null) => void
  disabled?: boolean
}) {
  return (
    <div className="space-y-1.5">
      <Label className="text-xs">{label}</Label>
      <Input
        type="number"
        min={0}
        max={18}
        className="h-8 w-24"
        value={value ?? ''}
        aria-label={label}
        onChange={(event) =>
          onChange(event.target.value === '' ? null : Number.parseInt(event.target.value, 10))
        }
        disabled={disabled}
      />
    </div>
  )
}

function CheckField({
  label,
  checked,
  onChange,
  disabled,
}: {
  label: string
  checked: boolean
  onChange: (checked: boolean) => void
  disabled?: boolean
}) {
  return (
    <label className="flex items-center gap-2 text-sm">
      <Checkbox
        checked={checked}
        onCheckedChange={(value) => onChange(value === true)}
        disabled={disabled}
      />
      {label}
    </label>
  )
}
