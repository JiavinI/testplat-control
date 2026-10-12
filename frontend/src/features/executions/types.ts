/**
 * 与后端 run / execution / Case schemas 对齐的 DTO。
 * 字段名与可空语义保持一致，避免前端另发明契约。
 */

export type ParamType = 'string' | 'number' | 'boolean'

export type RunStatus = 'success' | 'failed'

export type CaseStepStatus = 'success' | 'failed' | 'skipped'

export type CaseSystemErrorKind = 'timeout' | 'transport' | 'internal'

export interface ParamInfo {
  name: string
  type: ParamType
  required: boolean
  description: string | null
}

export interface ParamsResponse {
  asset_id: string
  params: ParamInfo[]
}

export interface RunRequest {
  params: Record<string, string | number | boolean>
}

export interface RunResponse {
  record_id: string
  status: RunStatus
  duration: number | null
  result: unknown
}

export interface ExecutionRecordListItem {
  id: string
  asset_id: string
  status: string
  start_time: string
  duration: number | null
}

export interface ExecutionDisplay {
  start_time: string
  end_time: string | null
  duration: string | null
}

export interface ExecutionRecordDetail {
  id: string
  project_id: string
  asset_id: string
  asset_type: string
  status: string
  start_time: string
  end_time: string | null
  duration: number | null
  display: ExecutionDisplay
  result: Record<string, unknown> | null
  request: unknown
  response: unknown
}

export interface ExecutionListQuery {
  skip?: number
  limit?: number
  status?: string
  asset_id?: string
  /** Phase 3：可选 api | case */
  asset_type?: 'api' | 'case'
  order_by?: string
}

export type ApiExecutionPanelProps = {
  projectId: string
  assetId: string
}

export type ExecutionHistoryProps = {
  projectId: string
  assetId?: string
}

/** GET /projects/{id}/cases/{case_id} */
export interface CaseAssetDetail {
  case_id: string
  path: string
  file_name: string
  size_bytes: number
  modified_at: string
}

export interface CaseRunRequest {
  params?: Record<string, unknown>
}

export interface CaseSummary {
  total: number
  success: number
  failed: number
  skipped: number
}

export interface CaseStepRequest {
  method: string
  url: string
  headers?: Record<string, unknown>
  body?: unknown
}

export interface CaseStepResponse {
  status_code: number
  headers?: Record<string, unknown>
  body?: unknown
}

export interface CaseStepError {
  kind: string
  message: string
  stage?: 'preflight' | 'execution' | null
  step_id?: string | null
  path?: string | null
}

export interface CaseStepResult {
  step_id: string
  name: string | null
  type: string
  status: CaseStepStatus
  duration_seconds: number
  request: CaseStepRequest | null
  response: CaseStepResponse | null
  error: CaseStepError | null
  output: string | null
  skip_reason: 'fail_fast' | null
}

export interface CaseSystemError {
  kind: CaseSystemErrorKind
  stage: 'execution'
  message: string
}

export interface CaseResult {
  case_id: string
  status: RunStatus
  duration_seconds: number
  steps: CaseStepResult[]
  summary: CaseSummary
  error: CaseSystemError | null
}

export interface CaseRunResponse {
  record_id: string
  status: RunStatus
  duration: number | null
  result: CaseResult
}

export interface CaseExecutionRecordDetail {
  id: string
  project_id: string
  asset_id: string
  asset_type: 'case'
  status: string
  start_time: string
  end_time: string | null
  duration: number | null
  display: ExecutionDisplay
  result: CaseResult | null
}

export type CaseExecutionPanelProps = {
  projectId: string
  caseId: string
}
