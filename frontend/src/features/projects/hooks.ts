import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from '@tanstack/react-query'
import {
  createProject,
  deleteProject,
  getProject,
  listProjects,
  updateProject,
} from './api'
import type { ProjectCreate, ProjectResponse, ProjectUpdate } from '@/shared/types/project'

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

export function useCreateProject() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: ProjectCreate) => createProject(payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: projectKeys.lists() })
    },
  })
}

export function useUpdateProject(projectId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: ProjectUpdate) => updateProject(projectId, payload),
    onSuccess: (data) => {
      void queryClient.invalidateQueries({ queryKey: projectKeys.lists() })
      queryClient.setQueryData(projectKeys.detail(projectId), data)
    },
  })
}

export function useDeleteProject() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (projectId: string) => deleteProject(projectId),
    onSuccess: (_data, projectId) => {
      void queryClient.invalidateQueries({ queryKey: projectKeys.lists() })
      queryClient.removeQueries({ queryKey: projectKeys.detail(projectId) })
    },
  })
}
