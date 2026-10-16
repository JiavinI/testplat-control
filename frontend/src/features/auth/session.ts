import { ApiHttpError } from '@/shared/api/errors'

/** 当前操作人查询键。401 时写成 null，表示需要重新登录。 */
export const authKeys = {
  me: ['auth', 'me'] as const,
}

export function isUnauthenticated(error: unknown): boolean {
  return error instanceof ApiHttpError && error.status === 401
}
