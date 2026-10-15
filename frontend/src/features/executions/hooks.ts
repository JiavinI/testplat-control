import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from '@tanstack/react-query'
import {
  getAssetParams,
  getCaseAssetDetail,
  getCaseExecutionRecord,
  getExecutionRecord,
  listExecutionRecords,
  runAsset,
  runCase,
} from './api'
import type {
  CaseAssetDetail,
  CaseExecutionRecordDetail,
  CaseRunRequest,
  CaseRunResponse,
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
  caseDetail: (projectId: string, caseId: string) =>
    [...executionKeys.all, 'caseDetail', projectId, caseId] as const,
  caseRecord: (projectId: string, recordId: string) =>
    [...executionKeys.all, 'caseRecord', projectId, recordId] as const,
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

export function useCaseAssetDetail(
  projectId: string,
  caseId: string | undefined,
  enabled: boolean,
): UseQueryResult<CaseAssetDetail, Error> {
  return useQuery({
    queryKey: executionKeys.caseDetail(projectId, caseId ?? ''),
    queryFn: () => getCaseAssetDetail(projectId, caseId!),
    enabled: Boolean(projectId) && Boolean(caseId) && enabled,
  })
}

export function useCaseExecutionRecord(
  projectId: string,
  recordId: string | null,
): UseQueryResult<CaseExecutionRecordDetail, Error> {
  return useQuery({
    queryKey: executionKeys.caseRecord(projectId, recordId ?? ''),
    queryFn: () => getCaseExecutionRecord(projectId, recordId!),
    enabled: Boolean(projectId && recordId),
  })
}

export function useRunCase(projectId: string, caseId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: CaseRunRequest) => runCase(projectId, caseId, body),
    onSuccess: (_data: CaseRunResponse) => {
      void queryClient.invalidateQueries({
        queryKey: [...executionKeys.all, 'records', projectId],
      })
    },
    onError: () => {
      // 5xx 也会落 failed 记录；刷新历史供面板定位
      void queryClient.invalidateQueries({
        queryKey: [...executionKeys.all, 'records', projectId],
      })
    },
  })
}
