import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { ConfigProvider, App as AntApp } from 'antd'
import { ProjectWorkspacePage } from './ProjectWorkspacePage'
import type { ProjectResponse } from '@/shared/types/project'
import type { AssetDetails, AssetNode } from '@/features/assets'
import type {
  ExecutionRecordDetail,
  ExecutionRecordListItem,
  ParamsResponse,
  RunResponse,
} from '@/features/executions'

const project: ProjectResponse = {
  id: 'main/demo',
  repo: 'main',
  project: 'demo',
  name: 'fixture-demo',
  envs: ['test', 'staging'],
  default_env: 'test',
  archived: false,
  commit_sha: 'abcdef0123456789abcdef0123456789abcdef01',
  created_at: '2026-10-10T00:00:00.000Z',
  updated_at: '2026-10-10T01:00:00.000Z',
}

const tree: AssetNode = {
  id: 'assets',
  name: 'assets',
  type: 'directory',
  path: '.',
  children: [
    {
      id: 'api',
      name: 'api',
      type: 'directory',
      path: 'api',
      children: [
        {
          id: 'api.user',
          name: 'user',
          type: 'directory',
          path: 'api/user',
          children: [
            {
              id: 'api.user.login',
              name: 'login.yaml',
              type: 'file',
              path: 'api/user/login.yaml',
              metadata: { method: 'POST' },
            },
          ],
        },
        {
          id: 'api.common',
          name: 'common',
          type: 'directory',
          path: 'api/common',
          children: [
            {
              id: 'api.common.health_check',
              name: 'health_check.yaml',
              type: 'file',
              path: 'api/common/health_check.yaml',
              metadata: { method: 'GET' },
            },
          ],
        },
      ],
    },
    {
      id: 'docs',
      name: 'readme.md',
      type: 'file',
      path: 'readme.md',
      metadata: { kind: 'doc' },
    },
  ],
}

const loginDetails: AssetDetails = {
  id: 'api.user.login',
  name: 'login.yaml',
  type: 'file',
  path: 'api/user/login.yaml',
  metadata: { name: '登录接口', method: 'POST', host: 'gsb', url: '/login', auth: 'gsb.b2.primary', request: { type: 'json', body: {} } },
}

const loginParams: ParamsResponse = {
  asset_id: 'api.user.login',
  params: [
    { name: 'username', type: 'string', required: false, description: '用户名' },
    { name: 'password', type: 'string', required: true, description: '密码' },
  ],
}

const runOk: RunResponse = {
  record_id: 'rec-1',
  status: 'success',
  duration: 0.05,
  commit_sha: 'abcdef0123456789abcdef0123456789abcdef01',
  result: {
    status: 'success',
    request: { method: 'POST' },
    response: { status_code: 200 },
    error: null,
  },
}

const historyItem: ExecutionRecordListItem = {
  id: 'rec-1',
  asset_id: 'api.user.login',
  status: 'success',
  start_time: '2026-10-10T02:00:00.000Z',
  duration: 0.05,
  env: 'test',
  commit_sha: 'abcdef0123456789abcdef0123456789abcdef01',
}

const historyDetail: ExecutionRecordDetail = {
  id: 'rec-1',
  project_id: 'main/demo',
  asset_id: 'api.user.login',
  asset_type: 'api',
  status: 'success',
  start_time: '2026-10-10T02:00:00.000Z',
  end_time: '2026-10-10T02:00:00.050Z',
  duration: 0.05,
  display: {
    start_time: '2026-10-10 10:00:00',
    end_time: '2026-10-10 10:00:00',
    duration: '50ms',
  },
  result: { status: 'success' },
  request: { method: 'POST' },
  response: { status_code: 200 },
  env: 'test',
  commit_sha: 'abcdef0123456789abcdef0123456789abcdef01',
}

const getProject = vi.fn()
const getAssetsTree = vi.fn()
const getAssetDetails = vi.fn()
const getAssetParams = vi.fn()
const runAsset = vi.fn()
const listExecutionRecords = vi.fn()
const getExecutionRecord = vi.fn()
const listEnvironments = vi.fn()
const listAccounts = vi.fn()

function dbEnv(env: string, enabled = true) {
  return {
    env,
    enabled,
    api_hosts: { gsb: 'http://127.0.0.1:9' },
    timeout_seconds: null,
    case_params: {},
    revision: 1,
    updated_by: 'alice',
  }
}

vi.mock('@/features/projects/api', () => ({
  getProject: (...args: unknown[]) => getProject(...args),
  listProjects: vi.fn(),
}))

vi.mock('@/features/assets/api', () => ({
  getAssetsTree: (...args: unknown[]) => getAssetsTree(...args),
  getAssetDetails: (...args: unknown[]) => getAssetDetails(...args),
}))

vi.mock('@/features/environments/api', () => ({
  listEnvironments: (...args: unknown[]) => listEnvironments(...args),
  listAccounts: (...args: unknown[]) => listAccounts(...args),
  listLoginProfiles: vi.fn().mockResolvedValue({ commit_sha: 'abc', profiles: [] }),
  createEnvironment: vi.fn(),
  updateEnvironment: vi.fn(),
  getEnvironment: vi.fn(),
  createAccount: vi.fn(),
  updateAccount: vi.fn(),
  getAccount: vi.fn(),
  getAccountCredentials: vi.fn(),
}))

vi.mock('@/features/executions/api', () => ({
  getParameterContext: vi.fn().mockImplementation(async (projectId, assetType, assetId, env) => {
    const environments = await listEnvironments(projectId)
    const shared = environments.find((item: { env: string }) => item.env === env)?.case_params ?? {}
    return {
    project_id: projectId, asset_type: assetType, asset_id: assetId, env, commit_sha: project.commit_sha,
    environment_revision: 1, git_defaults: {}, shared_environment: shared,
    asset_default: { values: {}, revision: 0 }, environment_override: { values: {}, revision: 0 }, effective: shared, sources: {},
  }}),
  saveParameterSet: vi.fn(),
  getAssetParams: (...args: unknown[]) => getAssetParams(...args),
  runAsset: (...args: unknown[]) => runAsset(...args),
  listExecutionRecords: (...args: unknown[]) => listExecutionRecords(...args),
  getExecutionRecord: (...args: unknown[]) => getExecutionRecord(...args),
  getCaseAssetDetail: vi.fn(),
  runCase: vi.fn(),
  getCaseExecutionRecord: vi.fn(),
}))

function renderWorkspace(repo = 'main', projectKey = 'demo') {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <ConfigProvider theme={{ token: { motion: false } }}>
      <AntApp>
        <QueryClientProvider client={client}>
          <MemoryRouter initialEntries={[`/projects/${repo}/${projectKey}`]}>
            <Routes>
              <Route
                path="/projects/:repo/:project"
                element={<ProjectWorkspacePage />}
              />
              <Route path="/configuration/:repo/:project" element={<div data-testid="config-route">config</div>} />
              <Route path="/projects" element={<div data-testid="list-route">list</div>} />
            </Routes>
          </MemoryRouter>
        </QueryClientProvider>
      </AntApp>
    </ConfigProvider>,
  )
}

function clickTreeNode(user: ReturnType<typeof userEvent.setup>, assetId: string) {
  const el = document.querySelector(`[data-asset-id="${assetId}"]`)
  if (!el) {
    throw new Error(`tree node not found: ${assetId}`)
  }
  return user.click(el)
}

beforeEach(() => {
  getProject.mockReset()
  getAssetsTree.mockReset()
  getAssetDetails.mockReset()
  getAssetParams.mockReset()
  runAsset.mockReset()
  listExecutionRecords.mockReset()
  getExecutionRecord.mockReset()
  listEnvironments.mockReset()
  listAccounts.mockReset()

  getProject.mockResolvedValue(project)
  listEnvironments.mockResolvedValue([dbEnv('test'), dbEnv('staging')])
  listAccounts.mockResolvedValue([])
  getAssetsTree.mockResolvedValue(tree)
  getAssetDetails.mockResolvedValue(loginDetails)
  getAssetParams.mockResolvedValue(loginParams)
  runAsset.mockResolvedValue(runOk)
  listExecutionRecords.mockResolvedValue([])
  getExecutionRecord.mockResolvedValue(historyDetail)
})

afterEach(() => {
  vi.clearAllMocks()
})

describe('ProjectWorkspacePage 集成', () => {
  it('进工作台 → 选 API → 填参 → 运行 → 历史 → 详情', async () => {
    const user = userEvent.setup({ delay: null })
    listExecutionRecords.mockResolvedValue([{ ...historyItem }])

    renderWorkspace()

    expect(await screen.findByTestId('project-workspace')).toBeInTheDocument()
    expect(await screen.findByTestId('project-workspace')).toBeInTheDocument()
    expect(await screen.findByTestId('asset-browser')).toHaveAttribute(
      'data-layout',
      'tree',
    )
    expect(screen.queryByTestId('api-execution-panel')).not.toBeInTheDocument()

    // 展开并选择可运行 API
    await clickTreeNode(user, 'api')
    await clickTreeNode(user, 'api.user')
    await clickTreeNode(user, 'api.user.login')

    expect(await screen.findByTestId('api-execution-panel')).toBeInTheDocument()
    expect(await screen.findByTestId('api-info-panel')).toHaveTextContent(
      'gsb.b2.primary',
    )
    await screen.findByLabelText('password')

    fireEvent.change(screen.getByTestId('param-password'), {
      target: { value: 'secret' },
    })
    fireEvent.change(screen.getByTestId('param-username'), {
      target: { value: 'alice' },
    })

    await user.click(screen.getByRole('button', { name: '执行 API' }))

    await waitFor(() => {
      expect(runAsset).toHaveBeenCalledWith('main/demo', 'api.user.login', {
        env: 'test',
        params: { username: 'alice', password: 'secret' },
      })
    })
    expect(await screen.findByTestId('api-run-response')).toHaveTextContent(
      'success',
    )

    await user.click(screen.getByText('执行历史', { exact: true }))
    await waitFor(() => {
      expect(listExecutionRecords).toHaveBeenCalled()
    })
    expect(await screen.findByTestId('execution-history')).toHaveTextContent(
      'api.user.login',
    )

    await user.click(screen.getByRole('button', { name: /查看记录 rec-1/ }))
    expect(await screen.findByTestId('execution-detail')).toBeInTheDocument()
    expect(screen.getByTestId('execution-detail')).toHaveTextContent('rec-1')
  }, 45_000)

  it('接口管理只展示 API，不混入文档和场景，也不包含配置编辑入口', async () => {
    renderWorkspace()
    await screen.findByTestId('asset-browser')
    expect(document.querySelector('[data-asset-id="docs"]')).toBeNull()
    expect(document.querySelector('[data-asset-id="scenarios"]')).toBeNull()
    expect(screen.queryByText('环境与账号')).not.toBeInTheDocument()
    fireEvent.click(screen.getByText('执行历史', { exact: true }))
    await waitFor(() => expect(listExecutionRecords).toHaveBeenCalledWith('main/demo', expect.objectContaining({ asset_type: 'api' })))
    expect(screen.getByRole('combobox', { name: '按资产类型筛选' })).toBeDisabled()
  })

  it('项目切换清空选中，不串执行面板', async () => {
    const user = userEvent.setup({ delay: null })
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    })

    function Switchable() {
      return (
        <ConfigProvider theme={{ token: { motion: false } }}>
          <AntApp>
            <QueryClientProvider client={client}>
              <MemoryRouter initialEntries={['/projects/main/demo']}>
                <Routes>
                  <Route
                    path="/projects/:repo/:project"
                    element={<ProjectWorkspacePage />}
                  />
                </Routes>
              </MemoryRouter>
            </QueryClientProvider>
          </AntApp>
        </ConfigProvider>
      )
    }

    const { rerender } = render(<Switchable />)
    await screen.findByTestId('asset-browser')
    await clickTreeNode(user, 'api')
    await clickTreeNode(user, 'api.user')
    await clickTreeNode(user, 'api.user.login')
    expect(await screen.findByTestId('api-execution-panel')).toBeInTheDocument()

    getProject.mockResolvedValue({
      ...project,
      id: 'main/other',
      project: 'other',
      name: 'other',
    })
    getAssetsTree.mockResolvedValue({
      id: 'assets',
      name: 'assets',
      type: 'directory',
      path: '.',
      children: [
        {
          id: 'api',
          name: 'api',
          type: 'directory',
          path: 'api',
          children: [
            {
              id: 'api.other',
              name: 'other.yaml',
              type: 'file',
              path: 'api/other.yaml',
            },
          ],
        },
      ],
    })

    // 通过重新挂载不同路由模拟项目切换
    rerender(
      <ConfigProvider theme={{ token: { motion: false } }}>
        <AntApp>
          <QueryClientProvider client={client}>
            <MemoryRouter initialEntries={['/projects/main/other']}>
              <Routes>
                <Route
                  path="/projects/:repo/:project"
                  element={<ProjectWorkspacePage />}
                />
              </Routes>
            </MemoryRouter>
          </QueryClientProvider>
        </AntApp>
      </ConfigProvider>,
    )

    expect(await screen.findByTestId('project-workspace')).toBeInTheDocument()
    await waitFor(() => {
      expect(screen.queryByTestId('api-execution-panel')).not.toBeInTheDocument()
    })
  })

  it('环境选择写入 localStorage，运行带 env', async () => {
    const user = userEvent.setup({ delay: null })
    window.localStorage.clear()
    renderWorkspace()
    const envSelect = await screen.findByTestId('workspace-env-select')
    expect(screen.getByTestId('workspace-commit-sha')).toHaveTextContent('abcdef0')

    // 切换到 staging（antd Select：combobox + title）
    await user.click(within(envSelect).getByRole('combobox'))
    await user.click(await screen.findByTitle('staging'))

    expect(window.localStorage.getItem('testplat.control.projectEnv:main/demo')).toBe(
      'staging',
    )

    await clickTreeNode(user, 'api')
    await clickTreeNode(user, 'api.user')
    await clickTreeNode(user, 'api.user.login')
    expect(await screen.findByTestId('api-execution-panel')).toBeInTheDocument()
    await screen.findByLabelText('password')
    fireEvent.change(screen.getByTestId('param-password'), {
      target: { value: 'secret' },
    })
    await user.click(screen.getByRole('button', { name: '执行 API' }))
    await waitFor(() => {
      expect(runAsset).toHaveBeenCalledWith(
        'main/demo',
        'api.user.login',
        expect.objectContaining({
          env: 'staging',
          params: expect.objectContaining({ password: 'secret' }),
        }),
      )
    })
  }, 45_000)

  it('停用的数据库环境不出现在运行下拉', async () => {
    const user = userEvent.setup({ delay: null })
    listEnvironments.mockResolvedValue([
      dbEnv('test', true),
      dbEnv('old', false),
    ])
    renderWorkspace()
    const envSelect = await screen.findByTestId('workspace-env-select')
    await user.click(within(envSelect).getByRole('combobox'))
    expect(screen.getAllByTitle('test').length).toBeGreaterThan(0)
    expect(screen.queryByTitle('old')).not.toBeInTheDocument()
  })

  it('没有启用环境时提示去配置，运行不使用 Git 环境', async () => {
    const user = userEvent.setup({ delay: null })
    listEnvironments.mockResolvedValue([])
    renderWorkspace()
    expect(await screen.findByTestId('workspace-no-env')).toHaveTextContent('数据库环境')
    expect(screen.getByRole('combobox', { name: '运行环境' })).toBeDisabled()
    expect(screen.getByTestId('open-env-config').closest('a')).toHaveAttribute('href', '/configuration/main/demo?tab=environments')
    await user.click(screen.getByTestId('open-env-config'))
    expect(await screen.findByTestId('config-route')).toBeInTheDocument()
    expect(screen.queryByTitle('test')).not.toBeInTheDocument()
  })

  it('环境默认值允许必填留空，切到无默认值的环境后恢复必填', async () => {
    const user = userEvent.setup({ delay: null })
    window.localStorage.clear()
    listEnvironments.mockResolvedValue([
      { ...dbEnv('test'), case_params: { password: 'web-default' } },
      dbEnv('staging'),
    ])
    renderWorkspace()
    await screen.findByTestId('asset-browser')
    await clickTreeNode(user, 'api')
    await clickTreeNode(user, 'api.user')
    await clickTreeNode(user, 'api.user.login')
    const password = await screen.findByLabelText('password')
    expect(password).toHaveAttribute('placeholder', '留空使用环境默认值')
    expect(password).toHaveValue('')
    await user.click(screen.getByRole('button', { name: '执行 API' }))
    await waitFor(() => {
      expect(runAsset).toHaveBeenCalledWith('main/demo', 'api.user.login', {
        env: 'test',
        params: {},
      })
    })
    expect(JSON.stringify(runAsset.mock.calls[0][2])).not.toContain('web-default')

    const envSelect = screen.getByTestId('workspace-env-select')
    await user.click(within(envSelect).getByRole('combobox'))
    await user.click(await screen.findByTitle('staging'))
    expect(await screen.findByLabelText('password')).toHaveAttribute('placeholder', '必填')
    await user.click(screen.getByRole('button', { name: '执行 API' }))
    expect(await screen.findByText('请填写该参数')).toBeInTheDocument()
    expect(runAsset).toHaveBeenCalledTimes(1)
  }, 45_000)

  it('运行工作台不再混入项目配置摘要', async () => {
    renderWorkspace()
    await screen.findByTestId('project-workspace')
    expect(screen.queryByText('项目摘要')).not.toBeInTheDocument()
    expect(screen.queryByText('资产目录')).not.toBeInTheDocument()
    expect(screen.queryByText('配置目录')).not.toBeInTheDocument()
  })
})


it('按环境展示完整 URL；切换环境和接口清空临时草稿与结果', async () => {
  const user = userEvent.setup({ delay: null })
  window.localStorage.clear()
  listEnvironments.mockResolvedValue([
    { ...dbEnv('test'), api_hosts: { gsb: 'https://test.example/base/' } },
    { ...dbEnv('staging'), api_hosts: { gsb: 'https://stage.example' } },
  ])
  renderWorkspace()
  await screen.findByTestId('asset-browser')
  await clickTreeNode(user, 'api.user')
  await clickTreeNode(user, 'api.user.login')
  expect(await screen.findByTestId('api-full-url')).toHaveTextContent('https://test.example/base/login')
  await user.click(await screen.findByText('编辑完整请求内容'))
  fireEvent.change(screen.getByLabelText('临时请求内容'), { target: { value: '{"draft":1}' } })
  await user.click(screen.getByRole('button', { name: '执行 API' }))
  await screen.findByTestId('api-run-response')
  await user.click(within(screen.getByTestId('workspace-env-select')).getByRole('combobox'))
  await user.click(await screen.findByTitle('staging'))
  expect(await screen.findByTestId('api-full-url')).toHaveTextContent('https://stage.example/login')
  expect(screen.queryByLabelText('临时请求内容')).not.toBeInTheDocument()
  expect(screen.queryByTestId('api-run-response')).not.toBeInTheDocument()
  await user.click(screen.getByText('编辑完整请求内容'))
  expect(screen.getByLabelText('临时请求内容')).toHaveValue('{}')
  fireEvent.change(screen.getByLabelText('临时请求内容'), { target: { value: '{"second":2}' } })
  await clickTreeNode(user, 'api.common')
  await clickTreeNode(user, 'api.common.health_check')
  await screen.findByTestId('api-execution-panel')
  expect(screen.queryByLabelText('临时请求内容')).not.toBeInTheDocument()
})

it('缺少接口 host 映射时提示配置并阻止执行', async () => {
  const user = userEvent.setup({ delay: null })
  listEnvironments.mockResolvedValue([{ ...dbEnv('test'), api_hosts: {} }])
  renderWorkspace()
  await screen.findByTestId('asset-browser')
  await clickTreeNode(user, 'api.user')
  await clickTreeNode(user, 'api.user.login')
  expect(await screen.findByTestId('api-info-panel')).toHaveTextContent('未配置服务地址：gsb')
  expect(await screen.findByRole('button', { name: '执行 API' })).toBeDisabled()
  expect(screen.getByText('配置环境').closest('a')).toHaveAttribute('href', '/configuration/main/demo?tab=environments')
  expect(runAsset).not.toHaveBeenCalled()
})
