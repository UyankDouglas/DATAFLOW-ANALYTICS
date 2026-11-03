import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { UploadDropzone } from './upload-dropzone'

const csv = (name: string, content = 'a,b\n1,2\n') =>
  new File([content], name, { type: 'text/csv' })
const sized = (name: string, megabytes: number) => {
  const file = new File(['x'], name)
  Object.defineProperty(file, 'size', { value: megabytes * 1024 * 1024 + 1 })
  return file
}

describe('UploadDropzone', () => {
  it('aceita CSV e XLSX pelo seletor de arquivos', async () => {
    const onFiles = vi.fn()
    const onReject = vi.fn()
    render(<UploadDropzone onFiles={onFiles} onReject={onReject} />)
    await userEvent.upload(screen.getByLabelText('Selecionar arquivos CSV ou XLSX'), [
      csv('vendas.csv'),
      csv('planilha.xlsx'),
    ])
    expect(onFiles).toHaveBeenCalledWith([
      expect.objectContaining({ name: 'vendas.csv' }),
      expect.objectContaining({ name: 'planilha.xlsx' }),
    ])
    expect(onReject).not.toHaveBeenCalled()
  })

  it('recusa formatos legados, com macros, desconhecidos e vazios com motivo', () => {
    const onFiles = vi.fn()
    const onReject = vi.fn()
    render(<UploadDropzone onFiles={onFiles} onReject={onReject} />)
    fireEvent.drop(screen.getByTestId('dropzone'), {
      dataTransfer: {
        files: [csv('antiga.xls'), csv('macro.xlsm'), csv('foto.png'), csv('vazio.csv', '')],
      },
    })
    expect(onFiles).not.toHaveBeenCalled()
    const reasons = (onReject.mock.calls[0]?.[0] as { reason: string }[]).map((r) => r.reason)
    expect(reasons[0]).toMatch(/XLS antigo não é aceito/)
    expect(reasons[1]).toMatch(/macros não são aceitas/)
    expect(reasons[2]).toMatch(/Formato não suportado/)
    expect(reasons[3]).toBe('O arquivo está vazio.')
  })

  it('aplica o limite de cada formato', () => {
    const onFiles = vi.fn()
    const onReject = vi.fn()
    render(<UploadDropzone onFiles={onFiles} onReject={onReject} />)
    fireEvent.drop(screen.getByTestId('dropzone'), {
      dataTransfer: { files: [sized('grande.xlsx', 25), sized('medio.csv', 25)] },
    })
    expect(onFiles).toHaveBeenCalledWith([expect.objectContaining({ name: 'medio.csv' })])
    const reasons = (onReject.mock.calls[0]?.[0] as { reason: string }[]).map((r) => r.reason)
    expect(reasons).toEqual(['O arquivo excede o limite de 25 MB para XLSX.'])
  })
})
