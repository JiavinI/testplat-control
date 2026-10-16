/**
 * 与后端 run / execution / Case schemas 对齐的 DTO。
 * 字段名与可空语义保持一致，避免前端另发明契约。
 */

export type ParamType = 'string' | 'number' | 'boolean'

export type RunStatus = 'success' | 'failed'

export type CaseStepStatus = 'success' | 'failed' | 'skipped'

export type CaseSystemErrorKind = 'timeout' | 'transport' | 'internal'

/**
 * Phase 3.3d 公开身份（九键）：只有名字与档位，没有秘密值。
 * null 的含义由上下文决定：单 API / 历史详情里是匿名执行；
 * Case 步骤里也可能是“没有发出请求”（见 auth.ts）。
 * 旧记录缺 session_source / reauthenticated 时解析侧按 null / false 兼容。
 */
export interface ExecutionAuth {
  identity: string
  /** static_headers | login */
  kind: string
  /** generic | configured | plugin；静态 header 为 null */
  tier: string | null
  header_names: string[]
  overridden_headers: string[]
  /** 携带的 Cookie 名（不含值）；静态 header 恒为 [] */
  cookie_names: string[]
  /** 指向结果顶层 logins 下标；静态 header 或未登录 / 缓存命中为 null */
  login_ref: number | null
  /** login / execution / cache；静态 header 或旧记录为 null */
  session_source: string | null
  /** 本步是否触发了 401 重登重发；旧记录缺省 false */
  reauthenticated: boolean
}

/** 登录失败 reason 枚举（与 Engine LOGIN_FAILURE_REASONS 对齐） */
export type LoginFailureReason =
  | 'assertion'
  | 'extract_missing'
  | 'token_too_short'
  | 'probe_failed'
  | 'timeout'
  | 'transport'
  | 'strategy_error'
  | string

/** 结果顶层 logins[] 单条（已脱敏） */
export interface LoginRecord {
  identity: string
  strategy: string
  tier: string | null
  status: 'success' | 'failed' | string
  duration_seconds: number
  steps: LoginStepRecord[]
  probe: LoginStepRecord | null
  error: { reason?: string; failed_step?: string | null; [key: string]: unknown } | null
}

export interface LoginStepRecord {
  name: string
  request: CaseStepRequest | null
  response: CaseStepResponse | null
}

export type BodyType = 'json' | 'form' | 'query' | 'raw' | string

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
  /** 必填：须在项目 envs 内，否则后端 422 */
  env: string
  params: Record<string, string | number | boolean>
  request_override?: { body: unknown }
}

export interface RunResponse {
  record_id: string
  status: RunStatus
  duration: number | null
  result: unknown
  /** 顶层公开身份；旧后端无此键时视为 null（匿名） */
  auth?: ExecutionAuth | null
  /** 本次执行固定的 commit；缺省兼容旧响应 */
  commit_sha?: string | null
  /** 平台操作人；旧响应缺省 */
  operator?: string | null
  /** 启动时冻结的环境 revision；没有则不展示 */
  config_revision?: number | null
}

export interface ExecutionRecordListItem {
  id: string
  asset_id: string
  status: string
  start_time: string
  duration: number | null
  /**
   * 可选：历史列表标记「登录失败」。
   * 后端列表契约暂未冻结此字段；e2e mock 与后续后端可提供。
   */
  login_failed?: boolean
  env?: string | null
  commit_sha?: string | null
  repo?: string | null
  operator?: string | null
  config_revision?: number | null
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
  /** 顶层公开身份；Phase 3.3 之前的旧记录无此键 → null（匿名） */
  auth?: ExecutionAuth | null
  env?: string | null
  commit_sha?: string | null
  repo?: string | null
  operator?: string | null
  config_revision?: number | null
}

export interface ExecutionListQuery {
  skip?: number
  limit?: number
  status?: string
  asset_id?: string
  /** Phase 3：可选 api | case */
  asset_type?: 'api' | 'case'
  /** Phase 4.0：按运行环境过滤 */
  env?: string
  order_by?: string
}

export type ApiExecutionPanelProps = {
  projectId: string
  assetId: string
  /** 运行必填 env；由工作台环境下拉传入 */
  env: string
  /**
   * 当前环境的 case_params。
   * 已有默认值时必填项可以留空，空白不写入本次请求，显式输入仍然优先。
   */
  caseParams?: Record<string, unknown>
  requestDefinition?: Record<string, unknown>
  runDisabled?: boolean
}

export type ExecutionHistoryProps = {
  assetTypeScope?: 'api' | 'case'
  projectId: string
  assetId?: string
  /** 项目可选环境，供历史筛选下拉 */
  envs?: string[]
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
  /** 必填：须在项目 envs 内 */
  env: string
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
  /** Phase 3.3b：json/form/query/raw，缺省视为 json（A8） */
  body_type?: BodyType
  /** query 类型请求的参数对象（已脱敏）；其它类型为 null/缺省 */
  query?: Record<string, unknown> | null
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
  /** login_failed 时后端附带的登录错误摘要（无秘密） */
  login?: {
    identity?: string | null
    strategy?: string | null
    failed_step?: string | null
    reason?: LoginFailureReason | null
    [key: string]: unknown
  } | null
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
  skip_reason: 'fail_fast' | 'login_failed' | null
  /** 步骤公开身份；null 时需结合 status / error / request 区分“匿名”与“—” */
  auth?: ExecutionAuth | null
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
  /** 本次执行的登录记录（已脱敏）；无登录时为 []（A8） */
  logins: LoginRecord[]
}

export interface CaseRunResponse {
  record_id: string
  status: RunStatus
  duration: number | null
  result: CaseResult
  commit_sha?: string | null
  operator?: string | null
  config_revision?: number | null
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
  env?: string | null
  commit_sha?: string | null
  repo?: string | null
  operator?: string | null
  config_revision?: number | null
}

export type CaseExecutionPanelProps = {
  projectId: string
  caseId: string
  env: string
}
