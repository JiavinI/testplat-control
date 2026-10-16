import { MutationCache, QueryCache, QueryClient } from '@tanstack/react-query'
import { dropSessionOnUnauthorized } from '@/features/auth/hooks'
import { isUnauthenticated } from '@/features/auth/session'

export function createAppQueryClient(): QueryClient {
  const client = new QueryClient({
    queryCache: new QueryCache({
      onError: (error, query) => {
        dropSessionOnUnauthorized(client, error, query.queryKey[0])
      },
    }),
    mutationCache: new MutationCache({
      onError: (error, _variables, _context, mutation) => {
        dropSessionOnUnauthorized(client, error, mutation.options.mutationKey?.[0])
      },
    }),
    defaultOptions: {
      queries: {
        // 测试工具场景：窗口聚焦不自动狂刷，由用户显式刷新/重试
        refetchOnWindowFocus: false,
        retry: (failureCount, error) => {
          if (isUnauthenticated(error)) {
            return false
          }
          return failureCount < 1
        },
        staleTime: 30_000,
      },
      mutations: {
        retry: 0,
      },
    },
  })
  return client
}
