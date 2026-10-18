import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor, cleanup } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ConfigProvider } from 'antd'
import { StoredParameters } from './StoredParameters'
import { ApiHttpError } from '@/shared/api/errors'
import type { ParameterContext } from './types'

const getParameterContext = vi.fn()
const saveParameterSet = vi.fn()
vi.mock('./api', () => ({ getParameterContext: (...args: unknown[]) => getParameterContext(...args), saveParameterSet: (...args: unknown[]) => saveParameterSet(...args) }))
const initial: ParameterContext = {
  project_id: 'main/demo', asset_type: 'api', asset_id: 'api.demo', env: 'test', commit_sha: 'abc',
  environment_revision: 1, git_defaults: { count: 1 }, shared_environment: {},
  asset_default: { values: {}, revision: 0 }, environment_override: { values: {}, revision: 0 },
  effective: { count: 1 }, sources: { count: 'git' },
}
function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<ConfigProvider theme={{ token: { motion: false } }}><QueryClientProvider client={client}>
    <StoredParameters projectId="main/demo" assetType="api" assetId="api.demo" env="test" commit="abc">
      {(context) => <div data-testid="effective">{JSON.stringify(context?.effective)}</div>}
    </StoredParameters>
  </QueryClientProvider></ConfigProvider>)
}
beforeEach(() => { vi.clearAllMocks(); getParameterContext.mockResolvedValue(initial) })
afterEach(cleanup)
describe('当前资产参数保存', () => {
  it('显式保存本层，刷新生效值，清空后不发送旧默认值', async () => {
    const user = userEvent.setup()
    setup()
    await screen.findByTestId('effective')
    await user.click(screen.getByRole('button', { name: '维护 test 覆盖' }))
    fireEvent.change(screen.getByLabelText('持久化参数 JSON'), { target: { value: '{"count":0,"active":false}' } })
    saveParameterSet.mockImplementation(async () => {
      getParameterContext.mockResolvedValue({ ...initial, environment_override: { values: { count: 0, active: false }, revision: 1 }, effective: { count: 0, active: false } })
      return { revision: 1, values: { count: 0, active: false } }
    })
    await user.click(screen.getByRole('button', { name: '保存参数' }))
    await waitFor(() => expect(screen.getByTestId('effective')).toHaveTextContent('"count":0'))
    expect(saveParameterSet).toHaveBeenCalledWith('main/demo', 'api', 'api.demo', 'test', { scope: 'environment_override', values: { count: 0, active: false }, revision: 0, commit_sha: 'abc' })
    await user.click(screen.getByRole('button', { name: '维护 test 覆盖' }))
    expect(screen.getByLabelText('持久化参数 JSON')).toHaveValue(JSON.stringify({ count: 0, active: false }, null, 2))
    fireEvent.change(screen.getByLabelText('持久化参数 JSON'), { target: { value: '{}' } })
    await user.click(screen.getByRole('button', { name: '保存参数' }))
    await waitFor(() => expect(saveParameterSet).toHaveBeenLastCalledWith('main/demo', 'api', 'api.demo', 'test', { scope: 'environment_override', values: {}, revision: 1, commit_sha: 'abc' }))
  })
  it('冲突保留草稿和旧版本，不自动重试覆盖；非法 JSON 不提交', async () => {
    const user = userEvent.setup()
    setup()
    await screen.findByTestId('effective')
    await user.click(screen.getByRole('button', { name: '维护默认值' }))
    fireEvent.change(screen.getByLabelText('持久化参数 JSON'), { target: { value: '[]' } })
    await user.click(screen.getByRole('button', { name: '保存参数' }))
    expect(saveParameterSet).not.toHaveBeenCalled()
    fireEvent.change(screen.getByLabelText('持久化参数 JSON'), { target: { value: '{"count":0}' } })
    saveParameterSet.mockRejectedValue(new ApiHttpError(409, '参数集版本冲突，请刷新后再保存', ''))
    await user.click(screen.getByRole('button', { name: '保存参数' }))
    await screen.findByText('参数集版本冲突，请刷新后再保存')
    expect(screen.getByLabelText('持久化参数 JSON')).toHaveValue('{"count":0}')
    expect(saveParameterSet).toHaveBeenCalledTimes(1)
  })
  it('配置读取失败与资产版本过期均不呈现运行内容', async () => {
    getParameterContext.mockRejectedValue(new Error('unavailable'))
    const view = setup()
    await screen.findByText('参数配置加载失败')
    expect(screen.queryByTestId('effective')).not.toBeInTheDocument()
    view.unmount()
    getParameterContext.mockResolvedValue({ ...initial, commit_sha: 'new' })
    setup()
    await screen.findByText('资产版本已更新，请刷新工作区后运行或维护参数')
    expect(screen.queryByTestId('effective')).not.toBeInTheDocument()
  })
  it('仅明确未升级服务的缺路由兼容旧调试，资产缺失不回退', async () => {
    getParameterContext.mockRejectedValue(new ApiHttpError(404, 'Not Found', ''))
    const view = setup()
    await screen.findByText('当前服务尚未启用参数保存；可继续使用已有默认值和本次输入。')
    expect(screen.getByTestId('effective')).toBeInTheDocument()
    view.unmount()
    getParameterContext.mockRejectedValue(new ApiHttpError(404, 'Asset not found', ''))
    setup()
    await screen.findByText('参数配置加载失败')
    expect(screen.queryByTestId('effective')).not.toBeInTheDocument()
  })
})
