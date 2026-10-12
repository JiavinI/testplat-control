import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ConfigProvider, App as AntApp } from 'antd'
import { CaseExecutionPanel } from './CaseExecutionPanel'
import { ApiHttpError, ApiParseError } from '@/shared/api/errors'
import type { CaseRunResponse } from './types'

const runCase = vi.fn()
const listExecutionRecords = vi.fn()
const getCaseExecutionRecord = vi.fn()

vi.mock('./api', () => ({
  runCase: (...args: unknown[]) => runCase(...args),
  listExecutionRecords: (...args: unknown[]) => listExecutionRecords(...args),
  getCaseExecutionRecord: (...args: unknown[]) => getCaseExecutionRecord(...args),
  getAssetParams: vi.fn(),
  runAsset: vi.fn(),
  getExecutionRecord: vi.fn(),
  getCaseAssetDetail: vi.fn(),
}))

const successResponse: CaseRunResponse = {
  record_id: 'rec-ok',
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
        duration_seconds: 0.02,
        request: { method: 'POST', url: 'http://x/create' },
        response: { status_code: 201, body: { id: '1' } },
        error: null,
        output: 'created',
        skip_reason: null,
      },
      {
        step_id: 'get',
        name: null,
        type: 'api',
        status: 'success',
        duration_seconds: 0.01,
        request: { method: 'GET', url: 'http://x/get' },
        response: { status_code: 200, body: { ok: true } },
        error: null,
        output: null,
        skip_reason: null,
      },
    ],
    summary: { total: 2, success: 2, failed: 0, skipped: 0 },
    error: null,
  },
}

const failedSkipped: CaseRunResponse = {
  record_id: 'rec-fail',
  status: 'failed',
  duration: 0.01,
  result: {
    case_id: 'case.demo.assert_failed',
    status: 'failed',
    duration_seconds: 0.01,
    steps: [
      {
        step_id: 'bad',
        name: null,
        type: 'api',
        status: 'failed',
        duration_seconds: 0.01,
        request: { method: 'GET', url: 'http://x' },
        response: { status_code: 200 },
        error: { kind: 'assertion', message: '断言失败', stage: null, step_id: null, path: null },
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
  },
}

function renderPanel(caseId = 'case.demo.create_then_get') {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <ConfigProvider theme={{ token: { motion: false } }}>
      <AntApp>
        <QueryClientProvider client={client}>
          <CaseExecutionPanel projectId="p1" caseId={caseId} />
        </QueryClientProvider>
      </AntApp>
    </ConfigProvider>,
  )
}

beforeEach(() => {
  runCase.mockReset()
  listExecutionRecords.mockReset()
  getCaseExecutionRecord.mockReset()
  listExecutionRecords.mockResolvedValue([])
})

afterEach(() => {
  vi.clearAllMocks()
})

describe('CaseExecutionPanel', () => {
  it('success：展示汇总与步骤，不预渲染全部 JSON', async () => {
    const user = userEvent.setup({ delay: null })
    runCase.mockResolvedValue(successResponse)
    renderPanel()

    await user.click(screen.getByRole('button', { name: '执行 Case' }))
    expect(await screen.findByTestId('case-result-view')).toBeInTheDocument()
    expect(screen.getAllByText(/成功（success）/).length).toBeGreaterThan(0)
    expect(runCase).toHaveBeenCalledWith('p1', 'case.demo.create_then_get', {
      params: {},
    })
    // 未点开步骤时，折叠面板内 JSON 可能仍在 DOM；以可点开的 header 为准
    expect(screen.getByText('create', { selector: 'code' })).toBeInTheDocument()
  })

  it('failed+skipped：突出首个失败，区分 skipped', async () => {
    const user = userEvent.setup({ delay: null })
    runCase.mockResolvedValue(failedSkipped)
    renderPanel('case.demo.assert_failed')

    await user.click(screen.getByRole('button', { name: '执行 Case' }))
    expect(await screen.findByTestId('first-failed-marker')).toBeInTheDocument()
    expect(screen.getAllByText(/已跳过（skipped）/).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/失败（failed）/).length).toBeGreaterThan(0)
  })

  it('422 preflight：展示 detail，不建结果区', async () => {
    const user = userEvent.setup({ delay: null })
    runCase.mockRejectedValue(
      new ApiHttpError(422, '步骤 only 引用未声明 alias', '{"detail":"..."}'),
    )
    renderPanel()
    await user.click(screen.getByRole('button', { name: '执行 Case' }))
    expect(await screen.findByText(/预检失败/)).toBeInTheDocument()
    expect(screen.getByText(/未声明 alias/)).toBeInTheDocument()
    expect(screen.queryByTestId('case-result-view')).not.toBeInTheDocument()
    expect(listExecutionRecords).not.toHaveBeenCalled()
  })

  it('5xx：按 asset_type=case 定位历史并展示步骤', async () => {
    const user = userEvent.setup({ delay: null })
    runCase.mockRejectedValue(new ApiHttpError(504, 'API 请求超时', '{"detail":"API 请求超时"}'))
    listExecutionRecords.mockResolvedValue([
      {
        id: 'rec-sys',
        asset_id: 'case.demo.create_then_get',
        status: 'failed',
        start_time: '2026-10-12T11:30:00',
        duration: 0.2,
      },
    ])
    getCaseExecutionRecord.mockResolvedValue({
      id: 'rec-sys',
      project_id: 'p1',
      asset_id: 'case.demo.create_then_get',
      asset_type: 'case',
      status: 'failed',
      start_time: '2026-10-12T11:30:00',
      end_time: null,
      duration: 0.2,
      display: { start_time: 't', end_time: null, duration: '200ms' },
      result: {
        case_id: 'case.demo.create_then_get',
        status: 'failed',
        duration_seconds: 0.2,
        steps: [
          {
            step_id: 'slow',
            name: null,
            type: 'api',
            status: 'failed',
            duration_seconds: 0.2,
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
          },
        ],
        summary: { total: 1, success: 0, failed: 1, skipped: 0 },
        error: { kind: 'timeout', stage: 'execution', message: 'API 请求超时' },
      },
    })

    renderPanel()
    await user.click(screen.getByRole('button', { name: '执行 Case' }))

    await waitFor(() => {
      expect(listExecutionRecords).toHaveBeenCalledWith(
        'p1',
        expect.objectContaining({
          asset_type: 'case',
          asset_id: 'case.demo.create_then_get',
          status: 'failed',
        }),
      )
    })
    expect(await screen.findByTestId('case-system-error-located')).toBeInTheDocument()
    expect(screen.getByText(/系统错误 · timeout/)).toBeInTheDocument()
  })

  it('malformed response：展示解析失败', async () => {
    const user = userEvent.setup({ delay: null })
    runCase.mockRejectedValue(new ApiParseError('CaseRunResponse.status 非法', '{}'))
    renderPanel()
    await user.click(screen.getByRole('button', { name: '执行 Case' }))
    expect(await screen.findByText(/响应格式异常/)).toBeInTheDocument()
  })

  it('执行中禁用防重复提交', async () => {
    const user = userEvent.setup({ delay: null })
    let resolveRun: (value: CaseRunResponse) => void = () => undefined
    runCase.mockImplementation(
      () =>
        new Promise<CaseRunResponse>((resolve) => {
          resolveRun = resolve
        }),
    )
    renderPanel()
    const btn = screen.getByRole('button', { name: '执行 Case' })
    await user.click(btn)
    expect(btn).toBeDisabled()
    expect(screen.getByText('执行中…')).toBeInTheDocument()
    resolveRun(successResponse)
    expect(await screen.findByTestId('case-result-view')).toBeInTheDocument()
  })
})
