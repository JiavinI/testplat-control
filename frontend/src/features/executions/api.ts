import { apiClient, encodePath } from '@/shared/api/client'
import type { ApiClientOptions } from '@/shared/api/client'
import { ApiParseError } from '@/shared/api/errors'
import {
  assertArray,
  assertObject,
  requireNullableNumber,
  requireNullableString,
  requireString,
} from '@/shared/api/validate'
import {
  parseCaseAssetDetail,
  parseCaseExecutionRecordDetail,
  parseCaseRunResponse,
} from './caseParse'
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
  if (query.asset_type) {
    params.set('asset_type', query.asset_type)
  }
  if (query.order_by) {
    params.set('order_by', query.order_by)
  }
  const qs = params.toString()
  return qs ? `${base}?${qs}` : base
}

function parseParamsResponse(payload: unknown): ParamsResponse {
  assertObject(payload, 'ParamsResponse')
  const assetId = requireString(payload, 'asset_id', 'ParamsResponse')
  assertArray(payload.params, 'ParamsResponse.params')
  const params = payload.params.map((item, index) => {
    assertObject(item, `ParamsResponse.params[${index}]`)
    const name = requireString(item, 'name', `ParamsResponse.params[${index}]`)
    const typeRaw = requireString(item, 'type', `ParamsResponse.params[${index}]`)
    if (typeRaw !== 'string' && typeRaw !== 'number' && typeRaw !== 'boolean') {
      throw new ApiParseError(
        `ParamsResponse.params[${index}].type 非法`,
        JSON.stringify(item),
      )
    }
    const type = typeRaw as 'string' | 'number' | 'boolean'
    if (typeof item.required !== 'boolean') {
      throw new ApiParseError(
        `ParamsResponse.params[${index}].required 应为布尔值`,
        JSON.stringify(item),
      )
    }
    const description =
      item.description === null || item.description === undefined
        ? null
        : typeof item.description === 'string'
          ? item.description
          : (() => {
              throw new ApiParseError(
                `ParamsResponse.params[${index}].description 非法`,
                JSON.stringify(item),
              )
            })()
    return { name, type, required: item.required, description }
  })
  return { asset_id: assetId, params }
}

function parseRunResponse(payload: unknown): RunResponse {
  assertObject(payload, 'RunResponse')
  const recordId = requireString(payload, 'record_id', 'RunResponse')
  const status = requireString(payload, 'status', 'RunResponse')
  if (status !== 'success' && status !== 'failed') {
    throw new ApiParseError('RunResponse.status 非法', JSON.stringify(payload))
  }
  return {
    record_id: recordId,
    status,
    duration: requireNullableNumber(payload, 'duration', 'RunResponse'),
    result: payload.result,
  }
}

function parseListItem(payload: unknown, index: number): ExecutionRecordListItem {
  assertObject(payload, `ExecutionRecordListItem[${index}]`)
  return {
    id: requireString(payload, 'id', `ExecutionRecordListItem[${index}]`),
    asset_id: requireString(payload, 'asset_id', `ExecutionRecordListItem[${index}]`),
    status: requireString(payload, 'status', `ExecutionRecordListItem[${index}]`),
    start_time: requireString(payload, 'start_time', `ExecutionRecordListItem[${index}]`),
    duration: requireNullableNumber(payload, 'duration', `ExecutionRecordListItem[${index}]`),
  }
}

function parseRecordDetail(payload: unknown): ExecutionRecordDetail {
  assertObject(payload, 'ExecutionRecordDetail')
  assertObject(payload.display, 'ExecutionRecordDetail.display')
  const display = payload.display
  const result =
    payload.result === null || payload.result === undefined
      ? null
      : (() => {
          assertObject(payload.result, 'ExecutionRecordDetail.result')
          return payload.result
        })()
  return {
    id: requireString(payload, 'id', 'ExecutionRecordDetail'),
    project_id: requireString(payload, 'project_id', 'ExecutionRecordDetail'),
    asset_id: requireString(payload, 'asset_id', 'ExecutionRecordDetail'),
    asset_type: requireString(payload, 'asset_type', 'ExecutionRecordDetail'),
    status: requireString(payload, 'status', 'ExecutionRecordDetail'),
    start_time: requireString(payload, 'start_time', 'ExecutionRecordDetail'),
    end_time: requireNullableString(payload, 'end_time', 'ExecutionRecordDetail'),
    duration: requireNullableNumber(payload, 'duration', 'ExecutionRecordDetail'),
    display: {
      start_time: requireString(display, 'start_time', 'ExecutionRecordDetail.display'),
      end_time: requireNullableString(display, 'end_time', 'ExecutionRecordDetail.display'),
      duration: requireNullableString(display, 'duration', 'ExecutionRecordDetail.display'),
    },
    result,
    request: payload.request ?? null,
    response: payload.response ?? null,
  }
}

export async function getAssetParams(
  projectId: string,
  assetId: string,
  options?: ApiClientOptions,
): Promise<ParamsResponse> {
  const payload = await apiClient.get<unknown>(
    encodePath(['projects', projectId, 'assets', assetId, 'params']),
    options,
  )
  return parseParamsResponse(payload)
}

export async function runAsset(
  projectId: string,
  assetId: string,
  body: RunRequest,
  options?: ApiClientOptions,
): Promise<RunResponse> {
  const payload = await apiClient.post<unknown>(
    encodePath(['projects', projectId, 'assets', assetId, 'run']),
    body,
    options,
  )
  return parseRunResponse(payload)
}

export async function listExecutionRecords(
  projectId: string,
  query: ExecutionListQuery = {},
  options?: ApiClientOptions,
): Promise<ExecutionRecordListItem[]> {
  const payload = await apiClient.get<unknown>(recordsPath(projectId, query), options)
  assertArray(payload, 'ExecutionRecordList')
  return payload.map((item, index) => parseListItem(item, index))
}

export async function getExecutionRecord(
  projectId: string,
  recordId: string,
  options?: ApiClientOptions,
): Promise<ExecutionRecordDetail> {
  const payload = await apiClient.get<unknown>(
    encodePath(['projects', projectId, 'execution-records', recordId]),
    options,
  )
  return parseRecordDetail(payload)
}

export async function getCaseAssetDetail(
  projectId: string,
  caseId: string,
  options?: ApiClientOptions,
): Promise<CaseAssetDetail> {
  const payload = await apiClient.get<unknown>(
    encodePath(['projects', projectId, 'cases', caseId]),
    options,
  )
  return parseCaseAssetDetail(payload)
}

/**
 * 同步等待 Case 跑完；不设客户端 Abort 超时。
 * Control 每步最多约 30s，N 步最坏约 N×30s，短超时会误杀仍在执行的请求。
 */
export async function runCase(
  projectId: string,
  caseId: string,
  body: CaseRunRequest = {},
  options?: ApiClientOptions,
): Promise<CaseRunResponse> {
  const payload = await apiClient.post<unknown>(
    encodePath(['projects', projectId, 'cases', caseId, 'run']),
    { params: body.params ?? {} },
    options,
  )
  return parseCaseRunResponse(payload)
}

export async function getCaseExecutionRecord(
  projectId: string,
  recordId: string,
  options?: ApiClientOptions,
): Promise<CaseExecutionRecordDetail> {
  const payload = await apiClient.get<unknown>(
    encodePath(['projects', projectId, 'case-execution-records', recordId]),
    options,
  )
  return parseCaseExecutionRecordDetail(payload)
}
