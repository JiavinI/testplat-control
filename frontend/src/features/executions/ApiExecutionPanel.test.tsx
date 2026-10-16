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

const keywordParams: ParamsResponse = {
  asset_id: 'api.demo.search',
  params: [{ name: 'product_keyword', type: 'string', required: true, description: null }],
}

function renderPanel(
  projectId = 'main/demo',
  assetId = 'api.demo.mixed',
  env = 'test',
  caseParams?: Record<string, unknown>,
  requestDefinition?: Record<string, unknown>,
) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  const view = render(panelTree(client, { projectId, assetId, env, caseParams, requestDefinition }))
  return { ...view, client }
}

function panelTree(
  client: QueryClient,
  props: {
    projectId: string
    assetId: string
    env: string
    caseParams?: Record<string, unknown>
    requestDefinition?: Record<string, unknown>
  },
) {
  return (
    <ConfigProvider theme={{ token: { motion: false } }}>
      <AntApp>
        <QueryClientProvider client={client}>
          <ApiExecutionPanel
            projectId={props.projectId}
            assetId={props.assetId}
            env={props.env}
            caseParams={props.caseParams}
            requestDefinition={props.requestDefinition}
          />
        </QueryClientProvider>
      </AntApp>
    </ConfigProvider>
  )
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
    expect(await screen.findByTestId('api-run-response')).toHaveTextContent('success')
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
    await user.click(await screen.findByText('运行详情与登录过程'))
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
    expect(screen.queryByTestId('api-run-response')).not.toBeInTheDocument()
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

    const result = await screen.findByTestId('api-run-response')
    expect(result).toHaveTextContent('failed')
    expect(result).toHaveTextContent('assertion failed')
    fireEvent.click(screen.getByText('运行详情与登录过程'))
    expect(await screen.findByTestId('execution-result')).toHaveTextContent('r-fail')

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
    await screen.findByTestId('api-run-response')

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
    await screen.findByTestId('api-run-response')
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
    expect(screen.queryByTestId('api-run-response')).not.toBeInTheDocument()
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

  it('有环境默认值时必填可留空，切换环境或默认值后空白仍不写进请求，显式输入优先', async () => {
    const user = userEvent.setup({ delay: null })
    getAssetParams.mockResolvedValue(keywordParams)
    runAsset.mockResolvedValue({
      record_id: 'r-default',
      status: 'success',
      duration: 0.01,
      result: { status: 'success', request: {}, response: {}, error: null },
    } satisfies RunResponse)

    const { rerender, client } = renderPanel('main/demo', 'api.demo.search', 'pre', {
      product_keyword: 'web-default',
    })
    const field = await screen.findByLabelText('product_keyword')
    expect(field).toHaveAttribute('placeholder', '留空使用环境默认值')
    expect(field).toHaveValue('')
    await user.click(screen.getByRole('button', { name: '执行 API' }))
    await waitFor(() => {
      expect(runAsset).toHaveBeenCalledTimes(1)
    })
    expect(runAsset.mock.calls[0][2]).toEqual({ env: 'pre', params: {} })
    expect(runAsset.mock.calls[0][2].params).not.toHaveProperty('product_keyword')

    rerender(
      panelTree(client, {
        projectId: 'main/demo',
        assetId: 'api.demo.search',
        env: 'pre',
        caseParams: { product_keyword: 'updated-default' },
      }),
    )
    expect(screen.getByLabelText('product_keyword')).toHaveValue('')
    await user.click(screen.getByRole('button', { name: '执行 API' }))
    await waitFor(() => {
      expect(runAsset).toHaveBeenCalledTimes(2)
    })
    expect(runAsset.mock.calls[1][2]).toEqual({ env: 'pre', params: {} })
    expect(JSON.stringify(runAsset.mock.calls[1][2])).not.toContain('web-default')
    expect(JSON.stringify(runAsset.mock.calls[1][2])).not.toContain('updated-default')

    fireEvent.change(screen.getByLabelText('product_keyword'), {
      target: { value: 'explicit-keyword' },
    })
    rerender(
      panelTree(client, {
        projectId: 'main/demo',
        assetId: 'api.demo.search',
        env: 'pre',
        caseParams: { product_keyword: 'newer-default' },
      }),
    )
    expect(screen.getByLabelText('product_keyword')).toHaveValue('explicit-keyword')
    await user.click(screen.getByRole('button', { name: '执行 API' }))
    await waitFor(() => {
      expect(runAsset).toHaveBeenCalledTimes(3)
    })
    expect(runAsset.mock.calls[2][2]).toEqual({
      env: 'pre',
      params: { product_keyword: 'explicit-keyword' },
    })

    rerender(
      panelTree(client, {
        projectId: 'main/demo',
        assetId: 'api.demo.search',
        env: 'staging',
        caseParams: {},
      }),
    )
    expect(screen.getByLabelText('product_keyword')).toHaveAttribute('placeholder', '必填')
    fireEvent.change(screen.getByLabelText('product_keyword'), { target: { value: '' } })
    await user.click(screen.getByRole('button', { name: '执行 API' }))
    expect(await screen.findByText('请填写该参数')).toBeInTheDocument()
    expect(runAsset).toHaveBeenCalledTimes(3)

    rerender(
      panelTree(client, {
        projectId: 'main/demo',
        assetId: 'api.demo.search',
        env: 'staging',
        caseParams: { product_keyword: '   ' },
      }),
    )
    await user.click(screen.getByRole('button', { name: '执行 API' }))
    expect(await screen.findByText('请填写该参数')).toBeInTheDocument()
    expect(runAsset).toHaveBeenCalledTimes(3)
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

describe('完整临时请求内容', () => {
  it('允许增加、删除字段并发送整个 body，不要求填写模板参数', async () => {
    getAssetParams.mockResolvedValue(mixedParams)
    runAsset.mockResolvedValue({ record_id: 'temporary', status: 'success', duration: 0.1, result: {} })
    renderPanel('main/demo', 'api.demo.mixed', 'test', undefined, {
      type: 'json', body: { username: '${username}', old: 'delete me' },
    })
    await screen.findByTestId('api-execution-panel')
    fireEvent.click(screen.getByText('编辑完整请求内容'))
    const body = { added: 9, nested: { active: false }, items: [null], literal: '${username}' }
    fireEvent.change(screen.getByLabelText('临时请求内容'), { target: { value: JSON.stringify(body) } })
    fireEvent.click(screen.getByRole('button', { name: '执行 API' }))
    await waitFor(() => expect(runAsset).toHaveBeenCalledWith(
      'main/demo', 'api.demo.mixed', { env: 'test', params: {}, request_override: { body } },
    ))
  })

  it('JSON 语法有误时不发送，恢复后可以切回 YAML 模板', async () => {
    getAssetParams.mockResolvedValue(emptyParams)
    renderPanel('main/demo', 'api.common.health_check', 'test', undefined, { type: 'json', body: {} })
    await screen.findByTestId('api-execution-panel')
    fireEvent.click(screen.getByText('编辑完整请求内容'))
    fireEvent.change(screen.getByLabelText('临时请求内容'), { target: { value: '{broken' } })
    fireEvent.click(screen.getByRole('button', { name: '执行 API' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('临时请求内容不是合法 JSON')
    expect(runAsset).not.toHaveBeenCalled()
    fireEvent.click(screen.getByText('从 YAML 恢复'))
    expect(screen.getByLabelText('临时请求内容')).toHaveValue('{}')
    fireEvent.click(screen.getByText('使用 YAML 模板'))
    expect(screen.queryByLabelText('临时请求内容')).not.toBeInTheDocument()
  })
})


describe('协议与响应展示', () => {
  it('Query 拦截嵌套对象，允许增删标量并保留空值和 false', async () => {
    getAssetParams.mockResolvedValue(keywordParams)
    runAsset.mockResolvedValue({ record_id: 'query', status: 'success', duration: 0.1,
      result: { response: { status_code: 200, body: { errorCode: '0' } } } })
    renderPanel('main/demo', 'api.demo.search', 'test', undefined, {
      type: 'query', body: { keywords: '${product_keyword}' },
    })
    expect(await screen.findByLabelText('请求模板')).toHaveTextContent('keywords')
    fireEvent.click(screen.getByText('编辑完整请求内容'))
    setInput(screen.getByLabelText('临时请求内容'), '{"nested": {"x": 1}}')
    fireEvent.click(screen.getByRole('button', { name: '执行 API' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('一层标量键值对象')
    expect(runAsset).not.toHaveBeenCalled()
    const body = { keywords: '鞋 & 包', active: false, count: 2, empty: null }
    setInput(screen.getByLabelText('临时请求内容'), JSON.stringify(body))
    fireEvent.click(screen.getByRole('button', { name: '执行 API' }))
    await waitFor(() => expect(runAsset).toHaveBeenCalledWith('main/demo', 'api.demo.search', {
      env: 'test', params: {}, request_override: { body },
    }))
    expect(await screen.findByLabelText('响应内容')).toHaveTextContent('errorCode')
    expect(screen.queryByTestId('execution-result')).not.toBeInTheDocument()
  })

  it('JSON 模板 null 恢复后仍为 null，Raw 按原始字符串发送', async () => {
    getAssetParams.mockResolvedValue(emptyParams)
    runAsset.mockResolvedValue({ record_id: 'null', status: 'success', duration: 0, result: {} })
    const { rerender, client } = renderPanel('main/demo', 'api.demo.null', 'test', undefined, { type: 'json', body: null })
    await screen.findByTestId('api-execution-panel')
    fireEvent.click(screen.getByText('编辑完整请求内容'))
    expect(screen.getByLabelText('临时请求内容')).toHaveValue('null')
    fireEvent.click(screen.getByRole('button', { name: '执行 API' }))
    await waitFor(() => expect(runAsset).toHaveBeenCalledWith('main/demo', 'api.demo.null', {
      env: 'test', params: {}, request_override: { body: null },
    }))
    rerender(panelTree(client, { projectId: 'main/demo', assetId: 'api.demo.raw', env: 'test', requestDefinition: { type: 'raw', body: 'text' } }))
    await screen.findByTestId('api-execution-panel')
    fireEvent.click(screen.getByText('编辑完整请求内容'))
    setInput(screen.getByLabelText('临时请求内容'), 'literal ${value}\nraw')
    fireEvent.click(screen.getByRole('button', { name: '执行 API' }))
    await waitFor(() => expect(runAsset).toHaveBeenLastCalledWith('main/demo', 'api.demo.raw', {
      env: 'test', params: {}, request_override: { body: 'literal ${value}\nraw' },
    }))
  })

  it('HTTP 200 业务失败不展示为通过，默认展示响应体', async () => {
    getAssetParams.mockResolvedValue(emptyParams)
    runAsset.mockResolvedValue({ record_id: 'business-fail', status: 'failed', duration: 0.02,
      result: { response: { status_code: 200, body: { errorCode: '7' } }, error: { message: '业务码断言失败' } } })
    renderPanel()
    fireEvent.click(await screen.findByRole('button', { name: '执行 API' }))
    expect(await screen.findByTestId('api-business-result')).toHaveTextContent('执行未通过')
    expect(screen.getByTestId('api-run-response')).toHaveTextContent('HTTP 200')
    expect(screen.getByLabelText('响应内容')).toHaveTextContent('"7"')
    expect(screen.queryByText('业务判定通过')).not.toBeInTheDocument()
  })
})
