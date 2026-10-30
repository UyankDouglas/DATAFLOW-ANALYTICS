import type { DatasetStatus, JobStatus } from '@/types/api'

/** Códigos estáveis da API → rótulos em português. */
export const JOB_STATUS_LABEL: Record<JobStatus, string> = {
  queued: 'Aguardando',
  validating: 'Validando',
  processing: 'Processando',
  saving: 'Salvando',
  succeeded: 'Concluído',
  failed: 'Falhou',
  cancelled: 'Cancelado',
}

export const JOB_STAGES: JobStatus[] = ['queued', 'validating', 'processing', 'saving', 'succeeded']

export const ACTIVE_STATUSES: JobStatus[] = ['queued', 'validating', 'processing', 'saving']

export function isActive(status: JobStatus): boolean {
  return ACTIVE_STATUSES.includes(status)
}

export type Tone = 'neutral' | 'info' | 'primary' | 'success' | 'warning' | 'danger'

export const JOB_STATUS_TONE: Record<JobStatus, Tone> = {
  queued: 'neutral',
  validating: 'info',
  processing: 'primary',
  saving: 'info',
  succeeded: 'success',
  failed: 'danger',
  cancelled: 'warning',
}

export const DATASET_STATUS_LABEL: Record<DatasetStatus, string> = {
  draft: 'Aguardando configuração',
  processing: 'Processando',
  ready: 'Pronto',
  failed: 'Falhou',
}

export const DATASET_STATUS_TONE: Record<DatasetStatus, Tone> = {
  draft: 'neutral',
  processing: 'primary',
  ready: 'success',
  failed: 'danger',
}

export const REJECTION_LABEL: Record<string, string> = {
  tipo_invalido: 'Tipo inválido',
  casas_decimais_excedidas: 'Casas decimais excedidas',
  linha_vazia: 'Linha vazia',
  campos_a_menos: 'Campos a menos',
  campos_a_mais: 'Campos a mais',
  csv_malformado: 'CSV malformado',
}

export const TIMING_LABEL: Record<string, string> = {
  upload: 'Envio do arquivo',
  download_validate: 'Leitura e validação',
  processing: 'Processamento total',
  processing_read: 'Leitura (tokenização)',
  processing_transform: 'Conversão de tipos',
  processing_write: 'Escrita Parquet',
  persist_upload: 'Persistência',
  total: 'Tempo total do job',
}
