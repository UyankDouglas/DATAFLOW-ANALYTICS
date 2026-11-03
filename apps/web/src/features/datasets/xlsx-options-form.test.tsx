import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { ParseOptions, SheetInfo } from '@/types/api'

import { XlsxOptionsForm } from './xlsx-options-form'

const options: ParseOptions = {
  encoding: 'utf-8',
  delimiter: ',',
  has_header: true,
  decimal_separator: '.',
  thousands_separator: '',
  null_values: ['', 'NULL'],
  sheet: 'Vendas',
  header_row: 3,
}
const sheets: SheetInfo[] = [
  { name: 'Vendas', hidden: false, declared_rows: 7, declared_columns: 5 },
  { name: 'Metas', hidden: true, declared_rows: 5, declared_columns: 3 },
]

describe('XlsxOptionsForm', () => {
  it('aplica a linha do cabeçalho informada e valida o intervalo', async () => {
    const onApply = vi.fn()
    render(<XlsxOptionsForm value={options} sheets={sheets} dataRange="A3:E7" onApply={onApply} />)
    expect(screen.getByText('Intervalo de dados detectado: A3:E7')).toBeInTheDocument()

    const row = screen.getByLabelText('Linha do cabeçalho')
    await userEvent.clear(row)
    await userEvent.type(row, '2000')
    expect(screen.getByText('Informe uma linha entre 1 e 1000.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Aplicar e recarregar/ })).toBeDisabled()

    await userEvent.clear(row)
    await userEvent.type(row, '4')
    await userEvent.click(screen.getByRole('button', { name: /Aplicar e recarregar/ }))
    expect(onApply).toHaveBeenCalledWith(
      expect.objectContaining({ sheet: 'Vendas', header_row: 4, null_values: ['', 'NULL'] }),
    )
  })

  it('oferece importar as outras abas como novos datasets', async () => {
    const onImportSheet = vi.fn()
    render(
      <XlsxOptionsForm
        value={options}
        sheets={sheets}
        dataRange="A3:E7"
        onApply={vi.fn()}
        onImportSheet={onImportSheet}
      />,
    )
    await userEvent.click(
      screen.getByRole('button', { name: 'Importar a aba Metas como novo dataset' }),
    )
    expect(onImportSheet).toHaveBeenCalledWith('Metas')
    expect(
      screen.queryByRole('button', { name: 'Importar a aba Vendas como novo dataset' }),
    ).not.toBeInTheDocument()
  })
})
