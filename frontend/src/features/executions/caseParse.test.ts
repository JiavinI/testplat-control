import { describe, expect, it } from 'vitest'
import { ApiParseError } from '@/shared/api/errors'
import {
  findFirstFailedStepIndex,
  parseCaseAssetDetail,
  parseCaseExecutionRecordDetail,
  parseCaseResult,
  parseCaseRunResponse,
} from './caseParse'

const successRun = {
  record_id: '00000000-0000-4000-8000-000000000001',
  status: 'success',
  duration: 0.04,
  result: {
    case_id: 'case.demo.create_then_get',
    status: 'success',
    duration_seconds: 0.039,
    steps: [
      {
        step_id: 'create',
        name: '创建资源',
        type: 'api',
        status: 'success',
        duration_seconds: 0.032,
        request: {
          method: 'POST',
          url: 'http://127.0.0.1:18080/demo/resources',
          headers: { 'Content-Type': 'application/json' },
          body: { name: 'alpha' },
        },
        response: {
          status_code: 201,
          headers: { 'content-type': 'application/json' },
          body: { id: 'res-42', access_token: '***' },
        },
        error: null,
        output: 'created',
        skip_reason: null,
      },
      {
        step_id: 'get',
        name: null,
        type: 'api',
        status: 'success',
        duration_seconds: 0.007,
        request: {
          method: 'GET',
          url: 'http://127.0.0.1:18080/demo/resources/item',
          headers: { 'X-Resource-Id': 'res-42' },
          body: null,
        },
        response: {
          status_code: 200,
          headers: { 'content-type': 'application/json' },
          body: { ok: true },
        },
        error: null,
        output: null,
        skip_reason: null,
      },
    ],
    summary: { total: 2, success: 2, failed: 0, skipped: 0 },
    error: null,
    logins: [],
  },
}

const failedRun = {
  record_id: 'r-fail',
  status: 'failed',
  duration: 0.008,
  result: {
    case_id: 'case.demo.assert_failed',
    status: 'failed',
    duration_seconds: 0.007,
    steps: [
      {
        step_id: 'bad_assert',
        name: null,
        type: 'api',
        status: 'failed',
        duration_seconds: 0.007,
        request: { method: 'GET', url: 'http://127.0.0.1:18080/status/200' },
        response: { status_code: 200, body: { ok: true } },
        error: {
          kind: 'assertion',
          message: '断言失败: 响应不符合成功条件',
          stage: null,
          step_id: null,
          path: null,
        },
        output: null,
        skip_reason: null,
      },
      {
        step_id: 'after',
        name: null,
        type: 'api',
        status: 'skipped',
        duration_seconds: 0,
        request: null,
        response: null,
        error: null,
        output: null,
        skip_reason: 'fail_fast',
      },
    ],
    summary: { total: 2, success: 0, failed: 1, skipped: 1 },
    error: null,
    logins: [],
  },
}

describe('caseParse', () => {
  it('解析 Case 元信息', () => {
    const detail = parseCaseAssetDetail({
      case_id: 'case.demo.create_then_get',
      path: 'scenarios/demo/create_then_get.case.yaml',
      file_name: 'create_then_get.case.yaml',
      size_bytes: 435,
      modified_at: '2026-10-12T03:00:00Z',
    })
    expect(detail.case_id).toBe('case.demo.create_then_get')
    expect(detail.size_bytes).toBe(435)
  })

  it('解析 success / failed+skipped 运行响应', () => {
    const ok = parseCaseRunResponse(successRun)
    expect(ok.status).toBe('success')
    expect(ok.result.summary).toEqual({ total: 2, success: 2, failed: 0, skipped: 0 })
    expect(findFirstFailedStepIndex(ok.result.steps)).toBe(-1)

    const failed = parseCaseRunResponse(failedRun)
    expect(failed.status).toBe('failed')
    expect(failed.result.steps[1].status).toBe('skipped')
    expect(failed.result.steps[1].skip_reason).toBe('fail_fast')
    expect(findFirstFailedStepIndex(failed.result.steps)).toBe(0)
  })

  it('解析系统错误历史详情（timeout partial_outcome）', () => {
    const detail = parseCaseExecutionRecordDetail({
      id: 'rec-timeout',
      project_id: 'p1',
      asset_id: 'case.demo.timeout',
      asset_type: 'case',
      status: 'failed',
      start_time: '2026-10-12T11:30:00',
      end_time: '2026-10-12T11:30:00.250',
      duration: 0.218,
      display: {
        start_time: '2026-10-12 11:30:00',
        end_time: '2026-10-12 11:30:00',
        duration: '218ms',
      },
      result: {
        case_id: 'case.demo.timeout',
        status: 'failed',
        duration_seconds: 0.216,
        steps: [
          {
            step_id: 'create',
            type: 'api',
            status: 'success',
            duration_seconds: 0.007,
            request: { method: 'POST', url: 'http://x' },
            response: { status_code: 201 },
            error: null,
            output: null,
            skip_reason: null,
            name: null,
          },
          {
            step_id: 'slow',
            type: 'api',
            status: 'failed',
            duration_seconds: 0.209,
            request: null,
            response: null,
            error: {
              kind: 'timeout',
              message: 'API 请求超时',
              stage: 'execution',
              step_id: null,
              path: null,
            },
            output: null,
            skip_reason: null,
            name: null,
          },
          {
            step_id: 'after',
            type: 'api',
            status: 'skipped',
            duration_seconds: 0,
            request: null,
            response: null,
            error: null,
            output: null,
            skip_reason: 'fail_fast',
            name: null,
          },
        ],
        summary: { total: 3, success: 1, failed: 1, skipped: 1 },
        error: { kind: 'timeout', stage: 'execution', message: 'API 请求超时' },
        logins: [],
      },
    })
    expect(detail.asset_type).toBe('case')
    expect(detail.result?.error?.kind).toBe('timeout')
    expect(findFirstFailedStepIndex(detail.result!.steps)).toBe(1)
  })

  it('畸形响应抛 ApiParseError', () => {
    expect(() => parseCaseRunResponse({ status: 'success' })).toThrow(ApiParseError)
    expect(() =>
      parseCaseResult({
        case_id: 'c',
        status: 'success',
        duration_seconds: 1,
        steps: 'nope',
        summary: { total: 0, success: 0, failed: 0, skipped: 0 },
      }),
    ).toThrow(ApiParseError)
    expect(() =>
      parseCaseExecutionRecordDetail({
        id: 'x',
        project_id: 'p',
        asset_id: 'case.x',
        asset_type: 'api',
        status: 'success',
        start_time: 't',
        display: { start_time: 't', end_time: null, duration: null },
        result: null,
      }),
    ).toThrow(ApiParseError)
  })
})
