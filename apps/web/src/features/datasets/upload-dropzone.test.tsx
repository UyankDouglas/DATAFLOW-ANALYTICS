import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { UploadDropzone } from './upload-dropzone'

const csv = (name: string, content = 'a,b\n1,2\n') =>
  new File([content], name, { type: 'text/csv' })

describe('UploadDropzone', () => {
  it('aceita CSV pelo seletor de arquivos', async () => {
    const onFiles = vi.fn()
    const onReject = vi.fn()
    render(<UploadDropzone onFiles={onFiles} onReject={onReject} />)
    await userEvent.upload(screen.getByLabelText('Selecionar arquivos CSV'), csv('vendas.csv'))
    expect(onFiles).toHaveBeenCalledWith([expect.objectContaining({ name: 'vendas.csv' })])
    expect(onReject).not.toHaveBeenCalled()
  })

  it('recusa XLSX (fase futura), formatos desconhecidos e arquivos vazios com motivo', () => {
    const onFiles = vi.fn()
    const onReject = vi.fn()
    render(<UploadDropzone onFiles={onFiles} onReject={onReject} />)
    fireEvent.drop(screen.getByTestId('dropzone'), {
      dataTransfer: { files: [csv('planilha.xlsx'), csv('foto.png'), csv('vazio.csv', '')] },
    })
    expect(onFiles).not.toHaveBeenCalled()
    const reasons = (onReject.mock.calls[0]?.[0] as { reason: string }[]).map((r) => r.reason)
    expect(reasons[0]).toMatch(/XLSX serão aceitos na próxima fase/)
    expect(reasons[1]).toMatch(/Formato não suportado/)
    expect(reasons[2]).toBe('O arquivo está vazio.')
  })
})
