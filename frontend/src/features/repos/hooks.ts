import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from '@tanstack/react-query'
import { listRepos, syncRepo } from './api'
import { projectKeys } from '@/features/projects/hooks'
import type { RepoResponse, SyncResponse } from '@/shared/types/project'

export const repoKeys = {
  all: ['repos'] as const,
  lists: () => [...repoKeys.all, 'list'] as const,
}

export function useRepoList(): UseQueryResult<RepoResponse[], Error> {
  return useQuery({
    queryKey: repoKeys.lists(),
    queryFn: () => listRepos(),
  })
}

export function useSyncRepo() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (repo: string) => syncRepo(repo),
    onSuccess: (_data: SyncResponse) => {
      // 同步后刷新仓库状态与项目列表（清单 upsert / archived）
      void queryClient.invalidateQueries({ queryKey: repoKeys.lists() })
      void queryClient.invalidateQueries({ queryKey: projectKeys.lists() })
      void queryClient.invalidateQueries({ queryKey: projectKeys.all })
    },
  })
}
