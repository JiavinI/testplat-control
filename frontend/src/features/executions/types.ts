/**
 * 与后端 run / execution schemas 对齐的 DTO。
 * 字段名与可空语义保持一致，避免前端另发明契约。
 */

export type ParamType = 'string' | 'number' | 'boolean'

export type RunStatus = 'success' | 'failed'

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
