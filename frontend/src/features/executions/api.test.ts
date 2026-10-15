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

const PID = 'main/demo'

describe('executions api (Phase 4.0)', () => {
  it('getAssetParams 走两段式路径', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      jsonResponse({
        asset_id: 'api.user.create',
        params: [
          { name: 'username', type: 'string', required: true, description: '用户名' },
        ],
      }),
    )
    const result = await getAssetParams(PID, 'api.user.create', {
      baseUrl: '',
      fetchImpl,
    })
    expect(fetchImpl.mock.calls[0][0]).toBe(
      '/repos/main/projects/demo/assets/api.user.create/params',
    )
    expect(result.params[0].name).toBe('username')
  })

  it('runAsset 提交 {env, params} body 并解析 commit_sha', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      jsonResponse({
        record_id: 'r1',
        status: 'success',
        duration: 0.01,
        result: { ok: true },
        commit_sha: 'abcdef0123456789abcdef0123456789abcdef01',
      }),
    )
    const body = { env: 'test', params: { username: 'alice', active: false } }
    const result = await runAsset(PID, 'api.user.login', body, {
      baseUrl: '',
      fetchImpl,
    })
    expect(result.status).toBe('success')
    expect(result.commit_sha?.startsWith('abcdef0')).toBe(true)
    expect(fetchImpl.mock.calls[0][1].method).toBe('POST')
    expect(JSON.parse(String(fetchImpl.mock.calls[0][1].body))).toEqual(body)
  })

  it('listExecutionRecords 拼接 env 筛选与两段式路径', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse([]))
    await listExecutionRecords(
      PID,
      {
        skip: 20,
        limit: 10,
        status: 'failed',
        asset_id: 'api.user.login',
        env: 'staging',
        order_by: '-start_time',
      },
      { baseUrl: '', fetchImpl },
    )
    const url = String(fetchImpl.mock.calls[0][0])
    expect(url.startsWith('/repos/main/projects/demo/execution-records?')).toBe(
      true,
    )
    expect(url).toContain('skip=20')
    expect(url).toContain('env=staging')
    expect(url).toContain('status=failed')
  })

  it('列表项解析 env 与 commit_sha', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      jsonResponse([
        {
          id: 'r1',
          asset_id: 'api.x',
          status: 'success',
          start_time: '2026-10-15T00:00:00Z',
          duration: 0.1,
          env: 'test',
          commit_sha: 'abcdef0123456789abcdef0123456789abcdef01',
          repo: 'main',
          operator: null,
        },
      ]),
    )
    const rows = await listExecutionRecords(PID, {}, { baseUrl: '', fetchImpl })
    expect(rows[0].env).toBe('test')
    expect(rows[0].commit_sha?.slice(0, 7)).toBe('abcdef0')
  })

  it('getExecutionRecord 404 抛 ApiHttpError', async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(jsonResponse({ detail: 'Execution record not found' }, 404))
    await expect(
      getExecutionRecord(PID, 'missing', { baseUrl: '', fetchImpl }),
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
      listExecutionRecords(PID, {}, { baseUrl: '', fetchImpl }),
    ).rejects.toBeInstanceOf(ApiParseError)
  })

  it('run 响应缺 record_id 时抛 ApiParseError', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      jsonResponse({ status: 'success', duration: 1, result: {} }),
    )
    const { ApiParseError } = await import('@/shared/api/errors')
    await expect(
      runAsset(PID, 'api.user.login', { env: 'test', params: {} }, {
        baseUrl: '',
        fetchImpl,
      }),
    ).rejects.toBeInstanceOf(ApiParseError)
  })
})

describe('Case executions api (Phase 4.0)', () => {
  it('listExecutionRecords 支持 asset_type', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse([]))
    await listExecutionRecords(
      PID,
      { asset_type: 'case', status: 'failed', asset_id: 'case.demo.x' },
      { baseUrl: '', fetchImpl },
    )
    const url = String(fetchImpl.mock.calls[0][0])
    expect(url).toContain('asset_type=case')
    expect(url).toContain('/repos/main/projects/demo/')
  })

  it('getCaseAssetDetail / runCase / getCaseExecutionRecord 路径与 env', async () => {
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
          commit_sha: 'abcdef0123456789abcdef0123456789abcdef01',
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
          project_id: PID,
          asset_id: 'case.demo.create_then_get',
          asset_type: 'case',
          status: 'success',
          start_time: '2026-10-12T11:30:00',
          end_time: null,
          duration: 0.01,
          display: { start_time: 't', end_time: null, duration: '10ms' },
          env: 'test',
          commit_sha: 'abcdef0123456789abcdef0123456789abcdef01',
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

    await getCaseAssetDetail(PID, 'case.demo.create_then_get', {
      baseUrl: '',
      fetchImpl,
    })
    expect(fetchImpl.mock.calls[0][0]).toBe(
      '/repos/main/projects/demo/cases/case.demo.create_then_get',
    )

    await runCase(
      PID,
      'case.demo.create_then_get',
      { env: 'test', params: {} },
      { baseUrl: '', fetchImpl },
    )
    expect(fetchImpl.mock.calls[1][0]).toBe(
      '/repos/main/projects/demo/cases/case.demo.create_then_get/run',
    )
    expect(JSON.parse(String(fetchImpl.mock.calls[1][1].body))).toEqual({
      env: 'test',
      params: {},
    })

    const detail = await getCaseExecutionRecord(PID, 'r1', {
      baseUrl: '',
      fetchImpl,
    })
    expect(fetchImpl.mock.calls[2][0]).toBe(
      '/repos/main/projects/demo/case-execution-records/r1',
    )
    expect(detail.env).toBe('test')
    expect(detail.commit_sha?.slice(0, 7)).toBe('abcdef0')
  })
})
