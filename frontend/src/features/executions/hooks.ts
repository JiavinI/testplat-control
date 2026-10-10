import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from '@tanstack/react-query'
import {
  getAssetParams,
  getExecutionRecord,
  listExecutionRecords,
  runAsset,
} from './api'
import type {
  ExecutionListQuery,
  ExecutionRecordDetail,
  ExecutionRecordListItem,
  ParamsResponse,
  RunRequest,
  RunResponse,
} from './types'

export const executionKeys = {
  all: ['executions'] as const,
  params: (projectId: string, assetId: string) =>
    [...executionKeys.all, 'params', projectId, assetId] as const,
  records: (projectId: string, query: ExecutionListQuery) =>
    [...executionKeys.all, 'records', projectId, query] as const,
  record: (projectId: string, recordId: string) =>
    [...executionKeys.all, 'record', projectId, recordId] as const,
}

export function useAssetParams(
  projectId: string,
  assetId: string,
): UseQueryResult<ParamsResponse, Error> {
  return useQuery({
    queryKey: executionKeys.params(projectId, assetId),
    queryFn: () => getAssetParams(projectId, assetId),
    enabled: Boolean(projectId && assetId),
  })
}

export function useExecutionRecords(
  projectId: string,
  query: ExecutionListQuery,
): UseQueryResult<ExecutionRecordListItem[], Error> {
  return useQuery({
    queryKey: executionKeys.records(projectId, query),
    queryFn: () => listExecutionRecords(projectId, query),
    enabled: Boolean(projectId),
  })
}

export function useExecutionRecord(
  projectId: string,
  recordId: string | null,
): UseQueryResult<ExecutionRecordDetail, Error> {
  return useQuery({
    queryKey: executionKeys.record(projectId, recordId ?? ''),
    queryFn: () => getExecutionRecord(projectId, recordId!),
    enabled: Boolean(projectId && recordId),
  })
}

export function useRunAsset(projectId: string, assetId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: RunRequest) => runAsset(projectId, assetId, body),
    onSuccess: (_data: RunResponse) => {
      // success 与业务 failed 都是 HTTP 200，均需刷新历史
      void queryClient.invalidateQueries({
        queryKey: [...executionKeys.all, 'records', projectId],
      })
    },
  })
}
