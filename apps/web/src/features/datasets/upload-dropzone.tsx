import { FileUp, UploadCloud } from 'lucide-react'
import { useRef, useState } from 'react'

import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

import { MAX_CSV_MB, MAX_XLSX_MB, validateFile, type RejectedFile } from './upload-validation'

interface UploadDropzoneProps {
  onFiles: (files: File[]) => void
  onReject: (rejected: RejectedFile[]) => void
  disabled?: boolean
}

export function UploadDropzone({ onFiles, onReject, disabled }: UploadDropzoneProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)

  const handle = (list: FileList | null) => {
    if (!list) return
    const accepted: File[] = []
    const rejected: RejectedFile[] = []
    for (const file of Array.from(list)) {
      const reason = validateFile(file)
      if (reason) rejected.push({ file, reason })
      else accepted.push(file)
    }
    if (accepted.length) onFiles(accepted)
    if (rejected.length) onReject(rejected)
  }

  return (
    <div
      data-testid="dropzone"
      onDragOver={(event) => {
        event.preventDefault()
        if (!disabled) setDragging(true)
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(event) => {
        event.preventDefault()
        setDragging(false)
        if (!disabled) handle(event.dataTransfer.files)
      }}
      className={cn(
        'bg-grid relative flex flex-col items-center justify-center rounded-2xl border-2 border-dashed px-6 py-12 text-center transition-colors',
        dragging ? 'border-primary bg-primary/5' : 'border-border hover:border-primary/50',
        disabled && 'opacity-60',
      )}
    >
      <div className="mb-4 rounded-2xl bg-primary/10 p-4 text-primary ring-1 ring-primary/20">
        <UploadCloud className="size-8" aria-hidden />
      </div>
      <p className="text-base font-semibold">Arraste e solte seus arquivos CSV ou XLSX aqui</p>
      <p className="mt-1 text-sm text-muted-foreground">
        CSV até {MAX_CSV_MB} MB (encoding, delimitador e separador decimal detectados) · XLSX até{' '}
        {MAX_XLSX_MB} MB, com escolha da aba
      </p>
      <Button className="mt-5" onClick={() => inputRef.current?.click()} disabled={disabled}>
        <FileUp /> Selecionar arquivo
      </Button>
      <input
        ref={inputRef}
        type="file"
        accept=".csv,text/csv,.xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        multiple
        className="sr-only"
        aria-label="Selecionar arquivos CSV ou XLSX"
        tabIndex={-1}
        onChange={(event) => {
          handle(event.target.files)
          event.target.value = ''
        }}
      />
      <p className="mt-4 text-xs text-muted-foreground">
        Planilhas são lidas sem executar fórmulas ou macros. XLS, XLSM e arquivos protegidos por
        senha não são aceitos.
      </p>
    </div>
  )
}
