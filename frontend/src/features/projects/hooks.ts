import { useQuery, type UseQueryResult } from '@tanstack/react-query'
import { getProject, listProjects } from './api'
import type { ProjectResponse } from '@/shared/types/project'

export const projectKeys = {
  all: ['projects'] as const,
  lists: () => [...projectKeys.all, 'list'] as const,
  detail: (id: string) => [...projectKeys.all, 'detail', id] as const,
}

export function useProjectList(): UseQueryResult<ProjectResponse[], Error> {
  return useQuery({
    queryKey: projectKeys.lists(),
    queryFn: () => listProjects(),
  })
}

export function useProject(projectId: string): UseQueryResult<ProjectResponse, Error> {
  return useQuery({
    queryKey: projectKeys.detail(projectId),
    queryFn: () => getProject(projectId),
    enabled: Boolean(projectId),
  })
}
