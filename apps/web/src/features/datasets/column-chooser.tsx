import { ArrowDown, ArrowUp } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import type { DataType } from '@/types/api'

import { DATA_TYPE_LABEL } from './column-form'

interface ColumnChooserProps {
  columns: { name: string; data_type: DataType }[]
  /** Colunas visíveis, na ordem de exibição. */
  value: string[]
  onChange: (value: string[]) => void
}

/** Mostra visíveis (na ordem escolhida) e ocultas; reordena só as visíveis. */
export function ColumnChooser({ columns, value, onChange }: ColumnChooserProps) {
  const byName = new Map(columns.map((column) => [column.name, column]))
  const visible = value.filter((name) => byName.has(name))
  const hidden = columns.filter((column) => !visible.includes(column.name))
  const move = (index: number, delta: -1 | 1) => {
    const target = index + delta
    if (target < 0 || target >= visible.length) return
    const next = [...visible]
    const [moved] = next.splice(index, 1)
    if (moved) next.splice(target, 0, moved)
    onChange(next)
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        <Button variant="outline" size="sm" onClick={() => onChange(columns.map((c) => c.name))}>
          Mostrar todas na ordem original
        </Button>
      </div>
      <ul className="max-h-72 space-y-1 overflow-y-auto rounded-md border p-2" aria-label="Colunas">
        {visible.map((name, index) => (
          <li key={name} className="flex items-center gap-2 text-sm">
            <Checkbox
              checked
              aria-label={`Mostrar ${name}`}
              disabled={visible.length === 1}
              onCheckedChange={() => onChange(visible.filter((n) => n !== name))}
            />
            <span className="min-w-0 flex-1 truncate">{name}</span>
            <span className="text-xs text-muted-foreground">
              {DATA_TYPE_LABEL[byName.get(name)?.data_type ?? 'text']}
            </span>
            <Button
              variant="ghost"
              size="icon"
              className="size-7"
              aria-label={`Mover ${name} para a esquerda`}
              onClick={() => move(index, -1)}
              disabled={index === 0}
            >
              <ArrowUp />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className="size-7"
              aria-label={`Mover ${name} para a direita`}
              onClick={() => move(index, 1)}
              disabled={index === visible.length - 1}
            >
              <ArrowDown />
            </Button>
          </li>
        ))}
        {hidden.map((column) => (
          <li key={column.name} className="flex items-center gap-2 text-sm text-muted-foreground">
            <Checkbox
              checked={false}
              aria-label={`Mostrar ${column.name}`}
              onCheckedChange={() => onChange([...visible, column.name])}
            />
            <span className="min-w-0 flex-1 truncate">{column.name}</span>
            <span className="text-xs">{DATA_TYPE_LABEL[column.data_type]}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}
