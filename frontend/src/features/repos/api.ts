import { apiClient, encodePath } from '@/shared/api/client'
import type { ApiClientOptions } from '@/shared/api/client'
import {
  assertArray,
  assertObject,
  requireNullableString,
  requireString,
} from '@/shared/api/validate'
import { ApiParseError } from '@/shared/api/errors'
import type { RepoResponse, SyncResponse } from '@/shared/types/project'

function parseRepo(payload: unknown, label = 'RepoResponse'): RepoResponse {
  assertObject(payload, label)
  return {
    key: requireString(payload, 'key', label),
    branch: requireString(payload, 'branch', label),
    current_sha: requireNullableString(payload, 'current_sha', label),
    last_sync_at: requireNullableString(payload, 'last_sync_at', label),
    last_sync_result: requireNullableString(payload, 'last_sync_result', label),
  }
}

function parseSync(payload: unknown): SyncResponse {
  assertObject(payload, 'SyncResponse')
  if (typeof payload.ok !== 'boolean') {
    throw new ApiParseError('SyncResponse.ok 应为布尔值', JSON.stringify(payload))
  }
  return {
    repo: requireString(payload, 'repo', 'SyncResponse'),
    ok: payload.ok,
    category: requireString(payload, 'category', 'SyncResponse'),
    commit_sha: requireNullableString(payload, 'commit_sha', 'SyncResponse'),
  }
}

export async function listRepos(options?: ApiClientOptions): Promise<RepoResponse[]> {
  const payload = await apiClient.get<unknown>('/repos', options)
  assertArray(payload, 'RepoList')
  return payload.map((item, index) => parseRepo(item, `RepoList[${index}]`))
}

export async function syncRepo(
  repo: string,
  options?: ApiClientOptions,
): Promise<SyncResponse> {
  const payload = await apiClient.post<unknown>(
    encodePath(['repos', repo, 'sync']),
    undefined,
    options,
  )
  return parseSync(payload)
}
