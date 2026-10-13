import { describe, expect, it } from 'vitest'
import {
  bodyTypeLabel,
  caseHasLoginFailed,
  loginReasonLabel,
  loginTierLabel,
  parseLoginRecords,
  skipReasonLabel,
} from './loginDisplay'
import type { CaseResult, CaseStepResult } from './types'

const FAKE = 'tp-fake-login-token-aabbcc'

function step(overrides: Partial<CaseStepResult>): CaseStepResult {
  return {
    step_id: 's',
    name: null,
    type: 'api',
    status: 'success',
    duration_seconds: 0.01,
    request: { method: 'GET', url: 'http://x', body_type: 'json' },
    response: { status_code: 200 },
    error: null,
    output: null,
    skip_reason: null,
    auth: null,
    ...overrides,
  }
}

describe('loginDisplay 映射', () => {
  it('reason 枚举映射；未知 reason 原样', () => {
    expect(loginReasonLabel('timeout')).toBe('超时')
    expect(loginReasonLabel('assertion')).toBe('断言未通过')
    expect(loginReasonLabel('weird_new')).toBe('weird_new')
  })

  it('档位与 skip_reason 文案区分 fail_fast / login_failed', () => {
    expect(loginTierLabel('generic')).toBe('通用')
    expect(loginTierLabel('configured')).toBe('配置型')
    expect(loginTierLabel('plugin')).toBe('插件')
    expect(skipReasonLabel('fail_fast')).toBe('前序失败（fail_fast）')
    expect(skipReasonLabel('login_failed')).toBe('因登录失败跳过')
    expect(bodyTypeLabel(undefined)).toBe('json')
    expect(bodyTypeLabel('query')).toBe('query')
  })

  it('parseLoginRecords 丢弃畸形项且不把秘密键带进结构之外的渲染数据', () => {
    const parsed = parseLoginRecords(
      [
        {
          identity: 'buyer',
          strategy: 'generic_flow',
          tier: 'generic',
          status: 'success',
          duration_seconds: 0.1,
          steps: [
            {
              name: 'login',
              request: { method: 'POST', url: 'http://x', body: { password: '***' }, body_type: 'json' },
              response: { status_code: 200, body: { token: '***' } },
            },
          ],
          probe: null,
          error: null,
          // 多余键不应被 UI 直接展开；解析结果对象仍可能保留在 error 之外——我们不拷贝未知顶层键
          secret: FAKE,
        },
        { not: 'a login' },
      ],
      't',
    )
    expect(parsed).toHaveLength(1)
    expect(parsed[0].identity).toBe('buyer')
    expect(JSON.stringify(parsed)).not.toContain(FAKE)
  })

  it('caseHasLoginFailed 识别步骤 kind', () => {
    const result: CaseResult = {
      case_id: 'c',
      status: 'failed',
      duration_seconds: 1,
      steps: [
        step({
          status: 'failed',
          request: null,
          response: null,
          error: { kind: 'login_failed', message: '后端文案', login: { reason: 'assertion' } },
        }),
      ],
      summary: { total: 1, success: 0, failed: 1, skipped: 0 },
      error: null,
      logins: [],
    }
    expect(caseHasLoginFailed(result)).toBe(true)
  })
})
