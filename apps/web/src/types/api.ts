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
  /** Original apagado pela política de retenção; as versões continuam. */
  purged_at?: string | null
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
  /** Nota de qualidade (0–100); nula quando o relatório ainda não foi calculado. */
  quality_score: number | null
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
  /** Registros que atendem aos filtros; sem filtros, todos os da versão. */
  total: number
  total_unfiltered: number | null
  page: number
  page_size: number
}

export interface RowsQuery {
  version_id?: Uuid
  page: number
  page_size: number
  sort?: string
  direction?: 'asc' | 'desc'
  columns?: string[]
  filters: Condition[]
  match: 'all' | 'any'
  search?: string
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

// ---------------------------------------------------------------- qualidade

export interface QualityComponents {
  validity: number | null
  completeness: number | null
  uniqueness: number | null
}

export interface QualityIndicators {
  received: number
  valid: number
  rejected: number
  filtered: number
  duplicates_removed: number | null
  duplicates_remaining: number
  null_cells: number
  total_cells: number
  completeness: number | null
  columns_with_issues: number
  rules_violated: number
  violations: number
}

export interface QualityColumnProfile {
  name: string
  data_type: DataType
  non_null: number
  nulls: number
  completeness: number | null
  distinct: number
  min: unknown
  max: unknown
  issues: number
}

export interface QualityIssue {
  category: ExclusionCategory
  reason: string
  column: string | null
  rule: number | null
  rule_label: string
  count: number
  example_row: number | null
}

export interface QualityReport {
  id: Uuid
  dataset_id: Uuid
  version_id: Uuid
  version_number: number
  formula_version: string
  score: number | null
  metrics: {
    formula: { version: string; weights: Record<keyof QualityComponents, number> }
    components: QualityComponents
    indicators: QualityIndicators
    columns: QualityColumnProfile[]
    null_distribution: { nulls: number; rows: number }[]
    issue_groups_total: number
  }
  issues: QualityIssue[]
  computed_by_name: string | null
  computed_at: string
  duration_ms: number
}

export interface QualityVersionSummary {
  version_id: Uuid
  version_number: number
  parent_version_number: number | null
  kind: string
  created_at: string
  computed: boolean
  score: number | null
  indicators: Partial<QualityIndicators>
  components: Partial<QualityComponents>
}

export interface InconsistencyRow {
  row: number
  line: number | null
  category: ExclusionCategory
  reason: string
  column: string | null
  original_value: string | null
  rule: number | null
  rule_label: string
  treatment: string
  detail: string | null
  duplicate_of: number | null
  record: Record<string, string | null>
}

export interface InconsistencyPage {
  version_id: Uuid
  items: InconsistencyRow[]
  total: number
  page: number
  page_size: number
}

export interface ValueFrequency {
  column: string
  data_type: DataType
  total: number
  nulls: number
  distinct: number
  values: { value: unknown; count: number }[]
  others: number
}

// ---------------------------------------------------------------- Fase 4: BI

export type Aggregation = 'count' | 'count_distinct' | 'sum' | 'avg' | 'min' | 'max'
export type Granularity = 'day' | 'week' | 'month' | 'quarter' | 'year'
export type ChartType =
  'kpi' | 'line' | 'bar' | 'bar_horizontal' | 'area' | 'pie' | 'donut' | 'table'
export type WidgetSize = 'small' | 'medium' | 'large'

export interface Metric {
  aggregation: Aggregation
  /** Sem coluna, "count" conta registros. */
  column?: string | null
}

export interface Dimension {
  column: string
  granularity?: Granularity | null
}

export interface PeriodComparison {
  column: string
  start: string
  end: string
  mode?: 'previous_period' | 'previous_year'
}

/** Consulta analítica: o que calcular, sem SQL — colunas e operações de listas fechadas. */
export interface AggregateSpec {
  metrics: Metric[]
  dimension?: Dimension | null
  filters?: Condition[]
  match?: 'all' | 'any'
  sort?: 'metric' | 'dimension' | null
  direction?: 'asc' | 'desc' | null
  limit?: number
  comparison?: PeriodComparison | null
}

export interface AnalyticsQuery extends AggregateSpec {
  version_id?: Uuid | null
  /** Grupos combinados com E aos filtros da consulta, cada um com o próprio E/OU. */
  extra_filters?: FilterSet[]
}

export interface MetricInfo {
  key: string
  aggregation: Aggregation
  column: string | null
  label: string
  /** Tipo do resultado (contagens são inteiras; a média é decimal). */
  data_type: DataType
  scale: number | null
}

export interface AggregateResult {
  version_id: Uuid
  version_number: number
  metrics: MetricInfo[]
  dimension: { column: string; data_type: DataType; granularity: Granularity | null } | null
  rows: { key: unknown; values: unknown[]; previous: unknown[] | null }[]
  matched_rows: number
  total_groups: number | null
  others: { groups: number; values: unknown[]; previous: unknown[] | null } | null
  comparison: {
    column: string
    mode: 'previous_period' | 'previous_year'
    current_start: string
    current_end: string
    previous_start: string
    previous_end: string
    previous_rows: number
  } | null
  duration_ms: number
}

export interface FilterSet {
  filters: Condition[]
  match: 'all' | 'any'
}

export interface WidgetConfig {
  /** Ausente em widgets ainda não salvos. */
  id?: Uuid | null
  title: string
  chart_type: ChartType
  size: WidgetSize
  query: AggregateSpec
}

export interface DashboardWidget extends WidgetConfig {
  id: Uuid
  position: number
}

export interface Dashboard {
  id: Uuid
  name: string
  description: string | null
  dataset_id: Uuid
  dataset_name: string
  /** Versão fixada; nula = acompanha a versão atual do dataset. */
  version_id: Uuid | null
  version_number: number | null
  resolved_version_id: Uuid | null
  resolved_version_number: number | null
  filters: FilterSet
  widgets: DashboardWidget[]
  created_by_name: string | null
  updated_by_name: string | null
  created_at: string
  updated_at: string
}

export interface DashboardSummary {
  id: Uuid
  name: string
  description: string | null
  dataset_id: Uuid
  dataset_name: string
  version_id: Uuid | null
  version_number: number | null
  widget_count: number
  chart_types: ChartType[]
  updated_by_name: string | null
  updated_at: string
}

export interface DashboardInput {
  name: string
  description?: string | null
  dataset_id: Uuid
  version_id?: Uuid | null
  filters: FilterSet
  widgets: WidgetConfig[]
}

export interface WidgetResult {
  widget_id: Uuid
  result: AggregateResult
}

// ---------------------------------------------------------------- Fase 5: exportações e administração

export type ExportStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'expired'
export type ExportFormat = 'csv' | 'xlsx'
export type CsvStyle = 'padrao' | 'excel_br'

export interface RowsExportQuery {
  filters?: Condition[]
  match?: 'all' | 'any'
  search?: string | null
  columns?: string[] | null
  sort?: string | null
  direction?: 'asc' | 'desc'
  /** Grupos de filtros da tela, combinados com E aos filtros acima. */
  extra_filters?: FilterSet[]
}

export interface ExportRequest {
  dataset_id: Uuid
  version_id?: Uuid | null
  kind: 'rows' | 'report'
  format: ExportFormat
  csv_style?: CsvStyle
  rows?: RowsExportQuery
  report?: AggregateSpec & { extra_filters?: FilterSet[] }
}

export interface ExportJob {
  id: Uuid
  dataset_id: Uuid
  dataset_name: string
  version_id: Uuid
  version_number: number
  kind: 'rows' | 'report'
  format: ExportFormat
  status: ExportStatus
  file_name: string
  params: {
    csv_style?: CsvStyle
    rows?: RowsExportQuery | null
    report?: AggregateSpec | null
    estimated_rows?: number | null
  }
  estimated_rows: number | null
  row_count: number | null
  size_bytes: number | null
  error_code: string | null
  error_message: string | null
  created_by_name: string | null
  created_at: string
  started_at: string | null
  finished_at: string | null
  expires_at: string | null
  duration_ms: number | null
  download_count: number
}

export interface WorkspaceSettings {
  export_ttl_hours: number
  viewer_exports: boolean
  original_retention_days: number | null
}

export interface WorkspaceSettingsInfo {
  id: Uuid
  name: string
  slug: string
  settings: WorkspaceSettings
}

export interface Invitation {
  id: Uuid
  email: string
  role: Role
  invited_by_name: string | null
  created_at: string
  expires_at: string
}

export interface InvitationPreview {
  workspace_name: string
  role: Role
  email: string
  expires_at: string
}

export interface AuditEntry {
  id: Uuid
  action: string
  entity_type: string | null
  entity_id: string | null
  details: Record<string, unknown>
  actor_id: Uuid | null
  actor_name: string | null
  ip_address: string | null
  created_at: string
}

export interface DashboardRef {
  id: Uuid
  name: string
}

export interface DatasetImpact {
  dataset_id: Uuid
  dataset_name: string
  versions: number
  uploads: number
  jobs: number
  exports: number
  stored_bytes: number
  dashboards: DashboardRef[]
  blocked_reason: string | null
}

export interface VersionImpact {
  version_id: Uuid
  version_number: number
  is_current: boolean
  next_current_number: number | null
  derived_versions: number
  exports: number
  stored_bytes: number
  pinned_by: DashboardRef[]
  blocked_reason: string | null
}
