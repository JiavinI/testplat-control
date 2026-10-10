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

vi.mock('./api', () => ({
  listExecutionRecords: (...args: unknown[]) => listExecutionRecords(...args),
  getExecutionRecord: (...args: unknown[]) => getExecutionRecord(...args),
  getAssetParams: vi.fn(),
  runAsset: vi.fn(),
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

function renderHistory(projectId = 'p1', assetId?: string) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <ConfigProvider theme={{ token: { motion: false } }}>
      <AntApp>
        <QueryClientProvider client={client}>
          <ExecutionHistory projectId={projectId} assetId={assetId} />
        </QueryClientProvider>
      </AntApp>
    </ConfigProvider>,
  )
}

beforeEach(() => {
  listExecutionRecords.mockReset()
  getExecutionRecord.mockReset()
})

afterEach(() => {
  vi.clearAllMocks()
})

describe('ExecutionHistory', () => {
  it('按 status / asset_id / order_by 请求列表', async () => {
    const user = userEvent.setup({ delay: null })
    listExecutionRecords.mockResolvedValue([])
    renderHistory('p1', 'api.user.login')

    await waitFor(() => {
      expect(listExecutionRecords).toHaveBeenCalledWith(
        'p1',
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
        'p1',
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
        'p1',
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
      project_id: 'p1',
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

  it('空列表展示空态', async () => {
    listExecutionRecords.mockResolvedValue([])
    renderHistory()
    expect(await screen.findByText('暂无执行记录')).toBeInTheDocument()
  })
})
