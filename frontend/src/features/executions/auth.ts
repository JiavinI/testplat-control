/**
 * Phase 3.3b 公开身份（auth）字段的解析与展示判定。
 *
 * 契约来源：docs/phase3_3/openapi-phase3_3.json（Control Agent 2，七键 ExecutionAuth）。
 * 后端公开 auth 只有名字类字段，永远不含凭证值；前端只读取七键，其它键一律丢弃。
 * 旧三键响应（无 kind）按静态 header 缺省补齐，避免历史记录整页崩。
 */
import { ApiParseError } from '@/shared/api/errors'
import type { CaseStepResult, ExecutionAuth } from './types'

const SYSTEM_ERROR_KINDS = new Set(['timeout', 'transport', 'internal'])

function parseNameList(value: unknown, label: string): string[] {
  if (value === undefined || value === null) {
    return []
  }
  if (!Array.isArray(value) || value.some((item) => typeof item !== 'string')) {
    throw new ApiParseError(`${label} 非法`, JSON.stringify(value))
  }
  return [...(value as string[])]
}

function parseLoginRef(value: unknown, label: string): number | null {
  if (value === undefined || value === null) {
    return null
  }
  if (typeof value !== 'number' || !Number.isInteger(value) || value < 0) {
    throw new ApiParseError(`${label} 非法`, JSON.stringify(value))
  }
  return value
}

/**
 * 解析公开 auth：缺失或 null → null（匿名或“未发请求”，由调用方按上下文区分）。
 * 只挑出七个公开键；畸形时抛 ApiParseError，错误里只回显名字类结构。
 */
export function parseExecutionAuth(value: unknown, label: string): ExecutionAuth | null {
  if (value === undefined || value === null) {
    return null
  }
  if (typeof value !== 'object' || Array.isArray(value)) {
    throw new ApiParseError(`${label} 非法`, typeof value)
  }
  const obj = value as Record<string, unknown>
  if (typeof obj.identity !== 'string' || obj.identity === '') {
    throw new ApiParseError(`${label}.identity 非法`, typeof obj.identity)
  }
  // 兼容 Phase 3.3a 旧三键：缺 kind 时视为 static_headers
  const kind =
    obj.kind === undefined || obj.kind === null
      ? 'static_headers'
      : typeof obj.kind === 'string' && obj.kind !== ''
        ? obj.kind
        : (() => {
            throw new ApiParseError(`${label}.kind 非法`, typeof obj.kind)
          })()
  let tier: string | null = null
  if (obj.tier !== undefined && obj.tier !== null) {
    if (typeof obj.tier !== 'string') {
      throw new ApiParseError(`${label}.tier 非法`, typeof obj.tier)
    }
    tier = obj.tier
  }
  return {
    identity: obj.identity,
    kind,
    tier,
    header_names: parseNameList(obj.header_names, `${label}.header_names`),
    overridden_headers: parseNameList(obj.overridden_headers, `${label}.overridden_headers`),
    cookie_names: parseNameList(
      'cookie_names' in obj ? obj.cookie_names : [],
      `${label}.cookie_names`,
    ),
    login_ref: parseLoginRef(
      'login_ref' in obj ? obj.login_ref : null,
      `${label}.login_ref`,
    ),
  }
}

/** 展示模式：有身份 / 匿名执行 / 不适用（没有发出请求，身份无从谈起）。 */
export type AuthDisplayMode = 'identity' | 'anonymous' | 'not_applicable'

/** 单 API 结果与历史详情：auth 为 null 只有一种含义——匿名执行。 */
export function apiAuthDisplayMode(auth: ExecutionAuth | null): AuthDisplayMode {
  return auth ? 'identity' : 'anonymous'
}

/**
 * Case 步骤：auth 为 null 有两种含义，必须区分（设计稿 A4 / 3.3a 语义延续）。
 * - 因系统错误失败的步骤（error.stage === 'execution' 且 kind 为 timeout/transport/internal）
 *   与 request 一样为 null，并不代表匿名 → 显示“—”，绝不能显示“匿名”。
 * - skipped 步骤、发请求前就失败的步骤（request 为 null，含 login_failed）同样没有发出请求 → “—”。
 * - 其余（确实发出了请求）的 null 才是匿名执行。
 * - 若 auth 非空（含 login_failed 带 login_ref，A6）→ 按有身份展示。
 */
export function stepAuthDisplayMode(step: CaseStepResult): AuthDisplayMode {
  if (step.auth) {
    return 'identity'
  }
  const error = step.error
  if (error && error.stage === 'execution' && SYSTEM_ERROR_KINDS.has(error.kind)) {
    return 'not_applicable'
  }
  if (step.status === 'skipped' || step.request === null) {
    return 'not_applicable'
  }
  return 'anonymous'
}
