import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { ApiError } from '@/services/api-client'
import type { Me } from '@/types/api'

import { authApi, type LoginInput, type RegisterInput } from './api'

export const ME_KEY = ['auth', 'me'] as const

/** Sessão atual. `null` quando não autenticado (401). */
export function useSession() {
  return useQuery<Me | null>({
    queryKey: ME_KEY,
    queryFn: async () => {
      try {
        return await authApi.me()
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) return null
        throw error
      }
    },
    staleTime: 60_000,
    retry: (count, error) => !(error instanceof ApiError && error.status < 500) && count < 2,
  })
}

export function usePermission(permission: string): boolean {
  const { data } = useSession()
  return data?.permissions.includes(permission) ?? false
}

export function useLogin() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (input: LoginInput) => authApi.login(input),
    onSuccess: (me) => {
      client.clear()
      client.setQueryData(ME_KEY, me)
    },
  })
}

export function useRegister() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (input: RegisterInput) => authApi.register(input),
    onSuccess: (me) => {
      client.clear()
      client.setQueryData(ME_KEY, me)
    },
  })
}

export function useLogout() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => authApi.logout(),
    onSettled: () => {
      client.clear()
      client.setQueryData(ME_KEY, null)
    },
  })
}

export function useSwitchWorkspace() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (workspaceId: string) => authApi.switchWorkspace(workspaceId),
    onSuccess: async () => {
      // Todo dado em cache pertence ao workspace anterior.
      client.removeQueries({ predicate: (query) => query.queryKey[0] !== 'auth' })
      await client.invalidateQueries({ queryKey: ME_KEY })
    },
  })
}
