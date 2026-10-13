import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  getAssetParams,
  getCaseAssetDetail,
  getCaseExecutionRecord,
  getExecutionRecord,
  listExecutionRecords,
  runAsset,
  runCase,
} from './api'
import { ApiHttpError } from '@/shared/api/errors'

function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('executions api', () => {
  it('getAssetParams 路径编码并返回参数列表', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      jsonResponse({
        asset_id: 'api.user.create',
        params: [
          { name: 'username', type: 'string', required: true, description: '用户名' },
        ],
      }),
    )
    const result = await getAssetParams('p/1', 'api.user.create', {
      baseUrl: '',
      fetchImpl,
    })
    expect(fetchImpl.mock.calls[0][0]).toBe(
      '/projects/p%2F1/assets/api.user.create/params',
    )
    expect(result.params[0].name).toBe('username')
  })

  it('runAsset 提交 {params} body', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      jsonResponse({
        record_id: 'r1',
        status: 'success',
        duration: 0.01,
        result: { ok: true },
      }),
    )
    const body = { params: { username: 'alice', active: false } }
    const result = await runAsset('p1', 'api.user.login', body, {
      baseUrl: '',
      fetchImpl,
    })
    expect(result.status).toBe('success')
    expect(fetchImpl.mock.calls[0][1].method).toBe('POST')
    expect(JSON.parse(String(fetchImpl.mock.calls[0][1].body))).toEqual(body)
  })

  it('listExecutionRecords 拼接筛选与分页查询串', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse([]))
    await listExecutionRecords(
      'p1',
      {
        skip: 20,
        limit: 10,
        status: 'failed',
        asset_id: 'api.user.login',
        order_by: '-start_time',
      },
      { baseUrl: '', fetchImpl },
    )
    const url = String(fetchImpl.mock.calls[0][0])
    expect(url.startsWith('/projects/p1/execution-records?')).toBe(true)
    expect(url).toContain('skip=20')
    expect(url).toContain('limit=10')
    expect(url).toContain('status=failed')
    expect(url).toContain('asset_id=api.user.login')
    expect(url).toContain('order_by=-start_time')
  })

  it('getExecutionRecord 404 抛 ApiHttpError', async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(jsonResponse({ detail: 'Execution record not found' }, 404))
    await expect(
      getExecutionRecord('p1', 'missing', { baseUrl: '', fetchImpl }),
    ).rejects.toSatisfy((err: unknown) => {
      expect(err).toBeInstanceOf(ApiHttpError)
      expect((err as ApiHttpError).message).toBe('Execution record not found')
      return true
    })
  })

  it('列表响应非数组时抛 ApiParseError', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({ items: [] }))
    const { ApiParseError } = await import('@/shared/api/errors')
    await expect(
      listExecutionRecords('p1', {}, { baseUrl: '', fetchImpl }),
    ).rejects.toBeInstanceOf(ApiParseError)
  })

  it('run 响应缺 record_id 时抛 ApiParseError', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      jsonResponse({ status: 'success', duration: 1, result: {} }),
    )
    const { ApiParseError } = await import('@/shared/api/errors')
    await expect(
      runAsset('p1', 'api.user.login', { params: {} }, { baseUrl: '', fetchImpl }),
    ).rejects.toBeInstanceOf(ApiParseError)
  })
})

describe('Case executions api', () => {
  it('listExecutionRecords 支持 asset_type', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse([]))
    await listExecutionRecords(
      'p1',
      { asset_type: 'case', status: 'failed', asset_id: 'case.demo.x' },
      { baseUrl: '', fetchImpl },
    )
    const url = String(fetchImpl.mock.calls[0][0])
    expect(url).toContain('asset_type=case')
    expect(url).toContain('status=failed')
    expect(url).toContain('asset_id=case.demo.x')
  })

  it('getCaseAssetDetail / runCase / getCaseExecutionRecord 路径正确', async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse({
          case_id: 'case.demo.create_then_get',
          path: 'scenarios/demo/create_then_get.case.yaml',
          file_name: 'create_then_get.case.yaml',
          size_bytes: 10,
          modified_at: '2026-10-12T03:00:00Z',
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          record_id: 'r1',
          status: 'success',
          duration: 0.01,
          result: {
            case_id: 'case.demo.create_then_get',
            status: 'success',
            duration_seconds: 0.01,
            steps: [],
            summary: { total: 0, success: 0, failed: 0, skipped: 0 },
            error: null,
            logins: [],
          },
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          id: 'r1',
          project_id: 'p1',
          asset_id: 'case.demo.create_then_get',
          asset_type: 'case',
          status: 'success',
          start_time: '2026-10-12T11:30:00',
          end_time: null,
          duration: 0.01,
          display: { start_time: 't', end_time: null, duration: '10ms' },
          result: {
            case_id: 'case.demo.create_then_get',
            status: 'success',
            duration_seconds: 0.01,
            steps: [],
            summary: { total: 0, success: 0, failed: 0, skipped: 0 },
            error: null,
            logins: [],
          },
        }),
      )

    await getCaseAssetDetail('p1', 'case.demo.create_then_get', {
      baseUrl: '',
      fetchImpl,
    })
    expect(fetchImpl.mock.calls[0][0]).toBe(
      '/projects/p1/cases/case.demo.create_then_get',
    )

    await runCase('p1', 'case.demo.create_then_get', { params: {} }, {
      baseUrl: '',
      fetchImpl,
    })
    expect(fetchImpl.mock.calls[1][0]).toBe(
      '/projects/p1/cases/case.demo.create_then_get/run',
    )
    expect(JSON.parse(String(fetchImpl.mock.calls[1][1].body))).toEqual({
      params: {},
    })

    await getCaseExecutionRecord('p1', 'r1', { baseUrl: '', fetchImpl })
    expect(fetchImpl.mock.calls[2][0]).toBe(
      '/projects/p1/case-execution-records/r1',
    )
  })
})
