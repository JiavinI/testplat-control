import { describe, expect, it } from 'vitest'
import { loadContractExample } from '@/test/contractExamples'
import { ApiParseError } from '@/shared/api/errors'
import { parseRecordDetail, parseRunResponse } from './api'
import { apiAuthDisplayMode, parseExecutionAuth, stepAuthDisplayMode } from './auth'
import { parseCaseExecutionRecordDetail, parseCaseRunResponse } from './caseParse'
import type { CaseStepResult } from './types'

// 冻结契约示例（Control 12a8d6a，docs/phase3_3/examples/）直接作为解析输入，防止前后端漂移
const FAKE_SECRETS = ['tp-fake-secret-9f31c2a7', 'tp-fake-partner-4c8e11d0']

function baseStep(overrides: Partial<CaseStepResult>): CaseStepResult {
  return {
    step_id: 's',
    name: null,
    type: 'api',
    status: 'success',
    duration_seconds: 0.01,
    request: { method: 'GET', url: 'http://x/s' },
    response: { status_code: 200 },
    error: null,
    output: null,
    skip_reason: null,
    auth: null,
    ...overrides,
  }
}

describe('parseExecutionAuth（冻结示例）', () => {
  it('单 API 运行响应：顶层 auth 含身份名、header 名与被覆盖的 header 名', () => {
    const parsed = parseRunResponse(loadContractExample('api-run-with-auth.json'))
    expect(parsed.auth).toEqual({
      identity: 'admin',
      header_names: ['Authorization'],
      overridden_headers: ['authorization'],
    })
  })

  it('API 历史详情：顶层 auth 透传', () => {
    const parsed = parseRecordDetail(loadContractExample('api-history-detail-with-auth.json'))
    expect(parsed.auth?.identity).toBe('admin')
    expect(parsed.auth?.overridden_headers).toEqual(['authorization'])
  })

  it('Case 运行与历史详情：auth 在每个步骤上', () => {
    for (const parsed of [
      parseCaseRunResponse(loadContractExample('case-run-with-auth.json')).result,
      parseCaseExecutionRecordDetail(loadContractExample('case-history-detail-with-auth.json')).result!,
    ]) {
      expect(parsed.steps.map((step) => step.auth?.identity)).toEqual(['partner', 'partner'])
      expect(parsed.steps[0].auth?.header_names).toEqual(['X-Api-Key'])
      expect(parsed.steps[0].auth?.overridden_headers).toEqual([])
    }
  })

  it('缺失或 null → null（Phase 3 旧响应兼容）', () => {
    expect(parseExecutionAuth(undefined, 'x')).toBeNull()
    expect(parseExecutionAuth(null, 'x')).toBeNull()
    const legacy = parseRunResponse({ record_id: 'r', status: 'success', duration: 0, result: {} })
    expect(legacy.auth).toBeNull()
  })

  it('只保留三个名字键，多余键（即使含值）被丢弃', () => {
    const parsed = parseExecutionAuth(
      {
        identity: 'admin',
        header_names: ['Authorization'],
        overridden_headers: [],
        value: FAKE_SECRETS[0],
      },
      'x',
    )
    expect(JSON.stringify(parsed)).not.toContain(FAKE_SECRETS[0])
  })

  it('畸形 auth 抛 ApiParseError，错误不回显值', () => {
    expect(() => parseExecutionAuth('admin', 'x')).toThrow(ApiParseError)
    expect(() => parseExecutionAuth({ identity: '' }, 'x')).toThrow(ApiParseError)
    // 类型错误时 bodyText 只回显类型名，即便同一对象里有值也不会被带出
    try {
      parseExecutionAuth({ identity: 7, token: FAKE_SECRETS[1] }, 'x')
      throw new Error('应当抛出')
    } catch (error) {
      expect(error).toBeInstanceOf(ApiParseError)
      expect((error as ApiParseError).bodyText).not.toContain(FAKE_SECRETS[1])
      expect((error as ApiParseError).message).not.toContain(FAKE_SECRETS[1])
    }
    expect(() =>
      parseExecutionAuth({ identity: 'a', header_names: [1], overridden_headers: [] }, 'x'),
    ).toThrow(ApiParseError)
  })
})

describe('身份展示判定', () => {
  it('单 API：null 即匿名', () => {
    expect(apiAuthDisplayMode(null)).toBe('anonymous')
    expect(
      apiAuthDisplayMode({ identity: 'admin', header_names: [], overridden_headers: [] }),
    ).toBe('identity')
  })

  it('Case 步骤：发出请求且 auth 为 null → 匿名', () => {
    expect(stepAuthDisplayMode(baseStep({}))).toBe('anonymous')
  })

  it.each(['timeout', 'transport', 'internal'])(
    'Case 步骤：系统错误（%s · execution）的 null → “—”，不是匿名',
    (kind) => {
      const step = baseStep({
        status: 'failed',
        request: null,
        response: null,
        error: { kind, message: '后端文案', stage: 'execution', step_id: null, path: null },
      })
      expect(stepAuthDisplayMode(step)).toBe('not_applicable')
    },
  )

  it('Case 步骤：系统错误 kind 即使 request 非空也显示“—”', () => {
    const step = baseStep({
      status: 'failed',
      error: { kind: 'timeout', message: 'm', stage: 'execution', step_id: null, path: null },
    })
    expect(stepAuthDisplayMode(step)).toBe('not_applicable')
  })

  it('Case 步骤：skipped 与发请求前失败（request 为 null）→ “—”', () => {
    expect(
      stepAuthDisplayMode(
        baseStep({ status: 'skipped', request: null, response: null, skip_reason: 'fail_fast' }),
      ),
    ).toBe('not_applicable')
    expect(
      stepAuthDisplayMode(
        baseStep({
          status: 'failed',
          request: null,
          response: null,
          error: { kind: 'variable_resolution', message: 'm', stage: null, step_id: 's', path: null },
        }),
      ),
    ).toBe('not_applicable')
  })

  it('Case 步骤：业务断言失败但已发请求、auth 为 null → 匿名', () => {
    const step = baseStep({
      status: 'failed',
      error: { kind: 'assertion', message: 'm', stage: null, step_id: null, path: null },
    })
    expect(stepAuthDisplayMode(step)).toBe('anonymous')
  })
})
