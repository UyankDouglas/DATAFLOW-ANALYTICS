import { api } from '@/services/api-client'
import type {
  DuplicateAnalysis,
  Job,
  Rule,
  TransformationSet,
  TransformationSetInput,
  TransformPreview,
} from '@/types/api'

export const transformationsApi = {
  listSets: (datasetId: string) =>
    api<TransformationSet[]>(`/datasets/${datasetId}/transformation-sets`),
  createSet: (datasetId: string, body: TransformationSetInput) =>
    api<TransformationSet>(`/datasets/${datasetId}/transformation-sets`, {
      method: 'POST',
      body,
    }),
  updateSet: (datasetId: string, setId: string, body: TransformationSetInput) =>
    api<TransformationSet>(`/datasets/${datasetId}/transformation-sets/${setId}`, {
      method: 'PUT',
      body,
    }),
  deleteSet: (datasetId: string, setId: string) =>
    api<void>(`/datasets/${datasetId}/transformation-sets/${setId}`, { method: 'DELETE' }),
  preview: (datasetId: string, sourceVersionId: string, rules: Rule[]) =>
    api<TransformPreview>(`/datasets/${datasetId}/transformations/preview`, {
      method: 'POST',
      body: { source_version_id: sourceVersionId, rules },
    }),
  duplicates: (
    datasetId: string,
    versionId: string,
    body: { columns: string[]; keep: 'first' | 'last' },
  ) =>
    api<DuplicateAnalysis>(`/datasets/${datasetId}/versions/${versionId}/duplicates`, {
      method: 'POST',
      body,
    }),
  apply: (datasetId: string, sourceVersionId: string, setId: string, idempotencyKey: string) =>
    api<Job>(`/datasets/${datasetId}/transform-jobs`, {
      method: 'POST',
      body: { source_version_id: sourceVersionId, transformation_set_id: setId },
      headers: { 'Idempotency-Key': idempotencyKey },
    }),
}
