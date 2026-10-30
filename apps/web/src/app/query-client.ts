import { QueryCache, QueryClient } from '@tanstack/react-query'

import { ApiError } from '@/services/api-client'

export function createQueryClient() {
  const client: QueryClient = new QueryClient({
    queryCache: new QueryCache({
      onError: (error) => {
        // Sessão expirada em qualquer consulta: força revalidação da sessão (redireciona ao login).
        if (error instanceof ApiError && error.status === 401) {
          client.setQueryData(['auth', 'me'], null)
        }
      },
    }),
    defaultOptions: {
      queries: {
        staleTime: 15_000,
        refetchOnWindowFocus: false,
        retry: (count, error) => {
          if (error instanceof ApiError && error.status > 0 && error.status < 500) return false
          return count < 2
        },
      },
      mutations: { retry: false },
    },
  })
  return client
}
