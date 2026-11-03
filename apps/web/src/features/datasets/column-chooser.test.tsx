import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'

import type { DataType } from '@/types/api'

import { ColumnChooser } from './column-chooser'

const columns: { name: string; data_type: DataType }[] = [
  { name: 'data', data_type: 'date' },
  { name: 'vendedor', data_type: 'text' },
  { name: 'valor', data_type: 'decimal' },
]

function Harness({ onChange }: { onChange: (value: string[]) => void }) {
  const [value, setValue] = useState(columns.map((c) => c.name))
  return (
    <ColumnChooser
      columns={columns}
      value={value}
      onChange={(next) => {
        setValue(next)
        onChange(next)
      }}
    />
  )
}

describe('ColumnChooser', () => {
  it('oculta, reexibe no fim e reordena as colunas visíveis', async () => {
    const onChange = vi.fn()
    render(<Harness onChange={onChange} />)
    await userEvent.click(screen.getByRole('checkbox', { name: 'Mostrar vendedor' }))
    expect(onChange).toHaveBeenLastCalledWith(['data', 'valor'])

    await userEvent.click(screen.getByRole('button', { name: 'Mover valor para a esquerda' }))
    expect(onChange).toHaveBeenLastCalledWith(['valor', 'data'])

    await userEvent.click(screen.getByRole('checkbox', { name: 'Mostrar vendedor' }))
    expect(onChange).toHaveBeenLastCalledWith(['valor', 'data', 'vendedor'])

    await userEvent.click(screen.getByRole('button', { name: 'Mostrar todas na ordem original' }))
    expect(onChange).toHaveBeenLastCalledWith(['data', 'vendedor', 'valor'])
  })

  it('não deixa ocultar a última coluna visível', async () => {
    render(<ColumnChooser columns={columns} value={['valor']} onChange={vi.fn()} />)
    expect(screen.getByRole('checkbox', { name: 'Mostrar valor' })).toBeDisabled()
  })
})
