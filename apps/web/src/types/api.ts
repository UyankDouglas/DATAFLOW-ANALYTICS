/** Tipos espelhando os schemas da API (/api/openapi.json). */

export type Uuid = string

export interface ApiErrorBody {
  error: { code: string; message: string; details: unknown }
  request_id: string | null
}

export interface Page<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export type Role = 'admin' | 'analyst' | 'viewer'

export interface User {
  id: Uuid
  email: string
  full_name: string
  created_at: string
}

export interface WorkspaceRef {
  id: Uuid
  name: string
  slug: string
  role: Role
}

export interface Me {
  user: User
  workspace: WorkspaceRef | null
  permissions: string[]
  csrf_token: string
}

export interface Member {
  id: Uuid
  user_id: Uuid
  full_name: string
  email: string
  role: Role
  joined_at: string
}

export type DataType = 'text' | 'integer' | 'decimal' | 'date' | 'datetime' | 'boolean'
export type DatasetStatus = 'draft' | 'processing' | 'ready' | 'failed'
export type JobStatus =
  'queued' | 'validating' | 'processing' | 'saving' | 'succeeded' | 'failed' | 'cancelled'

export interface ParseOptions {
  encoding: 'utf-8' | 'windows-1252' | 'iso-8859-1'
  delimiter: ',' | ';' | '\t' | '|'
  has_header: boolean
  decimal_separator: '.' | ','
  thousands_separator: '' | '.' | ',' | ' '
  null_values: string[]
}

export interface UploadInfo {
  id: Uuid
  original_filename: string
  file_format: string
  size_bytes: number
  sha256: string
  detection: {
    utf8_valid?: boolean
    has_bom?: boolean
    encoding?: string | null
    suggested_encoding?: string
    delimiter?: string
    line_count?: number
  }
  upload_ms: number | null
  created_at: string
}

export interface Dataset {
  id: Uuid
  name: string
  description: string | null
  status: DatasetStatus
  source_format: string
  current_version_id: Uuid | null
  created_by_id: Uuid | null
  created_at: string
  updated_at: string
}

export interface DatasetListItem extends Dataset {
  current_version_number: number | null
  row_count: number | null
  latest_upload: UploadInfo | null
  latest_job_id: Uuid | null
  latest_job_status: JobStatus | null
}

export interface DatasetColumn {
  position: number
  source_name: string
  name: string
  data_type: DataType
  inferred_type: DataType | null
  format: string | null
}

export interface ColumnSchema {
  name: string
  source_name: string
  position: number
  data_type: DataType
  format: string | null
  scale: number | null
  null_count: number
}

export interface Reconciliation {
  received: number
  valid: number
  rejected: number
  duplicates: number | null
  duplicates_policy: string
  consistent: boolean
}

export interface DatasetVersion {
  id: Uuid
  version_number: number
  status: string
  job_id: Uuid
  upload_id: Uuid
  created_by_id: Uuid | null
  created_by_name: string | null
  row_count: number
  rejected_count: number
  size_bytes: number
  column_schema: ColumnSchema[]
  reconciliation: Reconciliation
  rules_version: string
  created_at: string
}

export interface DatasetDetail extends Dataset {
  parse_options: ParseOptions
  columns: DatasetColumn[]
  latest_upload: UploadInfo | null
  current_version: DatasetVersion | null
}

export interface UploadResponse {
  dataset: Dataset
  upload: UploadInfo
}

export interface ColumnPreview {
  position: number
  source_name: string
  inferred_type: DataType
  format: string | null
  scale: number | null
  ambiguous_formats: string[]
  null_count: number
  null_ratio: number
  distinct_count: number
  is_empty: boolean
  warnings: string[]
}

export interface Preview {
  dataset_id: Uuid
  dataset_name: string
  upload: UploadInfo
  parse_options: ParseOptions
  suggested_options: ParseOptions
  header: string[]
  rows: string[][]
  columns: ColumnPreview[]
  column_count: number
  row_count: { value: number; exact: boolean; method: string }
  sample_rows_analyzed: number
  sample_truncated: boolean
  ragged_rows_in_sample: number
  empty_rows_in_sample: number
  duplicate_header_names: string[]
  warnings: string[]
  saved_columns: DatasetColumn[]
}

export interface ColumnConfig {
  position: number
  source_name: string
  name: string
  data_type: DataType
  format: string | null
  scale: number | null
}

export interface ImportRequest {
  parse_options: ParseOptions
  columns: ColumnConfig[]
  confirm_ambiguous_formats: boolean
}

export interface RejectionSample {
  row: number
  line: number
  reason: string
  column: string | null
  detail: string
}

export interface Job {
  id: Uuid
  dataset_id: Uuid
  dataset_name: string | null
  upload_id: Uuid
  upload_filename: string | null
  kind: string
  status: JobStatus
  created_by_id: Uuid | null
  created_by_name: string | null
  attempts: number
  max_attempts: number
  cancel_requested: boolean
  bytes_total: number | null
  bytes_processed: number
  progress_percent: number | null
  rows_processed: number
  rows_total: number | null
  rows_valid: number | null
  rows_rejected: number | null
  error_code: string | null
  error_message: string | null
  warnings: { at: string; message: string }[]
  rejection_summary: {
    by_reason?: Record<string, number>
    by_column?: Record<string, number>
    samples?: RejectionSample[]
  }
  metrics: {
    timings_ms?: Record<string, number | null>
    peak_memory_mb?: number | null
    rows_per_second?: number
  }
  config: { parse_options?: ParseOptions; columns?: ColumnConfig[] }
  rules_version: string
  result_version_id: Uuid | null
  result_version_number: number | null
  queued_at: string
  started_at: string | null
  heartbeat_at: string | null
  finished_at: string | null
  created_at: string
  updated_at: string
}

export interface Overview {
  datasets_total: number
  datasets_ready: number
  versions_total: number
  rows_published: number
  jobs_running: number
  jobs_failed_7d: number
  jobs_succeeded_7d: number
  rows_rejected_7d: number
  jobs_by_day: { date: string; succeeded: number; failed: number; other: number; rows: number }[]
  recent_jobs: Job[]
}

export interface RowsResponse {
  version_id: Uuid
  version_number: number
  columns: { name: string; data_type: DataType; format: string | null; scale: number | null }[]
  rows: unknown[][]
  total: number
  page: number
  page_size: number
}

export interface RejectedRowsResponse {
  version_id: Uuid
  columns: string[]
  rows: unknown[][]
  total: number
  page: number
  page_size: number
}

export interface WorkspaceSummary {
  id: Uuid
  name: string
  slug: string
  role: Role
}
