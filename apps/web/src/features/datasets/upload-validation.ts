/** Validação prévia no navegador. O servidor revalida extensão, conteúdo real e tamanho. */
export const MAX_CSV_MB = 100

export interface RejectedFile {
  file: File
  reason: string
}

export function validateFile(file: File, maxMb = MAX_CSV_MB): string | null {
  const name = file.name.toLowerCase()
  if (name.endsWith('.xlsx'))
    return 'Arquivos XLSX serão aceitos na próxima fase. Exporte a planilha como CSV UTF-8.'
  if (name.endsWith('.xls'))
    return 'O formato XLS não é suportado. Exporte a planilha como CSV UTF-8.'
  if (!name.endsWith('.csv')) return 'Formato não suportado. Envie um arquivo .csv.'
  if (file.size === 0) return 'O arquivo está vazio.'
  if (file.size > maxMb * 1024 * 1024) return `O arquivo excede o limite de ${maxMb} MB para CSV.`
  return null
}
