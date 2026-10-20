import { parseExecutionAuth } from './auth'
import { parseLoginRecords } from './loginDisplay'
import { ApiParseError } from '@/shared/api/errors'
import {
  assertArray,
  assertObject,
  readOptionalNullableInteger,
  requireInteger,
  requireNullableNumber,
  requireNullableString,
  requireNumber,
  requireString,
} from '@/shared/api/validate'
import type {
  ScenarioStepDefinition,
  ScenarioDefinition,
  ScenarioTrace,
  CaseAssetDetail,
  CaseExecutionRecordDetail,
  CaseResult,
  CaseRunResponse,
  CaseStepError,
  CaseStepRequest,
  CaseStepResponse,
  CaseStepResult,
  CaseStepStatus,
  CaseSummary,
  CaseSystemError,
  ExecutionDisplay,
} from './types'

function parseDefinition(value: unknown, label: string): ScenarioDefinition {
  assertObject(value, label)
  if (value.schema_version !== '0.3' || (value.kind !== 'case' && value.kind !== 'flow')) {
    throw new ApiParseError(`${label} 版本或类型非法`, String(value.schema_version))
  }
  assertObject(value.params, `${label}.params`)
  assertObject(value.inputs, `${label}.inputs`)
  assertObject(value.outputs, `${label}.outputs`)
  assertArray(value.steps, `${label}.steps`)
  return {
    schema_version: '0.3', kind: value.kind,
    id: requireString(value, 'id', label), name: requireNullableString(value, 'name', label),
    params: value.params, inputs: value.inputs, outputs: value.outputs,
    steps: value.steps.map((step, index) => {
      const path = `${label}.steps[${index}]`
      assertObject(step, path)
      if (!['api', 'flow', 'map', 'extract', 'decimal', 'assert', 'transform'].includes(String(step.type))) throw new ApiParseError(`${path}.type 非法`, String(step.type))
      assertObject(step.params, `${path}.params`)
      return { step_id: requireString(step, 'step_id', path), type: step.type as ScenarioStepDefinition['type'],
        asset_id: requireString(step, 'asset_id', path), name: requireNullableString(step, 'name', path),
        params: step.params, output: requireNullableString(step, 'output', path),
        identity: requireNullableString(step, 'identity', path),
        ...parseConfiguration(step, path),
        ...(step.definition ? { definition: parseDefinition(step.definition, `${path}.definition`) } : {}),
      }
    }),
  }
}

/** Validate display data only; Engine owns DSL validation and execution. */
function parseConfiguration(step: Record<string, unknown>, label: string): Partial<ScenarioStepDefinition> {
  const result: Partial<ScenarioStepDefinition> = {}
  for (const key of ['source', 'cardinality', 'value_type', 'operation', 'rounding'] as const) {
    if (step[key] != null) result[key] = requireString(step, key, label)
  }
  if (step.selector != null) { assertObject(step.selector, `${label}.selector`); result.selector = step.selector }
  if (step.nullable != null) {
    if (typeof step.nullable !== 'boolean') throw new ApiParseError(`${label}.nullable 非法`, '')
    result.nullable = step.nullable
  }
  if ('operands' in step) result.operands = step.operands
  if (step.scale != null) result.scale = requireInteger(step, 'scale', label)
  if (step.path != null) {
    assertArray(step.path, `${label}.path`)
    if (!step.path.every(part => typeof part === 'string' || Number.isInteger(part))) throw new ApiParseError(`${label}.path 非法`, '')
    result.path = step.path as (string | number)[]
  }
  return result
}

function parseTrace(value: unknown, label: string): ScenarioTrace {
  assertObject(value, label)
  assertObject(value.inputs, `${label}.inputs`)
  if (!('outputs' in value)) throw new ApiParseError(`${label}.outputs 缺失`, '')
  assertArray(value.bindings, `${label}.bindings`)
  assertArray(value.children, `${label}.children`)
  return {
    node_id: requireString(value, 'node_id', label), parent_id: requireNullableString(value, 'parent_id', label),
    asset_id: requireString(value, 'asset_id', label), inputs: value.inputs, outputs: value.outputs,
    children: value.children.map((step, index) => parseStepResult(step, index)),
    ...parseEvidence(value, label),
    bindings: value.bindings.map((binding, index) => {
      const path = `${label}.bindings[${index}]`
      assertObject(binding, path)
      return { target_path: requireString(binding, 'target_path', path),
        reference: requireString(binding, 'reference', path),
        source_node_id: requireNullableString(binding, 'source_node_id', path),
        value: binding.value, value_type: requireString(binding, 'value_type', path) }
    }),
  }
}

function parseEvidence(value: Record<string, unknown>, label: string): Partial<ScenarioTrace> {
  const result: Partial<ScenarioTrace> = {}
  if (value.iteration_index != null) {
    const index = requireInteger(value, 'iteration_index', label)
    if (index < 0) throw new ApiParseError(`${label}.iteration_index 非法`, '')
    result.iteration_index = index
  }
  for (const key of ['extracts', 'calculations', 'assertions', 'transforms'] as const) {
    if (value[key] != null) {
      const entries = value[key]
      assertArray(entries, `${label}.${key}`)
      result[key] = entries.map((entry, index) => { assertObject(entry, `${label}.${key}[${index}]`); return entry })
    }
  }
  return result
}

function parseCaseStepStatus(value: string, label: string): CaseStepStatus {
  if (value !== 'success' && value !== 'failed' && value !== 'skipped') {
    throw new ApiParseError(`${label} 非法`, value)
  }
  return value
}

function parseSkipReason(
  value: unknown,
  label: string,
): 'fail_fast' | 'login_failed' | null {
  if (value === null || value === undefined) {
    return null
  }
  if (value === 'fail_fast' || value === 'login_failed') {
    return value
  }
  throw new ApiParseError(`${label} 非法`, JSON.stringify(value))
}

function parseStepRequest(
  value: unknown,
  label: string,
): CaseStepRequest | null {
  if (value === null || value === undefined) {
    return null
  }
  assertObject(value, label)
  const request: CaseStepRequest = {
    method: requireString(value, 'method', label),
    url: requireString(value, 'url', label),
  }
  if ('headers' in value) {
    if (
      value.headers === null ||
      value.headers === undefined ||
      (typeof value.headers === 'object' && !Array.isArray(value.headers))
    ) {
      request.headers = value.headers as Record<string, unknown> | undefined
    } else {
      throw new ApiParseError(`${label}.headers 非法`, JSON.stringify(value.headers))
    }
  }
  if ('body' in value) {
    request.body = value.body
  }
  if ('body_type' in value && value.body_type !== undefined && value.body_type !== null) {
    if (typeof value.body_type !== 'string') {
      throw new ApiParseError(`${label}.body_type 非法`, JSON.stringify(value.body_type))
    }
    request.body_type = value.body_type
  } else {
    request.body_type = 'json'
  }
  if ('query' in value) {
    const q = value.query
    if (q === null || q === undefined) {
      request.query = null
    } else if (typeof q === 'object' && !Array.isArray(q)) {
      request.query = q as Record<string, unknown>
    } else {
      throw new ApiParseError(`${label}.query 非法`, JSON.stringify(q))
    }
  }
  return request
}

function parseStepResponse(
  value: unknown,
  label: string,
): CaseStepResponse | null {
  if (value === null || value === undefined) {
    return null
  }
  assertObject(value, label)
  const response: CaseStepResponse = {
    status_code: requireInteger(value, 'status_code', label),
  }
  if ('headers' in value) {
    if (
      value.headers === null ||
      value.headers === undefined ||
      (typeof value.headers === 'object' && !Array.isArray(value.headers))
    ) {
      response.headers = value.headers as Record<string, unknown> | undefined
    } else {
      throw new ApiParseError(`${label}.headers 非法`, JSON.stringify(value.headers))
    }
  }
  if ('body' in value) {
    response.body = value.body
  }
  return response
}

function optionalNullableString(
  obj: Record<string, unknown>,
  key: string,
  label: string,
): string | null {
  if (!(key in obj) || obj[key] === undefined) {
    return null
  }
  return requireNullableString(obj, key, label)
}

function parseStepError(value: unknown, label: string): CaseStepError | null {
  if (value === null || value === undefined) {
    return null
  }
  assertObject(value, label)
  const stageRaw = value.stage
  let stage: 'preflight' | 'execution' | null = null
  if (stageRaw === undefined || stageRaw === null) {
    stage = null
  } else if (stageRaw === 'preflight' || stageRaw === 'execution') {
    stage = stageRaw
  } else {
    throw new ApiParseError(`${label}.stage 非法`, JSON.stringify(stageRaw))
  }
  const error: CaseStepError = {
    kind: requireString(value, 'kind', label),
    message: requireString(value, 'message', label),
    stage,
    step_id: optionalNullableString(value, 'step_id', label),
    path: optionalNullableString(value, 'path', label),
  }
  if ('login' in value && value.login !== undefined && value.login !== null) {
    if (typeof value.login !== 'object' || Array.isArray(value.login)) {
      throw new ApiParseError(`${label}.login 非法`, JSON.stringify(value.login))
    }
    error.login = value.login as CaseStepError['login']
  }
  return error
}

function parseStepResult(value: unknown, index: number): CaseStepResult {
  const label = `CaseResult.steps[${index}]`
  assertObject(value, label)
  const status = parseCaseStepStatus(
    requireString(value, 'status', label),
    `${label}.status`,
  )
  return {
    ...(value.trace ? { trace: parseTrace(value.trace, `${label}.trace`) } : {}),
    step_id: requireString(value, 'step_id', label),
    name: optionalNullableString(value, 'name', label),
    type: requireString(value, 'type', label),
    status,
    duration_seconds: requireNumber(value, 'duration_seconds', label),
    request: parseStepRequest(value.request, `${label}.request`),
    response: parseStepResponse(value.response, `${label}.response`),
    error: parseStepError(value.error, `${label}.error`),
    output: optionalNullableString(value, 'output', label),
    skip_reason: parseSkipReason(
      'skip_reason' in value ? value.skip_reason : null,
      `${label}.skip_reason`,
    ),
    auth: parseExecutionAuth(value.auth, `${label}.auth`),
  }
}

function parseSummary(value: unknown, label: string): CaseSummary {
  assertObject(value, label)
  return {
    total: requireInteger(value, 'total', label),
    success: requireInteger(value, 'success', label),
    failed: requireInteger(value, 'failed', label),
    skipped: requireInteger(value, 'skipped', label),
  }
}

function parseSystemError(value: unknown, label: string): CaseSystemError | null {
  if (value === null || value === undefined) {
    return null
  }
  assertObject(value, label)
  const kind = requireString(value, 'kind', label)
  if (kind !== 'timeout' && kind !== 'transport' && kind !== 'internal') {
    throw new ApiParseError(`${label}.kind 非法`, kind)
  }
  const stage = requireString(value, 'stage', label)
  if (stage !== 'execution') {
    throw new ApiParseError(`${label}.stage 非法`, stage)
  }
  return {
    kind,
    stage: 'execution',
    message: requireString(value, 'message', label),
  }
}

/** 解析 CaseResult；畸形时抛 ApiParseError，禁止用 any 绕过。 */
export function parseCaseResult(payload: unknown, label = 'CaseResult'): CaseResult {
  assertObject(payload, label)
  const statusRaw = requireString(payload, 'status', label)
  if (statusRaw !== 'success' && statusRaw !== 'failed') {
    throw new ApiParseError(`${label}.status 非法`, statusRaw)
  }
  assertArray(payload.steps, `${label}.steps`)
  return {
    ...('result_version' in payload ? { result_version: requireString(payload, 'result_version', label) } : {}),
    case_id: requireString(payload, 'case_id', label),
    status: statusRaw,
    duration_seconds: requireNumber(payload, 'duration_seconds', label),
    steps: payload.steps.map((step, index) => parseStepResult(step, index)),
    summary: parseSummary(payload.summary, `${label}.summary`),
    error: parseSystemError(
      'error' in payload ? payload.error : null,
      `${label}.error`,
    ),
    logins: parseLoginRecords(
      'logins' in payload ? payload.logins : [],
      `${label}.logins`,
    ),
  }
}

export function parseCaseAssetDetail(payload: unknown): CaseAssetDetail {
  assertObject(payload, 'CaseAssetDetail')
  return {
    ...(payload.definition ? { definition: parseDefinition(payload.definition, 'CaseAssetDetail.definition') } : {}),
    case_id: requireString(payload, 'case_id', 'CaseAssetDetail'),
    path: requireString(payload, 'path', 'CaseAssetDetail'),
    file_name: requireString(payload, 'file_name', 'CaseAssetDetail'),
    size_bytes: requireInteger(payload, 'size_bytes', 'CaseAssetDetail'),
    modified_at: requireString(payload, 'modified_at', 'CaseAssetDetail'),
  }
}

export function parseCaseRunResponse(payload: unknown): CaseRunResponse {
  assertObject(payload, 'CaseRunResponse')
  const status = requireString(payload, 'status', 'CaseRunResponse')
  if (status !== 'success' && status !== 'failed') {
    throw new ApiParseError('CaseRunResponse.status 非法', JSON.stringify(payload))
  }
  return {
    record_id: requireString(payload, 'record_id', 'CaseRunResponse'),
    status,
    duration: requireNullableNumber(payload, 'duration', 'CaseRunResponse'),
    result: parseCaseResult(payload.result, 'CaseRunResponse.result'),
    commit_sha:
      'commit_sha' in payload
        ? requireNullableString(payload, 'commit_sha', 'CaseRunResponse')
        : null,
    operator:
      'operator' in payload
        ? requireNullableString(payload, 'operator', 'CaseRunResponse')
        : null,
    config_revision: readOptionalNullableInteger(
      payload,
      'config_revision',
      'CaseRunResponse',
    ),
  }
}

function parseDisplay(payload: unknown, label: string): ExecutionDisplay {
  assertObject(payload, label)
  return {
    start_time: requireString(payload, 'start_time', label),
    end_time: requireNullableString(payload, 'end_time', label),
    duration: requireNullableString(payload, 'duration', label),
  }
}

export function parseCaseExecutionRecordDetail(
  payload: unknown,
): CaseExecutionRecordDetail {
  assertObject(payload, 'CaseExecutionRecordDetail')
  const assetType = requireString(payload, 'asset_type', 'CaseExecutionRecordDetail')
  if (assetType !== 'case') {
    throw new ApiParseError(
      'CaseExecutionRecordDetail.asset_type 必须为 case',
      JSON.stringify(payload),
    )
  }
  const result =
    payload.result === null || payload.result === undefined
      ? null
      : parseCaseResult(payload.result, 'CaseExecutionRecordDetail.result')
  return {
    id: requireString(payload, 'id', 'CaseExecutionRecordDetail'),
    project_id: requireString(payload, 'project_id', 'CaseExecutionRecordDetail'),
    asset_id: requireString(payload, 'asset_id', 'CaseExecutionRecordDetail'),
    asset_type: 'case',
    status: requireString(payload, 'status', 'CaseExecutionRecordDetail'),
    start_time: requireString(payload, 'start_time', 'CaseExecutionRecordDetail'),
    end_time: requireNullableString(payload, 'end_time', 'CaseExecutionRecordDetail'),
    duration: requireNullableNumber(payload, 'duration', 'CaseExecutionRecordDetail'),
    display: parseDisplay(payload.display, 'CaseExecutionRecordDetail.display'),
    result,
    env:
      'env' in payload
        ? requireNullableString(payload, 'env', 'CaseExecutionRecordDetail')
        : null,
    commit_sha:
      'commit_sha' in payload
        ? requireNullableString(payload, 'commit_sha', 'CaseExecutionRecordDetail')
        : null,
    repo:
      'repo' in payload
        ? requireNullableString(payload, 'repo', 'CaseExecutionRecordDetail')
        : null,
    operator:
      'operator' in payload
        ? requireNullableString(payload, 'operator', 'CaseExecutionRecordDetail')
        : null,
    config_revision: readOptionalNullableInteger(
      payload,
      'config_revision',
      'CaseExecutionRecordDetail',
    ),
  }
}

/** 首个 failed 步骤下标；全成功返回 -1 */
export function findFirstFailedStepIndex(steps: CaseStepResult[]): number {
  return steps.findIndex((step) => step.status === 'failed')
}
