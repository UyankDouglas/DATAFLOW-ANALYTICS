import { api } from '@/services/api-client'
import type {
  AuditEntry,
  DatasetImpact,
  ExportJob,
  ExportRequest,
  Invitation,
  InvitationPreview,
  Page,
  Role,
  VersionImpact,
  WorkspaceSettings,
  WorkspaceSettingsInfo,
} from '@/types/api'

function query(params: Record<string, string | number | boolean | undefined | null>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== '') search.set(key, String(value))
  }
  const text = search.toString()
  return text ? `?${text}` : ''
}

export const exportsApi = {
  request: (body: ExportRequest) => api<ExportJob>('/exports', { method: 'POST', body }),
  list: (page: number, pageSize: number, mine = false) =>
    api<Page<ExportJob>>(`/exports${query({ page, page_size: pageSize, mine })}`),
  remove: (id: string) => api<void>(`/exports/${id}`, { method: 'DELETE' }),
  /** Download pela API (mesma origem, cookie de sessão): não existe URL pública do arquivo. */
  downloadUrl: (id: string) => `/api/v1/exports/${id}/download`,
}

export const membersApi = {
  changeRole: (memberId: string, role: Role) =>
    api<{ message: string }>(`/workspaces/current/members/${memberId}`, {
      method: 'PATCH',
      body: { role },
    }),
  remove: (memberId: string) =>
    api<void>(`/workspaces/current/members/${memberId}`, { method: 'DELETE' }),
  invitations: () => api<Invitation[]>('/workspaces/current/invitations'),
  invite: (email: string, role: Role) =>
    api<{ message: string }>('/workspaces/current/invitations', {
      method: 'POST',
      body: { email, role },
    }),
  revoke: (invitationId: string) =>
    api<void>(`/workspaces/current/invitations/${invitationId}`, { method: 'DELETE' }),
  previewInvitation: (token: string) =>
    api<InvitationPreview>('/invitations/preview', { method: 'POST', body: { token } }),
  acceptInvitation: (token: string) =>
    api<{ message: string }>('/invitations/accept', { method: 'POST', body: { token } }),
}

export const workspaceApi = {
  settings: () => api<WorkspaceSettingsInfo>('/workspaces/current/settings'),
  update: (body: { name?: string; settings?: WorkspaceSettings }) =>
    api<WorkspaceSettingsInfo>('/workspaces/current', { method: 'PATCH', body }),
}

export interface AuditFilters {
  action?: string
  dateFrom?: string
  dateTo?: string
  page: number
  pageSize: number
}

export const auditApi = {
  search: (f: AuditFilters) =>
    api<Page<AuditEntry>>(
      `/audit${query({
        action: f.action,
        date_from: f.dateFrom,
        date_to: f.dateTo,
        page: f.page,
        page_size: f.pageSize,
      })}`,
    ),
  actions: () => api<string[]>('/audit/actions'),
}

export const deletionApi = {
  datasetImpact: (datasetId: string) =>
    api<DatasetImpact>(`/datasets/${datasetId}/deletion-impact`),
  deleteDataset: (datasetId: string, confirmName: string) =>
    api<void>(`/datasets/${datasetId}`, {
      method: 'DELETE',
      body: { confirm_name: confirmName },
    }),
  versionImpact: (datasetId: string, versionId: string) =>
    api<VersionImpact>(`/datasets/${datasetId}/versions/${versionId}/deletion-impact`),
  deleteVersion: (datasetId: string, versionId: string) =>
    api<void>(`/datasets/${datasetId}/versions/${versionId}`, { method: 'DELETE' }),
}
