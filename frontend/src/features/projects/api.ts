import { apiClient, encodePath } from '@/shared/api/client'
import type { ApiClientOptions } from '@/shared/api/client'
import type {
  ProjectCreate,
  ProjectResponse,
  ProjectUpdate,
} from '@/shared/types/project'

export function listProjects(options?: ApiClientOptions): Promise<ProjectResponse[]> {
  return apiClient.get<ProjectResponse[]>('/projects', options)
}

export function getProject(
  projectId: string,
  options?: ApiClientOptions,
): Promise<ProjectResponse> {
  return apiClient.get<ProjectResponse>(encodePath(['projects', projectId]), options)
}

export function createProject(
  payload: ProjectCreate,
  options?: ApiClientOptions,
): Promise<ProjectResponse> {
  return apiClient.post<ProjectResponse>('/projects', payload, options)
}

export function updateProject(
  projectId: string,
  payload: ProjectUpdate,
  options?: ApiClientOptions,
): Promise<ProjectResponse> {
  return apiClient.put<ProjectResponse>(
    encodePath(['projects', projectId]),
    payload,
    options,
  )
}

export function deleteProject(
  projectId: string,
  options?: ApiClientOptions,
): Promise<{ message: string }> {
  return apiClient.delete<{ message: string }>(
    encodePath(['projects', projectId]),
    options,
  )
}
