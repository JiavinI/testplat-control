import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { App as AntApp, ConfigProvider } from 'antd'
import { MemoryRouter, useLocation, useRoutes } from 'react-router-dom'
import { router as browserRouter } from '@/app/router'
import type { AssetNode } from '@/features/assets'
import type { ProjectResponse } from '@/shared/types/project'

const first: ProjectResponse = {
  id: 'main/one', repo: 'main', project: 'one', name: '项目一', envs: ['test'], default_env: 'test',
  archived: false, commit_sha: 'abcdef0123456789', created_at: '', updated_at: '',
}
const second = { ...first, id: 'other/two', repo: 'other', project: 'two', name: '项目二' }
const tree: AssetNode = {
  id: 'assets', name: 'assets', type: 'directory', path: '.', children:
    ['api', 'pages', 'scenarios', 'flows', 'config'].map((path) => ({ id: path, name: path, path, type: 'directory', children: [] })),
}
const listProjects = vi.fn()
const getProject = vi.fn()
const getAssetsTree = vi.fn()
const listExecutionRecords = vi.fn()
vi.mock('@/features/auth/api', () => ({ getMe: vi.fn().mockResolvedValue({ username: 'operator' }), logout: vi.fn() }))
vi.mock('@/features/projects/api', () => ({
  listProjects: (...args: unknown[]) => listProjects(...args),
  getProject: (...args: unknown[]) => getProject(...args),
}))
vi.mock('@/features/assets/api', () => ({
  getAssetsTree: (...args: unknown[]) => getAssetsTree(...args), getAssetDetails: vi.fn(),
}))
vi.mock('@/features/environments/api', () => ({
  listEnvironments: vi.fn().mockResolvedValue([{ env: 'test', enabled: true, api_hosts: {}, case_params: {}, revision: 1 }]),
  listAccounts: vi.fn().mockResolvedValue([]),
  listLoginProfiles: vi.fn().mockResolvedValue({ commit_sha: 'abcdef', profiles: [] }),
}))
vi.mock('@/features/executions/api', () => ({
  listExecutionRecords: (...args: unknown[]) => listExecutionRecords(...args),
}))

function open(path: string) {
  const router = { state: { location: { pathname: path, search: '' } } }
  function RoutedTest() {
    router.state.location = useLocation()
    return useRoutes(browserRouter.routes)
  }
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  render(<ConfigProvider theme={{ token: { motion: false } }}><AntApp><QueryClientProvider client={client}><MemoryRouter initialEntries={[path]}><RoutedTest /></MemoryRouter></QueryClientProvider></AntApp></ConfigProvider>)
  return { router, client }
}

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  listProjects.mockResolvedValue([first, second])
  getProject.mockImplementation(async (id: string) => (await listProjects()).find((item: ProjectResponse) => item.id === id))
  getAssetsTree.mockResolvedValue(tree)
  listExecutionRecords.mockResolvedValue([])
})

describe('功能入口与项目上下文', () => {
  const platforms = () => [
    ['gsb', 'GSB', 'go2', 'gsb', 'gsb'], ['gsb', 'GSB', 'e3e3', 'gsb_e3e3', 'gsb_e3e3'],
    ['go2', 'GO2 网站', 'go2', 'go2', 'gsb'], ['e3e3', 'E3E3 网站', 'e3e3', 'e3e3', 'gsb_e3e3'],
    ['daifa_admin', '代发后台', 'go2', 'daifa_admin', 'daifa_admin'],
    ['daifa_picker', '拿货端', 'go2', 'daifa_picker', 'daifa_picker'],
    ['admin_go2', 'GO2 管理后台', 'go2', 'admin_go2', 'admin_go2'],
  ].map(([platform, label, project, key, owner]) => ({
    ...first, id: `main/${key}`, project: key, name: `${label} ${project.toUpperCase()}`,
    workspace: { platform, platform_name: label, project, project_name: project.toUpperCase(), configuration_project_id: `main/${owner}` },
  }))

  it('六个平台入口、GSB 两个归属明确，切换平台保留适用项目并清空详情', async () => {
    listProjects.mockResolvedValue(platforms())
    const user = userEvent.setup({ delay: null })
    const { router } = open('/apis/main/gsb_e3e3')
    await screen.findByTestId('asset-browser')
    expect(screen.getByTestId('workspace-context-title')).toHaveTextContent('E3E3 的 GSB')
    await user.click(document.querySelector('[data-asset-id="api"]')!)
    expect(await screen.findByTestId('asset-detail-panel')).toBeInTheDocument()
    await user.click(screen.getByRole('combobox', { name: '选择平台' }))
    for (const label of ['GO2 网站', 'E3E3 网站', 'GSB', '代发后台', '拿货端', 'GO2 管理后台']) {
      expect((await screen.findAllByTitle(label)).length).toBeGreaterThan(0)
    }
    await user.click(await screen.findByTitle('E3E3 网站'))
    await waitFor(() => expect(router.state.location.pathname).toBe('/apis/main/e3e3'))
    expect(screen.queryByTestId('asset-detail-panel')).not.toBeInTheDocument()
    expect(screen.getByTestId('workspace-context-title')).toHaveTextContent('E3E3 网站 · E3E3')
    await user.click(screen.getByRole('combobox', { name: '选择平台' }))
    await user.click(await screen.findByTitle('GSB'))
    await waitFor(() => expect(router.state.location.pathname).toBe('/apis/main/gsb_e3e3'))
    await user.click(screen.getByRole('combobox', { name: '选择项目' }))
    await user.click(await screen.findByTitle('GO2'))
    await waitFor(() => expect(router.state.location.pathname).toBe('/apis/main/gsb'))
    expect(screen.getByTestId('workspace-context-title')).toHaveTextContent('GO2 的 GSB')
  })

  it('配置入口提示共享身份，平台切换保留账号页签', async () => {
    listProjects.mockResolvedValue(platforms())
    const user = userEvent.setup({ delay: null })
    const { router } = open('/configuration/main/go2?tab=accounts')
    await screen.findByTestId('account-manager')
    expect(screen.getByText(/环境和账号与「GSB GO2」共用/)).toBeInTheDocument()
    await user.click(screen.getByRole('combobox', { name: '选择平台' }))
    await user.click(await screen.findByTitle('GSB'))
    await waitFor(() => expect(router.state.location.pathname).toBe('/configuration/main/gsb'))
    expect(router.state.location.search).toBe('?tab=accounts')
    expect(screen.getByText(/环境和账号与「GO2 网站 GO2」共用/)).toBeInTheDocument()
  })

  it('首页直接进入接口管理，四个菜单保留项目，场景树和历史独立', async () => {
    const user = userEvent.setup({ delay: null })
    const { router } = open('/')
    await screen.findByTestId('asset-browser')
    expect(router.state.location.pathname).toBe('/apis/main/one')
    const nav = screen.getByRole('navigation', { name: '功能菜单' })
    expect(within(nav).getAllByRole('link')).toHaveLength(4)
    expect(within(nav).getByRole('link', { name: '配置' })).toHaveAttribute('href', '/configuration/main/one')
    expect(document.querySelector('[data-asset-id="api"]')).toBeTruthy()
    expect(document.querySelector('[data-asset-id="scenarios"]')).toBeNull()
    await user.click(within(nav).getByRole('link', { name: '场景测试' }))
    await screen.findByText('场景测试资产')
    expect(router.state.location.pathname).toBe('/scenarios/main/one')
    expect(document.querySelector('[data-asset-id="api"]')).toBeNull()
    expect(document.querySelector('[data-asset-id="scenarios"]')).toBeTruthy()
    expect(document.querySelector('[data-asset-id="flows"]')).toBeTruthy()
    await waitFor(() => expect(listExecutionRecords).toHaveBeenLastCalledWith('main/one', expect.objectContaining({ asset_type: 'case' })))
  })

  it('切换到已缓存项目后清空旧详情，菜单使用新项目', async () => {
    const user = userEvent.setup({ delay: null })
    const { router, client } = open('/apis/main/one')
    client.setQueryData(['projects', 'detail', second.id], second)
    client.setQueryData(['assets', 'tree', second.id], tree)
    await screen.findByTestId('asset-browser')
    await user.click(document.querySelector('[data-asset-id="api"]')!)
    expect(await screen.findByTestId('asset-detail-panel')).toBeInTheDocument()
    await user.click(screen.getByRole('combobox', { name: '选择项目' }))
    await user.click(await screen.findByTitle('项目二 · other/two'))
    await waitFor(() => expect(router.state.location.pathname).toBe('/apis/other/two'))
    expect(await screen.findByText('选择左侧资产以查看元信息')).toBeInTheDocument()
    expect(screen.queryByTestId('asset-detail-panel')).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Page 管理' })).toHaveAttribute('href', '/pages/other/two')
  })

  it('Page 只展示页面资产，不展示接口、场景历史或账号编辑入口', async () => {
    open('/pages/main/one')
    await screen.findByText('Page 管理资产')
    expect(document.querySelector('[data-asset-id="pages"]')).toBeTruthy()
    expect(document.querySelector('[data-asset-id="api"]')).toBeNull()
    expect(screen.queryByTestId('execution-history')).not.toBeInTheDocument()
    expect(screen.queryByTestId('workspace-env-select')).not.toBeInTheDocument()
    expect(screen.queryByTestId('account-manager')).not.toBeInTheDocument()
    expect(listExecutionRecords).not.toHaveBeenCalled()
  })

  it('配置集中展示项目文件、环境和账号，页签可通过 URL 直接打开', async () => {
    const user = userEvent.setup({ delay: null })
    const { router } = open('/configuration/main/one?tab=environments')
    await screen.findByTestId('environment-manager')
    expect(screen.queryByTestId('project-workspace')).not.toBeInTheDocument()
    await user.click(screen.getByRole('tab', { name: '测试账号' }))
    await screen.findByTestId('account-manager')
    expect(router.state.location.search).toBe('?tab=accounts')
    expect(screen.queryByTestId('environment-manager')).not.toBeInTheDocument()
    await user.click(screen.getByRole('tab', { name: '项目配置' }))
    await screen.findByText('配置资产')
    expect(document.querySelector('[data-asset-id="config"]')).toBeTruthy()
    expect(document.querySelector('[data-asset-id="api"]')).toBeNull()
    expect(screen.queryByTestId('account-manager')).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: '仓库同步' })).toHaveAttribute('href', '/configuration/repositories')
  })

  it('进入功能时恢复最近项目', async () => {
    localStorage.setItem('testplat.control.selectedProject', second.id)
    const { router } = open('/apis')
    await screen.findByTestId('asset-browser')
    expect(router.state.location.pathname).toBe('/apis/other/two')
  })

  it('旧工作台链接仍可打开', async () => {
    const { router } = open('/projects/other/two')
    await screen.findByTestId('asset-browser')
    expect(router.state.location.pathname).toBe('/apis/other/two')
  })

  it('无效项目不会拉取旧资产', async () => {
    open('/apis/missing/project')
    await screen.findByText('当前项目不存在，请从上方重新选择项目。')
    expect(getAssetsTree).not.toHaveBeenCalled()
  })

  it('没有项目时提供配置同步入口', async () => {
    listProjects.mockResolvedValue([])
    open('/apis')
    expect(await screen.findByRole('link', { name: '配置 / 仓库同步' })).toHaveAttribute('href', '/configuration/repositories')
    expect(getAssetsTree).not.toHaveBeenCalled()
  })
})
