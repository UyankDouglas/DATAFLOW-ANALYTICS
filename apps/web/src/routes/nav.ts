import {
  BarChart3,
  ClipboardCheck,
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
      { label: 'Transformações', to: '/transformacoes', icon: Wand2, phase: 2 },
      { label: 'Qualidade', to: '/qualidade', icon: ShieldCheck, phase: 3 },
      { label: 'Data Explorer', to: '/explorer', icon: Table2 },
    ],
  },
  {
    label: 'Análise',
    items: [
      { label: 'Dashboards', to: '/dashboards', icon: BarChart3, phase: 4 },
      {
        label: 'Construtor',
        to: '/dashboards/construtor',
        icon: LayoutTemplate,
        phase: 4,
      },
      { label: 'Relatórios', to: '/relatorios', icon: FileSpreadsheet, phase: 5 },
      { label: 'Exportações', to: '/exportacoes', icon: FileDown, phase: 5 },
    ],
  },
  {
    label: 'Administração',
    items: [
      { label: 'Usuários e permissões', to: '/usuarios', icon: Users, permission: 'members:view' },
      { label: 'Auditoria', to: '/auditoria', icon: ScrollText, phase: 5 },
      { label: 'Configurações', to: '/configuracoes', icon: Settings, phase: 5 },
    ],
  },
]

export const COMING_SOON: Record<
  string,
  { title: string; phase: number; description: string; icon: LucideIcon }
> = {
  '/transformacoes': {
    title: 'Transformações',
    phase: 2,
    icon: Wand2,
    description:
      'Motor de transformações configuráveis: limpeza de espaços, normalização de texto, tratamento de nulos, filtros, colunas derivadas e deduplicação com prévia.',
  },
  '/qualidade': {
    title: 'Qualidade dos Dados',
    phase: 3,
    icon: ClipboardCheck,
    description:
      'Pontuação de qualidade com fórmula documentada, completude por coluna, distribuição de nulos, duplicidades e tabela de inconsistências.',
  },
  '/dashboards': {
    title: 'Dashboards',
    phase: 4,
    icon: BarChart3,
    description:
      'Dashboards interativos com KPIs, gráficos e filtros sobre os dados reais das versões publicadas.',
  },
  '/dashboards/construtor': {
    title: 'Construtor de Dashboards',
    phase: 4,
    icon: LayoutTemplate,
    description:
      'Escolha dataset e versão, adicione widgets, defina dimensões, métricas, agregações e filtros.',
  },
  '/relatorios': {
    title: 'Relatórios',
    phase: 5,
    icon: FileSpreadsheet,
    description:
      'Indicadores agregados, comparação entre períodos e exportação CSV/XLSX em segundo plano.',
  },
  '/exportacoes': {
    title: 'Exportações',
    phase: 5,
    icon: FileDown,
    description:
      'Histórico de exportações com expiração, proteção contra formula injection e download autorizado.',
  },
  '/auditoria': {
    title: 'Auditoria',
    phase: 5,
    icon: ScrollText,
    description:
      'Consulta das ações registradas (login, uploads, processamentos, cancelamentos) com filtros.',
  },
  '/configuracoes': {
    title: 'Configurações',
    phase: 5,
    icon: Settings,
    description: 'Configurações do workspace, limites, retenção de arquivos e preferências.',
  },
}
