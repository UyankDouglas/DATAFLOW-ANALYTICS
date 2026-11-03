import type { Tone } from '@/features/jobs/status'
import type { ExportStatus, Role } from '@/types/api'

export const ROLE_INFO: Record<Role, { label: string; tone: Tone; description: string }> = {
  admin: {
    label: 'Administrador',
    tone: 'primary',
    description: 'Gerencia membros, configurações, exclusões e auditoria',
  },
  analyst: {
    label: 'Analista',
    tone: 'info',
    description: 'Importa, transforma, monta dashboards e exporta',
  },
  viewer: {
    label: 'Visualizador',
    tone: 'neutral',
    description: 'Consulta datasets e dashboards; exporta só se liberado',
  },
}

export const EXPORT_STATUS: Record<ExportStatus, { label: string; tone: Tone }> = {
  queued: { label: 'Na fila', tone: 'neutral' },
  running: { label: 'Gerando', tone: 'info' },
  succeeded: { label: 'Pronta', tone: 'success' },
  failed: { label: 'Falhou', tone: 'danger' },
  expired: { label: 'Expirada', tone: 'warning' },
}

export const isExportActive = (status: ExportStatus) => status === 'queued' || status === 'running'

/** Rótulos das ações registradas na auditoria; ações novas aparecem pelo código. */
export const AUDIT_ACTION: Record<string, string> = {
  'auth.register': 'Cadastro',
  'auth.login': 'Login',
  'auth.logout': 'Logout',
  'auth.password_reset': 'Senha redefinida',
  'auth.password_reset_requested': 'Redefinição de senha pedida',
  'workspace.created': 'Workspace criado',
  'workspace.switched': 'Troca de workspace',
  'workspace.updated': 'Configurações alteradas',
  'member.invited': 'Convite enviado',
  'member.invitation_revoked': 'Convite cancelado',
  'member.joined': 'Convite aceito',
  'member.role_changed': 'Perfil alterado',
  'member.removed': 'Membro removido',
  'dataset.upload': 'Arquivo enviado',
  'dataset.upload_rejected': 'Arquivo recusado',
  'dataset.sheet_imported': 'Aba importada',
  'dataset.parse_options_updated': 'Leitura configurada',
  'dataset.version_published': 'Versão publicada',
  'dataset.version_deleted': 'Versão excluída',
  'dataset.deleted': 'Dataset excluído',
  'import.requested': 'Processamento iniciado',
  'transform.requested': 'Transformação iniciada',
  'job.cancel_requested': 'Cancelamento pedido',
  'quality.computed': 'Qualidade calculada',
  'dashboard.created': 'Dashboard criado',
  'dashboard.updated': 'Dashboard alterado',
  'dashboard.deleted': 'Dashboard excluído',
  'export.requested': 'Exportação pedida',
  'export.downloaded': 'Exportação baixada',
  'export.deleted': 'Exportação excluída',
  'retention.original_purged': 'Original apagado (retenção)',
}

export const AUDIT_CATEGORY: Record<string, string> = {
  auth: 'Acesso',
  workspace: 'Workspace',
  member: 'Membros',
  dataset: 'Datasets',
  import: 'Processamentos',
  transform: 'Transformações',
  job: 'Jobs',
  quality: 'Qualidade',
  dashboard: 'Dashboards',
  export: 'Exportações',
  retention: 'Retenção',
}

export function auditLabel(action: string): string {
  return AUDIT_ACTION[action] ?? action
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

/** Detalhes curtos e legíveis; o registro nunca guarda conteúdo de arquivos nem senhas. */
export function describeDetails(details: Record<string, unknown>): string {
  return Object.entries(details)
    .filter(([, value]) => value !== null && value !== undefined && value !== '')
    .map(([key, value]) => {
      const raw = typeof value === 'object' ? JSON.stringify(value) : String(value)
      // Ids completos não ajudam a leitura: os 8 primeiros caracteres bastam para cruzar.
      const text = UUID.test(raw) ? raw.slice(0, 8) : raw
      return `${key}: ${text.length > 80 ? `${text.slice(0, 77)}…` : text}`
    })
    .join(' · ')
}
