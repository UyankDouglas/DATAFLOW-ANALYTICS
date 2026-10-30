import { api } from '@/services/api-client'
import type { Me, Member, WorkspaceSummary } from '@/types/api'

export interface LoginInput {
  email: string
  password: string
}

export interface RegisterInput {
  full_name: string
  email: string
  password: string
  workspace_name: string
}

export const authApi = {
  me: () => api<Me>('/auth/me'),
  login: (input: LoginInput) => api<Me>('/auth/login', { method: 'POST', body: input }),
  register: (input: RegisterInput) => api<Me>('/auth/register', { method: 'POST', body: input }),
  logout: () => api<{ message: string }>('/auth/logout', { method: 'POST' }),
  forgotPassword: (email: string) =>
    api<{ message: string }>('/auth/password/forgot', { method: 'POST', body: { email } }),
  resetPassword: (token: string, password: string) =>
    api<{ message: string }>('/auth/password/reset', { method: 'POST', body: { token, password } }),
  workspaces: () => api<WorkspaceSummary[]>('/workspaces'),
  switchWorkspace: (workspaceId: string) =>
    api<{ message: string }>('/workspaces/switch', {
      method: 'POST',
      body: { workspace_id: workspaceId },
    }),
  members: () => api<Member[]>('/workspaces/current/members'),
}
