import { apiClient, type ApiClientOptions } from '@/shared/api/client'
import { ApiParseError } from '@/shared/api/errors'
import { assertObject, requireString } from '@/shared/api/validate'
import type { AuthBody, MeResponse } from './types'

const OMITTED = '[已省略]'

function parseMe(payload: unknown): MeResponse {
  assertObject(payload, 'MeResponse', OMITTED)
  return {
    username: requireString(payload, 'username', 'MeResponse', OMITTED),
  }
}

export async function register(
  body: AuthBody,
  options?: ApiClientOptions,
): Promise<MeResponse> {
  const payload = await apiClient.post<unknown>('/auth/register', body, options)
  return parseMe(payload)
}

export async function login(
  body: AuthBody,
  options?: ApiClientOptions,
): Promise<MeResponse> {
  const payload = await apiClient.post<unknown>('/auth/login', body, options)
  return parseMe(payload)
}

/** 注销成功是 204，没有响应体。 */
export async function logout(options?: ApiClientOptions): Promise<void> {
  await apiClient.post<void>('/auth/logout', undefined, options)
}

export async function getMe(options?: ApiClientOptions): Promise<MeResponse> {
  const payload = await apiClient.get<unknown>('/auth/me', options)
  return parseMe(payload)
}

export function authFailureMessage(error: unknown): string {
  if (error instanceof ApiParseError) {
    return '登录响应无法解析'
  }
  if (error instanceof Error && error.message.trim()) {
    return error.message
  }
  return '登录失败'
}
