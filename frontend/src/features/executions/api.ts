import { apiClient, encodePath } from '@/shared/api/client'
import type { ApiClientOptions } from '@/shared/api/client'
import type {
  ExecutionListQuery,
  ExecutionRecordDetail,
  ExecutionRecordListItem,
  ParamsResponse,
  RunRequest,
  RunResponse,
} from './types'

function recordsPath(projectId: string, query: ExecutionListQuery = {}): string {
  const base = encodePath(['projects', projectId, 'execution-records'])
  const params = new URLSearchParams()
  if (query.skip !== undefined) {
    params.set('skip', String(query.skip))
  }
  if (query.limit !== undefined) {
    params.set('limit', String(query.limit))
  }
  if (query.status) {
    params.set('status', query.status)
  }
  if (query.asset_id) {
    params.set('asset_id', query.asset_id)
  }
  if (query.order_by) {
    params.set('order_by', query.order_by)
  }
  const qs = params.toString()
  return qs ? `${base}?${qs}` : base
}

export function getAssetParams(
  projectId: string,
  assetId: string,
  options?: ApiClientOptions,
): Promise<ParamsResponse> {
  return apiClient.get<ParamsResponse>(
    encodePath(['projects', projectId, 'assets', assetId, 'params']),
    options,
  )
}

export function runAsset(
  projectId: string,
  assetId: string,
  body: RunRequest,
  options?: ApiClientOptions,
): Promise<RunResponse> {
  return apiClient.post<RunResponse>(
    encodePath(['projects', projectId, 'assets', assetId, 'run']),
    body,
    options,
  )
}

export function listExecutionRecords(
  projectId: string,
  query: ExecutionListQuery = {},
  options?: ApiClientOptions,
): Promise<ExecutionRecordListItem[]> {
  return apiClient.get<ExecutionRecordListItem[]>(recordsPath(projectId, query), options)
}

export function getExecutionRecord(
  projectId: string,
  recordId: string,
  options?: ApiClientOptions,
): Promise<ExecutionRecordDetail> {
  return apiClient.get<ExecutionRecordDetail>(
    encodePath(['projects', projectId, 'execution-records', recordId]),
    options,
  )
}
