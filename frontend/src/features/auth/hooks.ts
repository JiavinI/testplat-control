import {
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
  type UseQueryResult,
} from '@tanstack/react-query'
import { getMe, login, logout, register } from './api'
import { authKeys, isUnauthenticated } from './session'
import type { AuthBody, MeResponse } from './types'

/**
 * 会话失效时清掉业务缓存，避免下一个操作人看到上一位的项目数据。
 * 不触碰 auth 查询本身，由调用方写入 null。
 */
export function clearAuthenticatedCache(client: QueryClient): void {
  client.setQueryData(authKeys.me, null)
  void client.removeQueries({
    predicate: (query) => query.queryKey[0] !== 'auth',
  })
}

export function dropSessionOnUnauthorized(
  client: QueryClient,
  error: unknown,
  keyHead: unknown,
): void {
  if (!isUnauthenticated(error) || keyHead === 'auth') {
    return
  }
  clearAuthenticatedCache(client)
}

export function useMe(): UseQueryResult<MeResponse | null, Error> {
  return useQuery({
    queryKey: authKeys.me,
    queryFn: async () => {
      try {
        return await getMe()
      } catch (error) {
        if (isUnauthenticated(error)) {
          return null
        }
        throw error
      }
    },
    retry: false,
  })
}

export function useLogin() {
  const client = useQueryClient()
  return useMutation({
    mutationKey: ['auth', 'login'],
    mutationFn: (body: AuthBody) => login(body),
    // 密码只用于这一次请求，不留在 mutation 缓存里。
    gcTime: 0,
    onSuccess: (me) => {
      client.setQueryData(authKeys.me, me)
    },
  })
}

export function useRegister() {
  const client = useQueryClient()
  return useMutation({
    mutationKey: ['auth', 'register'],
    mutationFn: (body: AuthBody) => register(body),
    gcTime: 0,
    onSuccess: (me) => {
      client.setQueryData(authKeys.me, me)
    },
  })
}

export function useLogout() {
  const client = useQueryClient()
  return useMutation({
    mutationKey: ['auth', 'logout'],
    mutationFn: () => logout(),
    onSuccess: () => {
      clearAuthenticatedCache(client)
    },
  })
}
