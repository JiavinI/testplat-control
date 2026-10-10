import { apiClient, encodePath } from '@/shared/api/client'
import type { ApiClientOptions } from '@/shared/api/client'
import {
  assertArray,
  assertObject,
  requireString,
} from '@/shared/api/validate'
import type {
  ProjectCreate,
  ProjectResponse,
  ProjectUpdate,
} from '@/shared/types/project'

function parseProject(payload: unknown, label = 'ProjectResponse'): ProjectResponse {
  assertObject(payload, label)
  return {
    id: requireString(payload, 'id', label),
    name: requireString(payload, 'name', label),
    env: requireString(payload, 'env', label),
    assets_root: requireString(payload, 'assets_root', label),
    config_root: requireString(payload, 'config_root', label),
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

export async function getProject(
  projectId: string,
  options?: ApiClientOptions,
): Promise<ProjectResponse> {
  const payload = await apiClient.get<unknown>(
    encodePath(['projects', projectId]),
    options,
  )
  return parseProject(payload)
}

export async function createProject(
  payload: ProjectCreate,
  options?: ApiClientOptions,
): Promise<ProjectResponse> {
  const data = await apiClient.post<unknown>('/projects', payload, options)
  return parseProject(data)
}

export async function updateProject(
  projectId: string,
  payload: ProjectUpdate,
  options?: ApiClientOptions,
): Promise<ProjectResponse> {
  const data = await apiClient.put<unknown>(
    encodePath(['projects', projectId]),
    payload,
    options,
  )
  return parseProject(data)
}

export async function deleteProject(
  projectId: string,
  options?: ApiClientOptions,
): Promise<{ message: string }> {
  const data = await apiClient.delete<unknown>(
    encodePath(['projects', projectId]),
    options,
  )
  assertObject(data, 'DeleteProjectResponse')
  return { message: requireString(data, 'message', 'DeleteProjectResponse') }
}
