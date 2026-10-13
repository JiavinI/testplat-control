/**
 * Phase 3.3b 登录过程与 login_failed 展示辅助。
 * 错误主文案一律来自后端 message/detail；reason 枚举仅做短标签映射，不发明错误正文。
 */
import type {
  CaseResult,
  CaseStepResult,
  LoginFailureReason,
  LoginRecord,
  LoginStepRecord,
} from './types'

/** reason → 短标签（只覆盖 Engine LOGIN_FAILURE_REASONS；未知 reason 原样展示） */
const LOGIN_REASON_LABELS: Record<string, string> = {
  assertion: '断言未通过',
  extract_missing: '提取缺失',
  token_too_short: 'token 过短',
  probe_failed: '探测失败',
  timeout: '超时',
  transport: '连接失败',
  strategy_error: '策略异常',
}

export function loginReasonLabel(reason: LoginFailureReason | null | undefined): string {
  if (reason === null || reason === undefined || reason === '') {
    return ''
  }
  return LOGIN_REASON_LABELS[reason] ?? String(reason)
}

/** 档位展示：通用 / 配置型 / 插件；未知原样 */
export function loginTierLabel(tier: string | null | undefined): string {
  if (tier === 'generic') return '通用'
  if (tier === 'configured') return '配置型'
  if (tier === 'plugin') return '插件'
  if (tier === null || tier === undefined || tier === '') return '—'
  return tier
}

export function bodyTypeLabel(bodyType: string | null | undefined): string {
  if (!bodyType) return 'json'
  return bodyType
}

export function skipReasonLabel(reason: 'fail_fast' | 'login_failed' | null): string {
  if (reason === 'login_failed') return '因登录失败跳过'
  if (reason === 'fail_fast') return '前序失败（fail_fast）'
  return ''
}

/** 步骤是否为登录失败（独立类别） */
export function isLoginFailedStep(step: CaseStepResult): boolean {
  return step.error?.kind === 'login_failed'
}

/** Case 结果是否含登录失败 */
export function caseHasLoginFailed(result: CaseResult): boolean {
  return result.steps.some((step) => isLoginFailedStep(step))
}

export function apiResultHasLoginFailed(result: unknown): boolean {
  if (!result || typeof result !== 'object' || Array.isArray(result)) {
    return false
  }
  const error = (result as Record<string, unknown>).error
  if (error && typeof error === 'object' && !Array.isArray(error)) {
    return (error as Record<string, unknown>).kind === 'login_failed'
  }
  return false
}

function parseLoginStep(raw: unknown): LoginStepRecord | null {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
    return null
  }
  const step = raw as Record<string, unknown>
  return {
    name: typeof step.name === 'string' ? step.name : 'step',
    request:
      step.request && typeof step.request === 'object' && !Array.isArray(step.request)
        ? (step.request as LoginStepRecord['request'])
        : null,
    response:
      step.response && typeof step.response === 'object' && !Array.isArray(step.response)
        ? (step.response as LoginStepRecord['response'])
        : null,
  }
}

/**
 * 宽松解析 logins[]：缺省 → []；单条畸形时跳过该条（不拖垮整页），
 * UI 只读已知字段，从不渲染未知秘密键。
 */
export function parseLoginRecords(value: unknown, label: string): LoginRecord[] {
  if (value === undefined || value === null) {
    return []
  }
  if (!Array.isArray(value)) {
    console.warn(`${label} 非法，已忽略`)
    return []
  }
  const out: LoginRecord[] = []
  for (const item of value) {
    if (!item || typeof item !== 'object' || Array.isArray(item)) {
      continue
    }
    const obj = item as Record<string, unknown>
    if (typeof obj.identity !== 'string' || typeof obj.strategy !== 'string') {
      continue
    }
    const stepsRaw = Array.isArray(obj.steps) ? obj.steps : []
    const steps: LoginStepRecord[] = []
    for (const s of stepsRaw) {
      const parsed = parseLoginStep(s)
      if (parsed) steps.push(parsed)
    }
    const probe = parseLoginStep(obj.probe)
    let error: LoginRecord['error'] = null
    if (obj.error && typeof obj.error === 'object' && !Array.isArray(obj.error)) {
      error = obj.error as LoginRecord['error']
    }
    const duration =
      typeof obj.duration_seconds === 'number' && !Number.isNaN(obj.duration_seconds)
        ? obj.duration_seconds
        : 0
    const tier =
      obj.tier === null || obj.tier === undefined
        ? null
        : typeof obj.tier === 'string'
          ? obj.tier
          : null
    out.push({
      identity: obj.identity,
      strategy: obj.strategy,
      tier,
      status: typeof obj.status === 'string' ? obj.status : 'success',
      duration_seconds: duration,
      steps,
      probe,
      error,
    })
  }
  return out
}

/** 从单 API 原始 result 取出 logins */
export function extractLoginsFromResult(result: unknown): LoginRecord[] {
  if (!result || typeof result !== 'object' || Array.isArray(result)) {
    return []
  }
  return parseLoginRecords((result as Record<string, unknown>).logins, 'result.logins')
}
