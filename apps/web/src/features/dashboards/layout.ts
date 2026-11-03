import type { WidgetSize } from '@/types/api'

/** Colunas da grade: celular 1, tablet 2, desktop 4. */
export const GRID_CLASS = 'grid gap-4 md:grid-cols-2 xl:grid-cols-4'
export const SIZE_CLASS: Record<WidgetSize, string> = {
  small: 'xl:col-span-1',
  medium: 'xl:col-span-2',
  large: 'md:col-span-2 xl:col-span-4',
}
