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
  /** Somente XLSX: aba lida e linha do cabeçalho (null = detectar automaticamente). */
  sheet?: string | null
  header_row?: number | null
}

export interface SheetInfo {
  name: string
  hidden: boolean
  declared_rows: number | null
  declared_columns: number | null
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
    format?: 'xlsx'
    sheets?: SheetInfo[]
    default_sheet?: string
    header_row?: number
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
  scale: number | null
  required: boolean
  fill_value: string | null
}

export interface ColumnSchema {
  name: string
  /** Nulo em versões transformadas (a coluna pode ter sido renomeada ou derivada). */
  source_name: string | null
  position: number
  data_type: DataType
  format: string | null
  scale: number | null
  required?: boolean
  null_count: number
}

export interface Reconciliation {
  received: number
  valid: number
  rejected: number
  /** Ausente em versões da Fase 1 (sem filtros). */
  filtered?: number
  duplicates: number | null
  duplicates_policy: 'nao_aplicada' | 'removidos_dos_validos' | string
  consistent: boolean
}

export interface VersionLineage {
  kind?: 'import' | 'transform'
  source_format?: string
  parse_options?: ParseOptions
  source_version_id?: Uuid
  source_version_number?: number
  transformation_set?: { id: Uuid; name: string; revision: number } | null
  steps?: Rule[]
}

export interface DatasetVersion {
  id: Uuid
  version_number: number
  status: string
  job_id: Uuid
  upload_id: Uuid
  created_by_id: Uuid | null
  created_by_name: string | null
  parent_version_id: Uuid | null
  parent_version_number: number | null
  transformation_set_id: Uuid | null
  row_count: number
  rejected_count: number
  filtered_count: number
  duplicate_count: number | null
  size_bytes: number
  column_schema: ColumnSchema[]
  transformations: VersionLineage
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
  source_format: 'csv' | 'xlsx'
  sheets: SheetInfo[]
  data_range: string | null
  first_column: number | null
  cell_issues_in_sample: number
}

export interface ColumnConfig {
  position: number
  source_name: string
  name: string
  data_type: DataType
  format: string | null
  scale: number | null
  required: boolean
  /** Valor usado quando a célula vier vazia (texto canônico: 2025-01-31, 10.5, true). */
  fill_value: string | null
}

export interface ImportRequest {
  parse_options: ParseOptions
  columns: ColumnConfig[]
  confirm_ambiguous_formats: boolean
}

export type ExclusionCategory = 'rejeitado' | 'filtrado' | 'duplicado'

export interface RejectionSample {
  row: number
  line: number | null
  reason: string
  column: string | null
  detail: string
  category?: ExclusionCategory
  rule?: number | null
  duplicate_of?: number | null
}

export type JobKind = 'import' | 'transform'

export interface Job {
  id: Uuid
  dataset_id: Uuid
  dataset_name: string | null
  upload_id: Uuid
  upload_filename: string | null
  kind: JobKind
  source_version_id: Uuid | null
  source_version_number: number | null
  transformation_set_id: Uuid | null
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
  rows_filtered: number | null
  /** null = deduplicação não aplicada neste job. */
  rows_duplicates: number | null
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
  config: {
    parse_options?: ParseOptions
    columns?: ColumnConfig[]
    source_format?: string
    source_version_number?: number
    transformation_set?: { id: Uuid; name: string; revision: number }
    rules?: Rule[]
  }
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

// ---------------------------------------------------------------- transformações

export type RuleOperation =
  | 'trim'
  | 'normalize_text'
  | 'change_case'
  | 'convert_type'
  | 'standardize_dates'
  | 'fix_numbers'
  | 'handle_nulls'
  | 'remove_empty_rows'
  | 'filter_rows'
  | 'rename_columns'
  | 'derived_column'
  | 'deduplicate'

export type FilterOperator =
  | 'eq'
  | 'ne'
  | 'gt'
  | 'gte'
  | 'lt'
  | 'lte'
  | 'between'
  | 'contains'
  | 'not_contains'
  | 'starts_with'
  | 'ends_with'
  | 'in'
  | 'not_in'
  | 'is_null'
  | 'not_null'
  | 'is_true'
  | 'is_false'

export interface Condition {
  column: string
  operator: FilterOperator
  value?: string | null
  value_to?: string | null
  values?: string[] | null
  case_insensitive?: boolean
}

export interface Operand {
  column?: string | null
  value?: string | null
}

export type Expression =
  | {
      kind: 'arithmetic'
      operator: 'add' | 'subtract' | 'multiply' | 'divide'
      left: Operand
      right: Operand
      scale: number
    }
  | { kind: 'concat'; parts: Operand[]; separator: string }
  | {
      kind: 'date_part'
      column: string
      part: 'year' | 'month' | 'day' | 'quarter' | 'weekday' | 'year_month'
    }
  | { kind: 'date_diff_days'; start: string; end: string }

interface RuleBase {
  enabled: boolean
}

export type Rule = RuleBase &
  (
    | { operation: 'trim'; columns: string[]; collapse_internal?: boolean }
    | {
        operation: 'normalize_text'
        columns: string[]
        remove_accents?: boolean
        form?: 'NFC' | 'NFKC'
      }
    | { operation: 'change_case'; columns: string[]; mode: 'upper' | 'lower' | 'title' }
    | {
        operation: 'convert_type'
        column: string
        target: DataType
        format?: string | null
        scale?: number | null
        decimal_separator?: '.' | ','
        thousands_separator?: '' | '.' | ',' | ' '
      }
    | {
        operation: 'standardize_dates'
        column: string
        target: 'date' | 'datetime'
        formats: string[]
      }
    | {
        operation: 'fix_numbers'
        column: string
        target: 'integer' | 'decimal'
        scale?: number | null
        decimal_separator: '.' | ','
        thousands_separator: '' | '.' | ',' | ' '
        strip_currency?: boolean
        parentheses_negative?: boolean
      }
    | {
        operation: 'handle_nulls'
        columns: string[]
        strategy: 'fill' | 'reject'
        fill_value?: string | null
      }
    | { operation: 'remove_empty_rows' }
    | { operation: 'filter_rows'; conditions: Condition[]; match: 'all' | 'any' }
    | { operation: 'rename_columns'; mapping: Record<string, string> }
    | { operation: 'derived_column'; name: string; expression: Expression }
    | { operation: 'deduplicate'; columns: string[]; keep: 'first' | 'last' }
  )

export interface TransformationSet {
  id: Uuid
  dataset_id: Uuid
  name: string
  description: string | null
  revision: number
  rules: Rule[]
  created_by_name: string | null
  updated_by_name: string | null
  created_at: string
  updated_at: string
}

export interface TransformationSetInput {
  name: string
  description: string | null
  rules: Rule[]
}

export interface ColumnSpec {
  name: string
  data_type: DataType
  format?: string | null
  scale?: number | null
}

export interface TransformPreview {
  source_version_id: Uuid
  source_version_number: number
  source_row_count: number
  sample_size: number
  sample_is_complete: boolean
  input_columns: ColumnSpec[]
  output_columns: ColumnSpec[]
  rows: { row: number; values: unknown[] }[]
  excluded: {
    row: number
    reason: string
    category: ExclusionCategory
    column: string | null
    detail: string | null
    rule: number | null
    duplicate_of: number | null
  }[]
  counts: {
    received: number
    valid: number
    rejected: number
    filtered: number
    duplicates: number | null
  }
  reasons: Record<string, number>
}

export interface DuplicateAnalysis {
  version_id: Uuid
  version_number: number
  columns: string[]
  keep: 'first' | 'last'
  total_rows: number
  distinct_keys: number
  duplicate_rows: number
  rows_after: number
  groups_with_duplicates: number
  top_groups: { key: unknown[]; count: number; kept_row: number; sample_rows: number[] }[]
}
