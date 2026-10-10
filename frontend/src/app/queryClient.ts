import { QueryClient } from '@tanstack/react-query'

export function createAppQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        // 测试工具场景：窗口聚焦不自动狂刷，由用户显式刷新/重试
        refetchOnWindowFocus: false,
        retry: 1,
        staleTime: 30_000,
      },
      mutations: {
        retry: 0,
      },
    },
  })
}
