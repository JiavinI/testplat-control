import { useMutation, useQuery, useQueryClient, type UseQueryResult } from '@tanstack/react-query'
import { projectKeys } from '@/features/projects/hooks'
import {
  createAccount,
  createEnvironment,
  getAccountCredentials,
  listAccounts,
  listEnvironments,
  listLoginProfiles,
  updateAccount,
  updateEnvironment,
} from './api'
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

export const environmentKeys = {
  all: ['environments'] as const,
  list: (projectId: string) => [...environmentKeys.all, 'list', projectId] as const,
  accounts: (projectId: string, env: string) =>
    [...environmentKeys.all, 'accounts', projectId, env] as const,
  profiles: (projectId: string) => [...environmentKeys.all, 'profiles', projectId] as const,
}

function useInvalidateProjectConfig() {
  const client = useQueryClient()
  return () => {
    void client.invalidateQueries({ queryKey: environmentKeys.all })
    void client.invalidateQueries({ queryKey: projectKeys.all })
  }
}

export function useEnvironments(
  projectId: string,
): UseQueryResult<ProjectEnvironment[], Error> {
  return useQuery({
    queryKey: environmentKeys.list(projectId),
    queryFn: () => listEnvironments(projectId),
    enabled: Boolean(projectId),
  })
}

export function useAccounts(
  projectId: string,
  env: string | null,
): UseQueryResult<TestAccount[], Error> {
  return useQuery({
    queryKey: environmentKeys.accounts(projectId, env ?? ''),
    queryFn: () => listAccounts(projectId, env!),
    enabled: Boolean(projectId && env),
  })
}

export function useLoginProfiles(
  projectId: string,
  enabled: boolean,
): UseQueryResult<LoginProfiles, Error> {
  return useQuery({
    queryKey: environmentKeys.profiles(projectId),
    queryFn: () => listLoginProfiles(projectId),
    enabled: Boolean(projectId) && enabled,
  })
}

export function useCreateEnvironment(projectId: string) {
  const invalidate = useInvalidateProjectConfig()
  return useMutation({
    mutationFn: (body: EnvironmentBody) => createEnvironment(projectId, body),
    onSuccess: invalidate,
  })
}

export function useUpdateEnvironment(projectId: string) {
  const invalidate = useInvalidateProjectConfig()
  const client = useQueryClient()
  return useMutation({
    mutationFn: (input: { env: string; body: EnvironmentUpdate }) =>
      updateEnvironment(projectId, input.env, input.body),
    onSuccess: () => {
      invalidate()
      void client.invalidateQueries({ queryKey: [...environmentKeys.all, 'accounts', projectId] })
    },
  })
}

export function useCreateAccount(projectId: string, env: string) {
  const client = useQueryClient()
  const invalidate = useInvalidateProjectConfig()
  return useMutation({
    mutationFn: (body: AccountBody) => createAccount(projectId, env, body),
    // 请求体含凭据，不留在 mutation 缓存。
    gcTime: 0,
    onSuccess: () => {
      invalidate()
      void client.invalidateQueries({ queryKey: environmentKeys.accounts(projectId, env) })
    },
  })
}

export function useUpdateAccount(projectId: string, env: string) {
  const client = useQueryClient()
  const invalidate = useInvalidateProjectConfig()
  return useMutation({
    mutationFn: (input: { name: string; body: AccountUpdate }) =>
      updateAccount(projectId, env, input.name, input.body),
    gcTime: 0,
    onSuccess: () => {
      invalidate()
      void client.invalidateQueries({ queryKey: environmentKeys.accounts(projectId, env) })
    },
  })
}

/** 凭据只在点击查看时拉取，不注册为可缓存查询。 */
export async function fetchAccountCredentials(
  projectId: string,
  env: string,
  name: string,
): Promise<AccountCredentials> {
  return getAccountCredentials(projectId, env, name)
}
