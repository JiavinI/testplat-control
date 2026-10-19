import { apiClient, encodePath } from '@/shared/api/client'
import type { ApiClientOptions } from '@/shared/api/client'
import {
  assertArray,
  assertObject,
  requireNullableString,
  requireString,
} from '@/shared/api/validate'
import { ApiParseError } from '@/shared/api/errors'
import { projectResourcePath, splitProjectId } from '@/shared/project/ids'
import type { ProjectResponse, WorkspaceContext } from '@/shared/types/project'

function requireBoolean(
  obj: Record<string, unknown>,
  key: string,
  label: string,
): boolean {
  const value = obj[key]
  if (typeof value !== 'boolean') {
    throw new ApiParseError(`${label}.${key} 应为布尔值`, JSON.stringify(obj))
  }
  return value
}

function requireStringArray(
  obj: Record<string, unknown>,
  key: string,
  label: string,
): string[] {
  const value = obj[key]
  if (value === undefined || value === null) {
    return []
  }
  if (!Array.isArray(value)) {
    throw new ApiParseError(`${label}.${key} 应为数组`, JSON.stringify(obj))
  }
  return value.map((item, index) => {
    if (typeof item !== 'string') {
      throw new ApiParseError(
        `${label}.${key}[${index}] 应为字符串`,
        JSON.stringify(obj),
      )
    }
    return item
  })
}

function parseWorkspace(value: unknown): WorkspaceContext | null {
  if (value === undefined || value === null) return null
  assertObject(value, 'WorkspaceContext')
  return {
    platform: requireString(value, 'platform', 'WorkspaceContext'),
    platform_name: requireString(value, 'platform_name', 'WorkspaceContext'),
    project: requireString(value, 'project', 'WorkspaceContext'),
    project_name: requireString(value, 'project_name', 'WorkspaceContext'),
    configuration_project_id: requireString(value, 'configuration_project_id', 'WorkspaceContext'),
  }
}

function parseProject(payload: unknown, label = 'ProjectResponse'): ProjectResponse {
  assertObject(payload, label)
  return {
    ...(payload.workspace == null ? {} : { workspace: parseWorkspace(payload.workspace) }),
    id: requireString(payload, 'id', label),
    repo: requireString(payload, 'repo', label),
    project: requireString(payload, 'project', label),
    name: requireString(payload, 'name', label),
    envs: requireStringArray(payload, 'envs', label),
    default_env: requireNullableString(payload, 'default_env', label),
    archived: requireBoolean(payload, 'archived', label),
    commit_sha: requireNullableString(payload, 'commit_sha', label),
    created_at: requireString(payload, 'created_at', label),
    updated_at: requireString(payload, 'updated_at', label),
  }
}

export async function listProjects(
  options?: ApiClientOptions,
): Promise<ProjectResponse[]> {
  const payload = await apiClient.get<unknown>('/projects', options)
  assertArray(payload, 'ProjectList')
  return payload.map((item, index) => parseProject(item, `ProjectList[${index}]`))
}

/** 两段式详情；也接受扁平 id "{repo}/{project}" */
export async function getProject(
  projectId: string,
  options?: ApiClientOptions,
): Promise<ProjectResponse> {
  const { repo, project } = splitProjectId(projectId)
  const payload = await apiClient.get<unknown>(
    encodePath(['repos', repo, 'projects', project]),
    options,
  )
  return parseProject(payload)
}

export { projectResourcePath, splitProjectId }
