import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ConfigProvider, App as AntApp } from 'antd'
import { ExecutionHistory } from './ExecutionHistory'
import { ApiHttpError } from '@/shared/api/errors'
import type { ExecutionRecordDetail, ExecutionRecordListItem } from './types'

const listExecutionRecords = vi.fn()
const getExecutionRecord = vi.fn()

const getCaseExecutionRecord = vi.fn()

vi.mock('./api', () => ({
  listExecutionRecords: (...args: unknown[]) => listExecutionRecords(...args),
  getExecutionRecord: (...args: unknown[]) => getExecutionRecord(...args),
  getCaseExecutionRecord: (...args: unknown[]) => getCaseExecutionRecord(...args),
  getAssetParams: vi.fn(),
  runAsset: vi.fn(),
  runCase: vi.fn(),
  getCaseAssetDetail: vi.fn(),
}))

function makeItem(
  partial: Partial<ExecutionRecordListItem> & Pick<ExecutionRecordListItem, 'id'>,
): ExecutionRecordListItem {
  return {
    asset_id: 'api.user.login',
    status: 'success',
    start_time: '2026-10-10T08:00:00.000Z',
    duration: 0.01,
    ...partial,
  }
}

function renderHistory(
  projectId = 'main/demo',
  assetId?: string,
  envs: string[] = ['test', 'staging'],
) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <ConfigProvider theme={{ token: { motion: false } }}>
      <AntApp>
        <QueryClientProvider client={client}>
          <ExecutionHistory projectId={projectId} assetId={assetId} envs={envs} />
        </QueryClientProvider>
      </AntApp>
    </ConfigProvider>,
  )
}

beforeEach(() => {
  listExecutionRecords.mockReset()
  getExecutionRecord.mockReset()
  getCaseExecutionRecord.mockReset()
})

afterEach(() => {
  vi.clearAllMocks()
})

describe('ExecutionHistory', () => {
  it('按 status / asset_id / order_by 请求列表', async () => {
    const user = userEvent.setup({ delay: null })
    listExecutionRecords.mockResolvedValue([])
    renderHistory('main/demo', 'api.user.login')

    await waitFor(() => {
      expect(listExecutionRecords).toHaveBeenCalledWith(
        'main/demo',
        expect.objectContaining({
          skip: 0,
          limit: 20,
          asset_id: 'api.user.login',
          order_by: '-start_time',
        }),
      )
    })

    const statusFilter = screen.getByTestId('filter-status')
    await user.click(within(statusFilter).getByRole('combobox'))
    // antd Select 下拉项是 div[title]，没有 option role
    await user.click(await screen.findByTitle('failed'))

    await waitFor(() => {
      expect(listExecutionRecords).toHaveBeenCalledWith(
        'main/demo',
        expect.objectContaining({
          status: 'failed',
          asset_id: 'api.user.login',
        }),
      )
    })
  })

  it('返回条数 < limit 时禁用下一页（末页）', async () => {
    listExecutionRecords.mockResolvedValue([
      makeItem({ id: 'r1' }),
      makeItem({ id: 'r2', status: 'failed' }),
    ])
    renderHistory()

    expect(await screen.findByRole('button', { name: '查看记录 r1' })).toBeInTheDocument()

    const next = screen.getByRole('button', { name: '下一页' })
    expect(next).toBeDisabled()
    expect(screen.getByRole('button', { name: '上一页' })).toBeDisabled()
  })

  it('满页时可翻到下一页，再用不足一页判末页', async () => {
    const user = userEvent.setup({ delay: null })
    const page1 = Array.from({ length: 20 }, (_, i) =>
      makeItem({ id: `r-${i}`, start_time: `2026-10-10T08:${String(i).padStart(2, '0')}:00.000Z` }),
    )
    const page2 = [makeItem({ id: 'r-last' })]

    listExecutionRecords
      .mockResolvedValueOnce(page1)
      .mockResolvedValueOnce(page2)

    renderHistory()
    expect(await screen.findByRole('button', { name: '查看记录 r-0' })).toBeInTheDocument()

    const next = screen.getByRole('button', { name: '下一页' })
    expect(next).not.toBeDisabled()
    await user.click(next)

    await waitFor(() => {
      expect(listExecutionRecords).toHaveBeenLastCalledWith(
        'main/demo',
        expect.objectContaining({ skip: 20, limit: 20 }),
      )
    })
    expect(await screen.findByText('第 2 页')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '下一页' })).toBeDisabled()
  })

  it('详情展示 null request/response 与 parse_error', async () => {
    const user = userEvent.setup({ delay: null })
    listExecutionRecords.mockResolvedValue([makeItem({ id: 'r-bad', status: 'failed' })])
    const detail: ExecutionRecordDetail = {
      id: 'r-bad',
      project_id: 'main/demo',
      asset_id: 'api.user.login',
      asset_type: 'api',
      status: 'failed',
      start_time: '2026-10-10T08:00:00.000Z',
      end_time: null,
      duration: 0.25,
      display: {
        start_time: '2026-10-10 08:00:00',
        end_time: null,
        duration: '250ms',
      },
      result: { parse_error: 'invalid JSON', raw: '{not-json' },
      request: null,
      response: null,
    }
    getExecutionRecord.mockResolvedValue(detail)

    renderHistory()
    await user.click(await screen.findByRole('button', { name: '查看记录 r-bad' }))

    const drawer = await screen.findByTestId('execution-detail')
    expect(drawer).toHaveTextContent('结果解析失败：invalid JSON')
    expect(within(drawer).getByLabelText('详情 request')).toHaveTextContent('null')
    expect(within(drawer).getByLabelText('详情 response')).toHaveTextContent('null')
    expect(within(drawer).getByLabelText('详情 result')).toHaveTextContent('parse_error')
  })

  it('列表 404 展示 detail 并可重试', async () => {
    const user = userEvent.setup({ delay: null })
    listExecutionRecords
      .mockRejectedValueOnce(new ApiHttpError(404, 'Project not found', ''))
      .mockResolvedValueOnce([])

    renderHistory()
    expect(await screen.findByRole('alert')).toHaveTextContent('Project not found')
    await user.click(screen.getByRole('button', { name: '重试' }))
    expect(await screen.findByText('暂无执行记录')).toBeInTheDocument()
  })


  it('空白下一页仍可返回上一页', async () => {
    const user = userEvent.setup({ delay: null })
    const page1 = Array.from({ length: 20 }, (_, i) =>
      makeItem({ id: `r-${i}`, start_time: `2026-10-10T08:${String(i).padStart(2, '0')}:00.000Z` }),
    )

    listExecutionRecords
      .mockResolvedValueOnce(page1)
      .mockResolvedValueOnce([]) // 恰好满页后再翻，得到空页
      .mockResolvedValueOnce(page1)

    renderHistory()
    expect(await screen.findByRole('button', { name: '查看记录 r-0' })).toBeInTheDocument()
    // 列表应展示运行 ID（表头可能与 title 属性各一份）
    expect(screen.getAllByText('运行 ID').length).toBeGreaterThan(0)
    expect(screen.getAllByText('r-0').length).toBeGreaterThan(0)

    await user.click(screen.getByRole('button', { name: '下一页' }))
    expect(await screen.findByText('本页无记录，可返回上一页')).toBeInTheDocument()
    expect(screen.getByText('第 2 页')).toBeInTheDocument()

    const prev = screen.getByRole('button', { name: '上一页' })
    expect(prev).not.toBeDisabled()
    await user.click(prev)

    await waitFor(() => {
      expect(listExecutionRecords).toHaveBeenLastCalledWith(
        'main/demo',
        expect.objectContaining({ skip: 0, limit: 20 }),
      )
    })
    expect(await screen.findByText('第 1 页')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '查看记录 r-0' })).toBeInTheDocument()
  })

  it('空列表展示空态', async () => {
    listExecutionRecords.mockResolvedValue([])
    renderHistory()
    expect(await screen.findByText('暂无执行记录')).toBeInTheDocument()
  })
  it('Case 历史详情走类型化端点并渲染步骤', async () => {
    const user = userEvent.setup({ delay: null })
    listExecutionRecords.mockResolvedValue([
      makeItem({ id: 'case-rec', asset_id: 'case.demo.create_then_get', status: 'failed' }),
    ])
    getCaseExecutionRecord.mockResolvedValue({
      id: 'case-rec',
      project_id: 'main/demo',
      asset_id: 'case.demo.create_then_get',
      asset_type: 'case',
      status: 'failed',
      start_time: '2026-10-12T11:30:00',
      end_time: null,
      duration: 0.01,
      display: { start_time: 't', end_time: null, duration: '10ms' },
      result: {
        case_id: 'case.demo.create_then_get',
        status: 'failed',
        duration_seconds: 0.01,
        steps: [
          {
            step_id: 'bad',
            name: null,
            type: 'api',
            status: 'failed',
            duration_seconds: 0.01,
            request: null,
            response: null,
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
        logins: [],
      },
    })

    renderHistory()
    await user.click(await screen.findByRole('button', { name: '查看记录 case-rec' }))
    expect(await screen.findByTestId('execution-detail')).toHaveAttribute(
      'data-asset-type',
      'case',
    )
    expect(getCaseExecutionRecord).toHaveBeenCalledWith('main/demo', 'case-rec')
    expect(getExecutionRecord).not.toHaveBeenCalled()
    expect(screen.getByTestId('case-result-view')).toBeInTheDocument()
    expect(screen.getAllByText(/已跳过（skipped）/).length).toBeGreaterThan(0)
  })

  it('asset_type 筛选会带入列表查询', async () => {
    const user = userEvent.setup({ delay: null })
    listExecutionRecords.mockResolvedValue([])
    renderHistory()
    const typeFilter = screen.getByTestId('filter-asset-type')
    await user.click(within(typeFilter).getByRole('combobox'))
    await user.click(await screen.findByTitle('case'))
    await waitFor(() => {
      expect(listExecutionRecords).toHaveBeenCalledWith(
        'main/demo',
        expect.objectContaining({ asset_type: 'case' }),
      )
    })
  })

  it('按 env 筛选并在列表展示 env 与短 SHA', async () => {
    const user = userEvent.setup({ delay: null })
    listExecutionRecords.mockResolvedValue([
      makeItem({
        id: 'r-env',
        env: 'staging',
        commit_sha: 'abcdef0123456789abcdef0123456789abcdef01',
      }),
    ])
    renderHistory('main/demo')

    await screen.findByText('r-env')
    expect(screen.getByText('staging')).toBeInTheDocument()
    expect(screen.getByText('abcdef0')).toBeInTheDocument()

    const envFilter = screen.getByTestId('filter-env')
    await user.click(within(envFilter).getByRole('combobox'))
    await user.click(await screen.findByTitle('staging'))

    await waitFor(() => {
      expect(listExecutionRecords).toHaveBeenCalledWith(
        'main/demo',
        expect.objectContaining({ env: 'staging' }),
      )
    })
  })

  it('详情抽屉展示 env 与短 SHA', async () => {
    const user = userEvent.setup({ delay: null })
    listExecutionRecords.mockResolvedValue([
      makeItem({
        id: 'r-detail',
        env: 'test',
        commit_sha: 'abcdef0123456789abcdef0123456789abcdef01',
      }),
    ])
    getExecutionRecord.mockResolvedValue({
      id: 'r-detail',
      project_id: 'main/demo',
      asset_id: 'api.user.login',
      asset_type: 'api',
      status: 'success',
      start_time: '2026-10-10T08:00:00.000Z',
      end_time: '2026-10-10T08:00:01.000Z',
      duration: 0.01,
      display: {
        start_time: '2026-10-10 08:00:00',
        end_time: '2026-10-10 08:00:01',
        duration: '10ms',
      },
      result: { status: 'success' },
      request: null,
      response: null,
      auth: null,
      env: 'test',
      commit_sha: 'abcdef0123456789abcdef0123456789abcdef01',
    })
    renderHistory()
    await screen.findByText('r-detail')
    await user.click(screen.getByRole('button', { name: '查看记录 r-detail' }))
    const detail = await screen.findByTestId('execution-detail')
    expect(within(detail).getByText('test')).toBeInTheDocument()
    expect(within(detail).getByText('abcdef0')).toBeInTheDocument()
  })
})
