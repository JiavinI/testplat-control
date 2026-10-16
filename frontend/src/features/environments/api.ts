import { apiRequest, type ApiClientOptions } from '@/shared/api/client'
import { ApiParseError } from '@/shared/api/errors'
import { projectResourcePath } from '@/shared/project/ids'
import {
  assertArray,
  assertObject,
  requireInteger,
  requireNullableString,
  requireString,
} from '@/shared/api/validate'
import type {
  AccountBody,
  AccountCredentials,
  AccountUpdate,
  EnvironmentBody,
  EnvironmentUpdate,
  LoginProfiles,
  ProjectEnvironment,
  TestAccount,
} from './types'

const OMITTED = '[已省略]'

function requireBoolean(obj: Record<string, unknown>, key: string, label: string): boolean {
  const value = obj[key]
  if (typeof value !== 'boolean') {
    throw new ApiParseError(`${label}.${key} 应为布尔值`, OMITTED)
  }
  return value
}

function readStringRecord(
  obj: Record<string, unknown>,
  key: string,
  label: string,
): Record<string, string> {
  const value = obj[key]
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    throw new ApiParseError(`${label}.${key} 应为对象`, OMITTED)
  }
  const result: Record<string, string> = {}
  for (const [field, item] of Object.entries(value)) {
    if (typeof item !== 'string') {
      throw new ApiParseError(`${label}.${key} 的值必须是字符串`, OMITTED)
    }
    result[field] = item
  }
  return result
}

function readJsonObject(
  obj: Record<string, unknown>,
  key: string,
  label: string,
): Record<string, unknown> {
  const value = obj[key]
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    throw new ApiParseError(`${label}.${key} 应为对象`, OMITTED)
  }
  return value
}

function readTimeout(obj: Record<string, unknown>, label: string): number | null {
  const value = obj.timeout_seconds
  if (value === null || value === undefined) {
    return null
  }
  if (typeof value !== 'number' || Number.isNaN(value)) {
    throw new ApiParseError(`${label}.timeout_seconds 应为数字或 null`, OMITTED)
  }
  return value
}

export function parseEnvironment(payload: unknown, label = 'EnvironmentResponse'): ProjectEnvironment {
  assertObject(payload, label, OMITTED)
  return {
    env: requireString(payload, 'env', label, OMITTED),
    enabled: requireBoolean(payload, 'enabled', label),
    api_hosts: readStringRecord(payload, 'api_hosts', label),
    timeout_seconds: readTimeout(payload, label),
    case_params: readJsonObject(payload, 'case_params', label),
    revision: requireInteger(payload, 'revision', label, OMITTED),
    updated_by: requireNullableString(payload, 'updated_by', label, OMITTED),
  }
}

export function parseAccount(payload: unknown, label = 'AccountResponse'): TestAccount {
  assertObject(payload, label, OMITTED)
  // 列表与详情契约不含凭据。即使响应多带了 credentials，也不放进账号状态。
  return {
    account_name: requireString(payload, 'account_name', label, OMITTED),
    display_name: requireNullableString(payload, 'display_name', label, OMITTED),
    business_role: requireNullableString(payload, 'business_role', label, OMITTED),
    login_profile: requireString(payload, 'login_profile', label, OMITTED),
    enabled: requireBoolean(payload, 'enabled', label),
    revision: requireInteger(payload, 'revision', label, OMITTED),
    updated_by: requireNullableString(payload, 'updated_by', label, OMITTED),
  }
}

function parseCredentials(payload: unknown): AccountCredentials {
  assertObject(payload, 'CredentialsResponse', OMITTED)
  return {
    account_name: requireString(payload, 'account_name', 'CredentialsResponse', OMITTED),
    credentials: readStringRecord(payload, 'credentials', 'CredentialsResponse'),
  }
}

export function parseLoginProfiles(payload: unknown): LoginProfiles {
  assertObject(payload, 'LoginProfilesResponse', OMITTED)
  assertArray(payload.profiles, 'LoginProfilesResponse.profiles', OMITTED)
  return {
    commit_sha: requireString(payload, 'commit_sha', 'LoginProfilesResponse', OMITTED),
    profiles: payload.profiles.map((item, index) => {
      const label = `LoginProfilesResponse.profiles[${index}]`
      assertObject(item, label, OMITTED)
      assertArray(item.credential_fields, `${label}.credential_fields`, OMITTED)
      return {
        name: requireString(item, 'name', label, OMITTED),
        credential_fields: item.credential_fields.map((field, fieldIndex) => {
          if (typeof field !== 'string') {
            throw new ApiParseError(`${label}.credential_fields[${fieldIndex}] 应为字符串`, OMITTED)
          }
          return field
        }),
      }
    }),
  }
}

export async function listEnvironments(
  projectId: string,
  options?: ApiClientOptions,
): Promise<ProjectEnvironment[]> {
  const payload = await apiRequest<unknown>(
    projectResourcePath(projectId, 'environments'),
    { method: 'GET' },
    options,
  )
  assertArray(payload, 'EnvironmentList', OMITTED)
  return payload.map((item, index) => parseEnvironment(item, `EnvironmentList[${index}]`))
}

export async function createEnvironment(
  projectId: string,
  body: EnvironmentBody,
  options?: ApiClientOptions,
): Promise<ProjectEnvironment> {
  const payload = await apiRequest<unknown>(
    projectResourcePath(projectId, 'environments'),
    { method: 'POST', body: JSON.stringify(body) },
    options,
  )
  return parseEnvironment(payload)
}

export async function getEnvironment(
  projectId: string,
  env: string,
  options?: ApiClientOptions,
): Promise<ProjectEnvironment> {
  const payload = await apiRequest<unknown>(
    projectResourcePath(projectId, 'environments', env),
    { method: 'GET' },
    options,
  )
  return parseEnvironment(payload)
}

/** 必须带读取时的 revision。冲突由调用方处理为 409，不在这里重试。 */
export async function updateEnvironment(
  projectId: string,
  env: string,
  body: EnvironmentUpdate,
  options?: ApiClientOptions,
): Promise<ProjectEnvironment> {
  const payload = await apiRequest<unknown>(
    projectResourcePath(projectId, 'environments', env),
    { method: 'PUT', body: JSON.stringify(body) },
    options,
  )
  return parseEnvironment(payload)
}

export async function listLoginProfiles(
  projectId: string,
  options?: ApiClientOptions,
): Promise<LoginProfiles> {
  const payload = await apiRequest<unknown>(
    projectResourcePath(projectId, 'login-profiles'),
    { method: 'GET' },
    options,
  )
  return parseLoginProfiles(payload)
}

export async function listAccounts(
  projectId: string,
  env: string,
  options?: ApiClientOptions,
): Promise<TestAccount[]> {
  const payload = await apiRequest<unknown>(
    projectResourcePath(projectId, 'environments', env, 'accounts'),
    { method: 'GET' },
    options,
  )
  assertArray(payload, 'AccountList', OMITTED)
  return payload.map((item, index) => parseAccount(item, `AccountList[${index}]`))
}

export async function createAccount(
  projectId: string,
  env: string,
  body: AccountBody,
  options?: ApiClientOptions,
): Promise<TestAccount> {
  const payload = await apiRequest<unknown>(
    projectResourcePath(projectId, 'environments', env, 'accounts'),
    { method: 'POST', body: JSON.stringify(body) },
    options,
  )
  return parseAccount(payload)
}

export async function getAccount(
  projectId: string,
  env: string,
  name: string,
  options?: ApiClientOptions,
): Promise<TestAccount> {
  const payload = await apiRequest<unknown>(
    projectResourcePath(projectId, 'environments', env, 'accounts', name),
    { method: 'GET' },
    options,
  )
  return parseAccount(payload)
}

export async function updateAccount(
  projectId: string,
  env: string,
  name: string,
  body: AccountUpdate,
  options?: ApiClientOptions,
): Promise<TestAccount> {
  const payload = await apiRequest<unknown>(
    projectResourcePath(projectId, 'environments', env, 'accounts', name),
    { method: 'PUT', body: JSON.stringify(body) },
    options,
  )
  return parseAccount(payload)
}

/**
 * 显式查看凭据。不经过 Query 缓存；请求禁止浏览器缓存。
 * 解析失败的异常正文固定为占位，不带凭据原文。
 */
export async function getAccountCredentials(
  projectId: string,
  env: string,
  name: string,
  options?: ApiClientOptions,
): Promise<AccountCredentials> {
  const payload = await apiRequest<unknown>(
    projectResourcePath(projectId, 'environments', env, 'accounts', name, 'credentials'),
    { method: 'GET', cache: 'no-store' },
    options,
  )
  return parseCredentials(payload)
}
