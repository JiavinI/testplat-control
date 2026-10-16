import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ConfigProvider, App as AntApp } from 'antd'
import { ApiExecutionPanel } from './ApiExecutionPanel'
import { ApiHttpError, ApiNetworkError } from '@/shared/api/errors'
import type { ParamsResponse, RunResponse } from './types'
import { executionKeys } from './hooks'

const getAssetParams = vi.fn()
const runAsset = vi.fn()
const listExecutionRecords = vi.fn()

vi.mock('./api', () => ({
  getAssetParams: (...args: unknown[]) => getAssetParams(...args),
  runAsset: (...args: unknown[]) => runAsset(...args),
  listExecutionRecords: (...args: unknown[]) => listExecutionRecords(...args),
  getExecutionRecord: vi.fn(),
}))

const mixedParams: ParamsResponse = {
  asset_id: 'api.demo.mixed',
  params: [
    { name: 'username', type: 'string', required: true, description: '用户名' },
    { name: 'nickname', type: 'string', required: false, description: null },
    { name: 'age', type: 'number', required: false, description: null },
    { name: 'active', type: 'boolean', required: false, description: null },
  ],
}

const emptyParams: ParamsResponse = {
  asset_id: 'api.common.health_check',
  params: [],
}

function renderPanel(
  projectId = 'main/demo',
  assetId = 'api.demo.mixed',
  env = 'test',
) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  const view = render(
    <ConfigProvider theme={{ token: { motion: false } }}>
      <AntApp>
        <QueryClientProvider client={client}>
          <ApiExecutionPanel projectId={projectId} assetId={assetId} env={env} />
        </QueryClientProvider>
      </AntApp>
    </ConfigProvider>,
  )
  return { ...view, client }
}

function setInput(element: HTMLElement, value: string) {
  fireEvent.change(element, { target: { value } })
}

beforeEach(() => {
  getAssetParams.mockReset()
  runAsset.mockReset()
  listExecutionRecords.mockReset()
  listExecutionRecords.mockResolvedValue([])
})

afterEach(() => {
  vi.clearAllMocks()
})

describe('ApiExecutionPanel', () => {
  it(
    '提交时做类型转换，空非必填省略，保留 false',
    async () => {
    const user = userEvent.setup({ delay: null })
    getAssetParams.mockResolvedValue(mixedParams)
    runAsset.mockResolvedValue({
      record_id: 'r-ok',
      status: 'success',
      duration: 0.02,
      result: { status: 'success', request: {}, response: { ok: true }, error: null },
    } satisfies RunResponse)

    renderPanel()
    await screen.findByLabelText('username')

    setInput(screen.getByTestId('param-username'), 'alice')
    setInput(screen.getByTestId('param-nickname'), '')
    // age 留空；boolean 通过 Radio 选 false（antd 隐藏 input，用 fireEvent）
    fireEvent.click(within(screen.getByTestId('param-active')).getByRole('radio', { name: 'false' }))

    await user.click(screen.getByRole('button', { name: '执行 API' }))

    await waitFor(() => {
      expect(runAsset).toHaveBeenCalledWith(
        'main/demo',
        'api.demo.mixed',
        { env: 'test', params: { username: 'alice', active: false } },
      )
    })
    expect(runAsset.mock.calls[0][2].params).not.toHaveProperty('nickname')
    expect(runAsset.mock.calls[0][2].params).not.toHaveProperty('age')
    expect(await screen.findByTestId('execution-result')).toHaveTextContent('success')
    },
    15_000,
  )

  it('账号缺失时提示账号名和当前环境', async () => {
    const user = userEvent.setup({ delay: null })
    getAssetParams.mockResolvedValue(emptyParams)
    runAsset.mockRejectedValue(new ApiHttpError(422, '身份不存在: gsb', ''))
    renderPanel('main/demo', 'api.common.health_check', 'pre')
    await user.click(await screen.findByRole('button', { name: '执行 API' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(
      '账号 gsb 在环境 pre 缺失或不可用',
    )
    expect(screen.getByRole('alert')).toHaveTextContent('身份不存在: gsb')
  })

  it('执行结果展示操作人、环境、短 SHA 和配置版本', async () => {
    const user = userEvent.setup({ delay: null })
    getAssetParams.mockResolvedValue(emptyParams)
    runAsset.mockResolvedValue({
      record_id: 'r-meta',
      status: 'success',
      duration: 0.01,
      operator: 'alice',
      config_revision: 3,
      commit_sha: 'abcdef0123456789abcdef0123456789abcdef01',
      result: { status: 'success', request: {}, response: {}, error: null },
    } satisfies RunResponse)
    renderPanel('main/demo', 'api.common.health_check', 'test')
    await user.click(await screen.findByRole('button', { name: '执行 API' }))
    expect(await screen.findByTestId('run-result-operator')).toHaveTextContent('alice')
    expect(screen.getByTestId('run-result-env')).toHaveTextContent('test')
    expect(screen.getByTestId('run-result-commit-sha')).toHaveTextContent('abcdef0')
    expect(screen.getByTestId('run-result-config-revision')).toHaveTextContent('3')
  })

  it('422 展示 FastAPI detail，不进入结果区', async () => {
    const user = userEvent.setup({ delay: null })
    getAssetParams.mockResolvedValue(mixedParams)
    runAsset.mockRejectedValue(
      new ApiHttpError(422, "missing required param 'username'", ''),
    )

    renderPanel()
    await screen.findByLabelText('username')
    setInput(screen.getByLabelText('username'), 'x')
    await user.click(screen.getByRole('button', { name: '执行 API' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      "missing required param 'username'",
    )
    expect(screen.queryByTestId('execution-result')).not.toBeInTheDocument()
  })

  it('HTTP 200 + failed 展示结果，并刷新历史 query', async () => {
    getAssetParams.mockResolvedValue(emptyParams)
    runAsset.mockResolvedValue({
      record_id: 'r-fail',
      status: 'failed',
      duration: 0.2,
      result: {
        status: 'failed',
        request: { params: {} },
        response: null,
        error: 'assertion failed',
      },
    } satisfies RunResponse)

    const { client } = renderPanel('main/demo', 'api.common.health_check')
    const invalidateSpy = vi.spyOn(client, 'invalidateQueries')

    await screen.findByTestId('params-empty')
    fireEvent.click(screen.getByRole('button', { name: '执行 API' }))

    const result = await screen.findByTestId('execution-result')
    expect(result).toHaveTextContent('failed')
    expect(result).toHaveTextContent('assertion failed')
    expect(result).toHaveTextContent('r-fail')

    await waitFor(() => {
      expect(invalidateSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          queryKey: [...executionKeys.all, 'records', 'main/demo'],
        }),
      )
    })
  })

  it('success 同样刷新历史 query', async () => {
    getAssetParams.mockResolvedValue(emptyParams)
    runAsset.mockResolvedValue({
      record_id: 'r-ok',
      status: 'success',
      duration: 0.01,
      result: { status: 'success' },
    } satisfies RunResponse)

    const { client } = renderPanel('main/demo', 'api.common.health_check')
    const invalidateSpy = vi.spyOn(client, 'invalidateQueries')

    await screen.findByTestId('params-empty')
    fireEvent.click(screen.getByRole('button', { name: '执行 API' }))
    await screen.findByTestId('execution-result')

    await waitFor(() => {
      expect(invalidateSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          queryKey: [...executionKeys.all, 'records', 'main/demo'],
        }),
      )
    })
  })

  it('提交中禁用重复执行', async () => {
    getAssetParams.mockResolvedValue(emptyParams)
    let resolveRun: (value: RunResponse) => void = () => undefined
    runAsset.mockImplementation(
      () =>
        new Promise<RunResponse>((resolve) => {
          resolveRun = resolve
        }),
    )

    renderPanel('main/demo', 'api.common.health_check')
    await screen.findByTestId('params-empty')

    const btn = screen.getByRole('button', { name: '执行 API' })
    fireEvent.click(btn)

    await waitFor(() => {
      expect(btn).toBeDisabled()
    })
    expect(screen.getByText(/执行中/)).toBeInTheDocument()

    resolveRun({
      record_id: 'r1',
      status: 'success',
      duration: 0.01,
      result: {},
    })
    await screen.findByTestId('execution-result')
  })

  it('切换资产清空参数、错误与结果', async () => {
    const user = userEvent.setup({ delay: null })
    getAssetParams
      .mockResolvedValueOnce(mixedParams)
      .mockResolvedValueOnce(emptyParams)
    runAsset.mockRejectedValue(new ApiHttpError(500, 'boom', ''))

    const { rerender, client } = renderPanel('main/demo', 'api.demo.mixed')
    await screen.findByLabelText('username')
    setInput(screen.getByLabelText('username'), 'stale')
    await user.click(screen.getByRole('button', { name: '执行 API' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('boom')

    rerender(
      <ConfigProvider theme={{ token: { motion: false } }}>
        <AntApp>
          <QueryClientProvider client={client}>
            <ApiExecutionPanel projectId="main/demo" assetId="api.common.health_check" env="test" />
          </QueryClientProvider>
        </AntApp>
      </ConfigProvider>,
    )

    expect(await screen.findByTestId('params-empty')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.queryByTestId('execution-result')).not.toBeInTheDocument()
    expect(screen.queryByDisplayValue('stale')).not.toBeInTheDocument()
  })

  it('网络错误展示为网络错误文案', async () => {
    getAssetParams.mockResolvedValue(emptyParams)
    runAsset.mockRejectedValue(new ApiNetworkError(new Error('Failed to fetch')))

    renderPanel('main/demo', 'api.common.health_check')
    await screen.findByTestId('params-empty')
    fireEvent.click(screen.getByRole('button', { name: '执行 API' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/网络错误/)
  })

  it('参数加载 404 可重试', async () => {
    const user = userEvent.setup({ delay: null })
    getAssetParams
      .mockRejectedValueOnce(new ApiHttpError(404, 'Asset not found', ''))
      .mockResolvedValueOnce(emptyParams)

    renderPanel('main/demo', 'api.missing')
    expect(await screen.findByRole('alert')).toHaveTextContent('Asset not found')
    await user.click(screen.getByRole('button', { name: '重试' }))
    expect(await screen.findByTestId('params-empty')).toBeInTheDocument()
  })
})
