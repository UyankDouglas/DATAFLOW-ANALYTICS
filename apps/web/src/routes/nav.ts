import {
  BarChart3,
  Database,
  FileDown,
  FileSpreadsheet,
  History,
  LayoutDashboard,
  LayoutTemplate,
  ScrollText,
  Settings,
  ShieldCheck,
  Table2,
  Upload,
  Users,
  Wand2,
  type LucideIcon,
} from 'lucide-react'

export interface NavItem {
  label: string
  to: string
  icon: LucideIcon
  /** Fase do roadmap em que o módulo será entregue; ausente = disponível. */
  phase?: number
  permission?: string
}

export interface NavGroup {
  label: string
  items: NavItem[]
}

export const NAV_GROUPS: NavGroup[] = [
  {
    label: 'Principal',
    items: [
      { label: 'Visão geral', to: '/', icon: LayoutDashboard },
      { label: 'Datasets', to: '/datasets', icon: Database },
      { label: 'Importar dados', to: '/importar', icon: Upload, permission: 'datasets:upload' },
      { label: 'Histórico de processamento', to: '/processamentos', icon: History },
    ],
  },
  {
    label: 'Tratamento',
    items: [
      { label: 'Transformações', to: '/transformacoes', icon: Wand2 },
      { label: 'Qualidade', to: '/qualidade', icon: ShieldCheck },
      { label: 'Data Explorer', to: '/explorer', icon: Table2 },
    ],
  },
  {
    label: 'Análise',
    items: [
      { label: 'Dashboards', to: '/dashboards', icon: BarChart3 },
      {
        label: 'Construtor',
        to: '/dashboards/construtor',
        icon: LayoutTemplate,
        permission: 'dashboards:manage',
      },
      { label: 'Relatórios', to: '/relatorios', icon: FileSpreadsheet },
      { label: 'Exportações', to: '/exportacoes', icon: FileDown, permission: 'data:export' },
    ],
  },
  {
    label: 'Administração',
    items: [
      { label: 'Usuários e permissões', to: '/usuarios', icon: Users, permission: 'members:view' },
      { label: 'Auditoria', to: '/auditoria', icon: ScrollText, permission: 'audit:view' },
      { label: 'Configurações', to: '/configuracoes', icon: Settings },
    ],
  },
]

/** Módulos anunciados e ainda não entregues aparecem como "Em desenvolvimento". */
export const COMING_SOON: Record<
  string,
  { title: string; phase: number; description: string; icon: LucideIcon }
> = {}
