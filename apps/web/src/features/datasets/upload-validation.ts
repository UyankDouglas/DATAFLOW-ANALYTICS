/** Validação prévia no navegador. O servidor revalida extensão, conteúdo real e tamanho. */
export const MAX_CSV_MB = 100
export const MAX_XLSX_MB = 25

export interface RejectedFile {
  file: File
  reason: string
}

const UNSUPPORTED: Record<string, string> = {
  '.xls': 'O formato XLS antigo não é aceito. Salve a planilha como .xlsx ou CSV UTF-8.',
  '.xlsm': 'Planilhas com macros não são aceitas. Salve como .xlsx (sem macros) ou CSV UTF-8.',
  '.xlsb': 'O formato XLSB não é aceito. Salve a planilha como .xlsx ou CSV UTF-8.',
}

export function fileFormat(name: string): 'csv' | 'xlsx' | null {
  const lower = name.toLowerCase()
  if (lower.endsWith('.csv')) return 'csv'
  if (lower.endsWith('.xlsx')) return 'xlsx'
  return null
}

export function validateFile(file: File): string | null {
  const name = file.name.toLowerCase()
  const legacy = Object.keys(UNSUPPORTED).find((extension) => name.endsWith(extension))
  if (legacy) return UNSUPPORTED[legacy] ?? null
  const format = fileFormat(name)
  if (!format) return 'Formato não suportado. Envie um arquivo .csv ou .xlsx.'
  if (file.size === 0) return 'O arquivo está vazio.'
  const maxMb = format === 'xlsx' ? MAX_XLSX_MB : MAX_CSV_MB
  if (file.size > maxMb * 1024 * 1024) {
    return `O arquivo excede o limite de ${maxMb} MB para ${format.toUpperCase()}.`
  }
  return null
}
